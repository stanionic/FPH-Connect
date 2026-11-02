import hmac
import time
from collections import defaultdict, deque
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, EmailStr, Field, ValidationError, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..audit import audit
from ..db import get_db
from ..deps import get_current_user, request_id, require
from ..integrations.outbox import sync_event
from ..integrations.protocol import derive_secret, is_public_event, sign
from ..models import (Church, EntityHistory, Event, Integration, Organization, Registration, User, now)
from ..permissions import DEPARTMENTS, forbid, in_scope, in_scope_event, in_scope_org
from ..registration_service import aware, promote_waitlist, register, registered_count
from ..workflow import check_transition, jsonable, record

router = APIRouter(prefix="/api/v1/events", tags=["Événements"])
inbound = APIRouter(prefix="/api/v1/inbound", tags=["Site web → FPH"])


def _need_tz(v):
    if v is not None and v.tzinfo is None:
        raise ValueError("Date/heure avec fuseau horaire obligatoire (ex. 2026-11-20T09:00:00-05:00)")
    return v


class EventCreate(BaseModel):
    title: str = Field(min_length=3, max_length=250)
    description: str | None = Field(default=None, max_length=5000)
    starts_at: datetime
    ends_at: datetime | None = None
    location: str | None = Field(default=None, max_length=300)
    organizer_church_id: str | None = None
    organizer_org_id: str | None = None
    department: str | None = None
    capacity: int | None = Field(default=None, ge=1, le=100000)
    registration_deadline: datetime | None = None
    _tz = field_validator("starts_at", "ends_at", "registration_deadline")(classmethod(lambda cls, v: _need_tz(v)))

    @field_validator("department")
    @classmethod
    def _dept(cls, v):
        if v is not None and v not in DEPARTMENTS:
            raise ValueError("Département inconnu")
        return v


class EventUpdate(BaseModel):
    version: int
    title: str | None = Field(default=None, min_length=3, max_length=250)
    description: str | None = Field(default=None, max_length=5000)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    location: str | None = Field(default=None, max_length=300)
    capacity: int | None = Field(default=None, ge=1, le=100000)
    registration_deadline: datetime | None = None
    _tz = field_validator("starts_at", "ends_at", "registration_deadline")(classmethod(lambda cls, v: _need_tz(v)))


class TransitionIn(BaseModel):
    action: str = Field(pattern="^(submit|approve|reject|publish|withdraw|archive)$")


class RegistrationOpenIn(BaseModel):
    open: bool


class ParticipantIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=200)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=50)
    consent: bool

    def validate_contact(self):
        if not self.email and not (self.phone and any(c.isdigit() for c in self.phone)):
            raise HTTPException(422, "E-mail ou téléphone requis")
        if not self.consent:
            raise HTTPException(422, "Le consentement au traitement des données est obligatoire")


def _out(e: Event) -> dict:
    return {"id": e.id, "title": e.title, "description": e.description,
            "starts_at": aware(e.starts_at).isoformat(), "ends_at": aware(e.ends_at).isoformat() if e.ends_at else None,
            "location": e.location, "department": e.department,
            "organizer_church_id": e.organizer_church_id, "organizer_org_id": e.organizer_org_id,
            "validation_status": e.validation_status, "registration_open": e.registration_open,
            "capacity": e.capacity,
            "registration_deadline": aware(e.registration_deadline).isoformat() if e.registration_deadline else None,
            "version": e.version}


def _reg_out(r: Registration) -> dict:
    return {"id": r.id, "full_name": r.full_name, "email": r.email, "phone": r.phone,
            "source": r.source, "status": r.status,
            "checked_in_at": r.checked_in_at.isoformat() if r.checked_in_at else None,
            "created_at": r.created_at.isoformat()}


def _get(db, user, event_id) -> Event:
    e = db.get(Event, event_id)
    if e is None or not in_scope_event(user, e):
        raise HTTPException(404, "Événement introuvable")
    return e


def _check_times(starts, ends, deadline):
    if ends and aware(ends) < aware(starts):
        raise HTTPException(422, "La fin ne peut pas précéder le début")
    if deadline and aware(deadline) > aware(starts):
        raise HTTPException(422, "La date limite d'inscription doit précéder le début")


