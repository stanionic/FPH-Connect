#!/usr/bin/env python3
"""Vérification sur un VRAI réseau (HTTP réel + découverte UDP réelle).

Simule deux machines et le super administrateur : enregistrement, approbation, présence,
messages dans les deux sens, révocation, dépôt d'un document et classement en un clic.

ATTENTION : écrit des données de test (église, 2 comptes « smoke-… », 1 document). À lancer
sur une base de test ou à nettoyer ensuite. Les mots de passe viennent de l'environnement.

  FPH_URL=http://192.168.1.10:8000     (sinon : découverte automatique)
  FPH_ADMIN_ID=...  FPH_ADMIN_PASSWORD=...  [FPH_ADMIN_NEW_PASSWORD=... si changement obligatoire]
  [FPH_CA_CERT=certs/ca.pem]   (serveur en https : autorité FPH à laquelle faire confiance)
  [FPH_DISCOVERY_TARGET=255.255.255.255] [FPH_DISCOVERY_PORT=50505]
"""
import os
import random
import string
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "client"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "connectors", "flask"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agent"))
from fph_client.api import ApiClient, ApiError          # noqa: E402
from fph_client.device import DeviceIdentity            # noqa: E402
from fph_client.discovery import discover               # noqa: E402
from fph_flask_connector import forward_registration     # noqa: E402

failures = []
CA = os.environ.get("FPH_CA_CERT") or None      # autorité FPH (ca.pem) si le serveur est en https


def check(label, ok, extra=""):
    print(("  OK   " if ok else "  ÉCHEC") + f" {label} {extra}")
    if not ok:
        failures.append(label)


def expect_status(label, fn, status):
    try:
        fn()
        check(label, False, "(aucune erreur reçue)")
    except ApiError as e:
        check(label, e.status == status, f"(HTTP {e.status})")


