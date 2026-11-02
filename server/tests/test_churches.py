from .conftest import CHURCH, login, make_church, make_user


def _setup(client, root):
    c1 = make_church(client, root)
    c2 = make_church(client, root, official_name="Église du Nord", department="Nord",
                     commune="Cap-Haïtien")
    make_user(client, root, "dept@fph.org", "dept_manager", department="Ouest")
    make_user(client, root, "pastor@fph.org", "church_admin", church_id=c1["id"])
    return c1, c2, login(client, "dept@fph.org", "Passw0rd-long-1"), \
        login(client, "pastor@fph.org", "Passw0rd-long-1")


def test_scope_department_and_church(client, root):
    c1, c2, dept, pastor = _setup(client, root)
    assert [c["id"] for c in client.get("/api/v1/churches", headers=dept).json()] == [c1["id"]]
    assert [c["id"] for c in client.get("/api/v1/churches", headers=pastor).json()] == [c1["id"]]
    assert client.get(f"/api/v1/churches/{c2['id']}", headers=dept).status_code == 404
    assert client.get(f"/api/v1/churches/{c2['id']}", headers=pastor).status_code == 404
    assert len(client.get("/api/v1/churches", headers=root).json()) == 2


def test_church_admin_cannot_create_or_publish(client, root):
    c1, _, _, pastor = _setup(client, root)
    assert client.post("/api/v1/churches", headers=pastor, json=CHURCH).status_code == 403
    r = client.post(f"/api/v1/churches/{c1['id']}/transition", headers=pastor,
                    json={"action": "publish"})
    assert r.status_code == 403


def test_dept_manager_cannot_create_outside_department(client, root):
    _, _, dept, _ = _setup(client, root)
    r = client.post("/api/v1/churches", headers=dept,
                    json={**CHURCH, "official_name": "Autre", "department": "Sud"})
    assert r.status_code == 403


def test_publication_workflow_and_public_visibility(client, root):
    c1, _, dept, pastor = _setup(client, root)
    cid = c1["id"]
    t = lambda h, a: client.post(f"/api/v1/churches/{cid}/transition", headers=h, json={"action": a})
    # brouillon : jamais public
    client.patch(f"/api/v1/churches/{cid}", headers=root,
                 json={"version": 1, "affiliation_status": "affiliated"})
    assert client.get("/api/v1/public/churches").json() == []
    assert t(root, "publish").status_code == 409          # impossible depuis draft
    assert t(pastor, "submit").status_code == 200          # pending
    assert t(pastor, "approve").status_code == 403         # le pasteur ne valide pas
    assert client.get("/api/v1/public/churches").json() == []
    assert t(dept, "approve").status_code == 200           # approved
    assert client.get("/api/v1/public/churches").json() == []   # approuvé != publié
    assert t(dept, "publish").status_code == 403           # le départemental ne publie pas
    assert t(root, "publish").status_code == 200
    pub = client.get("/api/v1/public/churches").json()
    assert len(pub) == 1
    assert "contact_email" not in pub[0] and "main_leader_name" not in pub[0]
    # une modification invalide la validation et retire de l'espace public
    cur = client.get(f"/api/v1/churches/{cid}", headers=root).json()
    r = client.patch(f"/api/v1/churches/{cid}", headers=root,
                     json={"version": cur["version"], "address": "Nouvelle adresse"})
    assert r.json()["validation_status"] == "pending"
    assert client.get("/api/v1/public/churches").json() == []
    # retrait
    for a in ("approve", "publish", "withdraw"):
        assert t(root, a).status_code == 200
    assert client.get("/api/v1/public/churches").json() == []


def test_version_conflict_detected(client, root):
    c = make_church(client, root)
    ok = client.patch(f"/api/v1/churches/{c['id']}", headers=root,
                      json={"version": 1, "commune": "Delmas"})
    assert ok.status_code == 200
    stale = client.patch(f"/api/v1/churches/{c['id']}", headers=root,
                         json={"version": 1, "commune": "Tabarre"})
    assert stale.status_code == 409
    assert stale.json()["detail"]["server_version"] == 2


def test_duplicate_church_rejected_and_idempotency_key(client, root):
    make_church(client, root)
    r = client.post("/api/v1/churches", headers=root, json=CHURCH)
    assert r.status_code == 409
    h = {**root, "Idempotency-Key": "op-123"}
    a = client.post("/api/v1/churches", headers=h, json={**CHURCH, "official_name": "Nouvelle Église"})
    b = client.post("/api/v1/churches", headers=h, json={**CHURCH, "official_name": "Nouvelle Église"})
    assert a.status_code == b.status_code == 201 and a.json()["id"] == b.json()["id"]
    assert len(client.get("/api/v1/churches", headers=root).json()) == 2


def test_validation_errors(client, root):
    r = client.post("/api/v1/churches", headers=root, json={**CHURCH, "department": "Narnia"})
    assert r.status_code == 422
    r = client.post("/api/v1/churches", headers=root, json={**CHURCH, "latitude": 999})
    assert r.status_code == 422


def test_history_and_audit(client, root):
    c = make_church(client, root)
    client.patch(f"/api/v1/churches/{c['id']}", headers=root, json={"version": 1, "commune": "Delmas"})
    h = client.get(f"/api/v1/churches/{c['id']}/history", headers=root).json()
    assert [x["action"] for x in h] == ["created", "updated"]
    audit = client.get("/api/v1/admin/audit", headers=root).json()
    assert any(a["action"] == "church.updated" for a in audit)
    make_user(client, root, "e@fph.org", "church_admin", church_id=c["id"])
    emp = login(client, "e@fph.org", "Passw0rd-long-1")
    assert client.get("/api/v1/admin/audit", headers=emp).status_code == 403


def test_request_id_header(client):
    r = client.get("/health", headers={"X-Request-ID": "abc123"})
    assert r.headers["X-Request-ID"] == "abc123"
