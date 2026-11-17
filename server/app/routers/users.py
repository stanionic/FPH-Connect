from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..audit import audit
from ..db import get_db
from ..deps import request_id, require
from ..models import AuthSession, Church, Organization, Role, User, now
from ..permissions import DEPARTMENTS, SHAREABLE_CODES, SHAREABLE_PERMISSIONS
from ..routers.auth import user_out
from ..schemas import UserCreate, UserOut
from ..security import check_password_policy, hash_password

router = APIRouter(prefix="/api/v1/users", tags=["Utilisateurs"])


class UserUpdate(BaseModel):
    """Modification d'un compte par un administrateur. `password` force une réinitialisation."""
    full_name: str | None = Field(default=None, min_length=2, max_length=200)
    role_code: str | None = None
    department: str | None = None
    church_id: str | None = None
    organization_id: str | None = None
    is_active: bool | None = None
    password: str | None = None
    # Droits accordés nommément (SuperAdmin uniquement).
    extra_permissions: list[str] | None = None


class PermissionsUpdate(BaseModel):
    permissions: list[str] = Field(default_factory=list)


def _require_superadmin(admin: User) -> None:
    if admin.role.code != "superadmin":
        raise HTTPException(403, "Seul le SuperAdmin peut accorder ces autorisations")


def _clean_permissions(values: list[str]) -> list[str]:
    cleaned: list[str] = []
    for value in values or []:
        if value not in SHAREABLE_CODES:
            raise HTTPException(422, f"Autorisation inconnue : {value}")
        if value not in cleaned:
            cleaned.append(value)
    return cleaned



def _role_for(admin: User, role_code: str, db: Session) -> Role:
    role = db.scalar(select(Role).where(Role.code == role_code))
    if role is None:
        raise HTTPException(422, "Rôle inconnu")
    if role.level < admin.role.level or (role.level == 0 and admin.role.level != 0):
        raise HTTPException(403, "Impossible d'attribuer un rôle supérieur ou égal au vôtre")
    return role


@router.get("", response_model=list[UserOut])
def list_users(limit: int = Query(default=100, ge=1, le=200),
               offset: int = Query(default=0, ge=0),
               admin: User = Depends(require("user:manage")), db: Session = Depends(get_db)):
    rows = db.scalars(select(User).order_by(User.full_name).limit(limit).offset(offset))
    return [user_out(user) for user in rows]


@router.post("", response_model=UserOut, status_code=201)
def create_user(body: UserCreate, request: Request,
                admin: User = Depends(require("user:manage")), db: Session = Depends(get_db)):
    role = db.scalar(select(Role).where(Role.code == body.role_code))
    if role is None:
        raise HTTPException(422, "Rôle inconnu")
    if role.level < admin.role.level or (role.level == 0 and admin.role.level != 0):
        raise HTTPException(403, "Impossible d'attribuer un rôle supérieur ou égal au vôtre")
    if role.code == "dept_manager" and body.department not in DEPARTMENTS:
        raise HTTPException(422, "Un responsable départemental doit avoir un département valide")
    if role.code in ("church_admin", "service_manager", "employee") and not (body.church_id or body.organization_id):
        raise HTTPException(422, "church_id ou organization_id obligatoire pour ce rôle")
    if body.organization_id and db.get(Organization, body.organization_id) is None:
        raise HTTPException(422, "Organisation inconnue")
    try:
        check_password_policy(body.password)
    except ValueError as e:
        raise HTTPException(422, str(e))
    extra_permissions: list[str] = []
    if body.extra_permissions:
        _require_superadmin(admin)
        extra_permissions = _clean_permissions(body.extra_permissions)
    u = User(email=body.email.lower(), username=body.username.lower() if body.username else None,
             full_name=body.full_name,
             password_hash=hash_password(body.password), role_id=role.id,
             department=body.department, church_id=body.church_id,
             organization_id=body.organization_id, extra_permissions=extra_permissions)
    db.add(u)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "E-mail ou pseudo déjà utilisé")
    audit(db, admin.id, "user.created", "user", u.id, {"role": role.code}, request_id(request))
    db.commit()
    db.refresh(u)
    return user_out(u)


@router.get("/roles")
def list_roles(_=Depends(require("user:manage")), db: Session = Depends(get_db)):
    """Rôles disponibles pour les formulaires d'administration."""
    return [{"code": r.code, "label": r.label, "level": r.level}
            for r in db.scalars(select(Role).order_by(Role.level, Role.code))]


@router.get("/permissions/catalog")
def permissions_catalog(_=Depends(require("user:manage"))):
    """Autorisations que le SuperAdmin peut accorder nommément à un utilisateur."""
    return SHAREABLE_PERMISSIONS


