"""Communication sur le réseau local : messages et documents conservés localement tant que
le serveur est injoignable, puis envoyés une seule fois au retour du réseau."""
import json
import os
import shutil
import uuid
from datetime import datetime, timezone

from .api import ApiClient, ApiError, NetworkError
from .localdb import LocalDB


def _now():
    return datetime.now(timezone.utc).isoformat()


# ---------------- messages ----------------
def queue_message(db: LocalDB, body: str, recipient_id: str | None = None, audience: str = "direct") -> str:
    ref = str(uuid.uuid4())
    with db.conn:
        db.conn.execute("INSERT INTO out_messages(client_ref,recipient_id,audience,body,created_at) VALUES(?,?,?,?,?)",
                        (ref, recipient_id, audience, body, _now()))
    return ref


def sync_messages(api: ApiClient, db: LocalDB) -> dict:
    """Envoie les messages en attente (client_ref = pas de doublon), puis récupère les nouveaux."""
    rep = {"sent": 0, "rejected": 0, "received": 0, "network_error": False, "auth_error": None}
    try:
        for r in list(db.conn.execute("SELECT * FROM out_messages WHERE status='pending' ORDER BY created_at")):
            try:
                api.send_message(r["body"], r["recipient_id"], r["audience"], r["client_ref"])
                db.conn.execute("UPDATE out_messages SET status='sent' WHERE client_ref=?", (r["client_ref"],))
                rep["sent"] += 1
            except ApiError as e:
                if e.status in (401, 403):
                    raise
                db.conn.execute("UPDATE out_messages SET status='rejected', error=? WHERE client_ref=?",
                                (json.dumps(e.detail), r["client_ref"]))
                rep["rejected"] += 1
            db.conn.commit()
        last = int(db.get_meta("last_message_id", "0"))
        for m in api.messages(after_id=last):
            db.conn.execute("INSERT OR IGNORE INTO in_messages VALUES(?,?)", (m["id"], json.dumps(m)))
            last = max(last, m["id"])
            rep["received"] += 1
        db.conn.commit()
        db.set_meta("last_message_id", str(last))
    except NetworkError:
        rep["network_error"] = True
    except ApiError as e:   # 401/403 : session expirée, appareil en attente ou révoqué
        rep["auth_error"] = e.detail if isinstance(e.detail, str) else str(e.status)
    return rep


def local_messages(db: LocalDB) -> list[dict]:
    return [json.loads(r["data"]) for r in db.conn.execute("SELECT data FROM in_messages ORDER BY id")]


# ---------------- documents ----------------
def queue_document(db: LocalDB, staging_dir: str, src_path: str, church_id=None, doc_type=None) -> str:
    """Copie le fichier dans un dossier tampon local : il survit même si l'original est déplacé."""
    os.makedirs(staging_dir, exist_ok=True)
    local_id = str(uuid.uuid4())
    dst = os.path.join(staging_dir, local_id)
    shutil.copyfile(src_path, dst)
    with db.conn:
        db.conn.execute("INSERT INTO out_documents(local_id,path,filename,church_id,doc_type,created_at) VALUES(?,?,?,?,?,?)",
                        (local_id, dst, os.path.basename(src_path), church_id, doc_type, _now()))
    return local_id


def sync_documents(api: ApiClient, db: LocalDB) -> dict:
    rep = {"sent": 0, "rejected": 0, "network_error": False, "auth_error": None}
    try:
        for r in list(db.conn.execute("SELECT * FROM out_documents WHERE status='pending' ORDER BY created_at")):
            try:
                with open(r["path"], "rb") as f:
                    content = f.read()
                api.upload_document(r["filename"], content, r["church_id"], r["doc_type"])
                db.conn.execute("UPDATE out_documents SET status='sent' WHERE local_id=?", (r["local_id"],))
                os.remove(r["path"])           # le serveur l'a : on libère la copie locale
                rep["sent"] += 1
            except ApiError as e:
                if e.status in (401, 403):
                    raise
                db.conn.execute("UPDATE out_documents SET status='rejected', error=? WHERE local_id=?",
                                (json.dumps(e.detail), r["local_id"]))
                rep["rejected"] += 1
            except FileNotFoundError:
                db.conn.execute("UPDATE out_documents SET status='rejected', error='copie locale absente' WHERE local_id=?",
                                (r["local_id"],))
                rep["rejected"] += 1
            db.conn.commit()
    except NetworkError:
        rep["network_error"] = True
    except ApiError as e:   # 401/403 : session expirée, appareil en attente ou révoqué
        rep["auth_error"] = e.detail if isinstance(e.detail, str) else str(e.status)
    return rep
