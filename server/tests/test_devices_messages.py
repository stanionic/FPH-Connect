from datetime import timedelta

from app.db import SessionLocal
from app.models import Device, now

from .conftest import device_for, login, make_church, make_user


def _staff(client, root, email, role="employee", **kw):
    if role in ("employee", "church_admin") and "church_id" not in kw:
        kw["church_id"] = make_church(client, root, official_name=f"Église de {email}", commune="Jacmel")["id"]
    make_user(client, root, email, role, **kw)
    return login(client, email, "Passw0rd-long-1")


def test_unapproved_device_cannot_communicate(client, root):
    u = _staff(client, root, "a@fph.org")
    h, d = device_for(client, root, u, approve=False)
    assert client.get("/api/v1/devices/status", headers=h).json()["status"] == "pending"
    r = client.get("/api/v1/messages", headers=h)
    assert r.status_code == 403 and "attente" in r.json()["detail"]
    assert client.get("/api/v1/network/presence", headers=h).status_code == 403
    assert client.get("/api/v1/messages", headers=u).status_code == 403          # pas d'appareil du tout
    client.post(f"/api/v1/devices/{d['id']}/approve", headers=root, json={"office": "Bureau Delmas"})
    assert client.get("/api/v1/messages", headers=h).status_code == 200


def test_only_admin_approves_and_token_is_hashed(client, root):
    u = _staff(client, root, "a@fph.org")
    r = client.post("/api/v1/devices/register", headers=u, json={"name": "PC", "platform": "windows"}).json()
    assert client.post(f"/api/v1/devices/{r['id']}/approve", headers=u, json={}).status_code == 403
    assert client.get("/api/v1/devices", headers=u).status_code == 403
    with SessionLocal() as db:
        dev = db.get(Device, r["id"])
        assert r["token"] not in dev.token_hash and len(dev.token_hash) == 64


def test_wrong_token_unknown_device_same_error(client, root):
    u = _staff(client, root, "a@fph.org")
    h, d = device_for(client, root, u)
    bad = {**u, "X-FPH-Device": f"{d['id']}:wrong"}
    unknown = {**u, "X-FPH-Device": "no-such-id:wrong"}
    r1, r2 = client.get("/api/v1/messages", headers=bad), client.get("/api/v1/messages", headers=unknown)
    assert r1.status_code == r2.status_code == 403 and r1.json() == r2.json()


def test_revocation_is_immediate(client, root):
    u = _staff(client, root, "a@fph.org")
    h, d = device_for(client, root, u)
    assert client.get("/api/v1/messages", headers=h).status_code == 200
    client.post(f"/api/v1/devices/{d['id']}/revoke", headers=root)
    r = client.get("/api/v1/messages", headers=h)
    assert r.status_code == 403 and "révoqué" in r.json()["detail"]
    assert client.post(f"/api/v1/devices/{d['id']}/approve", headers=root, json={}).status_code == 409


def test_device_assigned_to_another_user_refused(client, root):
    ua, ub = _staff(client, root, "a@fph.org"), _staff(client, root, "b@fph.org")
    me_b = client.get("/api/v1/auth/me", headers=ub).json()["id"]
    h, d = device_for(client, root, ua, assigned_user_id=me_b)
    assert client.get("/api/v1/messages", headers=h).status_code == 403


def test_presence_online_offline_and_ip_privacy(client, root):
    ua, ub = _staff(client, root, "a@fph.org"), _staff(client, root, "b@fph.org")
    ha, da = device_for(client, root, ua, "PC A", office="Bureau 1")
    hb, db_ = device_for(client, root, ub, "PC B")
    assert client.post("/api/v1/devices/heartbeat", headers=ha).status_code == 200
    pres = {p["name"]: p for p in client.get("/api/v1/network/presence", headers=hb).json()}
    assert pres["PC A"]["online"] is True and pres["PC B"]["online"] is False
    assert pres["PC A"]["office"] == "Bureau 1"
    assert "last_ip" not in pres["PC A"]                              # IP cachée aux non-admins
    adm = {d["name"]: d for d in client.get("/api/v1/devices", headers=root).json()}
    assert adm["PC A"]["last_ip"] and adm["PC A"]["online"] is True
    with SessionLocal() as db:                                         # A cesse d'émettre
        db.get(Device, da["id"]).last_seen_at = now() - timedelta(minutes=10)
        db.commit()
    pres = {p["name"]: p for p in client.get("/api/v1/network/presence", headers=hb).json()}
    assert pres["PC A"]["online"] is False


