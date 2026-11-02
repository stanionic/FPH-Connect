"""Tests d'intégration client <-> serveur (le client utilise le TestClient en mémoire)."""
import httpx

from fph_client.api import ApiClient
from fph_client.localdb import LocalDB
from fph_client.sync import sync

from .conftest import CHURCH, make_church


class Offline:
    def request(self, *a, **k):
        raise httpx.ConnectError("no network")


def _api(client):
    api = ApiClient("http://testserver", http=client)
    api.login("root@fph.org", "Root-Password-123")
    return api


def test_offline_create_then_sync_once(client, root):
    api, db = _api(client), LocalDB()
    db.queue_create({**CHURCH, "official_name": "Créée hors ligne"})
    real = api.http
    api.http = Offline()                      # coupure réseau
    r = sync(api, db)
    assert r["network_error"] and len(db.ops("pending")) == 1
    api.http = real                           # reconnexion
    assert sync(api, db)["sent"] == 1
    assert sync(api, db)["sent"] == 0         # pas de double envoi
    assert len(client.get("/api/v1/churches", headers=root).json()) == 1
    assert [c["official_name"] for c in db.churches()] == ["Créée hors ligne"]


def test_replayed_op_does_not_duplicate(client, root):
    api, db = _api(client), LocalDB()
    op = db.queue_create({**CHURCH, "official_name": "Rejouée"})
    sync(api, db)
    db.set_op(op, "pending")                  # simule une confirmation perdue -> renvoi
    sync(api, db)
    assert len(client.get("/api/v1/churches", headers=root).json()) == 1


def test_conflict_is_detected_and_local_change_kept(client, root):
    c = make_church(client, root)
    api, db = _api(client), LocalDB()
    sync(api, db)                             # cache local à la version 1
    db.queue_update(c["id"], {"commune": "Delmas"})
    # modification concurrente côté serveur
    client.patch(f"/api/v1/churches/{c['id']}", headers=root, json={"version": 1, "address": "Autre"})
    r = sync(api, db)
    assert r["conflicts"] == 1 and not r["refreshed"]
    op = db.ops("conflict")[0]
    assert '"server_version": 2' in op["error"] and "Delmas" in op["payload"]
    server = client.get(f"/api/v1/churches/{c['id']}", headers=root).json()
    assert server["commune"] == "Pétion-Ville"   # rien n'a été écrasé


def test_wipe_on_logout(client):
    api, db = _api(client), LocalDB()
    db.queue_create(CHURCH)
    sync(api, db)
    db.wipe()
    assert db.churches() == [] and db.ops("pending") == []
