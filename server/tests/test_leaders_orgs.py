import json

from app.db import SessionLocal
from app.models import EntityHistory

from .conftest import login, make_church, make_user


def _org(client, h, name="Collège Évangélique", dept="Ouest", **kw):
    return client.post("/api/v1/organizations", headers=h,
                       json={"name": name, "org_type": "ecole", "department": dept, **kw})


def _setup(client, root):
    c1 = make_church(client, root)
    c2 = make_church(client, root, official_name="Église du Nord", department="Nord", commune="Cap-Haïtien")
    make_user(client, root, "pastor1@fph.org", "church_admin", church_id=c1["id"])
    make_user(client, root, "pastor2@fph.org", "church_admin", church_id=c2["id"])
    make_user(client, root, "dept@fph.org", "dept_manager", department="Ouest")
    make_user(client, root, "emp@fph.org", "employee", church_id=c1["id"])
    H = {n: login(client, f"{n}@fph.org", "Passw0rd-long-1") for n in ("pastor1", "pastor2", "dept", "emp")}
    return c1, c2, H


def test_leader_scopes_and_attachment_rules(client, root):
    c1, c2, H = _setup(client, root)
    body = {"full_name": "Jean Pierre", "function": "pasteur_principal", "church_id": c1["id"],
            "professional_phone": "+509 1111 1111", "professional_email": "jp@eglise.org"}
    assert client.post("/api/v1/leaders", headers=H["pastor1"], json=body).status_code == 201
    assert client.post("/api/v1/leaders", headers=H["pastor2"], json=body).status_code == 404   # pas son église
    assert client.post("/api/v1/leaders", headers=H["dept"], json={**body, "full_name": "Paul"}).status_code == 201
    other = {**body, "church_id": c2["id"], "full_name": "Marc"}
    assert client.post("/api/v1/leaders", headers=H["dept"], json=other).status_code == 404       # autre département
    assert client.post("/api/v1/leaders", headers=root, json=other).status_code == 201
    assert client.post("/api/v1/leaders", headers=root, json={"full_name": "Sans lien", "function": "autre"}).status_code == 422
    assert client.post("/api/v1/leaders", headers=root, json={**body, "function": "roi"}).status_code == 422
    assert client.post("/api/v1/leaders", headers=H["pastor1"], json=body).status_code == 409    # doublon actif
    names = lambda h: sorted(l["full_name"] for l in client.get("/api/v1/leaders", headers=h).json())
    assert names(H["pastor1"]) == ["Jean Pierre", "Paul"] and names(H["pastor2"]) == ["Marc"]
    assert names(H["dept"]) == ["Jean Pierre", "Paul"] and len(names(root)) == 3
    # un employé ne voit aucune coordonnée de pasteur
    assert client.get("/api/v1/leaders", headers=H["emp"]).status_code == 403


def test_leader_history_has_no_personal_data_and_views_are_audited(client, root):
    c1, _, H = _setup(client, root)
    l = client.post("/api/v1/leaders", headers=root, json={
        "full_name": "Nom Secret", "function": "tresorier", "church_id": c1["id"],
        "professional_phone": "QZX-7777", "professional_email": "secret@eglise.org"}).json()
    client.patch(f"/api/v1/leaders/{l['id']}", headers=root, json={"version": 1, "professional_phone": "QZX-8888"})
    with SessionLocal() as db:
        dump = json.dumps([h.changes for h in db.query(EntityHistory).all()])
    assert "QZX" not in dump and "secret@" not in dump and "Nom Secret" not in dump
    client.get(f"/api/v1/leaders/{l['id']}", headers=root)
    acts = [a["action"] for a in client.get("/api/v1/admin/audit?limit=50", headers=root).json()]
    assert "leader.viewed" in acts and "QZX" not in str(client.get("/api/v1/admin/audit", headers=root).json())


