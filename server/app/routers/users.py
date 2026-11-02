from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..audit import audit
from ..db import get_db
from ..deps import request_id, require
from ..models import AuthSession, Organization, Role, User, now
from ..permissions import DEPARTMENTS
from ..routers.auth import user_out
from ..schemas import UserCreate, UserOut
from ..security import check_password_policy, hash_password

router = APIRouter(prefix="/api/v1/users", tags=["Utilisateurs"])


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
    u = User(email=body.email.lower(), username=body.username.lower() if body.username else None,
             full_name=body.full_name,
             password_hash=hash_password(body.password), role_id=role.id,
             department=body.department, church_id=body.church_id,
             organization_id=body.organization_id)
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
