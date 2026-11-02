import os
from datetime import timedelta

from app.config import settings
from app.db import SessionLocal
from app.models import Device, PrintJob, now

from .conftest import PDF, device_for, login, make_church, make_user

CAPS = {"duplex": True, "color": False, "paper": ["A4"], "max_copies": 5, "tracking": "full"}


def new_agent(client, root, name="Agent Bureau 2"):
    r = client.post("/api/v1/admin/agents", headers=root, json={"name": name, "platform": "linux"})
    assert r.status_code == 201, r.text
    d = r.json()
    return {"X-FPH-Device": d["device_header"]}, d["id"]


def report(client, ah, names=("HP-1",), caps=CAPS):
    r = client.post("/api/v1/agent/report", headers=ah, json={"printers": [
        {"system_name": n, "backend": "file", "capabilities": caps} for n in names]})
    assert r.status_code == 200, r.text
    return {p["system_name"]: p["id"] for p in r.json()["printers"]}


def setup(client, root, enable=True, grant=True):
    ah, aid = new_agent(client, root)
    pids = report(client, ah)
    pid = pids["HP-1"]
    c = make_church(client, root)
    make_user(client, root, "emp@fph.org", "employee", church_id=c["id"])
    make_user(client, root, "other@fph.org", "employee", church_id=c["id"])
    hu, _ = device_for(client, root, login(client, "emp@fph.org", "Passw0rd-long-1"), "PC emp")
    ho, _ = device_for(client, root, login(client, "other@fph.org", "Passw0rd-long-1"), "PC other")
    uid = client.get("/api/v1/auth/me", headers=hu).json()["id"]
    if enable:
        client.patch(f"/api/v1/admin/printers/{pid}", headers=root, json={"enabled": True, "location": "Bureau 2"})
    if grant:
        client.put(f"/api/v1/admin/printers/{pid}/grants/{uid}", headers=root)
    return ah, aid, pid, hu, ho, uid


def pj(client, h, pid, name="lettre.pdf", content=PDF + b"1", **form):
    return client.post("/api/v1/print-jobs", headers=h, data={"printer_id": pid, **form},
                       files={"file": (name, content)})


def claim(client, ah):
    r = client.post("/api/v1/agent/jobs/claim", headers=ah)
    assert r.status_code == 200, r.text
    return r.json()


def set_status(client, ah, jid, status, **kw):
    return client.post(f"/api/v1/agent/jobs/{jid}/status", headers=ah, json={"status": status, **kw})


def test_discovery_never_authorizes_and_access_is_deny_by_default(client, root):
    ah, aid, pid, hu, ho, uid = setup(client, root, enable=False, grant=False)
    assert client.get("/api/v1/printers", headers=hu).json() == []                 # découverte != autorisation
    assert pj(client, hu, pid).status_code == 404                                   # désactivée
    client.patch(f"/api/v1/admin/printers/{pid}", headers=root, json={"enabled": True})
    assert client.get("/api/v1/printers", headers=hu).json() == []                  # activée mais aucun accès accordé
    assert pj(client, hu, pid).status_code == 404
    client.put(f"/api/v1/admin/printers/{pid}/grants/{uid}", headers=root)
    seen = client.get("/api/v1/printers", headers=hu).json()
    assert [p["id"] for p in seen] == [pid] and seen[0]["capabilities"]["duplex"] is True
    assert client.get("/api/v1/printers", headers=ho).json() == []                  # l'autre employé : rien
    client.patch(f"/api/v1/admin/printers/{pid}", headers=root, json={"visibility": "all_staff"})
    assert len(client.get("/api/v1/printers", headers=ho).json()) == 1
    client.patch(f"/api/v1/admin/printers/{pid}", headers=root, json={"visibility": "granted"})
    client.delete(f"/api/v1/admin/printers/{pid}/grants/{uid}", headers=root)
    assert pj(client, hu, pid).status_code == 404                                   # accès retiré