def test_leader_reassignment_keeps_history_and_conflicts_detected(client, root):
    c1, c2, H = _setup(client, root)
    l = client.post("/api/v1/leaders", headers=root, json={
        "full_name": "Mobile", "function": "pasteur_assistant", "church_id": c1["id"], "start_date": "2024-01-01"}).json()
    r = client.patch(f"/api/v1/leaders/{l['id']}", headers=root,
                     json={"version": 1, "church_id": c2["id"], "function": "pasteur_principal"})
    assert r.status_code == 200 and r.json()["version"] == 2
    hist = client.get(f"/api/v1/leaders/{l['id']}/assignments", headers=root).json()
    assert len(hist) == 2 and hist[0]["church_id"] == c1["id"] and hist[0]["end_date"] is not None
    assert hist[1]["church_id"] == c2["id"] and hist[1]["end_date"] is None
    stale = client.patch(f"/api/v1/leaders/{l['id']}", headers=root, json={"version": 1, "full_name": "Autre"})
    assert stale.status_code == 409
    # l'ancien responsable d'église ne voit plus ce responsable
    assert client.get(f"/api/v1/leaders/{l['id']}", headers=H["pastor1"]).status_code == 404
    # affectation vers une église hors périmètre refusée
    r = client.patch(f"/api/v1/leaders/{l['id']}", headers=H["pastor2"], json={"version": 2, "church_id": c1["id"]})
    assert r.status_code == 404
    assert client.patch(f"/api/v1/leaders/{l['id']}", headers=root,
                        json={"version": 2, "admin_status": "retired"}).json()["admin_status"] == "retired"


def test_organization_workflow_scope_and_rules(client, root):
    c1, _, H = _setup(client, root)
    assert _org(client, H["pastor1"]).status_code == 403                         # création réservée
    assert _org(client, H["dept"], dept="Nord").status_code == 403               # hors département
    o = _org(client, H["dept"], affiliation_status="affiliated").json()
    assert _org(client, root, name="  collège   évangélique ").status_code == 409  # doublon (normalisé)
    # administrateur rattaché à l'organisation
    make_user(client, root, "orgadm@fph.org", "church_admin", organization_id=o["id"])
    oa = login(client, "orgadm@fph.org", "Passw0rd-long-1")
    o2 = _org(client, root, name="Autre Œuvre", dept="Sud").json()
    assert [x["id"] for x in client.get("/api/v1/organizations", headers=oa).json()] == [o["id"]]
    assert client.get(f"/api/v1/organizations/{o2['id']}", headers=oa).status_code == 404
    t = lambda h, a: client.post(f"/api/v1/organizations/{o['id']}/transition", headers=h, json={"action": a})
    assert t(oa, "submit").status_code == 200
    assert t(oa, "approve").status_code == 403
    assert t(H["dept"], "approve").status_code == 200
    assert t(H["dept"], "publish").status_code == 403
    assert t(root, "publish").status_code == 200
    cur = client.get(f"/api/v1/organizations/{o['id']}", headers=root).json()
    r = client.patch(f"/api/v1/organizations/{o['id']}", headers=oa, json={"version": cur["version"], "address": "Nouvelle rue"})
    assert r.json()["validation_status"] == "pending"                            # modif => à revalider
    assert len(client.get(f"/api/v1/organizations/{o['id']}/history", headers=oa).json()) >= 5
    assert client.post("/api/v1/organizations", headers=root, json={"name": "X", "org_type": "x", "department": "Ouest"}).status_code == 422
    # un employé n'a pas accès aux organisations
    assert client.get("/api/v1/organizations", headers=H["emp"]).status_code == 403


def test_user_requires_church_or_organization(client, root):
    r = client.post("/api/v1/users", headers=root, json={
        "email": "x@fph.org", "full_name": "X Y", "password": "Passw0rd-long-1", "role_code": "church_admin"})
    assert r.status_code == 422
    r = client.post("/api/v1/users", headers=root, json={
        "email": "x@fph.org", "full_name": "X Y", "password": "Passw0rd-long-1",
        "role_code": "church_admin", "organization_id": "inconnue"})
    assert r.status_code == 422
