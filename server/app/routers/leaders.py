from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import audit
from ..db import get_db
from ..deps import request_id, require
from ..models import Church, EntityHistory, Leader, LeaderAssignment, Organization, User
from ..permissions import LEADER_FUNCTIONS, in_scope, in_scope_org
from ..workflow import jsonable, record

router = APIRouter(prefix="/api/v1/leaders", tags=["Pasteurs et responsables"])
STATUSES = "^(active|suspended|inactive|retired)$"


class LeaderCreate(BaseModel):
    full_name: str = Field(min_length=2, max_length=200)
    function: str
    church_id: str | None = None
    organization_id: str | None = None
    professional_phone: str | None = Field(default=None, max_length=50)
    professional_email: EmailStr | None = None
    start_date: date | None = None

    @field_validator("function")
    @classmethod
    def _fn(cls, v):
        if v not in LEADER_FUNCTIONS:
            raise ValueError(f"Fonction inconnue. Valeurs : {', '.join(LEADER_FUNCTIONS)}")
        return v


class LeaderUpdate(BaseModel):
    version: int
    full_name: str | None = Field(default=None, min_length=2, max_length=200)
    function: str | None = None
    church_id: str | None = None
    organization_id: str | None = None
    professional_phone: str | None = Field(default=None, max_length=50)
    professional_email: EmailStr | None = None
    admin_status: str | None = Field(default=None, pattern=STATUSES)

    @field_validator("function")
    @classmethod
    def _fn(cls, v):
        if v is not None and v not in LEADER_FUNCTIONS:
            raise ValueError("Fonction inconnue")
        return v


def _out(l: Leader) -> dict:
    return {"id": l.id, "full_name": l.full_name, "function": l.function, "church_id": l.church_id,
            "organization_id": l.organization_id, "professional_phone": l.professional_phone,
            "professional_email": l.professional_email, "admin_status": l.admin_status,
            "version": l.version}


def _leader_in_scope(db: Session, user: User, l: Leader) -> bool:
    if l.church_id:
        c = db.get(Church, l.church_id)
        if c is not None and in_scope(user, c):
            return True
    if l.organization_id:
        o = db.get(Organization, l.organization_id)
        if o is not None and in_scope_org(user, o):
            return True
    return False


def _target_in_scope(db, user, church_id, org_id) -> None:
    """L'auteur doit avoir autorité sur l'église/l'organisation de rattachement."""
    if not church_id and not org_id:
        raise HTTPException(422, "Rattachement requis : church_id ou organization_id")
    if church_id:
        c = db.get(Church, church_id)
        if c is None or not in_scope(user, c):
            raise HTTPException(404, "Église introuvable")
    if org_id:
        o = db.get(Organization, org_id)
        if o is None or not in_scope_org(user, o):
            raise HTTPException(404, "Organisation introuvable")


def _get(db, user, leader_id) -> Leader:
    l = db.get(Leader, leader_id)
    if l is None or not _leader_in_scope(db, user, l):
        raise HTTPException(404, "Responsable introuvable")
    return l


@router.post("", status_code=201)
def create(body: LeaderCreate, request: Request, user: User = Depends(require("leader:write")),
           db: Session = Depends(get_db)):
    _target_in_scope(db, user, body.church_id, body.organization_id)
    dup = db.scalar(select(Leader.id).where(
        Leader.full_name == body.full_name, Leader.function == body.function,
        Leader.church_id == body.church_id, Leader.organization_id == body.organization_id,
        Leader.admin_status == "active"))
    if dup:
        raise HTTPException(409, "Ce responsable existe déjà pour ce rattachement")
    l = Leader(full_name=body.full_name, function=body.function, church_id=body.church_id,
               organization_id=body.organization_id, professional_phone=body.professional_phone,
               professional_email=body.professional_email, created_by=user.id)
    db.add(l)
    db.flush()
    db.add(LeaderAssignment(leader_id=l.id, church_id=l.church_id, organization_id=l.organization_id,
                            function=l.function, start_date=body.start_date or date.today(),
                            recorded_by=user.id))
    record(db, "leader", l, "created", {"function": l.function}, user)   # pas de données perso dans l'historique
    audit(db, user.id, "leader.created", "leader", l.id, request_id=request_id(request))
    db.commit()
    return _out(l)


