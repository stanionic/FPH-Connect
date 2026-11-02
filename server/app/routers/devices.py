import secrets
from datetime import timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import audit
from ..config import settings
from ..db import get_db
from ..deps import (get_current_device, get_current_user, get_device_any_status,
                    hash_device_token, request_id, require)
from ..models import Device, Role, User, now
from ..permissions import has_permission

router = APIRouter(prefix="/api/v1/devices", tags=["Appareils"])
network = APIRouter(prefix="/api/v1/network", tags=["Réseau local"])


class RegisterIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    platform: str = Field(pattern="^(android|windows|linux|macos|ios|other)$")


class ApproveIn(BaseModel):
    office: str | None = Field(default=None, max_length=120)
    assigned_user_id: str | None = None


def _aware(dt):
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _online(d: Device) -> bool:
    return (d.status == "approved" and d.last_seen_at is not None
            and _aware(d.last_seen_at) > now() - timedelta(seconds=settings.device_online_seconds))


def _admin_view(d: Device) -> dict:
    return {"id": d.id, "name": d.name, "platform": d.platform, "status": d.status,
            "office": d.office, "registered_by": d.registered_by,
            "assigned_user_id": d.assigned_user_id, "online": _online(d),
            "last_seen_at": d.last_seen_at.isoformat() if d.last_seen_at else None,
            "last_ip": d.last_ip, "is_agent": d.is_agent}


@router.post("/register", status_code=201)
def register(body: RegisterIn, request: Request,
             user: User = Depends(require("device:register")), db: Session = Depends(get_db)):
    """Crée un appareil EN ATTENTE. Le jeton n'est montré qu'une fois."""
    token = secrets.token_urlsafe(32)
    d = Device(name=body.name, platform=body.platform, token_hash=hash_device_token(token),
               registered_by=user.id)
    db.add(d)
    db.flush()
    audit(db, user.id, "device.registered", "device", d.id, {"platform": d.platform},
          request_id(request))
    db.commit()
    return {"id": d.id, "status": d.status, "token": token}


@router.get("/status")
def my_status(device: Device = Depends(get_device_any_status)):
    return {"id": device.id, "status": device.status, "office": device.office}


@router.get("/mine")
def mine(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Device).where(Device.registered_by == user.id))
    return [{"id": d.id, "name": d.name, "status": d.status, "office": d.office} for d in rows]


@router.get("")
def list_devices(status: str | None = None, _=Depends(require("device:manage")),
                 db: Session = Depends(get_db)):
    stmt = select(Device).order_by(Device.created_at.desc())
    if status:
        stmt = stmt.where(Device.status == status)
    return [_admin_view(d) for d in db.scalars(stmt)]


@router.post("/{device_id}/approve")
def approve(device_id: str, body: ApproveIn, request: Request,
            admin: User = Depends(require("device:manage")), db: Session = Depends(get_db)):
    d = db.get(Device, device_id)
    if d is None:
        raise HTTPException(404, "Appareil introuvable")
    if d.status == "revoked":
        raise HTTPException(409, "Appareil révoqué : en enregistrer un nouveau")
    if body.assigned_user_id and db.get(User, body.assigned_user_id) is None:
        raise HTTPException(422, "Utilisateur inconnu")
    d.status, d.approved_by, d.approved_at = "approved", admin.id, now()
    d.office, d.assigned_user_id = body.office, body.assigned_user_id
    audit(db, admin.id, "device.approved", "device", d.id, {"office": d.office},
          request_id(request))
    db.commit()
    return _admin_view(d)


@router.post("/{device_id}/revoke")
def revoke(device_id: str, request: Request,
           admin: User = Depends(require("device:manage")), db: Session = Depends(get_db)):
    """Révocation immédiate : le jeton cesse de fonctionner à la requête suivante."""
    d = db.get(Device, device_id)
    if d is None:
        raise HTTPException(404, "Appareil introuvable")
    d.status, d.revoked_at = "revoked", now()
    audit(db, admin.id, "device.revoked", "device", d.id, request_id=request_id(request))
    db.commit()
    return _admin_view(d)


@router.post("/heartbeat")
def heartbeat(request: Request, user: User = Depends(get_current_user),
              device: Device = Depends(get_current_device), db: Session = Depends(get_db)):
    device.last_seen_at = now()
    device.last_ip = request.client.host if request.client else None
    device.last_user_id = user.id
    db.commit()
    return {"server_time": now().isoformat(), "device_status": device.status,
            "online_window_seconds": settings.device_online_seconds}


@network.get("/presence")
def presence(user: User = Depends(require("message:send")),
             device: Device = Depends(get_current_device), db: Session = Depends(get_db)):
    """Qui est en ligne. N'expose ni adresse IP ni jeton aux utilisateurs ordinaires."""
    out = []
    for d in db.scalars(select(Device).where(Device.status == "approved", Device.is_agent.is_(False)).order_by(Device.name)):
        last = db.get(User, d.last_user_id) if d.last_user_id else None
        out.append({"device_id": d.id, "name": d.name, "office": d.office, "online": _online(d),
                    "last_user": ({"id": last.id, "full_name": last.full_name} if last else None)})
    return out


@network.get("/directory")
def directory(user: User = Depends(require("message:send")),
              device: Device = Depends(get_current_device), db: Session = Depends(get_db)):
    """Utilisateurs autorisés à qui écrire (pas d'e-mail, pas de compte public)."""
    rows = db.execute(select(User, Role).join(Role, User.role_id == Role.id)
                      .where(User.is_active.is_(True), Role.level < 60, User.id != user.id)
                      .order_by(User.full_name)).all()
    return [{"id": u.id, "full_name": u.full_name, "role": r.label} for u, r in rows]
