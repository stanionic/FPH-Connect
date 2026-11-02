"""Récepteur Flask pour FPH Connect.

Usage :
    from fph_flask_connector import create_blueprint, SqliteStore
    store = SqliteStore("fph_site.db")
    app.register_blueprint(create_blueprint(os.environ["FPH_SYNC_SECRET"], store))
    # Dans vos vues : store.list_churches(department="Ouest")

Le récepteur NE LIT NI N'ÉCRIT dans vos tables existantes : il utilise sa propre table.
Il ne reçoit que des champs publics et ne contient aucun identifiant de base FPH.
"""
import hashlib
import hmac
import json
import ssl
import sqlite3
import threading
import time
import urllib.error
import urllib.request
import uuid

from flask import Blueprint, jsonify, request

__all__ = ["create_blueprint", "SqliteStore", "verify_signature", "forward_registration"]

TOLERANCE_SECONDS = 300


def verify_signature(secret: str, timestamp: str, body: bytes, signature: str,
                     tolerance: int = TOLERANCE_SECONDS, now: float | None = None) -> bool:
    try:
        ts = int(timestamp)
    except (TypeError, ValueError):
        return False
    if abs((now if now is not None else time.time()) - ts) > tolerance:
        return False   # rejoue d'un ancien message
    expected = "sha256=" + hmac.new(secret.encode(), timestamp.encode() + b"." + body,
                                    hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature or "")


class SqliteStore:
    """Stockage minimal. Remplaçable par n'importe quel objet avec les mêmes méthodes."""

    def __init__(self, path: str = ":memory:"):
        self._lock = threading.Lock()
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("""CREATE TABLE IF NOT EXISTS fph_churches(
            church_id TEXT PRIMARY KEY, seq INTEGER NOT NULL, visible INTEGER NOT NULL,
            data TEXT NOT NULL)""")
        self.conn.execute("""CREATE TABLE IF NOT EXISTS fph_events(
            event_id TEXT PRIMARY KEY, seq INTEGER NOT NULL, visible INTEGER NOT NULL,
            data TEXT NOT NULL)""")
        self.conn.commit()

    _TABLES = {"church": ("fph_churches", "church_id"), "event": ("fph_events", "event_id")}

    def apply(self, entity_id: str, seq: int, action: str, data: dict | None, kind: str = "church") -> str:
        """Retourne 'applied' ou 'ignored_stale'. Idempotent : même seq rejoué = ignoré."""
        table, col = self._TABLES[kind]
        with self._lock:
            row = self.conn.execute(f"SELECT seq, data FROM {table} WHERE {col}=?", (entity_id,)).fetchone()
            if row is not None and seq <= row["seq"]:
                return "ignored_stale"
            if action == "upsert":
                self.conn.execute(f"INSERT OR REPLACE INTO {table} VALUES(?,?,1,?)",
                                  (entity_id, seq, json.dumps(data, ensure_ascii=False)))
            else:  # remove : on masque (réversible), on ne supprime pas
                self.conn.execute(f"INSERT OR REPLACE INTO {table} VALUES(?,?,0,?)",
                                  (entity_id, seq, row["data"] if row else "{}"))
            self.conn.commit()
            return "applied"

    def _list(self, kind: str):
        table, col = self._TABLES[kind]
        out = []
        for r in self.conn.execute(f"SELECT {col} AS id, data FROM {table} WHERE visible=1"):
            out.append({col: r["id"], **json.loads(r["data"])})
        return out

    def list_churches(self, department: str | None = None) -> list[dict]:
        rows = [d for d in self._list("church") if department is None or d.get("department") == department]
        return sorted(rows, key=lambda d: d.get("official_name", ""))

    def list_events(self, department: str | None = None) -> list[dict]:
        rows = [d for d in self._list("event") if department is None or d.get("department") == department]
        return sorted(rows, key=lambda d: d.get("starts_at") or "")


def forward_registration(base_url: str, integration_id: str, secret: str, payload: dict,
                         idempotency_key: str | None = None, post=None, timeout: float = 10.0,
                         ca_file: str | None = None):
    """Transmet une inscription saisie sur le site au serveur FPH, signée (HMAC).
    À appeler depuis le SERVEUR du site, jamais depuis le navigateur (le secret ne doit pas sortir).
    Générez UNE clé d'idempotence par envoi de formulaire et réutilisez-la en cas de nouvel essai.
    `ca_file` : certificat (ca.pem) de l'autorité FPH si le serveur utilise le TLS du réseau local ;
    la vérification du certificat et du nom n'est jamais désactivée.
    Retourne (code_http, dict_json)."""
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True, ensure_ascii=False).encode()
    ts = str(int(time.time()))
    sig = "sha256=" + hmac.new(secret.encode(), ts.encode() + b"." + body, hashlib.sha256).hexdigest()
    headers = {"Content-Type": "application/json", "X-FPH-Timestamp": ts, "X-FPH-Signature": sig,
               "X-FPH-Idempotency-Key": idempotency_key or uuid.uuid4().hex}
    url = f"{base_url.rstrip('/')}/api/v1/inbound/{integration_id}/registrations"
    if post is not None:
        status, text = post(url, body, headers)
    else:
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            ctx = ssl.create_default_context(cafile=ca_file) if ca_file else None
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
                status, text = r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            status, text = e.code, e.read().decode()
    try:
        return status, json.loads(text)
    except ValueError:
        return status, {"detail": text[:200]}


def create_blueprint(secret: str, store, url_prefix: str = "", tolerance: int = TOLERANCE_SECONDS,
                     enabled=lambda: True) -> Blueprint:
    if not secret or len(secret) < 32:
        raise ValueError("FPH_SYNC_SECRET manquant ou trop court")
    bp = Blueprint("fph_sync", __name__, url_prefix=url_prefix)

    @bp.post("/fph-sync")
    def fph_sync():
        if not enabled():                      # interrupteur : le reste du site n'est pas touché
            return jsonify(error="sync disabled"), 503
        body = request.get_data(cache=False)
        if len(body) > 64 * 1024:
            return jsonify(error="too large"), 413
        if not verify_signature(secret, request.headers.get("X-FPH-Timestamp", ""), body,
                                request.headers.get("X-FPH-Signature", ""), tolerance):
            return jsonify(error="invalid signature"), 401
        try:
            msg = json.loads(body)
            kind = msg.get("kind", "church")
            cid = str(msg.get("entity_id") or msg.get("church_id") or msg["event_id"])
            seq, action = int(msg["seq"]), msg["action"]
            if kind not in ("church", "event") or action not in ("upsert", "remove") or (
                    action == "upsert" and not isinstance(msg.get("data"), dict)):
                raise ValueError
        except (ValueError, KeyError, TypeError):
            return jsonify(error="invalid payload"), 422
        return jsonify(status=store.apply(cid, seq, action, msg.get("data"), kind))

    return bp
