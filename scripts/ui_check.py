#!/usr/bin/env python3
"""Vérification de l'application Kivy RÉELLE, pilotée comme un utilisateur (clics sur les vrais boutons),
contre un vrai serveur FPH lancé en mémoire. Linux : `xvfb-run -a python scripts/ui_check.py [dossier_captures]`

Ce que ça prouve : le fichier KV se charge, les écrans s'affichent à la taille d'un téléphone, les boutons déclenchent
le bon comportement, les erreurs sont affichées. Ce que ça NE prouve PAS : Android, Windows, le tactile, la lisibilité réelle.
"""
import os
import secrets
import shutil
import sys
import tempfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
TMP = tempfile.mkdtemp(prefix="fph-ui-")
PW = "Ui-" + secrets.token_urlsafe(12) + "-9"       # mot de passe jetable, différent à chaque exécution
SHOTS = sys.argv[1] if len(sys.argv) > 1 else os.path.join(TMP, "captures")
os.makedirs(SHOTS, exist_ok=True)

# --- serveur en mémoire (avant tout import de l'application) ---
os.environ.update(FPH_DATABASE_URL=f"sqlite:///{TMP}/ui.db", FPH_STORAGE_DIR=f"{TMP}/storage",
                  FPH_BOOTSTRAP_ADMIN_USERNAME="ui-admin", FPH_BOOTSTRAP_ADMIN_PASSWORD=PW,
                  FPH_BOOTSTRAP_FORCE_CHANGE="0", FPH_ENV="dev", KIVY_NO_ARGS="1")
for sub in ("server", "client", "agent", "connectors/flask"):
    sys.path.insert(0, os.path.join(ROOT, sub))

from fastapi.testclient import TestClient            # noqa: E402
from app.db import Base, engine                      # noqa: E402
from app.main import app as fastapi_app              # noqa: E402

Base.metadata.create_all(engine)

from kivy.config import Config                       # noqa: E402
Config.set("graphics", "width", "360")               # taille d'un téléphone
Config.set("graphics", "height", "640")
Config.set("graphics", "resizable", "0")
from kivy.app import App                             # noqa: E402
from kivy.base import EventLoop                      # noqa: E402
from kivy.core.window import Window                  # noqa: E402
from kivy.uix.button import Button                   # noqa: E402
from kivy.uix.filechooser import FileChooserListView  # noqa: E402
from kivy.uix.image import Image                     # noqa: E402
from kivy.uix.popup import Popup                     # noqa: E402

from fph_agent.agent import Agent                    # noqa: E402
from fph_agent.backends import FileBackend           # noqa: E402
from fph_agent.client import AgentClient             # noqa: E402
from fph_client.api import ApiClient                 # noqa: E402

sys.argv = [sys.argv[0]]
sys.path.insert(0, os.path.join(ROOT, "client"))
import main as fph_main                               # noqa: E402  (l'application Kivy du projet)

failures, shot_no = [], [0]


def check(label, ok, extra=""):
    print(("  OK    " if ok else "  ÉCHEC ") + f"{label} {extra}".rstrip())
    if not ok:
        failures.append(label)


def pump(n=5):
    for _ in range(n):
        EventLoop.idle()


def settle(max_seconds=3.0):
    """Attend la fin de l'animation de changement d'écran (elle dépend du temps réel) avant de photographier."""
    import time
    end = time.time() + max_seconds
    while time.time() < end:
        EventLoop.idle()
        sm_ = app.root
        if not getattr(sm_.transition, "is_active", False):
            break
        time.sleep(0.03)
    pump(3)


def shot(name):
    settle()
    shot_no[0] += 1
    path = Window.screenshot(name=os.path.join(SHOTS, f"{shot_no[0]:02d}-{name}.png"))
    return path


def walk():
    seen = list(Window.children)
    for w in list(seen):
        seen.extend(w.walk(restrict=True))
    return seen


def current_screen():
    return app.root.current_screen


def buttons(screen=None):
    return [w for w in (screen or current_screen()).walk(restrict=True) if isinstance(w, Button)]


def press(text, screen=None):
    for b in buttons(screen):
        if b.text == text:
            b.dispatch("on_release")
            settle()
            return b
    raise AssertionError(f"bouton « {text} » introuvable. Boutons : {[b.text for b in buttons(screen)]}")


def popup():
    for w in Window.children:
        if isinstance(w, Popup):
            return w
    return None


def popup_press_ok():
    pop = popup()
    assert pop is not None, "aucune fenêtre contextuelle ouverte"
    ok = next(w for w in pop.walk() if isinstance(w, Button) and w.text == "OK")
    ok.dispatch("on_release")
    pump()


def texts(screen=None):
    return " | ".join(str(getattr(w, "text", "")) for w in (screen or current_screen()).walk(restrict=True)
                      if getattr(w, "text", ""))


