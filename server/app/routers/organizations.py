from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..audit import audit
from ..db import get_db
from ..deps import get_current_user, request_id, require
from ..models import EntityHistory, Organization, User
from ..permissions import DEPARTMENT_UNKNOWN, DEPARTMENTS, ORG_TYPES, forbid, in_scope_org
from ..workflow import check_transition, jsonable, record

router = APIRouter(prefix="/api/v1/organizations", tags=["Organisations affiliées"])
AFFIL = "^(pending|affiliated|suspended)$"


def _dept(v):
    # « À déterminer » est une valeur du registre, pas un département : acceptée en conscience, elle
    # place la fiche hors de la portée de tout responsable départemental jusqu'à sa relecture.
    if v is not None and v not in DEPARTMENTS and v != DEPARTMENT_UNKNOWN:
        raise ValueError(f"Département inconnu (ou « {DEPARTMENT_UNKNOWN} »)")
    return v


def _type(v):
    if v is not None and v not in ORG_TYPES:
        raise ValueError(f"Type inconnu. Valeurs : {', '.join(ORG_TYPES)}")
    return v


class OrgCreate(BaseModel):
    name: str = Field(min_length=2, max_length=250)
    org_type: str
    department: str
    commune: str | None = Field(default=None, max_length=100)
    address: str | None = Field(default=None, max_length=1000)
    contact_email: EmailStr | None = None
    contact_phone: str | None = Field(default=None, max_length=50)
    affiliation_status: str = Field(default="pending", pattern=AFFIL)
    _v1 = field_validator("department")(classmethod(lambda cls, v: _dept(v)))
    _v2 = field_validator("org_type")(classmethod(lambda cls, v: _type(v)))


class OrgUpdate(BaseModel):
    version: int
    name: str | None = Field(default=None, min_length=2, max_length=250)
    org_type: str | None = None
    # Le département est modifiable : une fiche reprise d'un registre externe peut avoir été créée avec
    # un département à déterminer, et la relecture est justement là pour le corriger.
    department: str | None = None
    commune: str | None = None
    address: str | None = None
    contact_email: EmailStr | None = None
    contact_phone: str | None = None
    affiliation_status: str | None = Field(default=None, pattern=AFFIL)
    _v1 = field_validator("department")(classmethod(lambda cls, v: _dept(v)))
    _v2 = field_validator("org_type")(classmethod(lambda cls, v: _type(v)))


class TransitionIn(BaseModel):
    action: str = Field(pattern="^(submit|approve|reject|publish|withdraw|archive)$")


def _key(name: str) -> str:
    return " ".join(name.lower().split())


def _out(o: Organization) -> dict:
    return {"id": o.id, "name": o.name, "org_type": o.org_type, "department": o.department,
            "commune": o.commune, "address": o.address, "contact_email": o.contact_email,
            "contact_phone": o.contact_phone, "validation_status": o.validation_status,
            "affiliation_status": o.affiliation_status, "version": o.version}


def _get(db, user, oid) -> Organization:
    o = db.get(Organization, oid)
    if o is None or not in_scope_org(user, o):
        raise HTTPException(404, "Organisation introuvable")
    return o


@router.post("", status_code=201)
def create(body: OrgCreate, request: Request, user: User = Depends(require("org:write")),
           db: Session = Depends(get_db)):
    if user.role.level > 20:
        forbid("Création réservée aux niveaux national et départemental")
    if user.role.code == "dept_manager" and body.department != user.department:
        forbid("Création hors de votre département")
    o = Organization(**body.model_dump(), name_key=_key(body.name), created_by=user.id)
    db.add(o)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Une organisation de même nom existe déjà")
    record(db, "organization", o, "created", jsonable(body.model_dump()), user)
    audit(db, user.id, "organization.created", "organization", o.id, request_id=request_id(request))
    db.commit()
    return _out(o)


@router.get("")
def list_orgs(department: str | None = None, status: str | None = None,
              q: str | None = Query(default=None, max_length=100),
              limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0),
              user: User = Depends(require("org:read")), db: Session = Depends(get_db)):
    stmt = select(Organization).order_by(Organization.name)
    if department:
        stmt = stmt.where(Organization.department == department)
    if status:
        stmt = stmt.where(Organization.validation_status == status)
    if q:
        stmt = stmt.where(func.lower(Organization.name).like(f"%{q.lower()}%"))
    rows = [o for o in db.scalars(stmt) if in_scope_org(user, o)]
    return [_out(o) for o in rows[offset:offset + limit]]


@router.get("/{oid}")
def get_org(oid: str, user: User = Depends(require("org:read")), db: Session = Depends(get_db)):
    return _out(_get(db, user, oid))


@router.patch("/{oid}")
def update(oid: str, body: OrgUpdate, request: Request, user: User = Depends(require("org:write")),
           db: Session = Depends(get_db)):
    o = _get(db, user, oid)
    if o.validation_status == "archived":
        raise HTTPException(409, "Une organisation archivée n'est pas modifiable")
    if body.version != o.version:
        raise HTTPException(409, detail={"message": "Conflit de version", "server_version": o.version})
    changes = {k: v for k, v in body.model_dump(exclude_unset=True, exclude={"version"}).items()
               if getattr(o, k) != v}
    if not changes:
        return _out(o)
    for k, v in changes.items():
        setattr(o, k, v)
    o.name_key = _key(o.name)
    if o.validation_status in ("approved", "published", "pending"):
        changes["validation_status"] = "pending"      # modification => à revalider
        o.validation_status = "pending"
    o.version += 1
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Une organisation de même nom existe déjà")
    record(db, "organization", o, "updated", jsonable(changes), user)
    audit(db, user.id, "organization.updated", "organization", o.id, {"fields": sorted(changes)},
          request_id(request))
    db.commit()
    return _out(o)


@router.post("/{oid}/transition")
def transition(oid: str, body: TransitionIn, request: Request,
               user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    o = _get(db, user, oid)
    before = o.validation_status
    o.validation_status = check_transition(user, before, body.action)
    o.version += 1
    record(db, "organization", o, body.action, {"validation_status": [before, o.validation_status]}, user)
    audit(db, user.id, f"organization.{body.action}", "organization", o.id,
          {"from": before, "to": o.validation_status}, request_id(request))
    db.commit()
    return _out(o)


@router.get("/{oid}/history")
def history(oid: str, user: User = Depends(require("org:read")), db: Session = Depends(get_db)):
    _get(db, user, oid)
    rows = db.scalars(select(EntityHistory).where(EntityHistory.entity_type == "organization",
                      EntityHistory.entity_id == oid).order_by(EntityHistory.version, EntityHistory.at))
    return [{"version": h.version, "action": h.action, "changes": h.changes, "actor_id": h.actor_id,
             "at": h.at.isoformat()} for h in rows]
