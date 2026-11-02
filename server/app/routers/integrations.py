from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..audit import audit
from ..config import settings
from ..db import get_db
from ..deps import request_id, require
from ..integrations.dispatcher import default_sender, process_pending
from ..integrations.outbox import enqueue, live_state
from ..integrations.protocol import derive_secret, is_public, is_public_event
from ..models import Church, Event, Integration, OutboxItem, User, now

router = APIRouter(prefix="/api/v1/admin/integrations", tags=["Publication sur le site"])


def get_sender():
    """Surchargeable dans les tests (aucun appel réseau réel)."""
    return default_sender


class IntegrationCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    kind: str = Field(pattern="^(wordpress|flask|generic)$")
    base_url: str = Field(max_length=500)


class IntegrationPatch(BaseModel):
    enabled: bool | None = None
    mode: str | None = Field(default=None, pattern="^(test|live)$")
    base_url: str | None = Field(default=None, max_length=500)


def _check_url(url: str):
    u = urlparse(url)
    if u.scheme not in ("https", "http") or not u.netloc:
        raise HTTPException(422, "URL invalide")
    if settings.env == "prod" and u.scheme != "https":
        raise HTTPException(422, "HTTPS obligatoire en production")


def _out(i: Integration, secret: str | None = None):
    d = {"id": i.id, "name": i.name, "kind": i.kind, "base_url": i.base_url,
         "enabled": i.enabled, "mode": i.mode, "secret_version": i.secret_version}
    if secret:
        d["secret"] = secret   # affiché UNE seule fois (création / rotation)
    return d


def _get(db, iid) -> Integration:
    i = db.get(Integration, iid)
    if i is None:
        raise HTTPException(404, "Intégration introuvable")
    return i


@router.post("", status_code=201)
def create(body: IntegrationCreate, request: Request,
           admin: User = Depends(require("integration:manage")), db: Session = Depends(get_db)):
    _check_url(body.base_url)
    i = Integration(name=body.name, kind=body.kind, base_url=body.base_url.rstrip("/"))
    db.add(i)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Nom déjà utilisé")
    audit(db, admin.id, "integration.created", "integration", i.id, {"kind": i.kind},
          request_id(request))
    db.commit()
    return _out(i, derive_secret(i.id, i.secret_version))   # créée désactivée, en mode test


@router.get("")
def list_integrations(_=Depends(require("integration:manage")), db: Session = Depends(get_db)):
    return [_out(i) for i in db.scalars(select(Integration).order_by(Integration.name))]


@router.patch("/{iid}")
def patch(iid: str, body: IntegrationPatch, request: Request,
          admin: User = Depends(require("integration:manage")), db: Session = Depends(get_db)):
    i = _get(db, iid)
    changes = body.model_dump(exclude_unset=True)
    if "base_url" in changes:
        _check_url(changes["base_url"])
        changes["base_url"] = changes["base_url"].rstrip("/")
    for k, v in changes.items():
        setattr(i, k, v)
    audit(db, admin.id, "integration.updated", "integration", i.id, changes, request_id(request))
    db.commit()
    return _out(i)


@router.post("/{iid}/rotate-secret")
def rotate(iid: str, request: Request,
           admin: User = Depends(require("integration:manage")), db: Session = Depends(get_db)):
    i = _get(db, iid)
    i.secret_version += 1
    audit(db, admin.id, "integration.secret_rotated", "integration", i.id,
          request_id=request_id(request))
    db.commit()
    return _out(i, derive_secret(i.id, i.secret_version))


@router.post("/{iid}/resync")
def resync(iid: str, request: Request,
           admin: User = Depends(require("integration:manage")), db: Session = Depends(get_db)):
    """Met en file toutes les fiches actuellement publiques (première synchro, ou
    réactivation après une période de désactivation)."""
    i = _get(db, iid)
    n = 0
    for c in db.scalars(select(Church).where(Church.validation_status == "published")):
        if is_public(c):
            enqueue(db, i, c, "upsert")
            n += 1
    for ev in db.scalars(select(Event).where(Event.validation_status == "published")):
        if is_public_event(ev):
            enqueue(db, i, ev, "upsert", "event")
            n += 1
    audit(db, admin.id, "integration.resync", "integration", i.id, {"queued": n},
          request_id(request))
    db.commit()
    return {"queued": n}


@router.post("/{iid}/rollback")
def rollback(iid: str, request: Request,
             admin: User = Depends(require("integration:manage")), db: Session = Depends(get_db)):
    """Retour arrière : demande au site de retirer tout ce que cette intégration y a publié.
    Réversible (WordPress : brouillon, pas de suppression) ; `resync` republie."""
    i = _get(db, iid)
    n = 0
    for (kind, eid), last in live_state(db, i.id).items():
        if last.action == "upsert":
            ent = db.get(Church if kind == "church" else Event, eid)
            if ent is not None:
                enqueue(db, i, ent, "remove", kind)
                n += 1
    audit(db, admin.id, "integration.rollback", "integration", i.id, {"queued": n},
          request_id(request))
    db.commit()
    return {"queued_removals": n}


@router.get("/{iid}/export")
def export(iid: str, _=Depends(require("integration:manage")), db: Session = Depends(get_db)):
    """Sauvegarde : état que le site est censé afficher (dernier envoi réussi par fiche)."""
    i = _get(db, iid)
    return {"integration": i.name, "exported_at": now().isoformat(),
            "churches": [{"church_id": eid, "seq": it.id, "data": it.payload}
                         for (k, eid), it in live_state(db, i.id).items()
                         if it.action == "upsert" and k == "church"],
            "events": [{"event_id": eid, "seq": it.id, "data": it.payload}
                       for (k, eid), it in live_state(db, i.id).items()
                       if it.action == "upsert" and k == "event"]}


@router.get("/{iid}/outbox")
def outbox(iid: str, status: str | None = None, limit: int = Query(default=50, ge=1, le=500),
           _=Depends(require("integration:manage")), db: Session = Depends(get_db)):
    _get(db, iid)
    stmt = select(OutboxItem).where(OutboxItem.integration_id == iid)
    if status:
        stmt = stmt.where(OutboxItem.status == status)
    return [{"seq": o.id, "kind": o.kind, "church_id": o.church_id, "action": o.action, "status": o.status,
             "attempts": o.attempts, "http_status": o.last_http_status, "error": o.last_error,
             "next_attempt_at": o.next_attempt_at.isoformat(),
             "payload": o.payload} for o in db.scalars(stmt.order_by(OutboxItem.id.desc()).limit(limit))]


@router.post("/outbox/{seq}/requeue")
def requeue(seq: int, request: Request,
            admin: User = Depends(require("integration:manage")), db: Session = Depends(get_db)):
    o = db.get(OutboxItem, seq)
    if o is None or o.status not in ("dead", "failed"):
        raise HTTPException(404, "Élément introuvable ou non relançable")
    o.status, o.attempts, o.next_attempt_at = "pending", 0, now()
    audit(db, admin.id, "integration.requeue", "outbox", str(seq), request_id=request_id(request))
    db.commit()
    return {"status": "pending"}


@router.post("/dispatch")
def dispatch(_=Depends(require("integration:manage")), db: Session = Depends(get_db),
             sender=Depends(get_sender)):
    return process_pending(db, sender)
