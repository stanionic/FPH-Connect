"""Agent d'impression de bout en bout : vrai serveur (en mémoire) + backends fichier / faux CUPS."""
import json
import os
import stat

import httpx
import pytest

from fph_agent.agent import Agent
from fph_agent.backends import (Backend, BackendError, CupsBackend, FileBackend, WindowsBackend, safe_title)
from fph_agent.client import AgentClient

from .conftest import PDF, device_for, login, make_church, make_user
from .test_printing import CAPS, pj

SECRET_MARKER = "QZX-DOCUMENT"


class FakeBackend(Backend):
    """Backend à comportement contrôlé par le test."""
    def __init__(self):
        super().__init__({"HP-1": CAPS})
        self.next_status, self.fail, self.cancel_ok, self.submitted, self.cancelled = "processing", None, True, [], []

    def list_printers(self, share):
        return [{"system_name": q, "name": q, "backend": "file", "capabilities": self.caps_for(q)} for q in share]

    def submit(self, path, queue, copies, options, title):
        if self.fail:
            raise BackendError(self.fail)
        self.submitted.append({"queue": queue, "copies": copies, "options": options, "title": title,
                               "content": open(path, "rb").read()})
        return f"FAKE-{len(self.submitted)}"

    def status(self, bid, queue):
        return self.next_status

    def cancel(self, bid, queue):
        self.cancelled.append(bid)
        return self.cancel_ok


def make_agent(client, root, tmp_path, backend=None, share=("HP-1",), http=None):
    r = client.post("/api/v1/admin/agents", headers=root, json={"name": "Agent test", "platform": "linux"}).json()
    ac = AgentClient("http://testserver", r["device_header"], http=http or client)
    os.makedirs(tmp_path / "tmp", exist_ok=True)
    backend = backend or FileBackend(str(tmp_path / "out"), {"HP-1": CAPS})
    return Agent(ac, backend, list(share), tmp_root=str(tmp_path / "tmp"), log=lambda *_: None), ac, r["id"]


def enable_for_user(client, root, agent):
    agent.run_once()                                              # l'agent annonce ses imprimantes
    pid = client.get("/api/v1/admin/printers", headers=root).json()[0]["id"]
    c = make_church(client, root)
    make_user(client, root, "emp@fph.org", "employee", church_id=c["id"])
    hu, _ = device_for(client, root, login(client, "emp@fph.org", "Passw0rd-long-1"), "PC emp")
    uid = client.get("/api/v1/auth/me", headers=hu).json()["id"]
    client.patch(f"/api/v1/admin/printers/{pid}", headers=root, json={"enabled": True})
    client.put(f"/api/v1/admin/printers/{pid}/grants/{uid}", headers=root)
    return pid, hu


def state(client, hu, jid):
    return client.get(f"/api/v1/print-jobs/{jid}", headers=hu).json()


def test_end_to_end_file_printer_prints_and_cleans_up(client, root, tmp_path):
    ag, ac, aid = make_agent(client, root, tmp_path)
    pid, hu = enable_for_user(client, root, ag)
    j = pj(client, hu, pid, content=PDF + b"contenu", copies=2, duplex="two-sided-long-edge").json()
    stats = ag.run_once()
    assert stats == {"printed": 1, "errors": 0, "network_error": False}
    assert state(client, hu, j["id"])["status"] == "completed"
    outdir = tmp_path / "out" / "HP-1"
    bins = [f for f in os.listdir(outdir) if f.endswith(".bin")]
    assert len(bins) == 1 and (outdir / bins[0]).read_bytes() == PDF + b"contenu"
    meta = json.loads((outdir / bins[0].replace(".bin", ".json")).read_text())
    assert meta["copies"] == 2 and meta["duplex"] == "two-sided-long-edge" and meta["paper"] == "A4"
    assert os.listdir(tmp_path / "tmp") == []                        # aucun document résiduel sur le poste de l'agent
    assert ag.run_once()["printed"] == 0                             # pas de réimpression


