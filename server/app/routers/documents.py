import hashlib
import os
import re
import shutil
from datetime import datetime, timezone

from fastapi import (APIRouter, Depends, File, Form, HTTPException, Request, Response,
                     UploadFile)
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..audit import audit
from ..config import settings
from ..db import get_db
from ..deps import get_current_device, request_id, require
from ..documents import classify as clf
from ..documents import files as fs
from ..models import Church, Device, Document, InboxItem, User, new_id
from ..permissions import has_permission, in_scope

router = APIRouter(prefix="/api/v1/documents", tags=["Documents"])


# ---------- aides ----------
def _is_national(user: User) -> bool:
    return user.role.level <= 10


def _scoped_churches(db: Session, user: User) -> list[Church]:
    rows = db.scalars(select(Church).where(Church.validation_status != "archived")).all()
    return [c for c in rows if in_scope(user, c)]


def _item_out(i: InboxItem) -> dict:
    return {"id": i.id, "original_name": i.original_name, "size": i.size, "status": i.status,
            "suggested_type": i.suggested_type, "suggested_church_id": i.suggested_church_id,
            "note": i.note, "document_id": i.document_id, "uploader_id": i.uploader_id,
            "created_at": i.created_at.isoformat()}


def _doc_out(d: Document) -> dict:
    return {"id": d.id, "title": d.title, "doc_type": d.doc_type, "church_id": d.church_id,
            "original_name": d.original_name, "size": d.size, "mime": d.mime,
            "batch_id": d.batch_id, "created_at": d.created_at.isoformat()}


def _can_see_item(db: Session, user: User, item: InboxItem) -> bool:
    if item.uploader_id == user.id:
        return True
    if not has_permission(user, "document:organize"):
        return False
    if _is_national(user) or item.hint_church_id is None:
        return True
    c = db.get(Church, item.hint_church_id)
    return c is not None and in_scope(user, c)


def _visible_items(db: Session, user: User, status: str | None = None) -> list[InboxItem]:
    stmt = select(InboxItem).order_by(InboxItem.created_at)
    if status:
        stmt = stmt.where(InboxItem.status == status)
    return [i for i in db.scalars(stmt) if _can_see_item(db, user, i)]


def _can_read_doc(db: Session, user: User, d: Document) -> bool:
    if d.church_id is None:
        return _is_national(user)
    c = db.get(Church, d.church_id)
    return c is not None and in_scope(user, c)


def _title_from(name: str) -> str:
    return re.sub(r"[_\s]+", " ", name.rsplit(".", 1)[0]).strip()[:300] or "Document"


def _file_into_library(db: Session, item: InboxItem, doc_type: str, church_id, organizer: User,
                       batch: str, title: str | None = None) -> Document:
    """Crée la fiche et déplace le fichier. Lève ValueError/OSError/IntegrityError sans
    laisser d'état incohérent (fichier remis en place)."""
    src = fs.inbox_path(item.id)
    doc = Document(title=title or _title_from(item.original_name), doc_type=doc_type,
                   church_id=church_id, original_name=item.original_name, mime=item.mime,
                   size=item.size, sha256=item.sha256, storage_path="", uploaded_by=item.uploader_id,
                   organized_by=organizer.id, batch_id=batch, inbox_item_id=item.id)
    db.add(doc)
    db.flush()
    dst = fs.library_path(doc_type, church_id, datetime.now(timezone.utc).year, doc.id)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    try:
        doc.storage_path = str(dst.relative_to(fs.root()))
        item.status, item.document_id, item.note = "organized", doc.id, item.note
        db.commit()
    except Exception:
        db.rollback()
        shutil.move(str(dst), str(src))   # remet le fichier dans la zone tampon
        raise
    return doc


# ---------- zone tampon ----------
@router.post("/inbox", status_code=201)
async def upload_to_inbox(response: Response, request: Request, file: UploadFile = File(...),
                          church_id: str | None = Form(default=None),
                          doc_type: str | None = Form(default=None),
                          user: User = Depends(require("document:share")),
                          device: Device = Depends(get_current_device),
                          db: Session = Depends(get_db)):
    if doc_type is not None and doc_type not in fs.DOC_TYPES:
        raise HTTPException(422, f"doc_type inconnu. Valeurs : {', '.join(fs.DOC_TYPES)}")
    if church_id:
        c = db.get(Church, church_id)
        if c is None or not in_scope(user, c):
            raise HTTPException(404, "Église introuvable")
    name = fs.clean_filename(file.filename or "")
    limit = settings.max_upload_mb * 1024 * 1024
    item_id = new_id()
    tmp = fs.safe_path("inbox", f"{item_id}.part")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    h, size, head = hashlib.sha256(), 0, b""
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
                    raise HTTPException(413, f"Fichier trop volumineux (max {settings.max_upload_mb} Mo)")
                h.update(chunk)
                out.write(chunk)
        if size == 0:
            raise HTTPException(422, "Fichier vide")
        _, mime = fs.check_type(name, head)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    digest = h.hexdigest()
    prev = db.scalar(select(InboxItem).where(
        InboxItem.uploader_id == user.id, InboxItem.sha256 == digest,
        InboxItem.status.in_(("staged", "needs_review"))))
    if prev:                      # même fichier renvoyé (reprise après coupure) : pas de doublon
        tmp.unlink(missing_ok=True)
        response.status_code = 200
        return _item_out(prev)
    os.replace(tmp, fs.inbox_path(item_id))
    item = InboxItem(id=item_id, uploader_id=user.id, device_id=device.id, original_name=name,
                     mime=mime, size=size, sha256=digest, hint_church_id=church_id or None,
                     hint_doc_type=doc_type)
    db.add(item)
    audit(db, user.id, "document.staged", "inbox", item_id, {"size": size, "name": name},
          request_id(request))
    db.commit()
    return _item_out(item)