def test_direct_message_privacy_and_polling(client, root):
    ua, ub, uc = (_staff(client, root, f"{c}@fph.org") for c in "abc")
    ha, _ = device_for(client, root, ua)
    hb, _ = device_for(client, root, ub)
    hc, _ = device_for(client, root, uc)
    bid = client.get("/api/v1/auth/me", headers=ub).json()["id"]
    m = client.post("/api/v1/messages", headers=ha, json={"recipient_id": bid, "body": "Bonjour B"})
    assert m.status_code == 201
    got = client.get("/api/v1/messages", headers=hb).json()
    assert [x["body"] for x in got] == ["Bonjour B"]
    assert client.get("/api/v1/messages", headers=hc).json() == []     # C ne lit pas A->B
    assert client.get(f"/api/v1/messages?after_id={got[0]['id']}", headers=hb).json() == []
    assert client.post(f"/api/v1/messages/{got[0]['id']}/read", headers=hb).status_code == 204
    assert client.post(f"/api/v1/messages/{got[0]['id']}/read", headers=hc).status_code == 404
    assert client.get("/api/v1/messages", headers=ha).json()[0]["read"] is True


def test_message_validation_dedupe_and_unknown_recipient(client, root):
    ua, ub = _staff(client, root, "a@fph.org"), _staff(client, root, "b@fph.org")
    ha, _ = device_for(client, root, ua)
    bid = client.get("/api/v1/auth/me", headers=ub).json()["id"]
    body = {"recipient_id": bid, "body": "x", "client_ref": "r1"}
    a, b = client.post("/api/v1/messages", headers=ha, json=body), client.post("/api/v1/messages", headers=ha, json=body)
    assert (a.status_code, b.status_code) == (201, 200) and a.json()["id"] == b.json()["id"]
    assert client.post("/api/v1/messages", headers=ha, json={"recipient_id": bid, "body": ""}).status_code == 422
    assert client.post("/api/v1/messages", headers=ha, json={"recipient_id": bid, "body": "x" * 4001}).status_code == 422
    assert client.post("/api/v1/messages", headers=ha, json={"recipient_id": "nope", "body": "hi"}).status_code == 404
    client.post(f"/api/v1/users/{bid}/deactivate", headers=root)
    assert client.post("/api/v1/messages", headers=ha, json={"recipient_id": bid, "body": "hi"}).status_code == 404


def test_broadcast_requires_permission(client, root):
    ua, ub = _staff(client, root, "a@fph.org"), _staff(client, root, "b@fph.org")
    ha, _ = device_for(client, root, ua)
    hb, _ = device_for(client, root, ub)
    assert client.post("/api/v1/messages", headers=ha, json={"audience": "all", "body": "Alerte"}).status_code == 403
    hr, _ = device_for(client, root, root, "PC admin")
    assert client.post("/api/v1/messages", headers=hr, json={"audience": "all", "body": "Réunion à 10h"}).status_code == 201
    assert [m["body"] for m in client.get("/api/v1/messages", headers=hb).json()] == ["Réunion à 10h"]


def test_directory_has_no_emails_and_excludes_self_and_public(client, root):
    ua = _staff(client, root, "a@fph.org")
    make_user(client, root, "pub@fph.org", "public")
    ha, _ = device_for(client, root, ua)
    d = client.get("/api/v1/network/directory", headers=ha).json()
    text = str(d)
    assert "@" not in text and "Public" not in text
    names = [x["full_name"] for x in d]
    assert len(names) >= 1                                              # le superadmin est listé
    # un utilisateur public ne peut ni enregistrer d'appareil ni écrire
    up = login(client, "pub@fph.org", "Passw0rd-long-1")
    assert client.post("/api/v1/devices/register", headers=up, json={"name": "PC", "platform": "linux"}).status_code == 403


def test_message_content_not_in_audit_log(client, root):
    ua, ub = _staff(client, root, "a@fph.org"), _staff(client, root, "b@fph.org")
    ha, _ = device_for(client, root, ua)
    bid = client.get("/api/v1/auth/me", headers=ub).json()["id"]
    client.post("/api/v1/messages", headers=ha, json={"recipient_id": bid, "body": "SECRET-CONTENT-123"})
    audit = client.get("/api/v1/admin/audit", headers=root).json()
    assert any(a["action"] == "message.sent" for a in audit) and "SECRET-CONTENT-123" not in str(audit)