def test_agent_and_user_credentials_are_not_interchangeable(client, root):
    ah, aid, pid, hu, ho, uid = setup(client, root)
    assert client.get("/api/v1/printers", headers={**hu, "X-FPH-Device": ah["X-FPH-Device"]}).status_code == 403
    assert client.post("/api/v1/agent/jobs/claim", headers=hu).status_code == 403          # poste d'utilisateur
    assert client.post("/api/v1/agent/jobs/claim").status_code == 403
    assert client.post("/api/v1/agent/jobs/claim", headers={"X-FPH-Device": f"{aid}:faux"}).status_code == 403
    assert client.post("/api/v1/admin/agents", headers=hu, json={"name": "x", "platform": "linux"}).status_code == 403
    assert client.get("/api/v1/admin/printers", headers=hu).status_code == 403
    assert client.patch(f"/api/v1/admin/printers/{pid}", headers=hu, json={"enabled": False}).status_code == 403
    with SessionLocal() as db:
        assert ah["X-FPH-Device"].split(":")[1] not in db.get(Device, aid).token_hash


def test_options_validation_and_file_rules(client, root):
    ah, aid, pid, hu, ho, uid = setup(client, root)
    assert pj(client, hu, pid, copies=6).status_code == 422                          # > max_copies
    assert pj(client, hu, pid, copies=0).status_code == 422
    assert pj(client, hu, pid, color=True).status_code == 422                         # pas de couleur
    assert pj(client, hu, pid, paper="A3").status_code == 422
    assert pj(client, hu, pid, duplex="bizarre").status_code == 422
    assert pj(client, hu, pid, duplex="two-sided-long-edge").status_code == 201      # recto-verso pris en charge
    assert pj(client, hu, pid, name="rapport.docx", content=b"PK\x03\x04xx").status_code == 422   # non imprimable
    assert pj(client, hu, pid, name="faux.pdf", content=b"\x89PNG" + b"0" * 50).status_code == 422
    assert pj(client, hu, pid, name="vide.pdf", content=b"").status_code == 422
    assert pj(client, hu, pid, name="gros.pdf", content=PDF + b"0" * (21 * 1024 * 1024)).status_code == 413
    assert pj(client, hu, pid, name="../../x.pdf", content=PDF + b"9").json()["original_name"] == "x.pdf"
    # sans poste approuvé : refusé
    nodev = login(client, "emp@fph.org", "Passw0rd-long-1")
    assert pj(client, nodev, pid).status_code == 403
    assert not [f for f in os.listdir(os.path.join(settings.storage_dir, "print")) if f.endswith(".part")]


def test_full_lifecycle_and_file_deleted_at_end(client, root):
    ah, aid, pid, hu, ho, uid = setup(client, root)
    j = pj(client, hu, pid, copies=2).json()
    assert j["status"] == "pending" and j["status_label"] == "en attente" and j["printer_online"] is True
    got = claim(client, ah)
    assert [x["job_id"] for x in got["new"]] == [j["id"]] and got["new"][0]["copies"] == 2
    assert claim(client, ah)["new"] == []                                             # pas de double prise
    f = client.get(f"/api/v1/agent/jobs/{j['id']}/file", headers=ah)
    assert f.status_code == 200 and f.content == PDF + b"1" and f.headers["x-fph-sha256"] == got["new"][0]["sha256"]
    assert client.get(f"/api/v1/print-jobs/{j['id']}", headers=hu).json()["status"] == "accepted"
    assert set_status(client, ah, j["id"], "accepted", backend_job_id="FILE-1").status_code == 200
    set_status(client, ah, j["id"], "in_progress")
    assert client.get(f"/api/v1/print-jobs/{j['id']}", headers=hu).json()["status_label"] == "en cours"
    assert [r["job_id"] for r in claim(client, ah)["resume"]] == [j["id"]]            # l'agent peut reprendre le suivi
    set_status(client, ah, j["id"], "completed")
    done = client.get(f"/api/v1/print-jobs/{j['id']}", headers=hu).json()
    assert done["status"] == "completed" and done["final_state_known"] is True
    assert os.listdir(os.path.join(settings.storage_dir, "print")) == []              # document supprimé du serveur
    assert set_status(client, ah, j["id"], "in_progress").json()["status"] == "completed"   # jamais rouvert
    assert client.get(f"/api/v1/agent/jobs/{j['id']}/file", headers=ah).status_code == 409


