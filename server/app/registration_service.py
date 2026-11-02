"""Inscription à un événement : règles communes au personnel et au site (via HMAC)."""
import re
from datetime import timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Event, Registration, now


def aware(dt):
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def dedupe_key(full_name: str, email: str | None, phone: str | None) -> str:
    if email:
        return "e:" + email.strip().lower()
    return "p:" + re.sub(r"\D", "", phone or "") + ":" + " ".join(full_name.lower().split())


def registered_count(db: Session, event_id: str) -> int:
    return db.scalar(select(func.count()).select_from(Registration).where(
        Registration.event_id == event_id, Registration.status == "registered")) or 0


def register(db: Session, event: Event, *, full_name: str, email: str | None, phone: str | None,
             source: str, idempotency_key: str | None = None) -> tuple[Registration, str]:
    """Retourne (inscription, résultat) ; résultat ∈ registered | waitlisted | already | replayed."""
    if idempotency_key:
        prev = db.scalar(select(Registration).where(Registration.event_id == event.id,
                                                    Registration.idempotency_key == idempotency_key))
        if prev:
            return prev, "replayed"           # même envoi rejoué : aucun effet
    key = dedupe_key(full_name, email, phone)
    existing = db.scalar(select(Registration).where(Registration.event_id == event.id,
                                                    Registration.dedupe_key == key))
    if existing and existing.status in ("registered", "waitlisted"):
        return existing, "already"
    full = event.capacity is not None and registered_count(db, event.id) >= event.capacity
    status = "waitlisted" if full else "registered"
    if existing:                               # annulée auparavant : réactivation
        existing.status, existing.consent_at = status, now()
        existing.full_name, existing.email, existing.phone = full_name, email, phone
        existing.idempotency_key = idempotency_key or existing.idempotency_key
        db.flush()
        return existing, status
    r = Registration(event_id=event.id, full_name=full_name, email=email, phone=phone, source=source,
                     status=status, dedupe_key=key, idempotency_key=idempotency_key)
    db.add(r)
    db.flush()
    return r, status


def promote_waitlist(db: Session, event: Event) -> int:
    """Quand une place se libère, la plus ancienne personne en attente est inscrite."""
    n = 0
    while event.capacity is None or registered_count(db, event.id) < event.capacity:
        nxt = db.scalar(select(Registration).where(
            Registration.event_id == event.id, Registration.status == "waitlisted")
            .order_by(Registration.created_at, Registration.id).limit(1))
        if nxt is None:
            break
        nxt.status = "registered"
        db.flush()
        n += 1
    return n
