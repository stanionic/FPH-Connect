from datetime import datetime, timedelta, timezone

from .conftest import login, make_church, make_user


def when(days=10, hours=0):
    return (datetime.now(timezone.utc) + timedelta(days=days, hours=hours)).isoformat()


def ev(client, h, **kw):
    body = {"title": "Assemblée annuelle", "starts_at": when(10), "location": "Delmas", **kw}
    return client.post("/api/v1/events", headers=h, json=body)


def _setup(client, root):
    c1 = make_church(client, root)
    c2 = make_church(client, root, official_name="Église du Nord", department="Nord", commune="Cap-Haïtien")
    make_user(client, root, "pastor1@fph.org", "church_admin", church_id=c1["id"])
    make_user(client, root, "pastor2@fph.org", "church_admin", church_id=c2["id"])
    make_user(client, root, "dept@fph.org", "dept_manager", department="Ouest")
    make_user(client, root, "emp@fph.org", "employee", church_id=c1["id"])
    H = {n: login(client, f"{n}@fph.org", "Passw0rd-long-1") for n in ("pastor1", "pastor2", "dept", "emp")}
    return c1, c2, H


def publish(client, root, eid):
    for a in ("submit", "approve", "publish"):
        r = client.post(f"/api/v1/events/{eid}/transition", headers=root, json={"action": a})
        assert r.status_code == 200, r.text


def test_create_scopes_and_validation(client, root):
    c1, c2, H = _setup(client, root)
    mine = ev(client, H["pastor1"]).json()
    assert mine["organizer_church_id"] == c1["id"] and mine["department"] == "Ouest"   # défaut : son église
    assert ev(client, H["pastor1"], organizer_church_id=c2["id"]).status_code == 404
    d = ev(client, H["dept"], title="Rencontre départementale").json()
    assert d["department"] == "Ouest" and d["organizer_church_id"] is None
    assert ev(client, H["dept"], department="Nord").status_code == 403
    assert ev(client, root, title="Congrès national").json()["department"] is None
    assert ev(client, H["emp"]).status_code == 403                                       # lecture seule
    # validations
    assert ev(client, root, starts_at="2026-12-01T09:00:00").status_code == 422          # sans fuseau
    assert ev(client, root, ends_at=when(9)).status_code == 422                          # fin avant début
    assert ev(client, root, registration_deadline=when(11)).status_code == 422           # limite après début
    assert ev(client, root, capacity=0).status_code == 422
    assert ev(client, root, organizer_church_id=c1["id"], organizer_org_id="x").status_code == 422
    assert ev(client, root, title="ab").status_code == 422


def test_scopes_on_read(client, root):
    c1, c2, H = _setup(client, root)
    e1 = ev(client, H["pastor1"]).json()
    e2 = ev(client, H["pastor2"], title="Fête du Nord").json()
    nat = ev(client, root, title="Congrès national").json()
    ids = lambda h: sorted(x["id"] for x in client.get("/api/v1/events", headers=h).json())
    assert ids(H["pastor1"]) == [e1["id"]] and ids(H["pastor2"]) == [e2["id"]]
    assert ids(H["dept"]) == [e1["id"]] and ids(H["emp"]) == [e1["id"]]
    assert sorted(ids(root)) == sorted([e1["id"], e2["id"], nat["id"]])
    assert client.get(f"/api/v1/events/{e2['id']}", headers=H["pastor1"]).status_code == 404
    assert client.get(f"/api/v1/events/{nat['id']}", headers=H["pastor1"]).status_code == 404


def test_workflow_public_listing_and_edit_resets(client, root):
    c1, _, H = _setup(client, root)
    e = ev(client, H["pastor1"], capacity=5).json()
    t = lambda h, a: client.post(f"/api/v1/events/{e['id']}/transition", headers=h, json={"action": a})
    assert client.get("/api/v1/public/events").json() == []
    assert t(root, "publish").status_code == 409
    assert t(H["pastor1"], "submit").status_code == 200
    assert t(H["pastor1"], "approve").status_code == 403
    assert t(H["dept"], "approve").status_code == 200
    assert client.get("/api/v1/public/events").json() == []                              # approuvé != publié
    assert t(H["dept"], "publish").status_code == 403
    assert t(root, "publish").status_code == 200
    pub = client.get("/api/v1/public/events").json()
    assert len(pub) == 1 and pub[0]["spots_left"] == 5 and "created_by" not in pub[0]
    cur = client.get(f"/api/v1/events/{e['id']}", headers=root).json()
    r = client.patch(f"/api/v1/events/{e['id']}", headers=H["pastor1"], json={"version": cur["version"], "location": "Ailleurs"})
    assert r.json()["validation_status"] == "pending" and client.get("/api/v1/public/events").json() == []
    stale = client.patch(f"/api/v1/events/{e['id']}", headers=root, json={"version": 1, "location": "Z"})
    assert stale.status_code == 409
    assert len(client.get(f"/api/v1/events/{e['id']}/history", headers=root).json()) >= 5


