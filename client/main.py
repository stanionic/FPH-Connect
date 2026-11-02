"""FPH Connect — client Kivy : connexion, églises (création hors ligne), réseau local, documents, impression,
événements et inscriptions. Langue modifiable à chaud (français / créole haïtien / anglais).
Vérifié en fenêtre virtuelle par scripts/ui_check.py ; JAMAIS lancé sur Android ni Windows (voir docs/LIMITATIONS.md)."""
import os
import platform as _platform
import sys
import uuid
from datetime import datetime

if "--selftest" in sys.argv:
    os.environ["KIVY_NO_ARGS"] = "1"      # Kivy ne doit pas interpréter nos propres options

from kivy.app import App
from kivy.lang import Builder
from kivy.properties import StringProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.filechooser import FileChooserListView
from kivy.uix.image import Image
from kivy.uix.popup import Popup
from kivy.uix.screenmanager import Screen, ScreenManager

from fph_client import lan
from fph_client.api import ApiClient, ApiError, NetworkError
from fph_client.device import DeviceIdentity
from fph_client.i18n import t
from fph_client.localdb import LocalDB
from fph_client.sync import sync

DEPARTMENTS = ["Ouest", "Nord", "Nord-Est", "Nord-Ouest", "Artibonite", "Centre", "Sud", "Sud-Est", "Grand'Anse", "Nippes"]
# Valeur écrite par scripts/import_meols.py quand le registre ne désigne aucun département : ce n'est
# pas un département, mais le filtre du registre MEOL doit la proposer, sinon les fiches non rattachées
# deviennent impossibles à retrouver depuis le client.
MEOL_UNKNOWN_DEPT = "À déterminer"
# Une fiche du registre tient une ou deux lignes ; les afficher toutes d'un coup (307 aujourd'hui)
# donne un Label haut de plus de 10 000 dp, dont la texture dépasse la limite de la carte graphique :
# la liste ne s'affiche plus du tout (vérifié en capture d'écran, écran vide avec le compteur à 307).
# La page est donc bornée, et `Précédent / Suivant` fait le reste du registre.
MEOL_PAGE_SIZE = 15


def asset(name: str) -> str:
    """Chemin d'un fichier de `client/assets`, que l'application tourne depuis les sources, un
    exécutable PyInstaller (dossier _MEIPASS) ou un paquet Android. Chaîne vide si absent : l'écran
    s'affiche alors sans logo plutôt que de casser l'interface."""
    roots = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        roots.append(os.path.join(meipass, "assets"))
    roots.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets"))
    for root in roots:
        path = os.path.join(root, name)
        if os.path.isfile(path):
            return path
    return ""


LOGO = asset("logo-fph.png")