@router.get("/{user_id}", response_model=UserOut)
def get_user(user_id: str, _=Depends(require("user:manage")), db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(404, "Utilisateur introuvable")
    return user_out(u)


@router.patch("/{user_id}", response_model=UserOut)
def update_user(user_id: str, body: UserUpdate, request: Request,
                admin: User = Depends(require("user:manage")), db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(404, "Utilisateur introuvable")
    if u.role.level < admin.role.level and admin.role.level != 0:
        raise HTTPException(403, "Droits insuffisants sur ce compte")
    data = body.model_dump(exclude_unset=True)
    changes: dict = {}
    if "full_name" in data and data["full_name"] and data["full_name"] != u.full_name:
        u.full_name = data["full_name"]
        changes["full_name"] = True
    if data.get("role_code"):
        role = _role_for(admin, data["role_code"], db)
        if role.id != u.role_id:
            u.role_id = role.id
            changes["role"] = role.code
    if "department" in data:
        dept = data["department"] or None
        if dept is not None and dept not in DEPARTMENTS:
            raise HTTPException(422, "Département inconnu")
        if dept != u.department:
            u.department = dept
            changes["department"] = dept
    if "church_id" in data:
        if data["church_id"] and db.get(Church, data["church_id"]) is None:
            raise HTTPException(422, "Église inconnue")
        if data["church_id"] != u.church_id:
            u.church_id = data["church_id"] or None
            changes["church_id"] = u.church_id
    if "organization_id" in data:
        if data["organization_id"] and db.get(Organization, data["organization_id"]) is None:
            raise HTTPException(422, "Organisation inconnue")
        if data["organization_id"] != u.organization_id:
            u.organization_id = data["organization_id"] or None
            changes["organization_id"] = u.organization_id
    if "is_active" in data and data["is_active"] is not None and data["is_active"] != u.is_active:
        u.is_active = bool(data["is_active"])
        changes["is_active"] = u.is_active
        if not u.is_active:
            for s in db.scalars(select(AuthSession).where(AuthSession.user_id == u.id,
                                                          AuthSession.revoked_at.is_(None))):
                s.revoked_at = now()
    if data.get("password"):
        try:
            check_password_policy(data["password"])
        except ValueError as e:
            raise HTTPException(422, str(e))
        u.password_hash = hash_password(data["password"])
        u.must_change_password = True
        changes["password"] = "reset"
        for s in db.scalars(select(AuthSession).where(AuthSession.user_id == u.id,
                                                      AuthSession.revoked_at.is_(None))):
            s.revoked_at = now()
    if data.get("extra_permissions") is not None:
        permissions = _clean_permissions(data["extra_permissions"])
        if permissions != list(u.extra_permissions or []):
            _require_superadmin(admin)
            u.extra_permissions = permissions
            changes["extra_permissions"] = permissions
    if not changes:
        return user_out(u)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "E-mail ou pseudo déjà utilisé")
    audit(db, admin.id, "user.updated", "user", u.id, {"fields": sorted(changes)}, request_id=request_id(request))
    db.commit()
    db.refresh(u)
    return user_out(u)


@router.put("/{user_id}/permissions", response_model=UserOut)
def set_permissions(user_id: str, body: PermissionsUpdate, request: Request,
                    admin: User = Depends(require("user:manage")), db: Session = Depends(get_db)):
    """Accorde ou retire les autorisations nominales d'un compte (SuperAdmin uniquement)."""
    _require_superadmin(admin)
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(404, "Utilisateur introuvable")
    permissions = _clean_permissions(body.permissions)
    if permissions != list(u.extra_permissions or []):
        u.extra_permissions = permissions
        audit(db, admin.id, "user.permissions_updated", "user", u.id,
              {"permissions": permissions}, request_id=request_id(request))
        db.commit()
        db.refresh(u)
    return user_out(u)


@router.post("/{user_id}/activate", response_model=UserOut)
def activate(user_id: str, request: Request,
             admin: User = Depends(require("user:manage")), db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(404, "Utilisateur introuvable")
    u.is_active = True
    audit(db, admin.id, "user.activated", "user", u.id, request_id=request_id(request))
    db.commit()
    db.refresh(u)
    return user_out(u)


@router.delete("/{user_id}", response_model=UserOut)
def archive_user(user_id: str, request: Request,
                 admin: User = Depends(require("user:manage")), db: Session = Depends(get_db)):
    """« Supprimer » = archiver : le compte est désactivé, jamais effacé (audit et historique)."""
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(404, "Utilisateur introuvable")
    if u.role.level <= admin.role.level and u.id != admin.id and admin.role.level != 0:
        raise HTTPException(403, "Droits insuffisants sur ce compte")
    u.is_active = False
    for s in db.scalars(select(AuthSession).where(AuthSession.user_id == u.id,
                                                  AuthSession.revoked_at.is_(None))):
        s.revoked_at = now()
    audit(db, admin.id, "user.archived", "user", u.id, request_id=request_id(request))
    db.commit()
    db.refresh(u)
    return user_out(u)


@router.post("/{user_id}/deactivate", status_code=204)
def deactivate(user_id: str, request: Request,
               admin: User = Depends(require("user:manage")), db: Session = Depends(get_db)):
    """Désactivation immédiate : compte bloqué et toutes les sessions révoquées."""
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(404, "Utilisateur introuvable")
    if u.role.level <= admin.role.level and u.id != admin.id and admin.role.level != 0:
        raise HTTPException(403, "Droits insuffisants sur ce compte")
    u.is_active = False
    for s in db.scalars(select(AuthSession).where(AuthSession.user_id == u.id,
                                                  AuthSession.revoked_at.is_(None))):
        s.revoked_at = now()
    audit(db, admin.id, "user.deactivated", "user", u.id, request_id=request_id(request))
    db.commit()
