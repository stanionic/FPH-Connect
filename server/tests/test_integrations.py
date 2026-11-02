"""Publication vers un site : serveur FPH -> récepteur Flask réel (en mémoire)."""
import json
import time

import pytest
from flask import Flask

from app.main import app as fastapi_app
from app.routers.integrations import get_sender
from fph_flask_connector import SqliteStore, create_blueprint, verify_signature

from .conftest import CHURCH, login, make_church, make_user


class Site:
    """Un site Flask simulé + un 'expéditeur' qui lui parle, avec pannes injectables."""

    def __init__(self, secret):
        self.store = SqliteStore()
        self.flask = Flask(__name__)
        self.flask.register_blueprint(create_blueprint(secret, self.store))
        self.http = self.flask.test_client()
        self.down = False
        self.received = []

    def sender(self, integ, body, headers):
        if self.down:
            return 503, "maintenance"
        self.received.append((json.loads(body), dict(headers)))
        r = self.http.post("/fph-sync", data=body, headers=headers)
        return r.status_code, r.get_data(as_text=True)


@pytest.fixture()
def setup(client, root):
    r = client.post("/api/v1/admin/integrations", headers=root,
                    json={"name": "site-flask", "kind": "flask", "base_url": "https://fph.example.org"})
    assert r.status_code == 201
    integ = r.json()
    site = Site(integ["secret"])
    fastapi_app.dependency_overrides[get_sender] = lambda: site.sender
    yield client, root, integ, site
    fastapi_app.dependency_overrides.clear()


def go_live(client, root, integ):
    client.patch(f"/api/v1/admin/integrations/{integ['id']}", headers=root,
                 json={"enabled": True, "mode": "live"})


def publish(client, root, **over):
    c = make_church(client, root, affiliation_status="affiliated", **over)
    for a in ("submit", "approve", "publish"):
        r = client.post(f"/api/v1/churches/{c['id']}/transition", headers=root, json={"action": a})
        assert r.status_code == 200, r.text
    return c


def dispatch(client, root):
    r = client.post("/api/v1/admin/integrations/dispatch", headers=root)
    assert r.status_code == 200, r.text
    return r.json()


def test_publish_reaches_site_with_public_fields_only(setup):
    client, root, integ, site = setup
    go_live(client, root, integ)
    c = publish(client, root)
    assert dispatch(client, root)["sent"] == 1
    shown = site.store.list_churches()
    assert [s["official_name"] for s in shown] == [CHURCH["official_name"]]
    body = site.received[-1][0]
    assert "contact_email" not in json.dumps(body) and "main_leader_name" not in json.dumps(body)
    assert "contact@eglise.org" not in json.dumps(body) and "Pasteur X" not in json.dumps(body)
    assert body["church_id"] == c["id"]


def test_nothing_sent_before_publication_or_approval(setup):
    client, root, integ, site = setup
    go_live(client, root, integ)
    c = make_church(client, root, affiliation_status="affiliated")
    for a in ("submit", "approve"):
        client.post(f"/api/v1/churches/{c['id']}/transition", headers=root, json={"action": a})
    assert dispatch(client, root) == {"sent": 0, "failed": 0, "dead": 0, "dry_run": 0, "skipped": 0}
    assert site.store.list_churches() == []


def test_not_affiliated_is_not_sent(setup):
    client, root, integ, site = setup
    go_live(client, root, integ)
    c = make_church(client, root)  # affiliation 'pending'
    for a in ("submit", "approve", "publish"):
        client.post(f"/api/v1/churches/{c['id']}/transition", headers=root, json={"action": a})
    dispatch(client, root)
    assert site.store.list_churches() == []


