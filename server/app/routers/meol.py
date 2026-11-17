"""Enregistrement des MEOL (Mission, Église, Organisation, Ligue).

Le formulaire public crée une fiche `pending` (organisation + responsable + programmes
annuels). Seul un SuperAdministrateur peut approuver ou rejeter l'enregistrement.
"""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..audit import audit
from ..db import get_db
from ..deps import get_current_user, request_id, require
from ..models import (EntityHistory, Leader, LeaderAssignment, Organization,
                      OrganizationProgram, User)
from ..permissions import (DEPARTMENTS, DEPARTMENT_UNKNOWN, LEADER_FUNCTIONS, MEOL_TYPES,
                           in_scope_org)
from ..workflow import check_transition, jsonable, record

router = APIRouter(prefix="/api/v1/meol", tags=["MEOL (Mission, Église, Organisation, Ligue)"])
PUBLIC = APIRouter(prefix="/api/v1/public/meol", tags=["MEOL — enregistrement public"])


def require_superadmin(user: User = Depends(get_current_user)) -> User:
    """L'approbation d'un MEOL est réservée au SuperAdministrateur, pas à tout valideur."""
    if user.role.code != "superadmin":
        raise HTTPException(403, "Approbation réservée au SuperAdministrateur")
    return user


# --------------------------------------------------------------------------- schémas

class ProgramIn(BaseModel):
    year: int = Field(ge=2000, le=2100)
    title: str = Field(min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=4000)


class LeaderIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=200)
    function: str = "responsable_principal"
    professional_phone: str | None = Field(default=None, max_length=50)
    professional_email: EmailStr | None = None

    @field_validator("function")
    @classmethod
    def _fn(cls, v):
        if v not in LEADER_FUNCTIONS:
            raise ValueError(f"Fonction inconnue. Valeurs : {', '.join(LEADER_FUNCTIONS)}")
        return v


class MeolRegisterIn(BaseModel):
    name: str = Field(min_length=2, max_length=250)
    org_type: str
    department: str
    commune: str | None = Field(default=None, max_length=100)
    address: str | None = Field(default=None, max_length=2000)
    contact_email: EmailStr | None = None
    contact_phone: str | None = Field(default=None, max_length=50)
    leader: LeaderIn
    programs: list[ProgramIn] = Field(default_factory=list, max_length=50)

    @field_validator("org_type")
    @classmethod
    def _type(cls, v):
        if v not in MEOL_TYPES:
            raise ValueError(f"Catégorie MEOL inconnue. Valeurs : {', '.join(MEOL_TYPES)}")
        return v

    @field_validator("department")
    @classmethod
    def _dept(cls, v):
        if v not in DEPARTMENTS and v != DEPARTMENT_UNKNOWN:
            raise ValueError("Département inconnu")
        return v


class DecisionIn(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)


# --------------------------------------------------------------------------- sorties

def _key(name: str) -> str:
    return " ".join(name.lower().split())


def _leader_out(l: Leader) -> dict:
    return {"id": l.id, "full_name": l.full_name, "function": l.function,
            "professional_phone": l.professional_phone,
            "professional_email": l.professional_email, "admin_status": l.admin_status}


def _program_out(p: OrganizationProgram) -> dict:
    return {"id": p.id, "year": p.year, "title": p.title, "description": p.description}


def _leaders(db: Session, oid: str) -> list[Leader]:
    return list(db.scalars(select(Leader).where(Leader.organization_id == oid)
                           .order_by(Leader.created_at)))


def _programs(db: Session, oid: str) -> list[OrganizationProgram]:
    return list(db.scalars(select(OrganizationProgram)
                           .where(OrganizationProgram.organization_id == oid)
                           .order_by(OrganizationProgram.year.desc(), OrganizationProgram.title)))


def _out(db: Session, o: Organization, full: bool = True) -> dict:
    data = {"id": o.id, "name": o.name, "org_type": o.org_type, "department": o.department,
            "commune": o.commune, "address": o.address, "contact_email": o.contact_email,
            "contact_phone": o.contact_phone, "validation_status": o.validation_status,
            "affiliation_status": o.affiliation_status, "version": o.version,
            "created_at": o.created_at.isoformat() if o.created_at else None}
    if full:
        leaders = _leaders(db, o.id)
        data["leader"] = _leader_out(leaders[0]) if leaders else None
        data["leaders"] = [_leader_out(l) for l in leaders]
        data["programs"] = [_program_out(p) for p in _programs(db, o.id)]
    return data


def _get(db: Session, oid: str) -> Organization:
    o = db.get(Organization, oid)
    if o is None or o.org_type not in MEOL_TYPES:
        raise HTTPException(404, "Enregistrement MEOL introuvable")
    return o


# --------------------------------------------------------------------------- public

@PUBLIC.get("/options")
def options():
    """Valeurs autorisées pour le formulaire (aucune authentification)."""
    return {"org_types": MEOL_TYPES, "departments": DEPARTMENTS + [DEPARTMENT_UNKNOWN],
            "leader_functions": LEADER_FUNCTIONS,
            "program_year": date.today().year}