KV = """
<Button>:
    text_size: self.width - dp(12), None
    halign: 'center'
    valign: 'middle'

<WrapLabel@Label>:
    text_size: self.width - dp(8), None
    halign: 'center'
    size_hint_y: None
    height: max(dp(32), self.texture_size[1] + dp(8))

<ListLabel@Label>:
    text_size: self.width - dp(8), None
    halign: 'left'
    valign: 'top'
    size_hint_y: None
    height: max(dp(30), self.texture_size[1] + dp(8))

<LoginScreen>:
    BoxLayout:
        orientation: 'vertical'
        padding: dp(24)
        spacing: dp(12)
        Widget:
        Image:
            id: logo
            source: app.logo_source
            size_hint_y: None
            height: dp(120) if self.source else 0
        Label:
            text: app.tr('app', app.lang)
            font_size: '30sp'
            size_hint_y: None
            height: dp(70)
        TextInput:
            id: email
            hint_text: app.tr('email', app.lang)
            multiline: False
            write_tab: False
            size_hint_y: None
            height: dp(44)
        TextInput:
            id: password
            hint_text: app.tr('password', app.lang)
            password: True
            multiline: False
            write_tab: False
            size_hint_y: None
            height: dp(44)
        WrapLabel:
            id: msg
            color: 1, .35, .35, 1
        Button:
            text: app.tr('sign_in', app.lang)
            size_hint_y: None
            height: dp(52)
            on_release: root.do_login(email.text, password.text)
        BoxLayout:
            size_hint_y: None
            height: dp(40)
            spacing: dp(8)
            Label:
                text: app.tr('language', app.lang)
                size_hint_x: .4
            Spinner:
                id: lang
                text: app.lang
                values: ['fr', 'ht', 'en']
                on_text: app.lang = self.text
        Widget:

<ChurchesScreen>:
    on_pre_enter: root.refresh()
    BoxLayout:
        orientation: 'vertical'
        padding: dp(12)
        spacing: dp(8)
        WrapLabel:
            id: status
        ScrollView:
            ListLabel:
                id: listing
        GridLayout:
            cols: 2
            size_hint_y: None
            height: self.minimum_height
            row_default_height: dp(52)
            row_force_default: True
            spacing: dp(8)
            Button:
                text: app.tr('sync', app.lang)
                on_release: root.do_sync()
            Button:
                text: app.tr('new_church', app.lang)
                on_release: root.manager.current = 'church_form'
            Button:
                text: app.tr('meol', app.lang)
                on_release: root.manager.current = 'meol'
            Button:
                text: app.tr('network', app.lang)
                on_release: root.manager.current = 'network'
            Button:
                text: app.tr('documents', app.lang)
                on_release: root.manager.current = 'documents'
            Button:
                text: app.tr('printing', app.lang)
                on_release: root.manager.current = 'printing'
            Button:
                text: app.tr('events', app.lang)
                on_release: root.manager.current = 'events'
            Button:
                text: app.tr('logout', app.lang)
                on_release: root.do_logout()

<ChurchFormScreen>:
    on_pre_enter: root.reset()
    BoxLayout:
        orientation: 'vertical'
        padding: dp(16)
        spacing: dp(10)
        Label:
            text: app.tr('new_church', app.lang)
            font_size: '20sp'
            size_hint_y: None
            height: dp(40)
        TextInput:
            id: name
            hint_text: app.tr('church_name', app.lang)
            multiline: False
            write_tab: False
            size_hint_y: None
            height: dp(44)
        Spinner:
            id: dept
            text: app.tr('department', app.lang)
            values: root.departments
            size_hint_y: None
            height: dp(44)
        TextInput:
            id: commune
            hint_text: app.tr('commune', app.lang)
            multiline: False
            write_tab: False
            size_hint_y: None
            height: dp(44)
        WrapLabel:
            id: msg
        Widget:
        BoxLayout:
            size_hint_y: None
            height: dp(56)
            spacing: dp(8)
            Button:
                text: app.tr('save', app.lang)
                on_release: root.save()
            Button:
                text: app.tr('back', app.lang)
                on_release: root.manager.current = 'churches'

<MeolScreen>:
    on_pre_enter: root.open()
    BoxLayout:
        orientation: 'vertical'
        padding: dp(12)
        spacing: dp(8)
        Label:
            text: app.tr('meol', app.lang)
            font_size: '20sp'
            size_hint_y: None
            height: dp(36)
        WrapLabel:
            id: status
        TextInput:
            id: q
            hint_text: app.tr('meol_hint', app.lang)
            multiline: False
            write_tab: False
            size_hint_y: None
            height: dp(44)
            on_text_validate: root.refresh()
        Spinner:
            id: dept
            text: app.tr('meol_all', app.lang)
            values: root.departments
            size_hint_y: None
            height: dp(44)
            on_text: root.refresh()
        ScrollView:
            ListLabel:
                id: listing
        BoxLayout:
            size_hint_y: None
            height: dp(48)
            spacing: dp(8)
            Button:
                id: prev
                text: app.tr('meol_prev', app.lang)
                disabled: True
                on_release: root.go(-1)
            Button:
                id: next
                text: app.tr('meol_next', app.lang)
                on_release: root.go(1)
        BoxLayout:
            size_hint_y: None
            height: dp(52)
            spacing: dp(8)
            Button:
                text: app.tr('search', app.lang)
                on_release: root.refresh()
            Button:
                text: app.tr('refresh', app.lang)
                on_release: root.refresh()
            Button:
                text: app.tr('back', app.lang)
                on_release: root.manager.current = 'churches'

<NetworkScreen>:
    on_pre_enter: root.refresh()
    BoxLayout:
        orientation: 'vertical'
        padding: dp(12)
        spacing: dp(8)
        WrapLabel:
            id: device
        Button:
            id: reg
            text: app.tr('register_device', app.lang)
            size_hint_y: None
            height: dp(48)
            on_release: root.register()
        WrapLabel:
            id: presence
        ScrollView:
            ListLabel:
                id: msgs
        Spinner:
            id: to
            size_hint_y: None
            height: dp(44)
        TextInput:
            id: body
            hint_text: app.tr('message_hint', app.lang)
            multiline: False
            write_tab: False
            size_hint_y: None
            height: dp(44)
        BoxLayout:
            size_hint_y: None
            height: dp(52)
            spacing: dp(8)
            Button:
                text: app.tr('send', app.lang)
                on_release: root.send(body.text)
            Button:
                text: app.tr('refresh', app.lang)
                on_release: root.refresh()
            Button:
                text: app.tr('back', app.lang)
                on_release: root.manager.current = 'churches'

<DocumentsScreen>:
    on_pre_enter: root.refresh()
    BoxLayout:
        orientation: 'vertical'
        padding: dp(12)
        spacing: dp(8)
        WrapLabel:
            id: status
        ScrollView:
            ListLabel:
                id: report
        Button:
            text: app.tr('add_document', app.lang)
            size_hint_y: None
            height: dp(48)
            on_release: root.pick()
        Button:
            text: app.tr('send', app.lang)
            size_hint_y: None
            height: dp(48)
            on_release: root.push()
        Button:
            text: app.tr('organize_click', app.lang)
            size_hint_y: None
            height: dp(56)
            on_release: root.organize()
        Button:
            text: app.tr('back', app.lang)
            size_hint_y: None
            height: dp(48)
            on_release: root.manager.current = 'churches'

<PrintScreen>:
    on_pre_enter: root.refresh()
    BoxLayout:
        orientation: 'vertical'
        padding: dp(12)
        spacing: dp(8)
        WrapLabel:
            id: info
        Spinner:
            id: printer
            size_hint_y: None
            height: dp(44)
        BoxLayout:
            size_hint_y: None
            height: dp(44)
            spacing: dp(8)
            Label:
                text: app.tr('copies', app.lang)
                size_hint_x: .35
            TextInput:
                id: copies
                text: '1'
                input_filter: 'int'
                multiline: False
                write_tab: False
        Button:
            text: app.tr('choose_file', app.lang)
            size_hint_y: None
            height: dp(52)
            on_release: root.pick_and_print()
        ScrollView:
            ListLabel:
                id: jobs
        BoxLayout:
            size_hint_y: None
            height: dp(56)
            spacing: dp(8)
            Button:
                text: app.tr('cancel_job', app.lang)
                on_release: root.cancel_last()
            Button:
                text: app.tr('refresh', app.lang)
                on_release: root.refresh()
            Button:
                text: app.tr('back', app.lang)
                on_release: root.manager.current = 'churches'

<EventsScreen>:
    on_pre_enter: root.refresh()
    BoxLayout:
        orientation: 'vertical'
        padding: dp(12)
        spacing: dp(8)
        WrapLabel:
            id: info
        Spinner:
            id: event
            size_hint_y: None
            height: dp(44)
            on_text: root.show_stats()
        WrapLabel:
            id: stats
        TextInput:
            id: pname
            hint_text: app.tr('participant_name', app.lang)
            multiline: False
            write_tab: False
            size_hint_y: None
            height: dp(44)
        TextInput:
            id: pemail
            hint_text: app.tr('participant_email', app.lang)
            multiline: False
            write_tab: False
            size_hint_y: None
            height: dp(44)
        TextInput:
            id: pphone
            hint_text: app.tr('participant_phone', app.lang)
            multiline: False
            write_tab: False
            size_hint_y: None
            height: dp(44)
        BoxLayout:
            size_hint_y: None
            height: dp(56)
            spacing: dp(8)
            CheckBox:
                id: consent
                size_hint_x: None
                width: dp(40)
            Label:
                text: app.tr('consent_label', app.lang)
                text_size: self.width, None
                halign: 'left'
                valign: 'middle'
        WrapLabel:
            id: result
        Widget:
        BoxLayout:
            size_hint_y: None
            height: dp(56)
            spacing: dp(8)
            Button:
                text: app.tr('register_participant', app.lang)
                on_release: root.register()
            Button:
                text: app.tr('refresh', app.lang)
                on_release: root.refresh()
            Button:
                text: app.tr('back', app.lang)
                on_release: root.manager.current = 'churches'
"""


