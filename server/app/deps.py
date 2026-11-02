from datetime import timezone

import hashlib
import hmac

import jwt
from fastapi import Depends, Header, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .db import get_db
from .models import AuthSession, Device, User, now
from .permissions import has_permission
from .security import decode_token

bearer = HTTPBearer(auto_error=False)
_ALLOWED_WHEN_MUST_CHANGE = {"/api/v1/auth/me", "/api/v1/auth/change-password", "/api/v1/auth/logout"}


def _aware(dt):
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def get_current_user(request: Request,
                     creds: HTTPAuthorizationCredentials | None = Depends(bearer),
                     db: Session = Depends(get_db)) -> User:
    if creds is None:
        raise HTTPException(401, "Authentification requise")
    try:
        payload = decode_token(creds.credentials)
    except jwt.PyJWTError:
        raise HTTPException(401, "Jeton invalide ou expiré")
    session = db.get(AuthSession, payload.get("sid"))
    if (session is None or session.revoked_at is not None
            or _aware(session.expires_at) < now()):
        raise HTTPException(401, "Session révoquée ou expirée")
    user = db.get(User, payload["sub"])
    if user is None or not user.is_active:
        raise HTTPException(401, "Compte désactivé")
    if user.must_change_password and request.url.path not in _ALLOWED_WHEN_MUST_CHANGE:
        raise HTTPException(403, "Changement de mot de passe obligatoire avant toute autre action")
    request.state.session_id = session.id
    request.state.user_id = user.id
    return user


def require(permission: str):
    def checker(user: User = Depends(get_current_user)) -> User:
        if not has_permission(user, permission):
            raise HTTPException(403, "Droits insuffisants")
        return user
    return checker


def request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def hash_device_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _load_device(db: Session, header: str | None, user: User, allow_pending: bool) -> Device:
    """Un appareil doit être identifié ET approuvé. Même message pour 'inconnu' et
    'mauvais jeton' (pas d'oracle)."""
    if not header or ":" not in header:
        raise HTTPException(403, "Appareil non identifié (en-tête X-FPH-Device)")
    did, _, token = header.partition(":")
    d = db.get(Device, did)
    if d is None or d.is_agent or not hmac.compare_digest(d.token_hash, hash_device_token(token)):
        raise HTTPException(403, "Appareil non reconnu")      # un agent n'est pas un poste d'utilisateur
    if d.status == "revoked":
        raise HTTPException(403, "Appareil révoqué")
    if d.status == "pending" and not allow_pending:
        raise HTTPException(403, "Appareil en attente d'approbation par un administrateur")
    if d.assigned_user_id and d.assigned_user_id != user.id:
        raise HTTPException(403, "Appareil attribué à un autre utilisateur")
    return d


def get_current_device(user: User = Depends(get_current_user), db: Session = Depends(get_db),
                       x_fph_device: str | None = Header(default=None)) -> Device:
    return _load_device(db, x_fph_device, user, allow_pending=False)


def get_device_any_status(user: User = Depends(get_current_user), db: Session = Depends(get_db),
                          x_fph_device: str | None = Header(default=None)) -> Device:
    return _load_device(db, x_fph_device, user, allow_pending=True)


def get_agent_device(db: Session = Depends(get_db), x_fph_device: str | None = Header(default=None)) -> Device:
    """Authentification d'un AGENT d'impression : jeton d'appareil seul (pas d'utilisateur).
    Même message pour inconnu / mauvais jeton / pas un agent / révoqué (pas d'oracle)."""
    if not x_fph_device or ":" not in x_fph_device:
        raise HTTPException(403, "Agent non reconnu")
    did, _, token = x_fph_device.partition(":")
    d = db.get(Device, did)
    if (d is None or not d.is_agent or d.status != "approved"
            or not hmac.compare_digest(d.token_hash, hash_device_token(token))):
        raise HTTPException(403, "Agent non reconnu")
    return d