@router.post("", status_code=201)
def create(body: EventCreate, request: Request, user: User = Depends(require("event:write")),
           db: Session = Depends(get_db)):
    _check_times(body.starts_at, body.ends_at, body.registration_deadline)
    church_id, org_id, dept = body.organizer_church_id, body.organizer_org_id, body.department
    if church_id and org_id:
        raise HTTPException(422, "Un seul organisateur : église OU organisation")
    if church_id:
        c = db.get(Church, church_id)
        if c is None or not in_scope(user, c):
            raise HTTPException(404, "Église introuvable")
        dept = c.department
    elif org_id:
        o = db.get(Organization, org_id)
        if o is None or not in_scope_org(user, o):
            raise HTTPException(404, "Organisation introuvable")
        dept = o.department
    elif user.role.level <= 10:
        pass                                              # national : département facultatif
    elif user.role.code == "dept_manager":
        if dept not in (None, user.department):
            forbid("Événement hors de votre département")
        dept = user.department
    elif user.church_id:                                   # défaut : sa propre église
        church_id = user.church_id
        dept = db.get(Church, church_id).department
    elif user.organization_id:
        org_id = user.organization_id
        dept = db.get(Organization, org_id).department
    else:
        forbid()
    e = Event(title=body.title, description=body.description, starts_at=body.starts_at,
              ends_at=body.ends_at, location=body.location, department=dept,
              organizer_church_id=church_id, organizer_org_id=org_id, capacity=body.capacity,
              registration_deadline=body.registration_deadline, created_by=user.id)
    db.add(e)
    db.flush()
    record(db, "event", e, "created", {"title": e.title}, user)
    audit(db, user.id, "event.created", "event", e.id, request_id=request_id(request))
    db.commit()
    return _out(e)


@router.get("")
def list_events(status: str | None = None, department: str | None = None,
                limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0),
                user: User = Depends(require("event:read")), db: Session = Depends(get_db)):
    stmt = select(Event).order_by(Event.starts_at)
    if status:
        stmt = stmt.where(Event.validation_status == status)
    if department:
        stmt = stmt.where(Event.department == department)
    rows = [e for e in db.scalars(stmt) if in_scope_event(user, e)]
    return [_out(e) for e in rows[offset:offset + limit]]


@router.get("/{event_id}")
def get_event(event_id: str, user: User = Depends(require("event:read")), db: Session = Depends(get_db)):
    return _out(_get(db, user, event_id))


@router.patch("/{event_id}")
def update(event_id: str, body: EventUpdate, request: Request,
           user: User = Depends(require("event:write")), db: Session = Depends(get_db)):
    e = _get(db, user, event_id)
    if e.validation_status == "archived":
        raise HTTPException(409, "Un événement archivé n'est pas modifiable")
    if body.version != e.version:
        raise HTTPException(409, detail={"message": "Conflit de version", "server_version": e.version})
    data = body.model_dump(exclude_unset=True, exclude={"version"})
    changes = {k: v for k, v in data.items() if getattr(e, k) != v and
               (aware(getattr(e, k)) != aware(v) if isinstance(v, datetime) else True)}
    if not changes:
        return _out(e)
    _check_times(changes.get("starts_at", e.starts_at), changes.get("ends_at", e.ends_at),
                 changes.get("registration_deadline", e.registration_deadline))
    was_public = is_public_event(e)
    for k, v in changes.items():
        setattr(e, k, v)
    if e.validation_status in ("approved", "published", "pending"):
        changes["validation_status"] = "pending"      # contenu modifié => à revalider, retiré du site
        e.validation_status = "pending"
    e.version += 1
    db.flush()
    sync_event(db, e, was_public)
    record(db, "event", e, "updated", jsonable(changes), user)
    audit(db, user.id, "event.updated", "event", e.id, {"fields": sorted(changes)}, request_id(request))
    db.commit()
    return _out(e)


