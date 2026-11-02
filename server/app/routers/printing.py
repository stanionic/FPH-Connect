import hashlib
import os

from fastapi import (APIRouter, Depends, File, Form, Header, HTTPException, Query, Request,
                     Response, UploadFile)
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..audit import audit
from ..db import get_db
from ..deps import get_current_device, hash_device_token, request_id, require
from ..config import settings
from ..documents import files as fs
from ..models import (Device, IdempotencyKey, PrintGrant, PrintJob, Printer, User, new_id, now)
from ..printing_service import (ACTIVE, LABELS, PRINTABLE, TERMINAL, can_use, delete_file, expire_stale,
                                finish, printer_online)

router = APIRouter(prefix="/api/v1", tags=["Impression"])
SIDES = ("one-sided", "two-sided-long-edge", "two-sided-short-edge")


def _printer_out(db: Session, p: Printer, admin: bool = False) -> dict:
    d = {"id": p.id, "name": p.name, "location": p.location, "online": printer_online(db, p),
         "capabilities": p.capabilities}
    if admin:
        d.update(system_name=p.system_name, agent_device_id=p.agent_device_id, backend=p.backend,
                 enabled=p.enabled, visibility=p.visibility, present=p.present,
                 granted_user_ids=[g.user_id for g in db.scalars(
                     select(PrintGrant).where(PrintGrant.printer_id == p.id))])
    return d


def _job_out(db: Session, j: PrintJob) -> dict:
    p = db.get(Printer, j.printer_id)
    return {"id": j.id, "printer_id": j.printer_id, "printer_name": p.name if p else None,
            "original_name": j.original_name, "copies": j.copies, "options": j.options,
            "status": j.status, "status_label": LABELS[j.status], "error": j.error,
            "cancel_requested": j.cancel_requested, "final_state_known": j.status != "transmitted",
            "created_at": j.created_at.isoformat()}


# ---------------- utilisateurs ----------------
@router.get("/printers")
def list_printers(user: User = Depends(require("print:use")), device: Device = Depends(get_current_device),
                  db: Session = Depends(get_db)):
    """Imprimantes que CET utilisateur a le droit d'utiliser (nom, emplacement, état, options)."""
    rows = db.scalars(select(Printer).where(Printer.enabled.is_(True)).order_by(Printer.name))
    return [_printer_out(db, p) for p in rows if can_use(db, user, p)]