def _published_open(client, root, **kw):
    e = ev(client, root, **kw).json()
    publish(client, root, e["id"])
    client.post(f"/api/v1/events/{e['id']}/registration", headers=root, json={"open": True})
    return e


def test_staff_registration_capacity_waitlist_and_promotion(client, root):
    e = _published_open(client, root, capacity=2)
    reg = lambda n, **kw: client.post(f"/api/v1/events/{e['id']}/registrations", headers=root,
                                      json={"full_name": n, "email": f"{n.lower()}@x.org", "consent": True, **kw})
    a, b, c = reg("Alice"), reg("Bobby"), reg("Carol")
    assert [x.json()["outcome"] for x in (a, b, c)] == ["registered", "registered", "waitlisted"]
    again = reg("Alice")
    assert again.json()["outcome"] == "already" and again.json()["id"] == a.json()["id"]
    st = client.get(f"/api/v1/events/{e['id']}/stats", headers=root).json()
    assert st["by_status"] == {"registered": 2, "waitlisted": 1}
    # une annulation libère une place : la personne en attente est promue
    client.post(f"/api/v1/registrations/{a.json()['id']}/cancel", headers=root)
    statuses = {r["full_name"]: r["status"] for r in client.get(f"/api/v1/events/{e['id']}/registrations", headers=root).json()}
    assert statuses == {"Alice": "cancelled", "Bobby": "registered", "Carol": "registered"}
    # ré-inscription après annulation : liste d'attente (complet)
    assert reg("Alice").json()["outcome"] == "waitlisted"
    assert client.get("/api/v1/public/events").json()[0]["spots_left"] == 0


def test_registration_validation_checkin_and_erasure(client, root):
    e = _published_open(client, root, capacity=1)
    url = f"/api/v1/events/{e['id']}/registrations"
    assert client.post(url, headers=root, json={"full_name": "Sans consentement", "email": "a@x.org", "consent": False}).status_code == 422
    assert client.post(url, headers=root, json={"full_name": "Sans contact", "consent": True}).status_code == 422
    assert client.post(url, headers=root, json={"full_name": "Mauvais", "email": "pas-un-mail", "consent": True}).status_code == 422
    a = client.post(url, headers=root, json={"full_name": "Présent", "phone": "QZX-3333", "consent": True}).json()
    w = client.post(url, headers=root, json={"full_name": "Attente", "email": "w@x.org", "consent": True}).json()
    assert client.post(f"/api/v1/registrations/{w['id']}/checkin", headers=root).status_code == 409   # en attente : pas de pointage
    assert client.post(f"/api/v1/registrations/{a['id']}/checkin", headers=root).json()["checked_in_at"]
    assert client.get(f"/api/v1/events/{e['id']}/stats", headers=root).json()["checked_in"] == 1
    # effacement : données anonymisées, place réattribuée
    er = client.post(f"/api/v1/registrations/{a['id']}/erase", headers=root).json()
    assert er["full_name"] == "[supprimé]" and er["phone"] is None and er["status"] == "erased"
    rows = {r["id"]: r for r in client.get(url, headers=root).json()}
    assert rows[w["id"]]["status"] == "registered"
    assert "QZX" not in str(client.get(url, headers=root).json())
    audit = str(client.get("/api/v1/admin/audit?limit=100", headers=root).json())
    assert "registration.erased" in audit and "Présent" not in audit and "QZX" not in audit


def test_registration_access_is_scoped_and_audited(client, root):
    c1, c2, H = _setup(client, root)
    e = ev(client, H["pastor1"]).json()
    publish(client, root, e["id"])
    url = f"/api/v1/events/{e['id']}/registrations"
    body = {"full_name": "Visiteur", "email": "v@x.org", "consent": True}
    assert client.post(url, headers=H["pastor1"], json=body).status_code == 201
    assert client.post(url, headers=H["pastor2"], json=body).status_code == 404          # autre église
    assert client.get(url, headers=H["pastor2"]).status_code == 404
    assert client.get(url, headers=H["emp"]).status_code == 403                          # employé : pas de données perso
    assert len(client.get(url, headers=H["dept"]).json()) == 1
    assert client.get(f"/api/v1/events/{e['id']}/stats", headers=H["pastor2"]).status_code == 404
    acts = [a["action"] for a in client.get("/api/v1/admin/audit?limit=100", headers=root).json()]
    assert "registration.listed" in acts and "registration.created" in acts
    draft = ev(client, H["pastor1"], title="Brouillon").json()
    assert client.post(f"/api/v1/events/{draft['id']}/registrations", headers=H["pastor1"], json=body).status_code == 409
