#!/usr/bin/env python3
"""Photographie les écrans de l'application RÉELLE (vrai serveur en mémoire, vrai agent d'impression), sans assertions.

  xvfb-run -a python scripts/ui_screenshots.py --lang ht --size 360x640 --out captures/
  Options : --lang fr|ht|en   --size LARGEURxHAUTEUR   --out DOSSIER
Les données de démonstration sont fictives et créées en mémoire (supprimées à la fin).
"""
import argparse
import os
import secrets
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone

ap = argparse.ArgumentParser()
ap.add_argument("--lang", default="fr", choices=("fr", "ht", "en"))
ap.add_argument("--size", default="360x640")
ap.add_argument("--out", default="captures")
args = ap.parse_args()
W, H = (int(x) for x in args.size.lower().split("x"))

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
TMP = tempfile.mkdtemp(prefix="fph-shots-")
PW = "Demo-" + secrets.token_urlsafe(10) + "-7"
os.makedirs(args.out, exist_ok=True)
os.environ.update(FPH_DATABASE_URL=f"sqlite:///{TMP}/s.db", FPH_STORAGE_DIR=f"{TMP}/storage", FPH_BOOTSTRAP_ADMIN_USERNAME="demo-admin",
                  FPH_BOOTSTRAP_ADMIN_PASSWORD=PW, FPH_BOOTSTRAP_FORCE_CHANGE="0", FPH_ENV="dev", KIVY_NO_ARGS="1", FPH_LANG=args.lang)
for sub in ("server", "client", "agent"):
    sys.path.insert(0, os.path.join(ROOT, sub))

from fastapi.testclient import TestClient            # noqa: E402
from app.db import Base, engine                      # noqa: E402
from app.main import app as fastapi_app              # noqa: E402
Base.metadata.create_all(engine)

from kivy.config import Config                       # noqa: E402
Config.set("graphics", "width", str(W)); Config.set("graphics", "height", str(H)); Config.set("graphics", "resizable", "0")
from kivy.app import App                             # noqa: E402
from kivy.base import EventLoop                      # noqa: E402
from kivy.core.window import Window                  # noqa: E402
from fph_agent.agent import Agent                    # noqa: E402
from fph_agent.backends import FileBackend           # noqa: E402
from fph_agent.client import AgentClient             # noqa: E402
from fph_client import lan                           # noqa: E402
from fph_client.api import ApiClient                 # noqa: E402
sys.argv = [sys.argv[0]]
import main as fph_main                               # noqa: E402

n = [0]


def settle():
    import time
    end = time.time() + 3
    while time.time() < end:
        EventLoop.idle()
        if not getattr(sm.transition, "is_active", False):
            break
        time.sleep(0.03)
    for _ in range(3):
        EventLoop.idle()


def shot(label):
    settle(); n[0] += 1
    return Window.screenshot(name=os.path.join(args.out, f"{args.lang}-{W}x{H}-{n[0]:02d}-{label}.png"))


def go(name):
    sm.current = name
    settle()
    scr = sm.get_screen(name)
    if hasattr(scr, "refresh"):
        scr.refresh()


PDF = b"%PDF-1.4\n" + b"demo " * 80
with TestClient(fastapi_app) as srv:
    ops = ApiClient("http://testserver", http=srv)
    ops.login("demo-admin", PW)
    for name, dept, commune in (("Église Baptiste de Delmas", "Ouest", "Delmas"), ("Église Évangélique de Cap-Haïtien", "Nord", "Cap-Haïtien"),
                                ("Église de la Grâce", "Sud", "Les Cayes")):
        ops._req("POST", "/api/v1/churches", json={"official_name": name, "department": dept, "commune": commune, "affiliation_status": "affiliated"})
    ev = ops._req("POST", "/api/v1/events", json={"title": "Assemblée générale annuelle", "location": "Delmas", "capacity": 150,
                                                   "starts_at": (datetime.now(timezone.utc) + timedelta(days=12)).isoformat()})
    for a in ("submit", "approve", "publish"):
        ops._req("POST", f"/api/v1/events/{ev['id']}/transition", json={"action": a})
    ops._req("POST", f"/api/v1/events/{ev['id']}/registration", json={"open": True})
    for i, who in enumerate(("Marie Joseph", "Jean Baptiste", "Rose Laguerre")):
        ops._req("POST", f"/api/v1/events/{ev['id']}/registrations", json={"full_name": who, "email": f"p{i}@exemple.org", "consent": True})

    app = fph_main.FPHConnectApp(api=ApiClient("http://testserver", http=srv), data_dir=os.path.join(TMP, "appdata"))
    App._running_app = app
    app.root = app.build()
    sm = app.root
    EventLoop.ensure_window(); Window.add_widget(sm); settle()
    shot("connexion")
    sm.get_screen("login").do_login("demo-admin", PW); settle()
    shot("eglises")
    go("church_form"); shot("nouvelle-eglise")
    go("network"); shot("reseau-non-enregistre")
    sm.get_screen("network").register(); settle(); shot("reseau-en-attente")
    ops._req("POST", f"/api/v1/devices/{app.api.device.id}/approve", json={"office": "Bureau 1"})
    ns = sm.get_screen("network"); ns.refresh()
    lan.queue_message(app.db, "Réunion demain à 9 h", audience="all"); ns.refresh(); shot("reseau-messages")
    go("documents")
    open(os.path.join(TMP, "Rapport annuel.pdf"), "wb").write(PDF); open(os.path.join(TMP, "scan001.pdf"), "wb").write(PDF + b"2")
    for f in ("Rapport annuel.pdf", "scan001.pdf"):
        lan.queue_document(app.db, os.path.join(TMP, "tampon"), os.path.join(TMP, f))
    ds = sm.get_screen("documents"); ds.refresh(); shot("documents-en-attente")
    ds.push(); ds.organize(); shot("documents-classes")
    ag = ops._req("POST", "/api/v1/admin/agents", json={"name": "Agent", "platform": "linux"})
    agent = Agent(AgentClient("http://testserver", ag["device_header"], http=srv),
                  FileBackend(os.path.join(TMP, "sortie"), {"HP-LaserJet": {"duplex": True, "color": False, "paper": ["A4"], "max_copies": 5}}),
                  ["HP-LaserJet"], tmp_root=TMP, log=lambda *_: None)
    agent.run_once()
    go("printing"); shot("impression-aucune-imprimante")
    pr = next(p for p in ops._req("GET", "/api/v1/admin/printers") if p["agent_device_id"] == ag["id"])
    ops._req("PATCH", f"/api/v1/admin/printers/{pr['id']}", json={"enabled": True, "location": "Bureau 2"})
    ops._req("PUT", f"/api/v1/admin/printers/{pr['id']}/grants/{app.api.me()['id']}")
    agent.run_once()
    ps = sm.get_screen("printing"); ps.refresh()
    app.api.print_document(pr["id"], "Lettre officielle.pdf", PDF, copies=2); app.api.print_document(pr["id"], "Programme.pdf", PDF + b"3")
    agent.run_once(); ps.refresh(); shot("impression-travaux")
    go("events"); shot("evenements")
shutil.rmtree(TMP, ignore_errors=True)
print(f"{n[0]} captures dans {args.out}")