@router.post("/{event_id}/transition")
def transition(event_id: str, body: TransitionIn, request: Request,
               user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    e = _get(db, user, event_id)
    before, was_public = e.validation_status, is_public_event(e)
    e.validation_status = check_transition(user, before, body.action)
    e.version += 1
    db.flush()
    sync_event(db, e, was_public)
    record(db, "event", e, body.action, {"validation_status": [before, e.validation_status]}, user)
    audit(db, user.id, f"event.{body.action}", "event", e.id, {"from": before, "to": e.validation_status},
          request_id(request))
    db.commit()
    return _out(e)


@router.post("/{event_id}/registration")
def set_registration_open(event_id: str, body: RegistrationOpenIn, request: Request,
                          user: User = Depends(require("event:write")), db: Session = Depends(get_db)):
    """Ouvre/ferme les inscriptions SANS retirer l'événement du site (fermeture rapide possible)."""
    e = _get(db, user, event_id)
    if e.validation_status == "archived":
        raise HTTPException(409, "Événement archivé")
    if e.registration_open != body.open:
        was_public = is_public_event(e)
        e.registration_open = body.open
        e.version += 1
        db.flush()
        sync_event(db, e, was_public)
        record(db, "event", e, "registration_open" if body.open else "registration_closed", {}, user)
        audit(db, user.id, "event.registration_toggled", "event", e.id, {"open": body.open},
              request_id(request))
        db.commit()
    return _out(e)


@router.get("/{event_id}/history")
def history(event_id: str, user: User = Depends(require("event:read")), db: Session = Depends(get_db)):
    _get(db, user, event_id)
    rows = db.scalars(select(EntityHistory).where(EntityHistory.entity_type == "event",
                      EntityHistory.entity_id == event_id).order_by(EntityHistory.version, EntityHistory.at))
    return [{"version": h.version, "action": h.action, "changes": h.changes, "at": h.at.isoformat()} for h in rows]


# ---------------- inscriptions (personnel) ----------------
@router.post("/{event_id}/registrations", status_code=201)
def add_participant(event_id: str, body: ParticipantIn, request: Request,
                    user: User = Depends(require("registration:manage")), db: Session = Depends(get_db)):
    e = _get(db, user, event_id)
    if e.validation_status in ("archived", "withdrawn", "draft"):
        raise HTTPException(409, "Inscriptions impossibles pour cet événement dans son état actuel")
    body.validate_contact()
    db.execute(select(Event.id).where(Event.id == e.id).with_for_update())   # verrou (PostgreSQL)
    r, outcome = register(db, e, full_name=body.full_name, email=body.email, phone=body.phone, source="staff")
    audit(db, user.id, "registration.created", "registration", r.id, {"outcome": outcome},
          request_id(request))
    db.commit()
    return {**_reg_out(r), "outcome": outcome}


@router.get("/{event_id}/registrations")
def list_registrations(event_id: str, request: Request, status: str | None = None,
                       user: User = Depends(require("registration:manage")), db: Session = Depends(get_db)):
    e = _get(db, user, event_id)
    stmt = select(Registration).where(Registration.event_id == e.id).order_by(Registration.created_at)
    if status:
        stmt = stmt.where(Registration.status == status)
    rows = db.scalars(stmt).all()
    audit(db, user.id, "registration.listed", "event", e.id, {"count": len(rows)}, request_id(request))
    db.commit()
    return [_reg_out(r) for r in rows]


@router.get("/{event_id}/stats")
def stats(event_id: str, user: User = Depends(require("registration:manage")), db: Session = Depends(get_db)):
    e = _get(db, user, event_id)
    counts = dict(db.execute(select(Registration.status, func.count()).where(
        Registration.event_id == e.id).group_by(Registration.status)).all())
    checked = db.scalar(select(func.count()).select_from(Registration).where(
        Registration.event_id == e.id, Registration.checked_in_at.is_not(None))) or 0
    return {"capacity": e.capacity, "by_status": counts, "checked_in": checked}


reg_router = APIRouter(prefix="/api/v1/registrations", tags=["Inscriptions"])


def _reg(db, user, reg_id):
    r = db.get(Registration, reg_id)
    e = db.get(Event, r.event_id) if r else None
    if r is None or e is None or not in_scope_event(user, e):
        raise HTTPException(404, "Inscription introuvable")
    return r, e


@reg_router.post("/{reg_id}/checkin")
def checkin(reg_id: str, request: Request, user: User = Depends(require("registration:manage")),
            db: Session = Depends(get_db)):
    r, e = _reg(db, user, reg_id)
    if r.status != "registered":
        raise HTTPException(409, "Seules les personnes inscrites (non en attente, non annulées) peuvent être pointées")
    if r.checked_in_at is None:
        r.checked_in_at = now()
        audit(db, user.id, "registration.checkin", "registration", r.id, request_id=request_id(request))
        db.commit()
    return _reg_out(r)


@reg_router.post("/{reg_id}/cancel")
def cancel(reg_id: str, request: Request, user: User = Depends(require("registration:manage")),
           db: Session = Depends(get_db)):
    r, e = _reg(db, user, reg_id)
    if r.status in ("registered", "waitlisted"):
        was_registered = r.status == "registered"
        r.status = "cancelled"
        db.flush()
        promoted = promote_waitlist(db, e) if was_registered else 0
        audit(db, user.id, "registration.cancelled", "registration", r.id, {"promoted": promoted},
              request_id(request))
        db.commit()
    return _reg_out(r)


@reg_router.post("/{reg_id}/erase")
def erase(reg_id: str, request: Request, user: User = Depends(require("registration:manage")),
          db: Session = Depends(get_db)):
    """Droit à l'effacement : données personnelles anonymisées, la place libérée est réattribuée."""
    r, e = _reg(db, user, reg_id)
    was_registered = r.status == "registered"
    r.full_name, r.email, r.phone = "[supprimé]", None, None
    r.status, r.dedupe_key, r.idempotency_key = "erased", f"erased:{r.id}", None
    db.flush()
    if was_registered:
        promote_waitlist(db, e)
    audit(db, user.id, "registration.erased", "registration", r.id, request_id=request_id(request))
    db.commit()
    return _reg_out(r)


# ---------------- inscriptions envoyées par le site (signées) ----------------
class InboundRegistration(ParticipantIn):
    event_id: str


_hits: dict[str, deque] = defaultdict(deque)
RATE_LIMIT_PER_MIN = 60


def _rate_ok(key: str) -> bool:
    q, t = _hits[key], time.time()
    while q and q[0] < t - 60:
        q.popleft()
    if len(q) >= RATE_LIMIT_PER_MIN:
        return False
    q.append(t)
    return True


@inbound.post("/{integration_id}/registrations")
async def inbound_registration(integration_id: str, request: Request, db: Session = Depends(get_db)):
    """Appelé par le SERVEUR du site (jamais par le navigateur du public) : signature HMAC,
    horodatage borné, clé d'idempotence obligatoire."""
    integ = db.get(Integration, integration_id)
    if integ is None or not integ.enabled:
        raise HTTPException(404, "Intégration introuvable")
    if not _rate_ok(integration_id):
        raise HTTPException(429, "Trop de requêtes", headers={"Retry-After": "60"})
    body = await request.body()
    if len(body) > 8192:
        raise HTTPException(413, "Corps trop volumineux")
    ts = request.headers.get("X-FPH-Timestamp", "")
    sig = request.headers.get("X-FPH-Signature", "")
    if not ts.isdigit() or abs(time.time() - int(ts)) > 300 or not hmac.compare_digest(
            sign(derive_secret(integ.id, integ.secret_version), ts, body), sig):
        raise HTTPException(401, "Signature invalide")
    idem = request.headers.get("X-FPH-Idempotency-Key", "")
    if not (8 <= len(idem) <= 100):
        raise HTTPException(422, "X-FPH-Idempotency-Key requis (8 à 100 caractères)")
    try:
        data = InboundRegistration.model_validate_json(body)
    except ValidationError as ex:
        raise HTTPException(422, detail=[{"loc": x["loc"], "msg": x["msg"]} for x in ex.errors()])
    data.validate_contact()
    if integ.mode == "test":                                   # à blanc : rien n'est enregistré
        return {"status": "dry_run"}
    e = db.get(Event, data.event_id)
    if e is None or not is_public_event(e):
        raise HTTPException(404, "Événement introuvable")
    if not e.registration_open or (e.registration_deadline and aware(e.registration_deadline) < now()):
        raise HTTPException(409, "registration_closed")
    db.execute(select(Event.id).where(Event.id == e.id).with_for_update())
    r, outcome = register(db, e, full_name=data.full_name, email=data.email, phone=data.phone,
                          source="site", idempotency_key=idem)
    audit(db, None, "registration.inbound", "registration", r.id,
          {"integration": integ.id, "outcome": outcome})      # aucune donnée personnelle
    db.commit()
    return {"status": r.status, "registration_id": r.id}
