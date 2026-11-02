from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..audit import audit
from ..config import settings
from ..db import get_db
from ..deps import get_current_user, request_id
from ..models import AuthSession, LoginEvent, User, now
from ..schemas import LoginIn, PasswordChange, TokenOut, UserOut
from ..security import (check_password_policy, create_token, hash_password,
                        session_expiry, verify_password)

router = APIRouter(prefix="/api/v1/auth", tags=["Authentification"])


def user_out(u: User) -> UserOut:
    return UserOut(id=u.id, email=u.email, username=u.username,
                   must_change_password=u.must_change_password, full_name=u.full_name, role=u.role.code,
                   department=u.department, church_id=u.church_id,
                   organization_id=u.organization_id, is_active=u.is_active,
                   permissions=u.role.permissions or [])


def _aware(dt):
    from datetime import timezone
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    email = body.login_id           # e-mail ou pseudo (insensible à la casse)
    if not email:
        raise HTTPException(422, "Identifiant requis")
    ip = request.client.host if request.client else None
    user = db.scalar(select(User).where(or_(User.email == email, User.username == email)))
    generic = HTTPException(401, "Identifiants invalides")

    if user and user.locked_until and _aware(user.locked_until) > now():
        db.add(LoginEvent(email=email, success=False, ip=ip))
        db.commit()
        raise HTTPException(423, "Compte temporairement verrouillé. Réessayez plus tard.")

    ok = bool(user) and user.is_active and verify_password(body.password, user.password_hash)
    db.add(LoginEvent(email=email, success=ok, ip=ip))
    if not ok:
        if user:
            user.failed_logins += 1
            if user.failed_logins >= settings.max_failed_logins:
                user.locked_until = now() + timedelta(minutes=settings.lock_minutes)
                user.failed_logins = 0
                audit(db, user.id, "auth.locked", "user", user.id, request_id=request_id(request))
        db.commit()
        raise generic

    user.failed_logins = 0
    user.locked_until = None
    exp = session_expiry()
    s = AuthSession(user_id=user.id, expires_at=exp, device_label=body.device_label)
    db.add(s)
    db.flush()
    audit(db, user.id, "auth.login", "session", s.id, request_id=request_id(request))
    db.commit()
    return TokenOut(access_token=create_token(user.id, s.id, exp), expires_at=exp)


@router.post("/logout", status_code=204)
def logout(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    s = db.get(AuthSession, request.state.session_id)
    s.revoked_at = now()
    audit(db, user.id, "auth.logout", "session", s.id, request_id=request_id(request))
    db.commit()


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user_out(user)


@router.post("/change-password", status_code=204)
def change_password(body: PasswordChange, request: Request,
                    user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(403, "Mot de passe actuel incorrect")
    try:
        check_password_policy(body.new_password)
    except ValueError as e:
        raise HTTPException(422, str(e))
    if verify_password(body.new_password, user.password_hash):
        raise HTTPException(422, "Le nouveau mot de passe doit être différent de l'actuel")
    user.password_hash = hash_password(body.new_password)
    user.must_change_password = False
    # Révoque toutes les autres sessions
    for s in db.scalars(select(AuthSession).where(AuthSession.user_id == user.id,
                                                  AuthSession.revoked_at.is_(None))):
        if s.id != request.state.session_id:
            s.revoked_at = now()
    audit(db, user.id, "auth.password_changed", "user", user.id, request_id=request_id(request))
    db.commit()
