"""Site <-> FPH : publication des événements, inscriptions envoyées par le site (HMAC)."""
import json
import time

import pytest

from app.main import app as fastapi_app
from app.routers import events as events_router
from app.routers.integrations import get_sender
from fph_flask_connector import forward_registration

from .test_events import ev, publish
from .test_integrations import Site, dispatch, go_live


@pytest.fixture()
def env(client, root):
    events_router._hits.clear()
    integ = client.post("/api/v1/admin/integrations", headers=root,
                        json={"name": "site", "kind": "flask", "base_url": "https://fph.example.org"}).json()
    site = Site(integ["secret"])
    fastapi_app.dependency_overrides[get_sender] = lambda: site.sender
    yield client, root, integ, site
    fastapi_app.dependency_overrides.clear()


def send(client, integ, payload, idem="idem-0001-abcd", secret=None, integration_id=None, post=None):
    """Ce que fait le SERVEUR du site pour transmettre un formulaire d'inscription."""
    def _post(url, body, headers):
        r = client.post(url, content=body, headers=headers)
        return r.status_code, r.text
    return forward_registration("http://testserver", integration_id or integ["id"], secret or integ["secret"],
                                payload, idempotency_key=idem, post=post or _post)


def person(event_id, n="Marie", **kw):
    return {"event_id": event_id, "full_name": n, "email": f"{n.lower()}@x.org", "consent": True, **kw}


def live_event(client, root, integ, **kw):
    go_live(client, root, integ)
    e = ev(client, root, **kw).json()
    publish(client, root, e["id"])
    client.post(f"/api/v1/events/{e['id']}/registration", headers=root, json={"open": True})
    return e


def test_event_reaches_site_with_public_fields_only_and_is_withdrawn(env):
    client, root, integ, site = env
    go_live(client, root, integ)
    e = ev(client, root, description="Programme complet", capacity=50).json()
    publish(client, root, e["id"])
    assert dispatch(client, root)["sent"] == 1
    shown = site.store.list_events()
    assert len(shown) == 1 and shown[0]["title"] == "Assemblée annuelle" and shown[0]["event_id"] == e["id"]
    raw = json.dumps(site.received[-1][0])
    assert '"kind":"event"' in json.dumps(site.received[-1][0], separators=(",", ":"), sort_keys=True)
    assert "created_by" not in raw and "organizer" not in raw
    client.post(f"/api/v1/events/{e['id']}/transition", headers=root, json={"action": "withdraw"})
    dispatch(client, root)
    assert site.store.list_events() == []


def test_event_edit_removes_it_and_registration_toggle_does_not(env):
    client, root, integ, site = env
    e = live_event(client, root, integ)
    dispatch(client, root)
    assert site.store.list_events()[0]["registration_open"] is True
    client.post(f"/api/v1/events/{e['id']}/registration", headers=root, json={"open": False})   # fermeture rapide
    dispatch(client, root)
    assert site.store.list_events()[0]["registration_open"] is False                            # toujours affiché
    cur = client.get(f"/api/v1/events/{e['id']}", headers=root).json()
    client.patch(f"/api/v1/events/{e['id']}", headers=root, json={"version": cur["version"], "location": "Nouveau lieu"})
    dispatch(client, root)
    assert site.store.list_events() == []                                                       # contenu modifié => retiré


def test_rollback_and_export_cover_events(env):
    client, root, integ, site = env
    live_event(client, root, integ)
    dispatch(client, root)
    exp = client.get(f"/api/v1/admin/integrations/{integ['id']}/export", headers=root).json()
    assert len(exp["events"]) == 1
    assert client.post(f"/api/v1/admin/integrations/{integ['id']}/rollback", headers=root).json() == {"queued_removals": 1}
    dispatch(client, root)
    assert site.store.list_events() == []
    client.post(f"/api/v1/admin/integrations/{integ['id']}/resync", headers=root)
    dispatch(client, root)
    assert len(site.store.list_events()) == 1


def test_signed_registration_from_site_and_idempotency(env):
    client, root, integ, site = env
    e = live_event(client, root, integ, capacity=2)
    s1, r1 = send(client, integ, person(e["id"], "Marie"), idem="form-submit-0001")
    assert s1 == 200 and r1["status"] == "registered"
    s2, r2 = send(client, integ, person(e["id"], "Marie"), idem="form-submit-0001")       # nouvel essai réseau
    assert s2 == 200 and r2["registration_id"] == r1["registration_id"]
    s3, r3 = send(client, integ, person(e["id"], "Marie"), idem="form-submit-0002")       # même personne, autre envoi
    assert r3["registration_id"] == r1["registration_id"]
    send(client, integ, person(e["id"], "Jean"), idem="form-submit-0003")
    s5, r5 = send(client, integ, person(e["id"], "Paul"), idem="form-submit-0004")        # complet
    assert r5["status"] == "waitlisted"
    rows = client.get(f"/api/v1/events/{e['id']}/registrations", headers=root).json()
    assert sorted((r["full_name"], r["status"], r["source"]) for r in rows) == [
        ("Jean", "registered", "site"), ("Marie", "registered", "site"), ("Paul", "waitlisted", "site")]


