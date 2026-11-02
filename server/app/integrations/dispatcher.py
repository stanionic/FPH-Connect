"""Envoi des éléments de l'outbox : signature, reprises avec délais croissants,
mode test (à blanc), arrêt définitif après trop d'échecs."""
import time
from datetime import timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Integration, OutboxItem, now
from .protocol import build_body, derive_secret, sign

BACKOFF_MINUTES = [1, 5, 30, 120, 720]   # après l'échec n -> attente
MAX_ATTEMPTS = 6
PERMANENT_4XX = {400, 404, 405, 410, 413, 422}


def default_sender(integration: Integration, body: bytes, headers: dict) -> tuple[int, str]:
    url = integration.base_url.rstrip("/") + ("/wp-json/fph/v1/sync" if integration.kind == "wordpress"
                                               else "/fph-sync")
    r = httpx.post(url, content=body, headers=headers, timeout=10.0, follow_redirects=False)
    return r.status_code, r.text[:500]


def _aware(dt):
    from datetime import timezone
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def process_pending(db: Session, sender=None, limit: int = 100) -> dict:
    sender = sender or default_sender
    report = {"sent": 0, "failed": 0, "dead": 0, "dry_run": 0, "skipped": 0}
    integrations = {i.id: i for i in db.scalars(select(Integration))}
    due = db.scalars(select(OutboxItem).where(
        OutboxItem.status.in_(("pending", "failed")),
        OutboxItem.next_attempt_at <= now()).order_by(OutboxItem.id).limit(limit)).all()
    for item in due:
        integ = integrations.get(item.integration_id)
        if integ is None or not integ.enabled:
            report["skipped"] += 1          # intégration désactivée : on ne touche à rien
            continue
        if integ.mode == "test":
            item.status = "dry_run"          # rien n'est envoyé, le contenu reste consultable
            item.sent_at = now()
            report["dry_run"] += 1
            continue
        body = build_body(item)
        ts = str(int(time.time()))
        headers = {"Content-Type": "application/json", "X-FPH-Timestamp": ts,
                   "X-FPH-Event-Id": f"{integ.id}:{item.id}",
                   "X-FPH-Signature": sign(derive_secret(integ.id, integ.secret_version), ts, body)}
        item.attempts += 1
        try:
            status, text = sender(integ, body, headers)
            item.last_http_status = status
            if 200 <= status < 300:
                item.status, item.sent_at, item.last_error = "sent", now(), None
                report["sent"] += 1
                continue
            item.last_error = f"HTTP {status}: {text}"[:500]
            permanent = status in PERMANENT_4XX
        except Exception as e:  # réseau, délai dépassé, DNS...
            item.last_http_status = None
            item.last_error = f"{type(e).__name__}: {e}"[:500]
            permanent = False
        if permanent or item.attempts >= MAX_ATTEMPTS:
            item.status = "dead"
            report["dead"] += 1
        else:
            item.status = "failed"
            delay = BACKOFF_MINUTES[min(item.attempts - 1, len(BACKOFF_MINUTES) - 1)]
            item.next_attempt_at = now() + timedelta(minutes=delay)
            report["failed"] += 1
    db.commit()
    return report