@router.get("/inbox")
def list_inbox(status: str | None = None, user: User = Depends(require("document:share")),
               device: Device = Depends(get_current_device), db: Session = Depends(get_db)):
    return [_item_out(i) for i in _visible_items(db, user, status)]


class OrganizeIn(BaseModel):
    item_ids: list[str] | None = None
    include_review: bool = False   # réexamine aussi les éléments 'à vérifier' (ex. par le niveau national)


@router.post("/inbox/organize")
def organize(request: Request, body: OrganizeIn | None = None,
             user: User = Depends(require("document:organize")),
             device: Device = Depends(get_current_device), db: Session = Depends(get_db)):
    """LE CLIC : classe en une fois tout ce qui est dans la zone tampon.
    Chaque fichier est traité séparément ; le doute envoie en 'à vérifier'."""
    wanted = ("staged", "needs_review") if (body and body.include_review) else ("staged",)
    items = [i for i in _visible_items(db, user)
             if i.status in wanted and (body is None or body.item_ids is None or i.id in body.item_ids)]
    churches = _scoped_churches(db, user)
    batch, report = new_id(), []
    for item in items:
        res = {"item_id": item.id, "original_name": item.original_name}
        src = fs.inbox_path(item.id)
        if not src.exists():
            item.status, item.note = "error", "Fichier introuvable dans la zone tampon"
            db.commit()
            res.update(status="error", note=item.note)
            report.append(res)
            continue
        if db.scalar(select(Document.id).where(Document.sha256 == item.sha256)):
            src.unlink(missing_ok=True)
            item.status, item.note = "duplicate", "Ce fichier est déjà classé dans la base"
            db.commit()
            res.update(status="duplicate", note=item.note)
            report.append(res)
            continue
        hint_church = item.hint_church_id
        if hint_church and not any(c.id == hint_church for c in churches):
            item.status, item.note = "needs_review", "Église indiquée hors de votre périmètre"
            db.commit()
            res.update(status="needs_review", note=item.note)
            report.append(res)
            continue
        ext = item.original_name.rsplit(".", 1)[-1].lower() if "." in item.original_name else ""
        verdict = clf.classify(item.original_name, clf.content_head(src, ext), churches,
                               item.hint_doc_type, hint_church, allow_national=_is_national(user))
        if not verdict["ok"]:
            item.status, item.note = "needs_review", verdict["note"]
            item.suggested_type, item.suggested_church_id = verdict["doc_type"], verdict["church_id"]
            db.commit()
            res.update(status="needs_review", note=item.note, doc_type=verdict["doc_type"])
            report.append(res)
            continue
        item.note = verdict["note"]
        item.suggested_type = item.suggested_church_id = None
        try:
            doc = _file_into_library(db, item, verdict["doc_type"], verdict["church_id"], user, batch)
            res.update(status="organized", doc_type=doc.doc_type, church_id=doc.church_id,
                       document_id=doc.id, note=item.note)
        except IntegrityError:           # même contenu classé entre-temps
            db.rollback()
            item = db.get(InboxItem, item.id)
            item.status, item.note = "duplicate", "Ce fichier est déjà classé dans la base"
            db.commit()
            res.update(status="duplicate", note=item.note)
        except (OSError, ValueError) as e:
            db.rollback()
            item = db.get(InboxItem, item.id)
            item.status, item.note = "error", f"Échec du classement : {type(e).__name__}"
            db.commit()
            res.update(status="error", note=item.note)
        report.append(res)
    counts = {}
    for r in report:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    audit(db, user.id, "document.organize", "batch", batch, counts, request_id(request))
    db.commit()
    return {"batch_id": batch, "counts": counts, "items": report}