def fmt_dt(iso: str | None) -> str | None:
    """2026-10-17T23:06:30.07+00:00 -> « 2026-10-17 19:06 » (heure locale de l'appareil)."""
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso).astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return iso


def detail_text(e: ApiError) -> str:
    """Les erreurs de validation du serveur sont des listes ; on affiche un texte lisible."""
    d = e.detail
    if isinstance(d, list):
        return "; ".join(str(x.get("msg", x)) if isinstance(x, dict) else str(x) for x in d)
    if isinstance(d, dict):
        return str(d.get("message", d))
    return str(d)


class LoginScreen(Screen):
    def do_login(self, email, password):
        app = App.get_running_app()
        try:
            app.api.login(email.strip(), password)
            self.ids.msg.text = ""
            self.ids.password.text = ""
            self.manager.current = "churches"
            self.manager.get_screen("churches").do_sync()
        except ApiError as e:
            self.ids.msg.text = app.tr("error_login") if e.status in (401, 422) else detail_text(e)
        except NetworkError:
            self.ids.msg.text = app.tr("offline")


class ChurchesScreen(Screen):
    def refresh(self):
        app = App.get_running_app()
        rows = app.db.churches()
        self.ids.listing.text = "\n".join(
            f"• {c['official_name']} — {c['commune']} ({c['department']}) · {app.tr('vs_' + c['validation_status'])}"
            for c in rows) or "—"
        counts = {s: len(app.db.ops(s)) for s in ("pending", "conflict", "error")}
        last = fmt_dt(app.db.get_meta("last_sync")) or app.tr("never")
        self.ids.status.text = (f"{app.tr('pending_ops')}: {counts['pending']} · {app.tr('conflicts')}: {counts['conflict']} · "
                                f"{app.tr('rejected_ops')}: {counts['error']}\n{app.tr('last_sync')}: {last}")

    def do_sync(self):
        app = App.get_running_app()
        report = sync(app.api, app.db)
        self.refresh()
        if report["network_error"]:
            self.ids.status.text += f"\n{app.tr('offline')}"

    def do_logout(self):
        app = App.get_running_app()
        try:
            app.api.logout()
        except Exception:
            app.api.token = None
        app.db.wipe()          # pas de données institutionnelles résiduelles sur l'appareil
        login = self.manager.get_screen("login")
        login.ids.email.text = login.ids.password.text = login.ids.msg.text = ""   # poste partagé : on n'affiche plus le pseudo
        self.manager.current = "login"


