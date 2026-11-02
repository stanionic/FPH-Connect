"""API de l'agent d'impression (service installé sur le poste qui héberge les imprimantes).
Authentification : jeton d'appareil de l'agent uniquement. Un agent ne voit et ne touche QUE
les imprimantes et travaux qui lui sont rattachés."""
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..audit import audit
from ..config import settings
from ..db import get_db
from ..deps import get_agent_device, request_id
from ..documents import files as fs
from ..models import Device, PrintJob, Printer, now
from ..printing_service import (DEFAULT_CAPS, TERMINAL, finish, recover_stale_claims, expire_stale)

router = APIRouter(prefix="/api/v1/agent", tags=["Agent d'impression"])


class Capabilities(BaseModel):
    duplex: bool = False
    color: bool = False      # une capacité n'est annoncée que si elle est configurée
    paper: list[str] = Field(default=["A4", "Letter"], max_length=10)
    max_copies: int = Field(default=10, ge=1, le=99)
    tracking: str = Field(default="full", pattern="^(full|none)$")

    @field_validator("paper")
    @classmethod
    def _paper(cls, v):
        if not v or any(not (1 <= len(x) <= 20) for x in v):
            raise ValueError("liste de formats de papier invalide")
        return v


class PrinterReport(BaseModel):
    system_name: str = Field(min_length=1, max_length=200)
    name: str | None = Field(default=None, max_length=120)
    backend: str = Field(pattern="^(cups|windows|file)$")
    capabilities: Capabilities = Capabilities()


class ReportIn(BaseModel):
    printers: list[PrinterReport] = Field(max_length=50)


class StatusIn(BaseModel):
    status: str = Field(pattern="^(accepted|in_progress|completed|transmitted|error|unknown|cancelled)$")
    backend_job_id: str | None = Field(default=None, max_length=100)
    error: str | None = Field(default=None, max_length=300)


def _my_printers(db: Session, agent: Device) -> list[Printer]:
    return list(db.scalars(select(Printer).where(Printer.agent_device_id == agent.id)))


def _agent_job(db: Session, agent: Device, job_id: str) -> PrintJob:
    j = db.get(PrintJob, job_id)
    p = db.get(Printer, j.printer_id) if j else None
    if j is None or p is None or p.agent_device_id != agent.id:
        raise HTTPException(404, "Travail introuvable")
    return j


@router.post("/report")
def report(body: ReportIn, request: Request, agent: Device = Depends(get_agent_device),
           db: Session = Depends(get_db)):
    """L'agent annonce les imprimantes QU'IL PARTAGE. Une imprimante nouvelle est créée DÉSACTIVÉE :
    un administrateur doit l'activer et accorder l'accès."""
    agent.last_seen_at = now()
    agent.last_ip = request.client.host if request.client else None
    existing = {p.system_name: p for p in _my_printers(db, agent)}
    seen = set()
    for r in body.printers:
        seen.add(r.system_name)
        caps = r.capabilities.model_dump()
        p = existing.get(r.system_name)
        if p is None:
            p = Printer(name=r.name or r.system_name, system_name=r.system_name, agent_device_id=agent.id,
                        backend=r.backend, capabilities=caps, enabled=False)
            db.add(p)
            audit(db, None, "printer.discovered", "device", agent.id, {"queue": r.system_name},
                  request_id(request))
        else:
            p.capabilities, p.backend = caps, r.backend      # l'agent connaît le matériel ; l'admin garde nom/accès
        p.present = True
    for name, p in existing.items():
        if name not in seen:
            p.present = False
    db.commit()
    return {"printers": [{"id": p.id, "system_name": p.system_name, "name": p.name, "enabled": p.enabled}
                         for p in _my_printers(db, agent)]}


