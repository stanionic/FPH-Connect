import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone

import jwt

from .config import settings

_N, _R, _P = 2 ** 14, 8, 1


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${_N}${_R}${_P}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, expected = stored.split("$")
        dk = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt),
                            n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(dk.hex(), expected)
    except Exception:
        return False


def check_password_policy(password: str) -> None:
    if len(password) < 10:
        raise ValueError("Le mot de passe doit contenir au moins 10 caractères")
    if password.isdigit() or password.isalpha():
        raise ValueError("Le mot de passe doit mélanger lettres et chiffres/symboles")


def create_token(user_id: str, session_id: str, expires_at: datetime) -> str:
    return jwt.encode({"sub": user_id, "sid": session_id, "exp": expires_at},
                      settings.secret_key, algorithm="HS256")


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.secret_key, algorithms=["HS256"])


def session_expiry() -> datetime:
    return datetime.now(timezone.utc) + timedelta(minutes=settings.access_ttl_minutes)
