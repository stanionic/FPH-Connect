"""Circuit de validation partagé (organisations, événements) — mêmes statuts que les églises :
draft -> pending -> approved -> published -> withdrawn / archived."""
from fastapi import HTTPException

from .models import EntityHistory
from .permissions import forbid, has_permission

TRANSITIONS = {
    "submit":   ({"draft"}, "pending", "workflow:submit"),
    "approve":  ({"pending"}, "approved", "workflow:approve"),
    "reject":   ({"pending"}, "draft", "workflow:approve"),
    "publish":  ({"approved"}, "published", "workflow:publish"),
    "withdraw": ({"published"}, "withdrawn", "workflow:publish"),
    "archive":  ({"draft", "approved", "withdrawn"}, "archived", "workflow:archive"),
}


def check_transition(user, current_status: str, action: str) -> str:
    sources, target, perm = TRANSITIONS[action]
    if not has_permission(user, perm):
        forbid()
    if current_status not in sources:
        raise HTTPException(409, f"Transition '{action}' impossible depuis l'état '{current_status}'")
    return target


def record(db, entity_type: str, entity, action: str, changes: dict, actor) -> None:
    db.add(EntityHistory(entity_type=entity_type, entity_id=entity.id, version=entity.version,
                         action=action, changes=changes, actor_id=actor.id))


def jsonable(d: dict) -> dict:
    return {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in d.items()}