class ChurchFormScreen(Screen):
    departments = DEPARTMENTS

    def reset(self):
        app = App.get_running_app()
        self.ids.name.text = self.ids.commune.text = self.ids.msg.text = ""
        self.ids.dept.text = app.tr("department")

    def save(self):
        """Fonctionne hors ligne : la création est mise en file locale puis envoyée par la synchronisation existante."""
        app = App.get_running_app()
        name, dept, commune = self.ids.name.text.strip(), self.ids.dept.text, self.ids.commune.text.strip()
        if len(name) < 2 or dept not in DEPARTMENTS or len(commune) < 2:
            self.ids.msg.text = app.tr("invalid_form")
            return
        op_id = app.db.queue_create({"official_name": name, "department": dept, "commune": commune})
        report = sync(app.api, app.db)
        row = app.db.conn.execute("SELECT status, error FROM pending_ops WHERE op_id=?", (op_id,)).fetchone()
        if row["status"] == "pending":
            self.ids.msg.text = app.tr("saved_local") if report["network_error"] else app.tr("offline")
            self.manager.current = "churches"
        elif row["status"] == "done":
            self.manager.current = "churches"
        else:                                   # refusé (droits, doublon…) : on reste sur le formulaire et on explique
            import json
            try:
                why = json.loads(row["error"] or "null")
            except ValueError:
                why = row["error"]
            self.ids.msg.text = f"{app.tr('rejected_count')}: {why if isinstance(why, str) else (why or '')}"