def main():
    tag = "".join(random.choices(string.ascii_lowercase + string.digits, k=5))
    url = os.environ.get("FPH_URL")
    print("1. Découverte du serveur")
    found = discover(timeout=2.0, port=int(os.environ.get("FPH_DISCOVERY_PORT", 50505)),
                     target=os.environ.get("FPH_DISCOVERY_TARGET", "255.255.255.255"))
    check("serveur découvert sur le réseau", bool(found), str([f["url"] for f in found]))
    url = url or (found[0]["url"] if found else None)
    if not url:
        sys.exit("Aucun serveur : définissez FPH_URL")
    tmp = tempfile.mkdtemp()

    if url.startswith("https://"):
        import httpx
        print("1b. Chiffrement (TLS) : la vérification du certificat est réellement active")
        try:
            httpx.get(url + "/health", timeout=5)          # magasin du système : ne connaît pas l'autorité FPH
            check("sans l'autorité FPH, le certificat est refusé", False, "(connexion acceptée !)")
        except httpx.HTTPError as e:
            check("sans l'autorité FPH, le certificat est refusé", "CERTIFICATE_VERIFY_FAILED" in str(e))
        ok = httpx.get(url + "/health", timeout=5, verify=__import__("ssl").create_default_context(cafile=CA)) if CA else None
        check("avec l'autorité FPH, la connexion chiffrée aboutit", bool(ok) and ok.status_code == 200)
        try:
            httpx.get("http://" + url[len("https://"):] + "/health", timeout=5)
            check("HTTP clair refusé sur le port chiffré", False, "(réponse reçue en clair !)")
        except httpx.HTTPError:
            check("HTTP clair refusé sur le port chiffré", True)
    else:
        print("1b. (serveur en HTTP clair : aucun chiffrement — à ne pas utiliser hors essai)")

    print("2. Super administrateur")
    admin = ApiClient(url, ca_file=CA)
    admin.device = DeviceIdentity(os.path.join(tmp, "admin.json"))
    admin.login(os.environ["FPH_ADMIN_ID"], os.environ["FPH_ADMIN_PASSWORD"])
    me = admin.me()
    check("connexion du super administrateur", me["role"] == "superadmin")
    if me["must_change_password"]:
        expect_status("action bloquée tant que le mot de passe n'est pas changé", admin.list_churches, 403)
        new = os.environ.get("FPH_ADMIN_NEW_PASSWORD")
        if not new:
            sys.exit("Changement de mot de passe obligatoire : définissez FPH_ADMIN_NEW_PASSWORD")
        admin._req("POST", "/api/v1/auth/change-password",
                   json={"current_password": os.environ["FPH_ADMIN_PASSWORD"], "new_password": new})
        check("mot de passe changé, accès débloqué", admin.me()["must_change_password"] is False)
    d = admin.register_device("Poste super admin", "linux")
    admin._req("POST", f"/api/v1/devices/{d['id']}/approve", json={"office": "Siège"})

    church_name = f"Église Smoke {tag}"
    church = admin._req("POST", "/api/v1/churches", json={
        "official_name": church_name, "department": "Ouest", "commune": "Delmas"})
    machines = {}
    for who in ("a", "b"):
        uname = f"smoke-{who}-{tag}"
        admin._req("POST", "/api/v1/users", json={
            "username": uname, "email": f"{uname}@fph-smoke.org", "full_name": f"Machine {who.upper()}",
            "password": f"Smoke-{tag}-pass-1", "role_code": "employee", "church_id": church["id"]})
        c = ApiClient(url, ca_file=CA)
        c.device = DeviceIdentity(os.path.join(tmp, f"{who}.json"))
        c.login(uname, f"Smoke-{tag}-pass-1")
        machines[who] = c

    print("3. Une machine non autorisée ne communique pas")
    a, b = machines["a"], machines["b"]
    infos = {k: m.register_device(f"PC {k.upper()}", "linux") for k, m in machines.items()}
    expect_status("machine A refusée avant approbation", a.messages, 403)
    check("statut « pending » visible par la machine", a.device_status()["status"] == "pending")

    print("4. Le super administrateur autorise les machines")
    for k in ("a", "b"):
        admin._req("POST", f"/api/v1/devices/{infos[k]['id']}/approve", json={"office": f"Bureau {k.upper()}"})
    a.heartbeat(); b.heartbeat()
    pres = {p["name"]: p["online"] for p in a.presence()}
    check("A voit A et B en ligne", pres.get("PC A") and pres.get("PC B"), str(pres))

    print("5. Messages dans les deux sens")
    ids = {u["full_name"]: u["id"] for u in a.directory()}
    a.send_message("Bonjour B", recipient_id=ids["Machine B"], client_ref=f"r-{tag}-1")
    b_ids = {u["full_name"]: u["id"] for u in b.directory()}
    check("B reçoit le message de A", [m["body"] for m in b.messages()] == ["Bonjour B"])
    b.send_message("Bien reçu A", recipient_id=b_ids["Machine A"])
    check("A reçoit la réponse de B", "Bien reçu A" in [m["body"] for m in a.messages()])

    print("6. Révocation immédiate")
    admin._req("POST", f"/api/v1/devices/{infos['b']['id']}/revoke")
    expect_status("machine B révoquée refusée aussitôt", b.messages, 403)
    check("machine A continue de fonctionner", a.messages() is not None)

    print("7. Document : zone tampon puis classement en un clic")
    a.upload_document(f"Rapport {church_name}.pdf", b"%PDF-1.4\n" + tag.encode() * 40)
    check("document en zone tampon", len(a.inbox()) == 1)
    res = admin.organize()
    check("classé automatiquement", res["counts"] == {"organized": 1} and res["items"][0]["church_id"] == church["id"],
          str(res["counts"]))
    check("annulable", admin.undo_batch(res["batch_id"]) == {"restored": 1})
    admin.organize()                                     # remet le document en bibliothèque

    print("8. Site web -> inscription signée (HTTP réel, secret d'intégration)")
    from datetime import datetime, timedelta, timezone
    integ = admin._req("POST", "/api/v1/admin/integrations",
                       json={"name": f"smoke-site-{tag}", "kind": "flask", "base_url": url})
    admin._req("PATCH", f"/api/v1/admin/integrations/{integ['id']}", json={"enabled": True, "mode": "live"})
    start = (datetime.now(timezone.utc) + timedelta(days=10)).isoformat()
    ev = admin._req("POST", "/api/v1/events", json={"title": f"Assemblée smoke {tag}", "starts_at": start,
                                                    "capacity": 1, "location": "Delmas"})
    for act in ("submit", "approve", "publish"):
        admin._req("POST", f"/api/v1/events/{ev['id']}/transition", json={"action": act})
    admin._req("POST", f"/api/v1/events/{ev['id']}/registration", json={"open": True})
    check("événement visible publiquement", any(e["id"] == ev["id"] for e in admin._req("GET", "/api/v1/public/events")))
    person = lambda n: {"event_id": ev["id"], "full_name": n, "email": f"{n.lower()}@fph-smoke.org", "consent": True}
    st, r1 = forward_registration(url, integ["id"], integ["secret"], person("Alice"), idempotency_key=f"smoke-{tag}-0001", ca_file=CA)
    check("inscription signée acceptée", st == 200 and r1.get("status") == "registered", str(r1))
    st, r1b = forward_registration(url, integ["id"], integ["secret"], person("Alice"), idempotency_key=f"smoke-{tag}-0001", ca_file=CA)
    check("renvoi du même formulaire : pas de doublon", r1b.get("registration_id") == r1.get("registration_id"))
    st, r2 = forward_registration(url, integ["id"], integ["secret"], person("Bruno"), idempotency_key=f"smoke-{tag}-0002", ca_file=CA)
    check("événement complet : liste d'attente", r2.get("status") == "waitlisted", str(r2))
    st, _ = forward_registration(url, integ["id"], "x" * 64, person("Pirate"), idempotency_key=f"smoke-{tag}-0003", ca_file=CA)
    check("signature falsifiée refusée", st == 401, f"(HTTP {st})")
    regs = admin._req("GET", f"/api/v1/events/{ev['id']}/registrations")
    check("l'administrateur voit 2 inscriptions (pas le pirate)", sorted(r["full_name"] for r in regs) == ["Alice", "Bruno"])
    admin._req("PATCH", f"/api/v1/admin/integrations/{integ['id']}", json={"enabled": False})   # nettoyage

    print("9. Impression réseau (vrai agent, imprimante virtuelle « fichier »)")
    from fph_agent.agent import Agent
    from fph_agent.backends import FileBackend
    from fph_agent.client import AgentClient
    outdir = os.path.join(tmp, "impression")
    ag = admin._req("POST", "/api/v1/admin/agents", json={"name": f"agent-smoke-{tag}", "platform": "linux"})
    agent = Agent(AgentClient(url, ag["device_header"], ca_file=CA),
                  FileBackend(outdir, {"FILE-PRINTER": {"duplex": True, "color": False, "paper": ["A4"], "max_copies": 5}}),
                  ["FILE-PRINTER"], tmp_root=tmp, log=lambda *_: None)
    agent.run_once()
    pr = next(p for p in admin._req("GET", "/api/v1/admin/printers") if p["agent_device_id"] == ag["id"])
    check("imprimante découverte mais désactivée (aucune autorisation automatique)", pr["enabled"] is False)
    check("invisible pour l'utilisateur tant qu'elle n'est pas activée", a.printers() == [])
    admin._req("PATCH", f"/api/v1/admin/printers/{pr['id']}", json={"enabled": True, "location": "Bureau 2"})
    check("activée mais sans accès accordé : toujours invisible", a.printers() == [])
    a_id = a.me()["id"]
    admin._req("PUT", f"/api/v1/admin/printers/{pr['id']}/grants/{a_id}")
    check("accès accordé : l'utilisateur la voit", [p["id"] for p in a.printers()] == [pr["id"]])
    uc = f"smoke-c-{tag}"
    admin._req("POST", "/api/v1/users", json={"username": uc, "email": f"{uc}@fph-smoke.org", "full_name": "Machine C",
               "password": f"Smoke-{tag}-pass-1", "role_code": "employee", "church_id": church["id"]})
    cc = ApiClient(url, ca_file=CA)
    cc.device = DeviceIdentity(os.path.join(tmp, "c.json"))
    cc.login(uc, f"Smoke-{tag}-pass-1")
    ci = cc.register_device("PC C", "linux")
    admin._req("POST", f"/api/v1/devices/{ci['id']}/approve", json={})
    expect_status("utilisateur non autorisé : impression refusée", lambda: cc.print_document(pr["id"], "x.pdf", b"%PDF-1.4 x"), 404)
    pdf = b"%PDF-1.4\n" + tag.encode() * 60
    expect_status("option non prise en charge refusée (couleur)", lambda: a.print_document(pr["id"], "x.pdf", pdf, color=True), 422)
    expect_status("format non imprimable refusé (docx)", lambda: a.print_document(pr["id"], "x.docx", b"PK\x03\x04zz"), 422)
    job = a.print_document(pr["id"], "lettre.pdf", pdf, copies=2, duplex="two-sided-long-edge", idempotency_key=f"imp-{tag}-0001")
    again = a.print_document(pr["id"], "lettre.pdf", pdf, copies=2, duplex="two-sided-long-edge", idempotency_key=f"imp-{tag}-0001")
    check("travail créé « en attente », renvoi sans doublon", job["status"] == "pending" and again["id"] == job["id"])
    res = agent.run_once()
    check("l'agent imprime le travail", res["printed"] == 1, str(res))
    check("état final « terminé » confirmé", a.print_job(job["id"])["status"] == "completed")
    printed = [f for f in os.listdir(os.path.join(outdir, "FILE-PRINTER")) if f.endswith(".bin")]
    check("le document reçu par l'imprimante est identique", len(printed) == 1 and
          open(os.path.join(outdir, "FILE-PRINTER", printed[0]), "rb").read() == pdf)
    check("aucun document résiduel sur le poste de l'agent", not [f for f in os.listdir(tmp) if f.startswith("fph-")])
    j2 = a.print_document(pr["id"], "annule.pdf", pdf + b"2")
    check("annulation d'un travail en attente", a.cancel_print_job(j2["id"])["status"] == "cancelled")
    check("l'utilisateur C ne voit pas les travaux de A", cc.print_jobs() == [])
    admin._req("POST", f"/api/v1/devices/{ag['id']}/revoke")
    check("agent révoqué : cycle refusé aussitôt", agent.run_once()["errors"] == 1)

    print("\nRÉSULTAT :", "TOUT EST OK" if not failures else f"{len(failures)} ÉCHEC(S) -> {failures}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