@PUBLIC.post("/register", status_code=201)
def register(body: MeolRegisterIn, request: Request, db: Session = Depends(get_db)):
    """Dépose une demande d'enregistrement MEOL. Elle reste `pending` jusqu'à l'approbation
    d'un SuperAdministrateur."""
    o = Organization(name=body.name, name_key=_key(body.name), org_type=body.org_type,
                     department=body.department, commune=body.commune, address=body.address,
                     contact_email=str(body.contact_email) if body.contact_email else None,
                     contact_phone=body.contact_phone,
                     validation_status="pending", affiliation_status="pending", created_by=None)
    db.add(o)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Un MEOL portant ce nom existe déjà")

    leader = Leader(full_name=body.leader.full_name, function=body.leader.function,
                    organization_id=o.id,
                    professional_phone=body.leader.professional_phone,
                    professional_email=str(body.leader.professional_email)
                    if body.leader.professional_email else None,
                    created_by=None)
    db.add(leader)
    db.flush()
    db.add(LeaderAssignment(leader_id=leader.id, organization_id=o.id, function=leader.function,
                            start_date=date.today(), recorded_by=None))

    for p in body.programs:
        db.add(OrganizationProgram(organization_id=o.id, year=p.year, title=p.title,
                                   description=p.description, created_by=None))

    db.add(EntityHistory(entity_type="organization", entity_id=o.id, version=o.version,
                         action="registered", actor_id=None,
                         changes=jsonable({"name": o.name, "org_type": o.org_type,
                                           "department": o.department,
                                           "programs": len(body.programs)})))
    audit(db, None, "meol.registered", "organization", o.id,
          {"name": o.name, "org_type": o.org_type}, request_id=request_id(request))
    db.commit()
    return {"id": o.id, "name": o.name, "validation_status": o.validation_status,
            "message": "Demande envoyée. Elle sera visible après approbation d'un SuperAdministrateur."}


# --------------------------------------------------------------------------- SuperAdmin

@router.get("/pending")
def pending(status: str = Query(default="pending",
                                pattern="^(pending|approved|draft|published|withdrawn|archived|all)$"),
            q: str | None = Query(default=None, max_length=100),
            limit: int = Query(default=100, ge=1, le=200), offset: int = Query(default=0, ge=0),
            user: User = Depends(require_superadmin), db: Session = Depends(get_db)):
    """Liste des enregistrements MEOL à traiter (SuperAdministrateur uniquement)."""
    stmt = select(Organization).where(Organization.org_type.in_(MEOL_TYPES))
    if status != "all":
        stmt = stmt.where(Organization.validation_status == status)
    if q:
        stmt = stmt.where(Organization.name.ilike(f"%{q}%"))
    rows = list(db.scalars(stmt.order_by(Organization.created_at.desc())
                           .limit(limit).offset(offset)))
    return [_out(db, o) for o in rows]


@router.get("/{oid}")
def get_meol(oid: str, user: User = Depends(require_superadmin), db: Session = Depends(get_db)):
    return _out(db, _get(db, oid))


@router.post("/{oid}/approve")
def approve(oid: str, request: Request, body: DecisionIn | None = None,
            user: User = Depends(require_superadmin), db: Session = Depends(get_db)):
    o = _get(db, oid)
    before = o.validation_status
    o.validation_status = check_transition(user, before, "approve")
    o.affiliation_status = "affiliated"
    o.version += 1
    record(db, "organization", o, "approve", {"validation_status": [before, o.validation_status]}, user)
    audit(db, user.id, "meol.approved", "organization", o.id,
          {"from": before, "to": o.validation_status,
           "reason": body.reason if body else None}, request_id=request_id(request))
    db.commit()
    return _out(db, o)


@router.post("/{oid}/reject")
def reject(oid: str, request: Request, body: DecisionIn | None = None,
           user: User = Depends(require_superadmin), db: Session = Depends(get_db)):
    o = _get(db, oid)
    before = o.validation_status
    o.validation_status = check_transition(user, before, "reject")
    o.version += 1
    record(db, "organization", o, "reject", {"validation_status": [before, o.validation_status]}, user)
    audit(db, user.id, "meol.rejected", "organization", o.id,
          {"from": before, "to": o.validation_status,
           "reason": body.reason if body else None}, request_id=request_id(request))
    db.commit()
    return _out(db, o)


@router.post("/{oid}/programs", status_code=201)
def add_program(oid: str, body: ProgramIn, request: Request,
                user: User = Depends(require("org:write")), db: Session = Depends(get_db)):
    """Ajoute un programme annuel à un MEOL existant (personnel autorisé)."""
    o = _get(db, oid)
    if not in_scope_org(user, o):
        raise HTTPException(404, "Enregistrement MEOL introuvable")
    p = OrganizationProgram(organization_id=o.id, year=body.year, title=body.title,
                            description=body.description, created_by=user.id)
    db.add(p)
    db.flush()
    audit(db, user.id, "meol.program_added", "organization", o.id,
          {"year": body.year, "title": body.title}, request_id=request_id(request))
    db.commit()
    return _program_out(p)