def test_withdraw_and_edit_remove_from_site(setup):
    client, root, integ, site = setup
    go_live(client, root, integ)
    c1 = publish(client, root)
    c2 = publish(client, root, official_name="Autre Église", commune="Delmas")
    dispatch(client, root)
    assert len(site.store.list_churches()) == 2
    client.post(f"/api/v1/churches/{c1['id']}/transition", headers=root, json={"action": "withdraw"})
    cur = client.get(f"/api/v1/churches/{c2['id']}", headers=root).json()
    client.patch(f"/api/v1/churches/{c2['id']}", headers=root,
                 json={"version": cur["version"], "address": "Modifiée"})  # repasse en attente
    dispatch(client, root)
    assert site.store.list_churches() == []


def test_site_down_retries_then_succeeds_without_duplicates(setup):
    client, root, integ, site = setup
    go_live(client, root, integ)
    publish(client, root)
    site.down = True
    assert dispatch(client, root)["failed"] == 1
    items = client.get(f"/api/v1/admin/integrations/{integ['id']}/outbox", headers=root).json()
    assert items[0]["status"] == "failed" and items[0]["attempts"] == 1 and "503" in items[0]["error"]
    assert dispatch(client, root)["sent"] == 0       # délai de reprise pas encore écoulé
    site.down = False
    # force l'échéance de reprise
    from app.db import SessionLocal
    from app.models import OutboxItem, now
    with SessionLocal() as db:
        for o in db.query(OutboxItem).all():
            o.next_attempt_at = now()
        db.commit()
    assert dispatch(client, root)["sent"] == 1
    assert len(site.store.list_churches()) == 1


def test_dead_after_max_attempts_and_requeue(setup):
    client, root, integ, site = setup
    go_live(client, root, integ)
    publish(client, root)
    site.down = True
    from app.db import SessionLocal
    from app.models import OutboxItem, now
    for _ in range(6):
        with SessionLocal() as db:
            for o in db.query(OutboxItem).all():
                o.next_attempt_at = now()
            db.commit()
        dispatch(client, root)
    items = client.get(f"/api/v1/admin/integrations/{integ['id']}/outbox", headers=root).json()
    assert items[0]["status"] == "dead" and items[0]["attempts"] == 6
    site.down = False
    assert client.post(f"/api/v1/admin/integrations/outbox/{items[0]['seq']}/requeue",
                       headers=root).status_code == 200
    assert dispatch(client, root)["sent"] == 1


def test_test_mode_sends_nothing(setup):
    client, root, integ, site = setup
    client.patch(f"/api/v1/admin/integrations/{integ['id']}", headers=root, json={"enabled": True})
    publish(client, root)                       # mode test par défaut
    assert dispatch(client, root)["dry_run"] == 1
    assert site.received == [] and site.store.list_churches() == []
    out = client.get(f"/api/v1/admin/integrations/{integ['id']}/outbox", headers=root).json()
    assert out[0]["status"] == "dry_run" and out[0]["payload"]["official_name"]


def test_disabled_integration_is_untouched(setup):
    client, root, integ, site = setup           # créée désactivée
    publish(client, root)
    assert dispatch(client, root)["sent"] == 0
    assert client.get(f"/api/v1/admin/integrations/{integ['id']}/outbox", headers=root).json() == []
    # le reste de la plateforme fonctionne
    assert len(client.get("/api/v1/public/churches").json()) == 1
    # réactivation + resync
    go_live(client, root, integ)
    assert client.post(f"/api/v1/admin/integrations/{integ['id']}/resync", headers=root).json()["queued"] == 1
    assert dispatch(client, root)["sent"] == 1


def test_rollback_hides_everything_and_resync_restores(setup):
    client, root, integ, site = setup
    go_live(client, root, integ)
    publish(client, root)
    publish(client, root, official_name="Deux", commune="Jacmel")
    dispatch(client, root)
    exp = client.get(f"/api/v1/admin/integrations/{integ['id']}/export", headers=root).json()
    assert len(exp["churches"]) == 2             # sauvegarde de l'état publié
    assert client.post(f"/api/v1/admin/integrations/{integ['id']}/rollback", headers=root).json() == {"queued_removals": 2}
    dispatch(client, root)
    assert site.store.list_churches() == []
    client.post(f"/api/v1/admin/integrations/{integ['id']}/resync", headers=root)
    dispatch(client, root)
    assert len(site.store.list_churches()) == 2   # republication possible après retour arrière