@router.get("")
def list_leaders(church_id: str | None = None, organization_id: str | None = None,
                 status: str | None = None, limit: int = Query(default=100, ge=1, le=500),
                 offset: int = Query(default=0, ge=0),
                 user: User = Depends(require("leader:read")), db: Session = Depends(get_db)):
    stmt = select(Leader).order_by(Leader.full_name)
    if church_id:
        stmt = stmt.where(Leader.church_id == church_id)
    if organization_id:
        stmt = stmt.where(Leader.organization_id == organization_id)
    if status:
        stmt = stmt.where(Leader.admin_status == status)
    rows = [l for l in db.scalars(stmt) if _leader_in_scope(db, user, l)]
    return [_out(l) for l in rows[offset:offset + limit]]


@router.get("/{leader_id}")
def get_leader(leader_id: str, request: Request, user: User = Depends(require("leader:read")),
               db: Session = Depends(get_db)):
    l = _get(db, user, leader_id)
    audit(db, user.id, "leader.viewed", "leader", l.id, request_id=request_id(request))  # données sensibles
    db.commit()
    return _out(l)


@router.patch("/{leader_id}")
def update(leader_id: str, body: LeaderUpdate, request: Request,
           user: User = Depends(require("leader:write")), db: Session = Depends(get_db)):
    l = _get(db, user, leader_id)
    if body.version != l.version:
        raise HTTPException(409, detail={"message": "Conflit de version", "server_version": l.version})
    data = body.model_dump(exclude_unset=True, exclude={"version"})
    new_church = data.get("church_id", l.church_id)
    new_org = data.get("organization_id", l.organization_id)
    if ("church_id" in data or "organization_id" in data) and (
            new_church != l.church_id or new_org != l.organization_id):
        _target_in_scope(db, user, new_church, new_org)
    changes = {k: v for k, v in data.items() if getattr(l, k) != v}
    if not changes:
        return _out(l)
    reassigned = any(k in changes for k in ("function", "church_id", "organization_id"))
    for k, v in changes.items():
        setattr(l, k, v)
    if not l.church_id and not l.organization_id:
        raise HTTPException(422, "Rattachement requis")
    l.version += 1
    if reassigned:   # clôt l'affectation courante et en ouvre une nouvelle
        for a in db.scalars(select(LeaderAssignment).where(
                LeaderAssignment.leader_id == l.id, LeaderAssignment.end_date.is_(None))):
            a.end_date = date.today()
        db.add(LeaderAssignment(leader_id=l.id, church_id=l.church_id, organization_id=l.organization_id,
                                function=l.function, start_date=date.today(), recorded_by=user.id))
    record(db, "leader", l, "updated", {"fields": sorted(changes)}, user)   # noms des champs seulement
    audit(db, user.id, "leader.updated", "leader", l.id, {"fields": sorted(changes)}, request_id(request))
    db.commit()
    return _out(l)


@router.get("/{leader_id}/assignments")
def assignments(leader_id: str, user: User = Depends(require("leader:read")), db: Session = Depends(get_db)):
    _get(db, user, leader_id)
    rows = db.scalars(select(LeaderAssignment).where(LeaderAssignment.leader_id == leader_id)
                      .order_by(LeaderAssignment.start_date, LeaderAssignment.id))
    return [{"church_id": a.church_id, "organization_id": a.organization_id, "function": a.function,
             "start_date": a.start_date.isoformat(),
             "end_date": a.end_date.isoformat() if a.end_date else None} for a in rows]