def test_inbound_rejects_forgery_and_misuse(env):
    client, root, integ, site = env
    e = live_event(client, root, integ)
    ok = person(e["id"])
    assert send(client, integ, ok, secret="x" * 64)[0] == 401                             # mauvais secret
    assert send(client, integ, ok, integration_id="inconnue")[0] == 404
    assert send(client, integ, ok, idem="court")[0] == 422                                # clé d'idempotence trop courte
    assert send(client, integ, {**ok, "consent": False})[0] == 422
    assert send(client, integ, {**ok, "email": None, "phone": None})[0] == 422
    assert send(client, integ, {**ok, "email": "pas-un-mail"})[0] == 422
    assert send(client, integ, person("n-existe-pas"))[0] == 404
    # corps altéré après signature
    def tamper(url, body, headers):
        r = client.post(url, content=body.replace(b"Marie", b"Pirate"), headers=headers)
        return r.status_code, r.text
    assert send(client, integ, ok, post=tamper)[0] == 401
    # horodatage trop ancien
    def stale(url, body, headers):
        from fph_flask_connector import forward_registration as fr
        import hashlib, hmac
        ts = str(int(time.time()) - 3600)
        h = {**headers, "X-FPH-Timestamp": ts, "X-FPH-Signature": "sha256=" + hmac.new(
            integ["secret"].encode(), ts.encode() + b"." + body, hashlib.sha256).hexdigest()}
        r = client.post(url, content=body, headers=h)
        return r.status_code, r.text
    assert send(client, integ, ok, post=stale)[0] == 401
    assert client.get(f"/api/v1/events/{e['id']}/registrations", headers=root).json() == []   # rien d'enregistré


def test_inbound_respects_event_state(env):
    client, root, integ, site = env
    e = live_event(client, root, integ)
    client.post(f"/api/v1/events/{e['id']}/registration", headers=root, json={"open": False})
    s, r = send(client, integ, person(e["id"]))
    assert s == 409 and r["detail"] == "registration_closed"
    client.post(f"/api/v1/events/{e['id']}/registration", headers=root, json={"open": True})
    client.post(f"/api/v1/events/{e['id']}/transition", headers=root, json={"action": "withdraw"})
    assert send(client, integ, person(e["id"]))[0] == 404                                 # plus publié
    draft = ev(client, root, title="Pas publié").json()
    assert send(client, integ, person(draft["id"]))[0] == 404


def test_inbound_deadline_test_mode_disabled_and_rate_limit(env):
    client, root, integ, site = env
    e = live_event(client, root, integ, registration_deadline=None)
    # mode test : validé mais rien enregistré
    client.patch(f"/api/v1/admin/integrations/{integ['id']}", headers=root, json={"mode": "test"})
    s, r = send(client, integ, person(e["id"], "Test"))
    assert s == 200 and r == {"status": "dry_run"}
    assert client.get(f"/api/v1/events/{e['id']}/registrations", headers=root).json() == []
    # intégration désactivée : le site ne peut plus rien envoyer, le reste de la plateforme fonctionne
    client.patch(f"/api/v1/admin/integrations/{integ['id']}", headers=root, json={"mode": "live", "enabled": False})
    assert send(client, integ, person(e["id"], "Off"))[0] == 404
    assert len(client.get("/api/v1/public/events").json()) == 1
    # limitation de débit
    client.patch(f"/api/v1/admin/integrations/{integ['id']}", headers=root, json={"enabled": True})
    events_router._hits.clear()
    codes = [send(client, integ, person(e["id"], f"Pers{i:03d}"), idem=f"rate-limit-{i:04d}")[0] for i in range(62)]
    assert codes.count(429) >= 2 and codes[0] == 200


def test_inbound_audit_has_no_personal_data(env):
    client, root, integ, site = env
    e = live_event(client, root, integ)
    send(client, integ, person(e["id"], "Confidentielle", phone="QZX-5555"))
    audit = str(client.get("/api/v1/admin/audit?limit=100", headers=root).json())
    assert "registration.inbound" in audit and "Confidentielle" not in audit and "QZX" not in audit