class MeolScreen(Screen):
    """Registre MEOL (table `organizations`) importé depuis les listes : lecture seule ici, la reprise
    d'une fiche (département à confirmer, statut brouillon) reste un écran de validation à part."""

    departments = DEPARTMENTS + [MEOL_UNKNOWN_DEPT]

    def __init__(self, **kw):
        super().__init__(**kw)
        self.rows = []        # fiches du filtre courant, toutes pages confondues
        self.page = 0

    def open(self):
        """À l'entrée sur l'écran : le filtre reprend son défaut, dans la langue affichée."""
        self.ids.dept.text = App.get_running_app().tr("meol_all")
        self.refresh()

    def _department(self):
        """Le libellé « tous les départements » n'est pas une valeur de filtre : seul ce qui ressemble à
        un département du serveur (ou à la valeur « à déterminer ») est envoyé."""
        dept = self.ids.dept.text
        return dept if dept in self.departments else None

    def refresh(self):
        app = App.get_running_app()
        try:
            orgs = app.api.list_organizations(department=self._department(), q=self.ids.q.text.strip()[:100] or None)
        except NetworkError:
            self._show_error(app.tr("offline"))
            return
        except ApiError as e:
            self._show_error(detail_text(e))
            return
        self.rows, self.page = orgs, 0
        self.render()

    def _show_error(self, message):
        """Hors ligne ou refus du serveur : l'écran reste parlant, et la navigation de page se retire
        puisqu'il n'y a plus rien à parcourir."""
        self.rows, self.page = [], 0
        self.ids.listing.text = ""
        self.ids.status.text = message
        self.ids.prev.disabled = self.ids.next.disabled = True

    def render(self):
        """Une page à la fois (voir MEOL_PAGE_SIZE). Le compteur, lui, porte toujours le total du filtre :
        page après page, on ne doit jamais croire que le registre s'arrête à l'écran."""
        app = App.get_running_app()
        total = len(self.rows)
        pages = max(1, -(-total // MEOL_PAGE_SIZE))
        self.page = min(self.page, pages - 1)
        start = self.page * MEOL_PAGE_SIZE
        shown = self.rows[start:start + MEOL_PAGE_SIZE]
        self.ids.listing.text = "\n".join(self.line(o) for o in shown) or app.tr("meol_none")
        drafts = sum(1 for o in self.rows if o["validation_status"] == "draft")
        self.ids.status.text = (f"{app.tr('meol_total')}: {total} · {app.tr('vs_draft')}: {drafts}"
                                f" · {app.tr('meol_page')} {self.page + 1}/{pages}"
                                f"\n{app.tr('meol_draft_note')}")
        self.ids.prev.disabled = self.page == 0
        self.ids.next.disabled = self.page >= pages - 1

    def go(self, step):
        self.page += step
        self.render()

    def line(self, o):
        app = App.get_running_app()
        contact = " · ".join(x for x in (o["contact_phone"], o["contact_email"]) if x)
        return (f"• {o['name']} — {o['commune'] or '?'} ({o['department']}) · "
                f"{app.tr('ot_' + o['org_type'])} · {app.tr('vs_' + o['validation_status'])}"
                + (f"\n   {contact}" if contact else ""))


class NetworkScreen(Screen):
    recipients = {}
    names = {}
    me_id = None

    def refresh(self):
        app = App.get_running_app()
        dev = app.api.device
        if not dev or not dev.id:
            self.ids.device.text = f"{app.tr('device_status')}: {app.tr('not_registered')}"
            self.ids.reg.disabled = False
            return
        self.ids.reg.disabled = True
        try:
            st = app.api.device_status()["status"]
            label = {"pending": "pending_approval"}.get(st, st)
            self.ids.device.text = f"{app.tr('device_status')}: {app.tr(label)}"
            if st != "approved":
                return
            app.api.heartbeat()
            self.ids.presence.text = ", ".join(f"{p['name']}{' ●' if p['online'] else ''}" for p in app.api.presence())
            people = app.api.directory()
            self.recipients = {u["full_name"]: u["id"] for u in people}
            self.names = {u["id"]: u["full_name"] for u in people}
            self.me_id = self.me_id or app.api.me()["id"]
            self.ids.to.values = [app.tr("to_everyone")] + list(self.recipients)
            if self.ids.to.text not in self.ids.to.values:
                self.ids.to.text = self.ids.to.values[0]
            rep = lan.sync_messages(app.api, app.db)
            if rep["rejected"]:
                self.ids.device.text += f" · {app.tr('rejected_count')}: {rep['rejected']}"
            self.ids.msgs.text = "\n".join(
                f"{app.tr('you') if m['sender_id'] == self.me_id else self.names.get(m['sender_id'], '?')} : {m['body']}"
                for m in lan.local_messages(app.db))
        except NetworkError:
            self.ids.device.text += f" · {app.tr('offline')}"
        except ApiError as e:
            self.ids.device.text += f" · {detail_text(e)}"

    def register(self):
        app = App.get_running_app()
        plat = {"Linux": "linux", "Windows": "windows", "Darwin": "macos"}.get(_platform.system(), "other")
        try:
            app.api.register_device(f"{_platform.node() or 'appareil'}", plat)
        except (ApiError, NetworkError):
            pass
        self.refresh()

    def send(self, text):
        app = App.get_running_app()
        if not text.strip():
            return
        to = self.recipients.get(self.ids.to.text)
        lan.queue_message(app.db, text.strip(), recipient_id=to, audience="direct" if to else "all")
        self.ids.body.text = ""
        self.refresh()


class DocumentsScreen(Screen):
    def refresh(self):
        app = App.get_running_app()
        n = len(app.db.conn.execute("SELECT 1 FROM out_documents WHERE status='pending'").fetchall())
        self.ids.status.text = f"{app.tr('pending_docs')}: {n}"

    def pick(self):
        app = App.get_running_app()
        chooser = FileChooserListView(path=os.path.expanduser("~"))
        box = BoxLayout(orientation="vertical")
        box.add_widget(chooser)
        pop = Popup(title=app.tr("add_document"), content=box, size_hint=(0.95, 0.9))

        def ok(*_):
            if chooser.selection:
                lan.queue_document(app.db, os.path.join(app.data_dir, "tampon"), chooser.selection[0])
            pop.dismiss()
            self.refresh()
        b = Button(text="OK", size_hint_y=None, height=48)
        b.bind(on_release=ok)
        box.add_widget(b)
        pop.open()

    def push(self):
        app = App.get_running_app()
        r = lan.sync_documents(app.api, app.db)
        self.refresh()
        parts = []
        if r["sent"] or r["rejected"]:
            parts.append(f"{app.tr('sent_count')}: {r['sent']}" + (f" · {app.tr('rejected_count')}: {r['rejected']}" if r["rejected"] else ""))
        if r["network_error"]:
            parts.append(app.tr("offline"))
        if r.get("auth_error"):
            parts.append(str(r["auth_error"]))
        self.ids.report.text = "\n".join(parts) or app.tr("nothing_pending")

    def organize(self):
        app = App.get_running_app()
        try:
            r = app.api.organize()
            self.ids.report.text = "\n".join(
                f"[{app.tr('st_' + i['status'])}] {i['original_name']}"
                + (f" — {i['note']}" if i.get("note") and i["status"] != "organized" else "")
                for i in r["items"]) or "—"
        except ApiError as e:
            self.ids.report.text = detail_text(e)
        except NetworkError:
            self.ids.report.text = app.tr("offline")


class PrintScreen(Screen):
    printers = {}
    last_job = None

    def refresh(self):
        app = App.get_running_app()
        try:
            ps = app.api.printers()
            self.printers = {f"{p['name']} — {p.get('location') or ''}"
                             + ("" if p["online"] else f" ({app.tr('printer_offline')})"): p["id"] for p in ps}
            self.ids.printer.values = list(self.printers)
            if self.printers and self.ids.printer.text not in self.printers:
                self.ids.printer.text = next(iter(self.printers))
            self.ids.info.text = "" if ps else app.tr("no_printer")
            self.ids.jobs.text = "\n".join(
                f"{j['printer_name']} · {j['original_name']} · {app.tr('js_' + j['status'])}"
                + (f" ({j['error']})" if j.get("error") else "") for j in app.api.print_jobs())
        except NetworkError:
            self.ids.info.text = app.tr("offline")
        except ApiError as e:
            self.ids.info.text = detail_text(e)

    def pick_and_print(self):
        app = App.get_running_app()
        chooser = FileChooserListView(path=os.path.expanduser("~"))
        box = BoxLayout(orientation="vertical")
        box.add_widget(chooser)
        pop = Popup(title=app.tr("printing"), content=box, size_hint=(0.95, 0.9))

        def ok(*_):
            pop.dismiss()
            if not chooser.selection or self.ids.printer.text not in self.printers:
                return
            path = chooser.selection[0]
            try:
                with open(path, "rb") as f:
                    content = f.read()
                job = app.api.print_document(self.printers[self.ids.printer.text], os.path.basename(path), content,
                                             copies=int(self.ids.copies.text or 1), idempotency_key=str(uuid.uuid4()))
                self.last_job = job["id"]
            except ApiError as e:
                self.ids.info.text = detail_text(e)
            except (NetworkError, OSError) as e:
                self.ids.info.text = str(e)
            self.refresh()
        b = Button(text="OK", size_hint_y=None, height=48)
        b.bind(on_release=ok)
        box.add_widget(b)
        pop.open()

    def cancel_last(self):
        app = App.get_running_app()
        if self.last_job:
            try:
                app.api.cancel_print_job(self.last_job)
            except ApiError as e:
                self.ids.info.text = detail_text(e)
            except NetworkError as e:
                self.ids.info.text = str(e)
            self.refresh()


class EventsScreen(Screen):
    events = {}

    def refresh(self):
        app = App.get_running_app()
        try:
            evs = app.api.events()
        except NetworkError:
            self.ids.info.text = app.tr("offline")
            return
        except ApiError as e:
            self.ids.info.text = detail_text(e)
            return
        self.events = {f"{e['title']} — {e['starts_at'][:10]}": e["id"] for e in evs}
        self.ids.event.values = list(self.events)
        if self.events and self.ids.event.text not in self.events:
            self.ids.event.text = next(iter(self.events))
        self.ids.info.text = "" if evs else app.tr("no_events")
        self.show_stats()

    def show_stats(self):
        app = App.get_running_app()
        eid = self.events.get(self.ids.event.text)
        self.ids.stats.text = ""
        if not eid:
            return
        try:
            st = app.api.event_stats(eid)
            by = st["by_status"]
            self.ids.stats.text = app.tr("stats_line").format(registered=by.get("registered", 0),
                                                              waitlisted=by.get("waitlisted", 0), checked=st["checked_in"])
        except (ApiError, NetworkError):
            pass                                # pas de droit sur les statistiques, ou hors ligne : on n'affiche rien

    def register(self):
        app = App.get_running_app()
        eid = self.events.get(self.ids.event.text)
        if not eid:
            return
        if not self.ids.consent.active:
            self.ids.result.text = app.tr("consent_required")
            return
        try:
            r = app.api.add_participant(eid, self.ids.pname.text.strip(), self.ids.pemail.text.strip() or None,
                                        self.ids.pphone.text.strip() or None, consent=True)
            self.ids.result.text = app.tr("outcome_" + r["outcome"])
            self.ids.pname.text = self.ids.pemail.text = self.ids.pphone.text = ""
            self.ids.consent.active = False
            self.show_stats()
        except ApiError as e:
            self.ids.result.text = detail_text(e)
        except NetworkError:
            self.ids.result.text = app.tr("offline")


class FPHConnectApp(App):
    lang = StringProperty(os.environ.get("FPH_LANG", "fr"))
    # Résolu à l'import : le KV lie `source: app.logo_source` dès le chargement de la chaîne.
    logo_source = StringProperty(LOGO)

    def __init__(self, api=None, data_dir=None, **kw):
        super().__init__(**kw)
        self._api_injected, self._data_dir = api, data_dir

    def tr(self, key, lang=None):
        return t(lang or self.lang, key)

    def build(self):
        self.title = "FPH Connect"
        if self.logo_source:
            self.icon = self.logo_source       # icône de la fenêtre (bureau) ; sur Android c'est icon.filename de buildozer.spec
        self.data_dir = self._data_dir or self.user_data_dir
        os.makedirs(self.data_dir, exist_ok=True)
        self.api = self._api_injected or ApiClient(os.environ.get("FPH_API_URL", "https://127.0.0.1:8000"),
                                                   ca_file=os.environ.get("FPH_CA_CERT"))
        self.api.device = DeviceIdentity(os.path.join(self.data_dir, "device.json"))
        self.db = LocalDB(os.path.join(self.data_dir, "fph_cache.db"))
        Builder.load_string(KV)
        sm = ScreenManager()
        for name, cls in (("login", LoginScreen), ("churches", ChurchesScreen), ("church_form", ChurchFormScreen),
                          ("meol", MeolScreen),
                          ("network", NetworkScreen), ("documents", DocumentsScreen), ("printing", PrintScreen),
                          ("events", EventsScreen)):
            sm.add_widget(cls(name=name))
        return sm


def selftest(png_path: str | None = None) -> int:
    """Démarre l'interface SANS réseau, vérifie qu'elle s'affiche et que le changement de langue fonctionne, puis quitte.
    Sert à contrôler une installation ou un exécutable construit (PyInstaller) : `FPHConnect --selftest [capture.png]`.
    Code de sortie 0 = interface opérationnelle."""
    import tempfile
    from kivy.base import EventLoop
    from kivy.core.window import Window
    problems = []
    app = FPHConnectApp(api=ApiClient("https://127.0.0.1:9"), data_dir=tempfile.mkdtemp(prefix="fph-selftest-"))
    App._running_app = app
    app.root = app.build()
    EventLoop.ensure_window()
    Window.add_widget(app.root)
    for _ in range(5):
        EventLoop.idle()
    login = app.root.get_screen("login")
    if app.root.current != "login":
        problems.append("l'écran de connexion n'est pas affiché")
    names = [w.text for w in login.walk(restrict=True) if isinstance(w, Button)]
    if "Se connecter" not in names:
        problems.append(f"bouton de connexion introuvable ({names})")
    logo = next((w for w in login.walk(restrict=True) if isinstance(w, Image)), None)
    if app.logo_source and (logo is None or logo.texture is None):
        problems.append("logo FPH présent mais non affiché sur l'écran de connexion")
    for code, expected in (("ht", "Antre"), ("en", "Sign in"), ("fr", "Se connecter")):
        login.ids.lang.text = code
        for _ in range(3):
            EventLoop.idle()
        if not any(isinstance(w, Button) and w.text == expected for w in login.walk(restrict=True)):
            problems.append(f"langue {code} : « {expected} » absent")
    # Registre MEOL : l'API injectée est fermée (port 9), donc l'écran doit s'afficher QUAND MÊME et dire
    # qu'il est hors ligne — une fiche importée ne doit jamais laisser le client muet.
    app.root.current = "meol"
    for _ in range(5):
        EventLoop.idle()
    meol = app.root.get_screen("meol")
    if not any(isinstance(w, Button) and w.text == "Rechercher" for w in meol.walk(restrict=True)):
        problems.append("registre MEOL : bouton « Rechercher » introuvable")
    if app.tr("offline") not in meol.ids.status.text:
        problems.append(f"registre MEOL : état hors ligne non affiché ({meol.ids.status.text!r})")
    app.root.current = "login"
    for _ in range(5):
        EventLoop.idle()
    if sorted(app.root.screen_names) != sorted(["login", "churches", "church_form", "meol",
                                                "network", "documents", "printing", "events"]):
        problems.append(f"écrans inattendus : {app.root.screen_names}")
    if png_path:
        Window.screenshot(name=png_path)
    print("SELFTEST ÉCHEC : " + "; ".join(problems) if problems else "SELFTEST OK")
    return 1 if problems else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        i = sys.argv.index("--selftest")
        sys.exit(selftest(sys.argv[i + 1] if len(sys.argv) > i + 1 else None))
    FPHConnectApp().run()