def test_agent_shares_only_what_is_listed_and_refuses_empty_share(client, root, tmp_path):
    with pytest.raises(ValueError):
        make_agent(client, root, tmp_path, share=("", "  "))
    ag, ac, aid = make_agent(client, root, tmp_path, share=("HP-1",))
    ag.run_once()
    assert [p["system_name"] for p in client.get("/api/v1/admin/printers", headers=root).json()] == ["HP-1"]
    assert client.get("/api/v1/admin/printers", headers=root).json()[0]["enabled"] is False   # découverte != activation


def test_job_for_a_queue_not_shared_is_refused_locally(client, root, tmp_path):
    ag, ac, aid = make_agent(client, root, tmp_path)
    pid, hu = enable_for_user(client, root, ag)
    j = pj(client, hu, pid).json()
    ag.share = ["Autre-File"]                                       # l'opérateur a retiré HP-1 du partage
    assert ag.run_once()["errors"] == 1
    out = state(client, hu, j["id"])
    assert out["status"] == "error" and "non partagée" in out["error"]
    assert not os.path.exists(tmp_path / "out" / "HP-1")             # rien n'a été imprimé


def test_corrupted_download_is_detected_before_printing(client, root, tmp_path):
    fb = FakeBackend()
    ag, ac, aid = make_agent(client, root, tmp_path, backend=fb)
    pid, hu = enable_for_user(client, root, ag)
    j = pj(client, hu, pid, content=PDF + b"intact").json()
    ac.download = lambda job_id: PDF + b"altere"                     # corruption pendant le transfert
    ag.run_once()
    assert fb.submitted == []
    out = state(client, hu, j["id"])
    assert out["status"] == "error" and "corrompu" in out["error"]


def test_backend_failure_gives_clean_error_and_next_job_continues(client, root, tmp_path):
    fb = FakeBackend()
    ag, ac, aid = make_agent(client, root, tmp_path, backend=fb)
    pid, hu = enable_for_user(client, root, ag)
    a = pj(client, hu, pid, content=PDF + b"a").json()
    fb.fail = "L'impression a été refusée par le système local"
    ag.run_once()
    out = state(client, hu, a["id"])
    assert out["status"] == "error" and "refusée" in out["error"] and "/tmp" not in out["error"]
    fb.fail, fb.next_status = None, "completed"
    b = pj(client, hu, pid, content=PDF + b"b").json()
    ag.run_once()
    assert state(client, hu, b["id"])["status"] == "completed"


def test_restart_resumes_tracking_without_duplicate_print(client, root, tmp_path):
    fb = FakeBackend()
    ag, ac, aid = make_agent(client, root, tmp_path, backend=fb)
    pid, hu = enable_for_user(client, root, ag)
    j = pj(client, hu, pid).json()
    ag.run_once()
    assert state(client, hu, j["id"])["status"] == "in_progress" and len(fb.submitted) == 1
    ag2 = Agent(ac, fb, ["HP-1"], tmp_root=str(tmp_path / "tmp"), log=lambda *_: None)   # redémarrage : aucune mémoire
    fb.next_status = "completed"
    ag2.run_once()
    assert state(client, hu, j["id"])["status"] == "completed"
    assert len(fb.submitted) == 1                                    # imprimé UNE seule fois


def test_cancel_while_printing_is_attempted_and_honest_when_impossible(client, root, tmp_path):
    fb = FakeBackend()
    ag, ac, aid = make_agent(client, root, tmp_path, backend=fb)
    pid, hu = enable_for_user(client, root, ag)
    j = pj(client, hu, pid, content=PDF + b"x").json()
    ag.run_once()
    client.post(f"/api/v1/print-jobs/{j['id']}/cancel", headers=hu)
    fb.cancel_ok = False                                             # trop tard : déjà sorti de l'imprimante
    fb.next_status = "completed"
    ag.run_once()
    assert fb.cancelled == ["FAKE-1"] and state(client, hu, j["id"])["status"] == "completed"   # pas d'annulation mensongère
    k = pj(client, hu, pid, content=PDF + b"y").json()
    fb.cancel_ok, fb.next_status = True, "processing"
    ag.run_once()
    client.post(f"/api/v1/print-jobs/{k['id']}/cancel", headers=hu)
    ag.run_once()
    assert state(client, hu, k["id"])["status"] == "cancelled"