@router.post("/inbox/batches/{batch_id}/undo")
def undo_batch(batch_id: str, request: Request, user: User = Depends(require("document:organize")),
               device: Device = Depends(get_current_device), db: Session = Depends(get_db)):
    """Annule un classement : les documents retournent dans la zone tampon."""
    docs = db.scalars(select(Document).where(Document.batch_id == batch_id)).all()
    if not docs or not all(d.organized_by == user.id or _is_national(user) for d in docs):
        raise HTTPException(404, "Lot introuvable")
    restored = 0
    for d in docs:
        item = db.get(InboxItem, d.inbox_item_id)
        src = fs.safe_path(d.storage_path)
        if item is None or not src.exists():
            continue
        shutil.move(str(src), str(fs.inbox_path(item.id)))
        item.status, item.document_id, item.note = "staged", None, "Classement annulé"
        db.delete(d)
        restored += 1
    audit(db, user.id, "document.undo", "batch", batch_id, {"restored": restored},
          request_id(request))
    db.commit()
    return {"restored": restored}


class FileIn(BaseModel):
    doc_type: str
    church_id: str | None = None
    title: str | None = Field(default=None, max_length=300)


@router.post("/inbox/{item_id}/file")
def file_manually(item_id: str, body: FileIn, request: Request,
                  user: User = Depends(require("document:organize")),
                  device: Device = Depends(get_current_device), db: Session = Depends(get_db)):
    """Classement manuel d'un élément 'à vérifier'."""
    item = db.get(InboxItem, item_id)
    if item is None or not _can_see_item(db, user, item) or item.status not in ("staged", "needs_review", "error"):
        raise HTTPException(404, "Élément introuvable")
    if body.doc_type not in fs.DOC_TYPES:
        raise HTTPException(422, "doc_type inconnu")
    if body.church_id:
        c = db.get(Church, body.church_id)
        if c is None or not in_scope(user, c):
            raise HTTPException(404, "Église introuvable")
    elif not _is_national(user):
        raise HTTPException(403, "Classement sans église réservé au niveau national")
    if body.doc_type in fs.CHURCH_REQUIRED and not body.church_id:
        raise HTTPException(422, "Ce type de document doit être rattaché à une église")
    if db.scalar(select(Document.id).where(Document.sha256 == item.sha256)):
        raise HTTPException(409, "Ce fichier est déjà classé dans la base")
    if not fs.inbox_path(item.id).exists():
        raise HTTPException(409, "Fichier introuvable dans la zone tampon")
    try:
        doc = _file_into_library(db, item, body.doc_type, body.church_id, user, new_id(), body.title)
    except (OSError, ValueError, IntegrityError):
        db.rollback()
        raise HTTPException(500, "Échec du classement")
    audit(db, user.id, "document.filed_manually", "document", doc.id, request_id=request_id(request))
    db.commit()
    return _doc_out(doc)


@router.delete("/inbox/{item_id}", status_code=204)
def delete_staged(item_id: str, request: Request, user: User = Depends(require("document:share")),
                  device: Device = Depends(get_current_device), db: Session = Depends(get_db)):
    item = db.get(InboxItem, item_id)
    if item is None or not _can_see_item(db, user, item) or item.status == "organized":
        raise HTTPException(404, "Élément introuvable")
    fs.inbox_path(item.id).unlink(missing_ok=True)
    audit(db, user.id, "document.staged_deleted", "inbox", item.id, request_id=request_id(request))
    db.delete(item)
    db.commit()


# ---------- bibliothèque (base classée) ----------
@router.get("")
def list_documents(doc_type: str | None = None, church_id: str | None = None,
                   user: User = Depends(require("document:read")), db: Session = Depends(get_db)):
    stmt = select(Document).order_by(Document.created_at.desc())
    if doc_type:
        stmt = stmt.where(Document.doc_type == doc_type)
    if church_id:
        stmt = stmt.where(Document.church_id == church_id)
    return [_doc_out(d) for d in db.scalars(stmt) if _can_read_doc(db, user, d)]


def _get_doc(db, user, doc_id) -> Document:
    d = db.get(Document, doc_id)
    if d is None or not _can_read_doc(db, user, d):
        raise HTTPException(404, "Document introuvable")
    return d


@router.get("/{doc_id}")
def get_document(doc_id: str, user: User = Depends(require("document:read")),
                 db: Session = Depends(get_db)):
    return _doc_out(_get_doc(db, user, doc_id))


@router.get("/{doc_id}/download")
def download(doc_id: str, request: Request, user: User = Depends(require("document:read")),
             db: Session = Depends(get_db)):
    d = _get_doc(db, user, doc_id)
    path = fs.safe_path(d.storage_path)
    if not path.exists():
        raise HTTPException(410, "Fichier indisponible : restaurer depuis la sauvegarde")
    audit(db, user.id, "document.downloaded", "document", d.id, request_id=request_id(request))
    db.commit()
    return FileResponse(path, media_type=d.mime, filename=d.original_name)
