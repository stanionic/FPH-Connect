"""Cache SQLite local + file d'opérations en attente.
Ne contient que les données déjà autorisées pour l'utilisateur connecté."""
import json
import sqlite3
import uuid
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS churches(id TEXT PRIMARY KEY, data TEXT NOT NULL, version INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS pending_ops(
  op_id TEXT PRIMARY KEY, kind TEXT NOT NULL, church_id TEXT, payload TEXT NOT NULL,
  base_version INTEGER, status TEXT NOT NULL DEFAULT 'pending', error TEXT,
  created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS out_messages(
  client_ref TEXT PRIMARY KEY, recipient_id TEXT, audience TEXT NOT NULL, body TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending', error TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS in_messages(id INTEGER PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS out_documents(
  local_id TEXT PRIMARY KEY, path TEXT NOT NULL, filename TEXT NOT NULL, church_id TEXT,
  doc_type TEXT, status TEXT NOT NULL DEFAULT 'pending', error TEXT, created_at TEXT NOT NULL);
"""


class LocalDB:
    def __init__(self, path=":memory:"):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def wipe(self):
        """À appeler à la déconnexion / révocation de l'appareil."""
        self.conn.executescript("DELETE FROM churches; DELETE FROM pending_ops; DELETE FROM meta; "
                                "DELETE FROM out_messages; DELETE FROM in_messages; DELETE FROM out_documents;")

    def replace_churches(self, churches: list[dict]):
        with self.conn:
            self.conn.execute("DELETE FROM churches")
            self.conn.executemany("INSERT INTO churches VALUES(?,?,?)",
                                  [(c["id"], json.dumps(c), c["version"]) for c in churches])

    def upsert_church(self, c: dict):
        with self.conn:
            self.conn.execute("INSERT OR REPLACE INTO churches VALUES(?,?,?)",
                              (c["id"], json.dumps(c), c["version"]))

    def churches(self) -> list[dict]:
        return [json.loads(r["data"]) for r in
                self.conn.execute("SELECT data FROM churches ORDER BY json_extract(data,'$.official_name')")]

    def get_church(self, cid):
        r = self.conn.execute("SELECT data FROM churches WHERE id=?", (cid,)).fetchone()
        return json.loads(r["data"]) if r else None

    def queue_create(self, payload: dict) -> str:
        op_id = str(uuid.uuid4())
        self._queue(op_id, "create", None, payload, None)
        return op_id

    def queue_update(self, church_id: str, changes: dict) -> str:
        base = self.get_church(church_id)
        if base is None:
            raise KeyError(church_id)
        op_id = str(uuid.uuid4())
        self._queue(op_id, "update", church_id, changes, base["version"])
        return op_id

    def _queue(self, op_id, kind, church_id, payload, base_version):
        with self.conn:
            self.conn.execute(
                "INSERT INTO pending_ops(op_id,kind,church_id,payload,base_version,created_at) VALUES(?,?,?,?,?,?)",
                (op_id, kind, church_id, json.dumps(payload), base_version,
                 datetime.now(timezone.utc).isoformat()))

    def ops(self, status="pending"):
        return list(self.conn.execute(
            "SELECT * FROM pending_ops WHERE status=? ORDER BY created_at", (status,)))

    def set_op(self, op_id, status, error=None):
        with self.conn:
            self.conn.execute("UPDATE pending_ops SET status=?, error=? WHERE op_id=?",
                              (status, error, op_id))

    def set_meta(self, k, v):
        with self.conn:
            self.conn.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (k, v))

    def get_meta(self, k, default=None):
        r = self.conn.execute("SELECT value FROM meta WHERE key=?", (k,)).fetchone()
        return r["value"] if r else default