def test_job_visibility_and_isolation_between_agents(client, root):
    ah, aid, pid, hu, ho, uid = setup(client, root)
    j = pj(client, hu, pid).json()
    assert client.get(f"/api/v1/print-jobs/{j['id']}", headers=ho).status_code == 404         # autre utilisateur
    assert client.get("/api/v1/print-jobs", headers=ho).json() == []
    assert [x["id"] for x in client.get("/api/v1/admin/print-jobs", headers=root).json()] == [j["id"]]
    ah2, aid2 = new_agent(client, root, "Autre agent")
    report(client, ah2, names=("EPSON",))
    assert claim(client, ah2)["new"] == []                                                    # pas SES imprimantes
    claim(client, ah)
    assert client.get(f"/api/v1/agent/jobs/{j['id']}/file", headers=ah2).status_code == 404
    assert set_status(client, ah2, j["id"], "completed").status_code == 404


def test_cancellation_rules(client, root):
    ah, aid, pid, hu, ho, uid = setup(client, root)
    a = pj(client, hu, pid, content=PDF + b"a").json()
    assert client.post(f"/api/v1/print-jobs/{a['id']}/cancel", headers=ho).status_code == 404   # pas le propriétaire
    c = client.post(f"/api/v1/print-jobs/{a['id']}/cancel", headers=hu).json()
    assert c["status"] == "cancelled" and os.listdir(os.path.join(settings.storage_dir, "print")) == []
    assert client.post(f"/api/v1/print-jobs/{a['id']}/cancel", headers=hu).status_code == 409
    # pris en charge par l'agent : annulation DEMANDÉE, pas immédiate
    b = pj(client, hu, pid, content=PDF + b"b").json()
    claim(client, ah)
    r = client.post(f"/api/v1/print-jobs/{b['id']}/cancel", headers=hu).json()
    assert r["status"] == "accepted" and r["cancel_requested"] is True
    assert client.get(f"/api/v1/agent/jobs/{b['id']}/file", headers=ah).status_code == 409   # l'agent ne l'imprimera pas
    assert set_status(client, ah, b["id"], "cancelled").json()["status"] == "cancelled"
    # déjà en cours côté imprimante : l'agent reçoit l'ordre d'annuler
    d = pj(client, hu, pid, content=PDF + b"d").json()
    claim(client, ah)
    set_status(client, ah, d["id"], "accepted", backend_job_id="FILE-9")
    set_status(client, ah, d["id"], "in_progress")
    client.post(f"/api/v1/print-jobs/{d['id']}/cancel", headers=hu)
    got = claim(client, ah)
    entry = {"job_id": d["id"], "system_name": "HP-1", "backend_job_id": "FILE-9"}
    assert got["cancel"] == [entry]
    assert got["resume"] == [entry]          # non-régression : reste suivi, sinon bloqué « en cours » si l'annulation échoue
    # un terminé ne s'annule pas ; un administrateur peut annuler le travail d'un autre
    e = pj(client, hu, pid, content=PDF + b"e").json()
    hadmin, _ = device_for(client, root, root, "PC admin")                              # administrateur sur un poste approuvé
    assert client.post(f"/api/v1/print-jobs/{e['id']}/cancel", headers=ho).status_code == 404   # simple utilisateur : non
    r = client.post(f"/api/v1/print-jobs/{e['id']}/cancel", headers=hadmin)
    assert r.status_code == 200 and r.json()["status"] == "cancelled"                   # administrateur : oui
    f = pj(client, hu, pid, content=PDF + b"f").json()
    claim(client, ah); set_status(client, ah, f["id"], "completed")
    assert client.post(f"/api/v1/print-jobs/{f['id']}/cancel", headers=hu).status_code == 409
    # annulation faite sur le poste d'impression sans demande : enregistrée comme erreur, pas comme annulation utilisateur
    g = pj(client, hu, pid, content=PDF + b"g").json()
    claim(client, ah)
    assert set_status(client, ah, g["id"], "cancelled").json()["status"] == "error"