@router.post("/print-jobs", status_code=201)
async def create_job(response: Response, request: Request,
                     printer_id: str = Form(...), file: UploadFile = File(...),
                     copies: int = Form(default=1), duplex: str = Form(default="one-sided"),
                     color: bool = Form(default=False), paper: str = Form(default="A4"),
                     idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
                     user: User = Depends(require("print:use")),
                     device: Device = Depends(get_current_device), db: Session = Depends(get_db)):
    if idempotency_key:                                   # renvoi après coupure : pas de double impression
        prev = db.get(IdempotencyKey, f"printjob:{idempotency_key}")
        if prev and prev.user_id == user.id:
            j = db.get(PrintJob, prev.resource_id)
            if j:
                response.status_code = 200
                return _job_out(db, j)
    p = db.get(Printer, printer_id)
    if p is None or not can_use(db, user, p):
        raise HTTPException(404, "Imprimante introuvable")          # même réponse : n'indique pas son existence
    caps = p.capabilities or {}
    if not 1 <= copies <= int(caps.get("max_copies", 10)):
        raise HTTPException(422, f"Nombre de copies : 1 à {caps.get('max_copies', 10)}")
    if duplex not in SIDES:
        raise HTTPException(422, f"duplex doit être l'une de : {', '.join(SIDES)}")
    if duplex != "one-sided" and not caps.get("duplex"):
        raise HTTPException(422, "Cette imprimante ne prend pas en charge le recto-verso")
    if color and not caps.get("color"):
        raise HTTPException(422, "Cette imprimante n'imprime pas en couleur")
    if paper not in caps.get("paper", []):
        raise HTTPException(422, f"Papier pris en charge : {', '.join(caps.get('paper', []))}")
    active = db.scalar(select(func.count()).select_from(PrintJob).where(
        PrintJob.user_id == user.id, PrintJob.status.in_(ACTIVE))) or 0
    if active >= settings.print_max_active_per_user:
        raise HTTPException(429, "Trop de travaux d'impression en cours")
    name = fs.clean_filename(file.filename or "")
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in PRINTABLE:
        raise HTTPException(422, f"Format non imprimable. Formats acceptés : {', '.join(sorted(PRINTABLE))} "
                                 "(convertir les documents Word/Excel en PDF)")
    job_id = new_id()
    tmp = fs.safe_path("print", f"{job_id}.part")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    limit, size, h, head = settings.max_print_mb * 1024 * 1024, 0, hashlib.sha256(), b""
    try:
        with open(tmp, "wb") as out:
            while chunk := await file.read(1024 * 1024):
                if not head:
                    head = chunk[:4096]
                    try:
                        fs.check_type(name, head)
                    except ValueError as e:
                        raise HTTPException(422, str(e))
                size += len(chunk)
                if size > limit:
                    raise HTTPException(413, f"Fichier trop volumineux (max {settings.max_print_mb} Mo)")
                h.update(chunk)
                out.write(chunk)
        if size == 0:
            raise HTTPException(422, "Fichier vide")
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    final = fs.safe_path("print", job_id)
    os.replace(tmp, final)
    _, mime = fs.check_type(name, head)
    job = PrintJob(id=job_id, printer_id=p.id, user_id=user.id, device_id=device.id, original_name=name,
                   mime=mime, size=size, sha256=h.hexdigest(), storage_path=str(final.relative_to(fs.root())),
                   copies=copies, options={"duplex": duplex, "color": color, "paper": paper})
    db.add(job)
    if idempotency_key:
        db.add(IdempotencyKey(key=f"printjob:{idempotency_key}", user_id=user.id, resource_id=job_id))
    # le nom du document n'est pas journalisé (peut être confidentiel)
    audit(db, user.id, "print.job_created", "print_job", job_id, {"printer": p.id, "size": size},
          request_id(request))
    db.commit()
    out = _job_out(db, job)
    out["printer_online"] = printer_online(db, p)
    return out


def _my_job(db: Session, user: User, job_id: str) -> PrintJob:
    j = db.get(PrintJob, job_id)
    if j is None or (j.user_id != user.id and "print:manage" not in (user.role.permissions or [])):
        raise HTTPException(404, "Travail introuvable")
    return j


@router.get("/print-jobs")
def my_jobs(status: str | None = None, limit: int = Query(default=50, ge=1, le=200),
            user: User = Depends(require("print:use")), device: Device = Depends(get_current_device),
            db: Session = Depends(get_db)):
    expire_stale(db)
    stmt = select(PrintJob).where(PrintJob.user_id == user.id).order_by(PrintJob.created_at.desc()).limit(limit)
    if status:
        stmt = stmt.where(PrintJob.status == status)
    return [_job_out(db, j) for j in db.scalars(stmt)]


@router.get("/print-jobs/{job_id}")
def get_job(job_id: str, user: User = Depends(require("print:use")), device: Device = Depends(get_current_device),
            db: Session = Depends(get_db)):
    expire_stale(db)
    return _job_out(db, _my_job(db, user, job_id))


@router.post("/print-jobs/{job_id}/cancel")
def cancel_job(job_id: str, request: Request, user: User = Depends(require("print:use")),
               device: Device = Depends(get_current_device), db: Session = Depends(get_db)):
    """Annulation selon les droits : le propriétaire, ou un administrateur d'impression.
    En attente : immédiat. Déjà pris en charge : annulation DEMANDÉE (non garantie si l'impression a commencé)."""
    j = _my_job(db, user, job_id)
    if j.status in TERMINAL:
        raise HTTPException(409, f"Travail déjà {LABELS[j.status]}")
    if j.status == "pending":
        finish(j, "cancelled")
    else:
        j.cancel_requested = True
    audit(db, user.id, "print.job_cancel", "print_job", j.id, {"status": j.status}, request_id(request))
    db.commit()
    return _job_out(db, j)


