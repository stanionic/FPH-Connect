"""Synchronisation : envoie les opérations locales, puis rafraîchit le cache.
Règles : jamais d'écrasement silencieux. Un conflit de version marque l'opération
'conflict' et conserve la valeur locale pour décision explicite de l'utilisateur."""
from datetime import datetime, timezone

from .api import ApiClient, ApiError, NetworkError
from .localdb import LocalDB
import json


def sync(api: ApiClient, db: LocalDB) -> dict:
    report = {"sent": 0, "conflicts": 0, "errors": 0, "network_error": False, "refreshed": False}
    try:
        for op in db.ops("pending"):
            payload = json.loads(op["payload"])
            try:
                if op["kind"] == "create":
                    created = api.create_church(payload, op["op_id"])  # idempotent
                    db.upsert_church(created)
                else:
                    resp = api.update_church(op["church_id"],
                                             {**payload, "version": op["base_version"]})
                    db.upsert_church(resp)
                db.set_op(op["op_id"], "done")
                report["sent"] += 1
            except ApiError as e:
                if e.status == 409:
                    db.set_op(op["op_id"], "conflict", json.dumps(e.detail))
                    report["conflicts"] += 1
                elif e.status in (401, 403):
                    raise
                else:  # 4xx de validation : inutile de réessayer tel quel
                    db.set_op(op["op_id"], "error", json.dumps(e.detail))
                    report["errors"] += 1
        # Ne rafraîchit le cache que s'il n'y a plus d'opérations en attente de conflit
        # pour ne pas perdre le contexte local.
        if report["conflicts"] == 0:
            db.replace_churches(api.list_churches())
            report["refreshed"] = True
            db.set_meta("last_sync", datetime.now(timezone.utc).isoformat())
    except NetworkError:
        report["network_error"] = True  # les opérations restent 'pending' : reprise plus tard
    return report