@router.post("/jobs/claim")
def claim(request: Request, agent: Device = Depends(get_agent_device), db: Session = Depends(get_db)):
    agent.last_seen_at = now()
    expire_stale(db)
    recover_stale_claims(db)
    printers = {p.id: p for p in _my_printers(db, agent) if p.enabled}
    new_jobs, resume, cancel = [], [], []
    if printers:
        pending = db.scalars(select(PrintJob).where(PrintJob.printer_id.in_(list(printers)),
                                                    PrintJob.status == "pending")
                             .order_by(PrintJob.created_at, PrintJob.id).limit(5)).all()
        for j in pending:
            # prise de possession atomique : deux instances d'agent ne peuvent pas prendre le même travail
            res = db.execute(update(PrintJob).where(PrintJob.id == j.id, PrintJob.status == "pending")
                             .values(status="accepted", accepted_at=now(), attempts=PrintJob.attempts + 1,
                                     claim_expires_at=now() + timedelta(seconds=settings.print_lease_seconds)))
            if res.rowcount == 1:
                new_jobs.append({"job_id": j.id, "system_name": printers[j.printer_id].system_name,
                                 "copies": j.copies, "options": j.options, "mime": j.mime,
                                 "size": j.size, "sha256": j.sha256,
                                 "title": fs.clean_filename(j.original_name)[:100]})
        db.commit()
        for j in db.scalars(select(PrintJob).where(PrintJob.printer_id.in_(list(printers)),
                                                   PrintJob.status.in_(("accepted", "in_progress")),
                                                   PrintJob.backend_job_id.is_not(None))):
            entry = {"job_id": j.id, "system_name": printers[j.printer_id].system_name,
                     "backend_job_id": j.backend_job_id}
            resume.append(entry)                    # toujours suivi : on rapporte le résultat RÉEL
            if j.cancel_requested:
                cancel.append(entry)                # + ordre d'annuler (peut échouer s'il est déjà imprimé)
    return {"new": new_jobs, "resume": resume, "cancel": cancel}


@router.get("/jobs/{job_id}/file")
def job_file(job_id: str, agent: Device = Depends(get_agent_device), db: Session = Depends(get_db)):
    j = _agent_job(db, agent, job_id)
    if j.cancel_requested or j.status == "cancelled":
        raise HTTPException(409, "Travail annulé")
    if j.status != "accepted" or not j.storage_path:
        raise HTTPException(409, "Travail non disponible")
    path = fs.safe_path(j.storage_path)
    if not path.exists():
        finish(j, "error", "Fichier introuvable sur le serveur")
        db.commit()
        raise HTTPException(410, "Fichier introuvable")
    return FileResponse(path, media_type="application/octet-stream", headers={"X-FPH-SHA256": j.sha256})


@router.post("/jobs/{job_id}/status")
def job_status(job_id: str, body: StatusIn, request: Request, agent: Device = Depends(get_agent_device),
               db: Session = Depends(get_db)):
    j = _agent_job(db, agent, job_id)
    if j.status in TERMINAL:                       # état final : jamais rouvert (ex. annulé reste annulé)
        return {"status": j.status, "cancel_requested": j.cancel_requested}
    st = body.status
    if body.backend_job_id:
        j.backend_job_id, j.claim_expires_at = body.backend_job_id, None   # confirmé : plus de reprise automatique
    if st == "accepted":
        pass
    elif st == "in_progress":
        j.status = "in_progress"
    elif st == "unknown":                          # l'agent ne retrouve plus le travail dans la file locale
        j.unknown_polls += 1
        if j.unknown_polls >= 3:
            finish(j, "transmitted")
    elif st == "cancelled":
        if j.cancel_requested:
            finish(j, "cancelled")
        else:
            finish(j, "error", "Annulé localement sur le poste d'impression")
    else:                                          # completed | transmitted | error
        finish(j, st, body.error)
    if j.status in TERMINAL:
        audit(db, None, "print.job_finished", "print_job", j.id, {"status": j.status}, request_id(request))
    db.commit()
    return {"status": j.status, "cancel_requested": j.cancel_requested}
