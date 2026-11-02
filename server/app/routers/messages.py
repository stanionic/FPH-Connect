from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..audit import audit
from ..db import get_db
from ..deps import get_current_device, request_id, require
from ..models import Device, Message, User, now
from ..permissions import has_permission

router = APIRouter(prefix="/api/v1/messages", tags=["Messagerie"])


class MessageIn(BaseModel):
    audience: str = Field(default="direct", pattern="^(direct|all)$")
    recipient_id: str | None = None
    body: str = Field(min_length=1, max_length=4000)
    client_ref: str | None = Field(default=None, max_length=64)


def _out(m: Message) -> dict:
    return {"id": m.id, "sender_id": m.sender_id, "recipient_id": m.recipient_id,
            "audience": m.audience, "body": m.body, "created_at": m.created_at.isoformat(),
            "read": m.read_at is not None}


@router.post("", status_code=201)
def send(body: MessageIn, request: Request, response: Response,
         user: User = Depends(require("message:send")),
         device: Device = Depends(get_current_device), db: Session = Depends(get_db)):
    if body.client_ref:   # renvoi après coupure : pas de doublon
        prev = db.scalar(select(Message).where(Message.sender_id == user.id,
                                               Message.client_ref == body.client_ref))
        if prev:
            response.status_code = 200
            return _out(prev)
    if body.audience == "all":
        if not has_permission(user, "message:broadcast"):
            raise HTTPException(403, "Diffusion générale réservée aux administrateurs nationaux")
        recipient_id = None
    else:
        target = db.get(User, body.recipient_id) if body.recipient_id else None
        if target is None or not target.is_active or target.role.level >= 60:
            raise HTTPException(404, "Destinataire introuvable")   # même réponse dans tous les cas
        recipient_id = target.id
    m = Message(sender_id=user.id, sender_device_id=device.id, recipient_id=recipient_id,
                audience=body.audience, body=body.body, client_ref=body.client_ref)
    db.add(m)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Message déjà reçu")
    audit(db, user.id, "message.sent", "message", str(m.id),
          {"audience": m.audience}, request_id(request))   # le contenu n'est pas journalisé
    db.commit()
    return _out(m)


@router.get("")
def inbox(after_id: int = Query(default=0, ge=0), limit: int = Query(default=100, ge=1, le=500),
          user: User = Depends(require("message:send")),
          device: Device = Depends(get_current_device), db: Session = Depends(get_db)):
    """Messages que je peux lire : envoyés par moi, reçus par moi, ou diffusion générale."""
    stmt = select(Message).where(Message.id > after_id, or_(
        Message.sender_id == user.id, Message.recipient_id == user.id,
        Message.audience == "all")).order_by(Message.id).limit(limit)
    return [_out(m) for m in db.scalars(stmt)]


@router.post("/{message_id}/read", status_code=204)
def mark_read(message_id: int, user: User = Depends(require("message:send")),
              device: Device = Depends(get_current_device), db: Session = Depends(get_db)):
    m = db.get(Message, message_id)
    if m is None or m.recipient_id != user.id:
        raise HTTPException(404, "Message introuvable")
    if m.read_at is None:
        m.read_at = now()
        db.commit()