def test_agent_crash_recovery_without_double_printing(client, root):
    ah, aid, pid, hu, ho, uid = setup(client, root)
    j = pj(client, hu, pid).json()
    claim(client, ah)                                                                   # l'agent prend, puis disparaît
    def expire_lease():
        with SessionLocal() as db:
            for x in db.query(PrintJob).all():
                x.claim_expires_at = now() - timedelta(seconds=1)
            db.commit()
    expire_lease()
    again = claim(client, ah)                                                           # remis en file puis repris
    assert [x["job_id"] for x in again["new"]] == [j["id"]]
    with SessionLocal() as db:
        assert db.get(PrintJob, j["id"]).attempts == 2
    # l'agent confirme l'envoi à l'imprimante : plus JAMAIS repris automatiquement
    set_status(client, ah, j["id"], "accepted", backend_job_id="FILE-3")
    expire_lease()
    assert claim(client, ah)["new"] == []
    assert client.get(f"/api/v1/print-jobs/{j['id']}", headers=hu).json()["status"] == "accepted"
    # trop de tentatives sans confirmation : erreur claire
    k = pj(client, hu, pid, content=PDF + b"k").json()
    for _ in range(settings.print_max_attempts + 1):
        claim(client, ah)
        expire_lease()
    last = claim(client, ah)
    assert client.get(f"/api/v1/print-jobs/{k['id']}", headers=hu).json()["status"] == "error"


def test_stale_pending_jobs_expire_and_files_are_removed(client, root):
    ah, aid, pid, hu, ho, uid = setup(client, root)
    j = pj(client, hu, pid).json()
    with SessionLocal() as db:
        db.get(PrintJob, j["id"]).created_at = now() - timedelta(hours=settings.print_expiry_hours + 1)
        db.commit()
    got = client.get(f"/api/v1/print-jobs/{j['id']}", headers=hu).json()
    assert got["status"] == "error" and "Expiré" in got["error"]
    assert os.listdir(os.path.join(settings.storage_dir, "print")) == []


def test_unknown_state_becomes_transmitted_never_completed(client, root):
    ah, aid, pid, hu, ho, uid = setup(client, root)
    j = pj(client, hu, pid).json()
    claim(client, ah)
    set_status(client, ah, j["id"], "accepted", backend_job_id="Q-1")
    for _ in range(2):
        assert set_status(client, ah, j["id"], "unknown").json()["status"] == "accepted"
    assert set_status(client, ah, j["id"], "unknown").json()["status"] == "transmitted"
    out = client.get(f"/api/v1/print-jobs/{j['id']}", headers=hu).json()
    assert out["status"] == "transmitted" and out["final_state_known"] is False and "non confirmable" in out["status_label"]


def test_idempotency_quota_offline_and_revoked_agent(client, root):
    ah, aid, pid, hu, ho, uid = setup(client, root)
    h = {**hu, "Idempotency-Key": "impr-0001"}
    a = client.post("/api/v1/print-jobs", headers=h, data={"printer_id": pid}, files={"file": ("a.pdf", PDF + b"i")})
    b = client.post("/api/v1/print-jobs", headers=h, data={"printer_id": pid}, files={"file": ("a.pdf", PDF + b"i")})
    assert (a.status_code, b.status_code) == (201, 200) and a.json()["id"] == b.json()["id"]
    assert len(client.get("/api/v1/print-jobs", headers=hu).json()) == 1
    for i in range(settings.print_max_active_per_user - 1):
        assert pj(client, hu, pid, content=PDF + str(i).encode()).status_code == 201
    assert pj(client, hu, pid, content=PDF + b"trop").status_code == 429
    # imprimante hors ligne : le travail est accepté mais l'utilisateur est prévenu
    with SessionLocal() as db:
        db.get(Device, aid).last_seen_at = now() - timedelta(hours=1)
        db.commit()
    assert [p["online"] for p in client.get("/api/v1/printers", headers=hu).json()] == [False]
    # agent révoqué : bloqué immédiatement
    client.post(f"/api/v1/devices/{aid}/revoke", headers=root)
    assert client.post("/api/v1/agent/jobs/claim", headers=ah).status_code == 403
    assert client.post("/api/v1/agent/report", headers=ah, json={"printers": []}).status_code == 403


def test_audit_has_no_document_names(client, root):
    ah, aid, pid, hu, ho, uid = setup(client, root)
    pj(client, hu, pid, name="Licenciement-Pasteur-X.pdf")
    audit = str(client.get("/api/v1/admin/audit?limit=100", headers=root).json())
    assert "print.job_created" in audit and "Licenciement" not in audit and "printer.grant" in audit
    assert "printer.discovered" in audit
