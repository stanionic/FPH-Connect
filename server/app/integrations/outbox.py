from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Church, Event, Integration, OutboxItem, now
from .protocol import event_public_data, is_public, is_public_event, public_data


def _supersede(db: Session, integration_id: str, kind: str, entity_id: str):
    for old in db.scalars(select(OutboxItem).where(
            OutboxItem.integration_id == integration_id, OutboxItem.kind == kind,
            OutboxItem.church_id == entity_id, OutboxItem.status.in_(("pending", "failed")))):
        old.status = "superseded"


def enqueue(db: Session, integration: Integration, entity, action: str, kind: str = "church") -> OutboxItem:
    _supersede(db, integration.id, kind, entity.id)
    payload = {}
    if action == "upsert":
        payload = public_data(entity) if kind == "church" else event_public_data(entity)
    item = OutboxItem(integration_id=integration.id, kind=kind, church_id=entity.id,
                      church_version=entity.version, action=action, payload=payload,
                      next_attempt_at=now())
    db.add(item)
    db.flush()
    return item


def _fanout(db: Session, entity, now_public: bool, was_public: bool, kind: str) -> int:
    if not now_public and not was_public:
        return 0
    action = "upsert" if now_public else "remove"
    n = 0
    for integ in db.scalars(select(Integration).where(Integration.enabled.is_(True))):
        enqueue(db, integ, entity, action, kind)
        n += 1
    return n


def sync_church(db: Session, church: Church, was_public: bool) -> int:
    """À appeler dans la MÊME transaction que le changement de la fiche."""
    return _fanout(db, church, is_public(church), was_public, "church")


def sync_event(db: Session, event: Event, was_public: bool) -> int:
    return _fanout(db, event, is_public_event(event), was_public, "event")


def live_state(db: Session, integration_id: str) -> dict[tuple[str, str], OutboxItem]:
    """Dernier envoi réussi par entité : ce que le site est censé afficher. Clé = (kind, id)."""
    state: dict[tuple[str, str], OutboxItem] = {}
    for it in db.scalars(select(OutboxItem).where(
            OutboxItem.integration_id == integration_id,
            OutboxItem.status == "sent").order_by(OutboxItem.id)):
        state[(it.kind, it.church_id)] = it
    return state