def test_coalescing_keeps_only_latest_pending(setup):
    client, root, integ, site = setup
    go_live(client, root, integ)
    c = publish(client, root)
    client.post(f"/api/v1/churches/{c['id']}/transition", headers=root, json={"action": "withdraw"})
    out = client.get(f"/api/v1/admin/integrations/{integ['id']}/outbox", headers=root).json()
    assert [o["status"] for o in out] == ["pending", "superseded"]
    dispatch(client, root)
    assert site.store.list_churches() == []


def test_receiver_rejects_bad_signature_tampering_and_replay(setup):
    client, root, integ, site = setup
    go_live(client, root, integ)
    publish(client, root)
    dispatch(client, root)
    body, headers = site.received[-1]
    raw = json.dumps(body, separators=(",", ":"), sort_keys=True, ensure_ascii=False).encode()
    assert site.http.post("/fph-sync", data=raw, headers=headers).status_code == 200  # rejeu exact = ignoré
    assert site.http.post("/fph-sync", data=raw, headers=headers).get_json()["status"] == "ignored_stale"
    tampered = raw.replace(b"Ouest", b"Nord!")
    assert site.http.post("/fph-sync", data=tampered, headers=headers).status_code == 401
    bad = {**headers, "X-FPH-Signature": "sha256=" + "0" * 64}
    assert site.http.post("/fph-sync", data=raw, headers=bad).status_code == 401
    old = str(int(time.time()) - 3600)
    assert not verify_signature("x" * 40, old, raw, headers["X-FPH-Signature"])
    assert site.http.post("/fph-sync", data=raw, headers={}).status_code == 401


def test_wrong_secret_never_applies_and_item_is_retried(setup):
    client, root, integ, site = setup
    go_live(client, root, integ)
    client.post(f"/api/v1/admin/integrations/{integ['id']}/rotate-secret", headers=root)  # site garde l'ancien
    publish(client, root)
    r = dispatch(client, root)
    assert r["failed"] == 1 and site.store.list_churches() == []
    out = client.get(f"/api/v1/admin/integrations/{integ['id']}/outbox", headers=root).json()
    assert out[0]["http_status"] == 401


def test_out_of_order_delivery_is_ignored(setup):
    _, _, _, site = setup
    assert site.store.apply("c1", 5, "remove", None) == "applied"
    assert site.store.apply("c1", 3, "upsert", {"official_name": "Vieux"}) == "ignored_stale"
    assert site.store.list_churches() == []
    assert site.store.apply("c1", 6, "upsert", {"official_name": "Neuf", "department": "Nord"}) == "applied"
    assert site.store.list_churches()[0]["official_name"] == "Neuf"


def test_integration_admin_requires_permission_and_hides_secret(setup):
    client, root, integ, _ = setup
    c = make_church(client, root)
    make_user(client, root, "p@fph.org", "church_admin", church_id=c["id"])
    h = login(client, "p@fph.org", "Passw0rd-long-1")
    assert client.get("/api/v1/admin/integrations", headers=h).status_code == 403
    assert client.post("/api/v1/admin/integrations/dispatch", headers=h).status_code == 403
    listing = client.get("/api/v1/admin/integrations", headers=root).json()
    assert all("secret" not in d for d in listing) and integ["secret"] not in json.dumps(listing)
    assert integ["secret"] not in json.dumps(client.get(f"/api/v1/admin/integrations/{integ['id']}/outbox", headers=root).json())
    assert client.post("/api/v1/admin/integrations", headers=root,
                       json={"name": "x", "kind": "flask", "base_url": "ftp://bad"}).status_code == 422
    audit = client.get("/api/v1/admin/audit", headers=root).json()
    assert any(a["action"] == "integration.created" for a in audit)