def test_untrackable_backend_ends_transmitted_not_completed(client, root, tmp_path):
    fb = FakeBackend()
    fb.next_status = "unknown"
    ag, ac, aid = make_agent(client, root, tmp_path, backend=fb)
    pid, hu = enable_for_user(client, root, ag)
    j = pj(client, hu, pid).json()
    for _ in range(3):
        ag.run_once()
    out = state(client, hu, j["id"])
    assert out["status"] == "transmitted" and out["final_state_known"] is False


def test_network_outage_loses_nothing(client, root, tmp_path):
    class Offline:
        def request(self, *a, **k):
            raise httpx.ConnectError("réseau coupé")
    fb = FakeBackend()
    ag, ac, aid = make_agent(client, root, tmp_path, backend=fb)
    pid, hu = enable_for_user(client, root, ag)
    j = pj(client, hu, pid).json()
    online = ac.http
    ac.http = Offline()
    assert ag.run_once()["network_error"] is True and fb.submitted == []
    assert state(client, hu, j["id"])["status"] == "pending"
    ac.http = online
    fb.next_status = "completed"
    assert ag.run_once()["printed"] == 1 and state(client, hu, j["id"])["status"] == "completed"


def test_revoked_agent_cannot_pull_documents(client, root, tmp_path):
    ag, ac, aid = make_agent(client, root, tmp_path)
    pid, hu = enable_for_user(client, root, ag)
    j = pj(client, hu, pid).json()
    client.post(f"/api/v1/devices/{aid}/revoke", headers=root)
    assert ag.run_once()["errors"] == 1
    assert state(client, hu, j["id"])["status"] == "pending"
    assert not os.path.exists(tmp_path / "out" / "HP-1")


# ---------------- backend CUPS contre de FAUX exécutables ----------------
def fake_cups(tmp_path, monkeypatch):
    st = tmp_path / "state"
    st.mkdir()
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    scripts = {
        "lp": '#!/bin/sh\nprintf \'%s\\n\' "$@" > "$STATE/lp.args"\n[ -f "$STATE/lp.fail" ] && { echo "lp: erreur" >&2; exit 1; }\n'
              'n=$(cat "$STATE/counter" 2>/dev/null || echo 0); n=$((n+1)); echo $n > "$STATE/counter"\necho "request id is HP-1-$n (1 file(s))"\n',
        "lpstat": '#!/bin/sh\ncase "$1" in\n -a) cat "$STATE/accepting";;\n -o) cat "$STATE/active" 2>/dev/null;;\n'
                  ' -p) if [ -f "$STATE/printing" ]; then echo "printer $2 now printing $(cat $STATE/printing).  enabled since Mon 01 Jan 2026"; '
                  'else echo "printer $2 is idle.  enabled since Mon 01 Jan 2026"; fi;;\n -W) cat "$STATE/completed" 2>/dev/null;;\nesac\n',
        "cancel": '#!/bin/sh\nprintf \'%s\\n\' "$@" > "$STATE/cancel.args"\n[ -f "$STATE/cancel.fail" ] && exit 1\nexit 0\n',
    }
    for n, body in scripts.items():
        p = bin_ / n
        p.write_text(body)
        p.chmod(p.stat().st_mode | stat.S_IEXEC)
    (st / "accepting").write_text("HP-1 accepting requests since Mon 01 Jan 2026\nSecret-Printer accepting requests since Mon 01 Jan 2026\n")
    monkeypatch.setenv("STATE", str(st))
    return CupsBackend(lp=str(bin_ / "lp"), lpstat=str(bin_ / "lpstat"), cancel_cmd=str(bin_ / "cancel")), st


def test_cups_backend_lists_only_shared_and_submits_safely(tmp_path, monkeypatch):
    cb, st = fake_cups(tmp_path, monkeypatch)
    assert [p["system_name"] for p in cb.list_printers(["HP-1", "Absente"])] == ["HP-1"]    # pas de partage implicite
    f = tmp_path / "doc.pdf"
    f.write_bytes(PDF)
    bid = cb.submit(str(f), "HP-1", 3, {"duplex": "two-sided-long-edge", "paper": "A4", "color": False},
                    "$(touch %s/PWNED) ; rm -rf /" % tmp_path)
    assert bid == "HP-1-1"
    args = (st / "lp.args").read_text().splitlines()
    assert args[:4] == ["-d", "HP-1", "-n", "3"] and "sides=two-sided-long-edge" in args and "media=A4" in args
    assert "print-color-mode=monochrome" in args and args[-1] == str(f)
    title = args[args.index("-t") + 1]
    assert "$" not in title and "(" not in title and ";" not in title                          # titre assaini
    assert not (tmp_path / "PWNED").exists()                                                   # aucune exécution shell


