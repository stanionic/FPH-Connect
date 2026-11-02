"""Scénario complet côté client : appareil, coupure réseau, files locales, envoi, clic de classement."""
import os
import stat

import httpx

from fph_client.api import ApiClient
from fph_client.device import DeviceIdentity
from fph_client.lan import (local_messages, queue_document, queue_message, sync_documents,
                            sync_messages)
from fph_client.localdb import LocalDB

from .conftest import PDF, login, make_church, make_user


class Offline:
    def request(self, *a, **k):
        raise httpx.ConnectError("réseau coupé")


def _client_for(client, tmp_path, email, pw="Passw0rd-long-1"):
    api = ApiClient("http://testserver", http=client)
    api.device = DeviceIdentity(str(tmp_path / f"{email}-device.json"))
    api.login(email, pw)
    return api


def test_full_lan_flow_with_offline_queues(client, root, tmp_path):
    c1 = make_church(client, root)
    make_user(client, root, "emp@fph.org", "employee", church_id=c1["id"])
    make_user(client, root, "bob@fph.org", "church_admin", church_id=c1["id"])
    emp = _client_for(client, tmp_path, "emp@fph.org")
    bob = _client_for(client, tmp_path, "bob@fph.org")

    # 1. enregistrement : l'appareil reste inutilisable tant qu'il n'est pas approuvé
    info = emp.register_device("PC Delmas", "linux")
    assert info["status"] == "pending" and emp.device.id == info["id"]
    assert stat.S_IMODE(os.stat(emp.device.path).st_mode) == 0o600           # jeton lisible par le seul propriétaire
    db = LocalDB()
    assert sync_messages(emp, db)["sent"] == 0
    from fph_client.api import ApiError
    try:
        emp.messages()
        assert False
    except ApiError as e:
        assert e.status == 403
    client.post(f"/api/v1/devices/{info['id']}/approve", headers=root, json={"office": "Delmas"})
    bob_info = bob.register_device("PC Bob", "windows")
    client.post(f"/api/v1/devices/{bob_info['id']}/approve", headers=root, json={})
    assert emp.device_status()["status"] == "approved"
    emp.heartbeat()

    # 2. coupure : messages et documents sont conservés localement
    bob_id = next(u["id"] for u in emp.directory() if u["full_name"] == "Test User" and u)  # annuaire
    users = emp.directory()
    assert users and all("email" not in u for u in users)
    src = tmp_path / "Rapport mensuel.pdf"
    src.write_bytes(PDF + b"offline")
    online = emp.http
    emp.http = Offline()
    queue_message(db, "Réunion demain", recipient_id=bob_id)
    queue_document(db, str(tmp_path / "tampon"), str(src))
    src.unlink()                                                             # l'original disparaît : la copie locale survit
    assert sync_messages(emp, db)["network_error"] and sync_documents(emp, db)["network_error"]
    assert len(db.conn.execute("SELECT 1 FROM out_messages WHERE status='pending'").fetchall()) == 1

    # 3. retour du réseau : envoi unique, même si on relance plusieurs fois
    emp.http = online
    assert sync_messages(emp, db)["sent"] == 1 and sync_documents(emp, db)["sent"] == 1
    assert sync_messages(emp, db)["sent"] == 0 and sync_documents(emp, db)["sent"] == 0
    assert os.listdir(tmp_path / "tampon") == []                             # copie locale libérée après envoi
    assert len(emp.inbox()) == 1

    # 4. le destinataire reçoit le message (et seulement lui)
    bdb = LocalDB()
    assert sync_messages(bob, bdb)["received"] >= 1
    assert [m["body"] for m in local_messages(bdb) if m["audience"] == "direct"] == ["Réunion demain"]

    # 5. un administrateur lance LE clic
    admin = ApiClient("http://testserver", http=client)
    admin.device = DeviceIdentity(str(tmp_path / "admin-device.json"))
    admin.login("root@fph.org", "Root-Password-123")
    ai = admin.register_device("PC Admin", "linux")
    client.post(f"/api/v1/devices/{ai['id']}/approve", headers=root, json={})
    res = admin.organize()
    assert res["counts"] == {"organized": 1} and res["items"][0]["doc_type"] == "rapport"
    # 6. et peut annuler
    assert admin.undo_batch(res["batch_id"]) == {"restored": 1}


def test_logout_wipe_removes_queued_confidential_data(client, root, tmp_path):
    db = LocalDB()
    queue_message(db, "confidentiel", recipient_id="x")
    db.conn.execute("INSERT INTO in_messages VALUES(1,'{}')")
    db.wipe()
    assert db.conn.execute("SELECT COUNT(*) FROM out_messages").fetchone()[0] == 0
    assert db.conn.execute("SELECT COUNT(*) FROM in_messages").fetchone()[0] == 0