# ---------------- administration ----------------
admin = APIRouter(prefix="/api/v1/admin", tags=["Impression (administration)"])


class AgentCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    platform: str = Field(pattern="^(windows|linux|macos|other)$")


class PrinterPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    location: str | None = Field(default=None, max_length=200)
    enabled: bool | None = None
    visibility: str | None = Field(default=None, pattern="^(granted|all_staff)$")


@admin.post("/agents", status_code=201)
def create_agent(body: AgentCreate, request: Request, adm: User = Depends(require("print:manage")),
                 db: Session = Depends(get_db)):
    """Crée un agent d'impression (service installé sur le poste qui héberge les imprimantes).
    Créé par un administrateur = déjà approuvé. Le jeton n'est montré qu'une fois."""
    import secrets
    token = secrets.token_urlsafe(32)
    d = Device(name=body.name, platform=body.platform, token_hash=hash_device_token(token), status="approved",
               registered_by=adm.id, approved_by=adm.id, is_agent=True)
    d.approved_at = now()
    db.add(d)
    db.flush()
    audit(db, adm.id, "agent.created", "device", d.id, request_id=request_id(request))
    db.commit()
    return {"id": d.id, "token": token, "device_header": f"{d.id}:{token}"}


@admin.get("/printers")
def admin_printers(_=Depends(require("print:manage")), db: Session = Depends(get_db)):
    return [_printer_out(db, p, admin=True) for p in db.scalars(select(Printer).order_by(Printer.name))]


@admin.patch("/printers/{printer_id}")
def patch_printer(printer_id: str, body: PrinterPatch, request: Request,
                  adm: User = Depends(require("print:manage")), db: Session = Depends(get_db)):
    p = db.get(Printer, printer_id)
    if p is None:
        raise HTTPException(404, "Imprimante introuvable")
    changes = body.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(p, k, v)
    audit(db, adm.id, "printer.updated", "printer", p.id, changes, request_id(request))
    db.commit()
    return _printer_out(db, p, admin=True)


@admin.put("/printers/{printer_id}/grants/{user_id}", status_code=204)
def grant(printer_id: str, user_id: str, request: Request, adm: User = Depends(require("print:manage")),
          db: Session = Depends(get_db)):
    if db.get(Printer, printer_id) is None or db.get(User, user_id) is None:
        raise HTTPException(404, "Imprimante ou utilisateur introuvable")
    if db.scalar(select(PrintGrant.id).where(PrintGrant.printer_id == printer_id, PrintGrant.user_id == user_id)) is None:
        db.add(PrintGrant(printer_id=printer_id, user_id=user_id, granted_by=adm.id))
        audit(db, adm.id, "printer.grant", "printer", printer_id, {"user": user_id}, request_id(request))
        db.commit()


@admin.delete("/printers/{printer_id}/grants/{user_id}", status_code=204)
def revoke(printer_id: str, user_id: str, request: Request, adm: User = Depends(require("print:manage")),
           db: Session = Depends(get_db)):
    g = db.scalar(select(PrintGrant).where(PrintGrant.printer_id == printer_id, PrintGrant.user_id == user_id))
    if g is not None:
        db.delete(g)
        audit(db, adm.id, "printer.grant_revoked", "printer", printer_id, {"user": user_id}, request_id(request))
        db.commit()


@admin.get("/print-jobs")
def admin_jobs(status: str | None = None, limit: int = Query(default=100, ge=1, le=500),
               _=Depends(require("print:manage")), db: Session = Depends(get_db)):
    expire_stale(db)
    stmt = select(PrintJob).order_by(PrintJob.created_at.desc()).limit(limit)
    if status:
        stmt = stmt.where(PrintJob.status == status)
    return [{**_job_out(db, j), "user_id": j.user_id} for j in db.scalars(stmt)]