def test_cups_backend_rejects_hostile_input_and_reports_failure(tmp_path, monkeypatch):
    cb, st = fake_cups(tmp_path, monkeypatch)
    f = tmp_path / "doc.pdf"
    f.write_bytes(PDF)
    with pytest.raises(BackendError):
        cb.submit(str(f), "HP-1; rm -rf /", 1, {}, "t")
    with pytest.raises(BackendError):
        cb.submit(str(f), "HP-1", 1, {"paper": "A4; evil"}, "t")
    with pytest.raises(BackendError):
        cb.submit(str(f), "HP-1", 0, {}, "t")
    with pytest.raises(BackendError):
        cb.submit(str(f), "HP-1", 1, {"duplex": "../../x"}, "t")
    (st / "lp.fail").write_text("1")
    with pytest.raises(BackendError) as e:
        cb.submit(str(f), "HP-1", 1, {}, "t")
    assert "refusée" in str(e.value) and str(tmp_path) not in str(e.value)                     # pas de fuite de chemin


def test_cups_status_mapping_never_overclaims(tmp_path, monkeypatch):
    cb, st = fake_cups(tmp_path, monkeypatch)
    assert cb.status("HP-1-7", "HP-1") == "unknown"                                            # introuvable : on ne devine pas
    (st / "active").write_text("HP-1-7 emp 1024 Mon 01 Jan 2026\n")
    assert cb.status("HP-1-7", "HP-1") == "queued"
    (st / "printing").write_text("HP-1-7")
    assert cb.status("HP-1-7", "HP-1") == "processing"
    assert cb.status("HP-1-70", "HP-1") == "unknown"                                           # préfixe d'identifiant != même travail
    (st / "active").write_text("")
    (st / "printing").unlink()
    (st / "completed").write_text("HP-1-7 emp 1024 Mon 01 Jan 2026\n")
    assert cb.status("HP-1-7", "HP-1") == "completed"
    assert cb.cancel("HP-1-7", "HP-1") is True and (st / "cancel.args").read_text().strip() == "HP-1-7"
    (st / "cancel.fail").write_text("1")
    assert cb.cancel("HP-1-7", "HP-1") is False


def test_cups_missing_binaries_give_clean_error(tmp_path):
    cb = CupsBackend(lp="/nonexistent/lp", lpstat="/nonexistent/lpstat", cancel_cmd="/nonexistent/cancel")
    with pytest.raises(BackendError) as e:
        cb.list_printers(["HP-1"])
    assert "/nonexistent" not in str(e.value)


def test_windows_backend_builds_command_and_never_claims_completion(tmp_path, monkeypatch):
    calls = []

    class R:
        returncode = 0
        stdout = ""

    monkeypatch.setattr("fph_agent.backends.subprocess.run", lambda args, **kw: (calls.append(args), R())[1])
    wb = WindowsBackend("C:/Sumatra/SumatraPDF.exe")
    bid = wb.submit("C:/tmp/x.pdf", "Ma File", 2, {"duplex": "two-sided-short-edge", "paper": "A4", "color": True}, "t")
    args = calls[0]
    assert args[:4] == ["C:/Sumatra/SumatraPDF.exe", "-print-to", "Ma File", "-print-settings"]
    assert args[4] == "2x,color,paper=A4,duplexshort" and args[-2:] == ["-silent", "C:/tmp/x.pdf"]
    assert wb.status(bid, "Ma File") == "transmitted" and wb.tracking == "none"


def test_safe_title():
    assert safe_title("a/b\\c:$(x);`y`") == "a_b_c___x___y_"
    assert safe_title("") == "document" and len(safe_title("x" * 500)) == 60
