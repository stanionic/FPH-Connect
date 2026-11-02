"""Protocole FPH -> site web (identique pour WordPress, Flask ou tout autre récepteur).

POST {base_url}/fph-sync   (WordPress : /wp-json/fph/v1/sync)
En-têtes : X-FPH-Timestamp (secondes UNIX), X-FPH-Event-Id, X-FPH-Signature = "sha256=" + hex
Signature = HMAC-SHA256(secret, f"{timestamp}.{corps_brut}")
Corps JSON : {"seq": int, "action": "upsert"|"remove", "church_id": str, "data": {...}|null}
Réponse attendue : 2xx si traité OU ignoré (obsolète/doublon).
"""
import hashlib
import hmac
import json
from datetime import timezone

from ..config import settings

PUBLIC_FIELDS = ("official_name", "address", "department", "commune",
                 "latitude", "longitude", "contact_phone")


def derive_secret(integration_id: str, version: int) -> str:
    msg = f"integration:{integration_id}:{version}".encode()
    return hmac.new(settings.secret_key.encode(), msg, hashlib.sha256).hexdigest()


def sign(secret: str, timestamp: str, body: bytes) -> str:
    mac = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256)
    return "sha256=" + mac.hexdigest()


def is_public(church) -> bool:
    """Même règle que le répertoire public de l'API."""
    return church.validation_status == "published" and church.affiliation_status == "affiliated"


def public_data(church) -> dict:
    """Uniquement les champs publics : jamais d'e-mail ni de nom de responsable."""
    return {f: getattr(church, f) for f in PUBLIC_FIELDS} | {"version": church.version}


EVENT_PUBLIC_FIELDS = ("title", "description", "location", "department", "registration_open")


def _iso(dt):
    if dt is None:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).isoformat()


def is_public_event(ev) -> bool:
    return ev.validation_status == "published"


def event_public_data(ev) -> dict:
    """Champs publics d'un événement. Aucune donnée d'inscrit, aucun identifiant interne d'utilisateur."""
    d = {f: getattr(ev, f) for f in EVENT_PUBLIC_FIELDS}
    d.update(starts_at=_iso(ev.starts_at), ends_at=_iso(ev.ends_at),
             registration_deadline=_iso(ev.registration_deadline), version=ev.version)
    return d


def build_body(item) -> bytes:
    """`kind` = church | event. Les anciens champs (church_id) restent pour les récepteurs v1."""
    msg = {"seq": item.id, "action": item.action, "kind": item.kind, "entity_id": item.church_id,
           "data": item.payload if item.action == "upsert" else None}
    msg["church_id" if item.kind == "church" else "event_id"] = item.church_id
    return json.dumps(msg, separators=(",", ":"), sort_keys=True, ensure_ascii=False).encode()