PDF = b"%PDF-1.4\n% ui-check\n" + b"x" * 300
with TestClient(fastapi_app) as srv:
    # --- données préparées par un opérateur (hors interface) ---
    ops = ApiClient("http://testserver", http=srv)
    ops.login("ui-admin", PW)
    ops._req("POST", "/api/v1/churches", json={"official_name": "Église Baptiste de Delmas", "department": "Ouest",
                                              "commune": "Delmas", "affiliation_status": "affiliated"})

    ui_api = ApiClient("http://testserver", http=srv)
    app = fph_main.FPHConnectApp(api=ui_api, data_dir=os.path.join(TMP, "appdata"))
    App._running_app = app
    app.root = app.build()
    EventLoop.ensure_window()
    Window.add_widget(app.root)
    pump()
    sm = app.root

    # ============ 1. Connexion ============
    print("1. Écran de connexion")
    check("l'application démarre sur l'écran de connexion", sm.current == "login")
    login = sm.get_screen("login")
    logo = next((w for w in login.walk(restrict=True) if isinstance(w, Image)), None)
    check("le logo FPH est chargé et visible sur l'écran de connexion",
          logo is not None and logo.texture is not None and logo.height > 0,
          "" if logo else "aucun widget Image sur l'écran")
    shot("connexion")
    login.ids.email.text, login.ids.password.text = "ui-admin", "mauvais-mot-de-passe"
    press("Se connecter", login)
    check("mauvais mot de passe : message affiché, on reste sur la connexion",
          sm.current == "login" and login.ids.msg.text == "Identifiants invalides", repr(login.ids.msg.text))
    login.ids.password.text = PW
    press("Se connecter", login)
    check("bonne connexion : écran des églises", sm.current == "churches")
    cs = sm.get_screen("churches")
    check("la liste des églises affiche l'église du serveur", "Église Baptiste de Delmas" in cs.ids.listing.text,
          repr(cs.ids.listing.text[:60]))
    check("l'état de synchronisation est affiché", "Dernière synchronisation" in cs.ids.status.text, repr(cs.ids.status.text[:70]))
    shot("eglises")

    # ============ 2. Réseau local ============
    print("2. Réseau local (appareil, présence, messages)")
    press("Réseau local", cs)
    ns = sm.get_screen("network")
    check("écran réseau ouvert, appareil « non enregistré »", sm.current == "network" and "non enregistré" in ns.ids.device.text,
          repr(ns.ids.device.text))
    shot("reseau-non-enregistre")
    press("Enregistrer cet appareil", ns)
    check("après enregistrement : « en attente d'approbation »", "en attente" in ns.ids.device.text, repr(ns.ids.device.text))
    check("le bouton d'enregistrement est désactivé (pas de double enregistrement)", ns.ids.reg.disabled is True)
    dev_id = ui_api.device.id
    ops._req("POST", f"/api/v1/devices/{dev_id}/approve", json={"office": "Bureau test"})
    press("Actualiser", ns)
    check("après approbation par l'administrateur : « approuvé »", "approuvé" in ns.ids.device.text, repr(ns.ids.device.text))
    check("la présence est affichée", "●" in ns.ids.presence.text or ns.ids.presence.text != "", repr(ns.ids.presence.text))
    ns.ids.body.text = "Bonjour à tous"
    press("Envoyer", ns)
    check("message de diffusion écrit puis visible dans la liste", "Bonjour à tous" in ns.ids.msgs.text, repr(ns.ids.msgs.text))
    shot("reseau-approuve")
    press("Retour", ns)
    check("retour à la liste des églises", sm.current == "churches")

    # ============ 3. Documents ============
    print("3. Documents (zone tampon puis classement en un clic)")
    press("Documents", cs)
    ds = sm.get_screen("documents")
    check("compteur de documents en attente à 0", "0" in ds.ids.status.text, repr(ds.ids.status.text))
    src = os.path.join(TMP, "Rapport annuel.pdf")
    open(src, "wb").write(PDF)
    press("Ajouter un document", ds)
    pop = popup()
    check("le sélecteur de fichier s'ouvre", pop is not None)
    chooser = next(w for w in pop.walk() if isinstance(w, FileChooserListView))
    chooser.selection = [src]
    popup_press_ok()
    check("le document est conservé localement (1 en attente)", "1" in ds.ids.status.text, repr(ds.ids.status.text))
    press("Envoyer", ds)
    check("envoi au serveur : « Envoyés : 1 »", "Envoyés: 1" in ds.ids.report.text, repr(ds.ids.report.text))
    press("Classer en un clic", ds)
    check("classement en un clic : « [classé] Rapport annuel.pdf » (état traduit)", "[classé] Rapport annuel.pdf" in ds.ids.report.text and "organized" not in ds.ids.report.text,
          repr(ds.ids.report.text[:90]))
    shot("documents")
    press("Retour", ds)

    # ============ 4. Impression ============
    print("4. Impression réseau (avec un vrai agent)")
    ag = ops._req("POST", "/api/v1/admin/agents", json={"name": "Agent UI", "platform": "linux"})
    agent = Agent(AgentClient("http://testserver", ag["device_header"], http=srv),
                  FileBackend(os.path.join(TMP, "sortie"), {"HP-UI": {"duplex": False, "color": False, "paper": ["A4"], "max_copies": 5}}),
                  ["HP-UI"], tmp_root=TMP, log=lambda *_: None)
    agent.run_once()
    pr = next(p for p in ops._req("GET", "/api/v1/admin/printers") if p["agent_device_id"] == ag["id"])
    press("Imprimer", cs)
    ps = sm.get_screen("printing")
    check("imprimante découverte mais non autorisée : « Aucune imprimante autorisée »", "Aucune imprimante" in ps.ids.info.text, repr(ps.ids.info.text))
    shot("impression-aucune")
    ops._req("PATCH", f"/api/v1/admin/printers/{pr['id']}", json={"enabled": True, "location": "Bureau 2"})
    ops._req("PUT", f"/api/v1/admin/printers/{pr['id']}/grants/{ui_api.me()['id']}")
    agent.run_once()
    press("Actualiser", ps)
    check("après autorisation : l'imprimante est proposée", "HP-UI" in ps.ids.printer.text, repr(ps.ids.printer.text))
    press("Choisir un fichier (PDF, image, texte)", ps)
    pop = popup()
    chooser = next(w for w in pop.walk() if isinstance(w, FileChooserListView))
    chooser.selection = [src]
    ps.ids.copies.text = "2"
    popup_press_ok()
    check("travail créé : « en attente » dans la liste", "en attente" in ps.ids.jobs.text, repr(ps.ids.jobs.text))
    agent.run_once()
    press("Actualiser", ps)
    check("après passage de l'agent : « terminé »", "terminé" in ps.ids.jobs.text, repr(ps.ids.jobs.text))
    printed = [f for f in os.listdir(os.path.join(TMP, "sortie", "HP-UI")) if f.endswith(".bin")]
    check("le document a bien été reçu par l'imprimante", len(printed) == 1)
    shot("impression-terminee")
    press("Retour", ps)


    # ============ 4b. Nouvelle église (création hors ligne) ============
    print("4b. Nouvelle église : enregistrement hors ligne puis synchronisation")
    import httpx

    class Offline:
        def request(self, *a, **k):
            raise httpx.ConnectError("réseau coupé")

    press("Nouvelle église", cs)
    cf = sm.get_screen("church_form")
    check("le formulaire s'ouvre", sm.current == "church_form")
    shot("nouvelle-eglise")
    press("Enregistrer", cf)
    check("formulaire vide : message d'erreur, on reste sur le formulaire", sm.current == "church_form" and "obligatoires" in cf.ids.msg.text,
          repr(cf.ids.msg.text))
    cf.ids.name.text, cf.ids.dept.text, cf.ids.commune.text = "Église de la Grâce", "Ouest", "Pétion-Ville"
    real_http = ui_api.http
    ui_api.http = Offline()
    press("Enregistrer", cf)
    check("hors ligne : retour à la liste, création gardée localement (1 en attente)",
          sm.current == "churches" and "Modifications en attente: 1" in cs.ids.status.text, repr(cs.ids.status.text[:60]))
    ui_api.http = real_http
    press("Synchroniser", cs)
    check("réseau revenu : l'église apparaît dans la liste, plus rien en attente",
          "Église de la Grâce" in cs.ids.listing.text and "Modifications en attente: 0" in cs.ids.status.text, repr(cs.ids.status.text[:40]))
    shot("eglises-deux")

    # ============ 4c. Événements ============
    print("4c. Événements : inscription d'un participant et statistiques")
    from datetime import datetime, timedelta, timezone
    ev = ops._req("POST", "/api/v1/events", json={"title": "Assemblée générale", "starts_at": (datetime.now(timezone.utc) + timedelta(days=12)).isoformat(),
                                                   "capacity": 100, "location": "Delmas"})
    for act in ("submit", "approve", "publish"):
        ops._req("POST", f"/api/v1/events/{ev['id']}/transition", json={"action": act})
    ops._req("POST", f"/api/v1/events/{ev['id']}/registration", json={"open": True})
    press("Événements", cs)
    es = sm.get_screen("events")
    check("l'événement est proposé", "Assemblée générale" in es.ids.event.text, repr(es.ids.event.text))
    check("statistiques affichées (0 inscrit)", "Inscrits : 0" in es.ids.stats.text, repr(es.ids.stats.text))
    es.ids.pname.text, es.ids.pemail.text = "Marie Joseph", "marie@exemple.org"
    press("Inscrire", es)
    check("sans consentement : refusé avec explication", "consentement" in es.ids.result.text.lower(), repr(es.ids.result.text))
    es.ids.consent.active = True
    press("Inscrire", es)
    check("avec consentement : « Inscrit(e) » et statistiques à jour", es.ids.result.text == "Inscrit(e)" and "Inscrits : 1" in es.ids.stats.text,
          repr((es.ids.result.text, es.ids.stats.text)))
    es.ids.pname.text, es.ids.pemail.text, es.ids.consent.active = "Marie Joseph", "marie@exemple.org", True
    press("Inscrire", es)
    check("même personne : « Déjà inscrit(e) » (pas de doublon)", es.ids.result.text == "Déjà inscrit(e)", repr(es.ids.result.text))
    shot("evenements")
    press("Retour", es)

    # ============ 4d. Registre MEOL (fiches importées des listes) ============
    print("4d. Registre MEOL : liste, contacts, recherche et filtre par département")
    ops._req("POST", "/api/v1/organizations", json={"name": "Mission Espérance de Léogâne", "org_type": "ministere",
                                                    "department": "Ouest", "commune": "Léogâne",
                                                    "contact_phone": "3400-1122"})
    ops._req("POST", "/api/v1/organizations", json={"name": "Association des Femmes de Gonaïves",
                                                    "org_type": "association", "department": "Artibonite",
                                                    "commune": "Gonaïves"})
    press("Registre MEOL", cs)
    ms = sm.get_screen("meol")
    check("le registre MEOL s'ouvre depuis les églises", sm.current == "meol")
    check("les fiches du registre sont listées", "Mission Espérance de Léogâne" in ms.ids.listing.text,
          repr(ms.ids.listing.text[:70]))
    check("le contact de la fiche est visible", "3400-1122" in ms.ids.listing.text, repr(ms.ids.listing.text[-70:]))
    check("une fiche importée reste marquée « brouillon » (jamais publiée)", "brouillon" in ms.ids.listing.text,
          repr(ms.ids.listing.text[:80]))
    check("le compteur de fiches est affiché", "Fiches: 2" in ms.ids.status.text, repr(ms.ids.status.text[:60]))
    shot("registre-meol")
    ms.ids.q.text = "Femmes"
    press("Rechercher", ms)
    check("recherche par nom : la fiche demandée seule reste affichée",
          "Association des Femmes" in ms.ids.listing.text and "Mission Espérance" not in ms.ids.listing.text,
          repr(ms.ids.listing.text[:70]))
    ms.ids.q.text = ""
    ms.ids.dept.text = "Artibonite"               # le Spinner déclenche refresh() via on_text
    settle()
    check("filtre par département : une fiche sur deux",
          "Gonaïves" in ms.ids.listing.text and "Léogâne" not in ms.ids.listing.text, repr(ms.ids.listing.text[:70]))
    ms.ids.dept.text = "Sud"
    settle()
    check("département sans fiche : message « Aucun MEOL trouvé », écran vide mais pas muet",
          ms.ids.listing.text == "Aucun MEOL trouvé", repr(ms.ids.listing.text[:40]))
    press("Retour", ms)
    check("retour à la liste des églises depuis le registre", sm.current == "churches")

    # ============ 5. Langues ============
    print("5. Langues")
    check("français par défaut : bouton « Se connecter »", app.tr("sign_in") == "Se connecter")
    press("Déconnexion", cs)
    check("déconnexion : retour à l'écran de connexion, cache local vidé", sm.current == "login" and app.db.churches() == [])
    login = sm.get_screen("login")
    check("poste partagé : le pseudo n'est plus affiché après déconnexion", login.ids.email.text == "" and login.ids.password.text == "")
    login_btn = next(b for b in buttons(login) if b.text in ("Se connecter", "Antre", "Sign in"))
    for code, expected in (("ht", "Antre"), ("en", "Sign in"), ("fr", "Se connecter")):
        login.ids.lang.text = code            # le vrai sélecteur de langue de l'écran
        settle()
        check(f"changement de langue à chaud ({code}) : le bouton devient « {expected} »", login_btn.text == expected, repr(login_btn.text))
    login.ids.lang.text = "ht"
    settle()
    shot("connexion-creole")
    login.ids.lang.text = "fr"
    settle()

print(f"\nRÉSULTAT : {'TOUT EST OK' if not failures else str(len(failures)) + ' ÉCHEC(S) -> ' + str(failures)}")
print(f"Captures d'écran : {SHOTS}")
shutil.rmtree(TMP, ignore_errors=True) if not failures and len(sys.argv) <= 1 and "FPH_KEEP" not in os.environ else None
sys.exit(1 if failures else 0)
