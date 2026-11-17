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
from kivy.metrics import dp
from kivy.properties import BooleanProperty, StringProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.checkbox import CheckBox
from kivy.uix.filechooser import FileChooserListView
from kivy.uix.gridlayout import GridLayout
from kivy.uix.image import Image
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.screenmanager import Screen, ScreenManager
from kivy.uix.scrollview import ScrollView
from kivy.uix.spinner import Spinner
from kivy.uix.textinput import TextInput

from fph_client import lan
from fph_client.api import ApiClient, ApiError, NetworkError
from fph_client.device import DeviceIdentity
from fph_client.i18n import t
from fph_client.localdb import LocalDB
from fph_client.sync import sync

DEPARTMENTS = ["Ouest", "Nord", "Nord-Est", "Nord-Ouest", "Artibonite", "Centre", "Sud", "Sud-Est", "Grand'Anse", "Nippes", "La Diaspora"]
MEOL_TYPES = ["mission", "eglise", "organisation", "ligue"]
LEADER_FUNCTIONS = ["pasteur_principal", "pasteur_assistant", "responsable_principal", "president",
                   "secretaire", "tresorier", "responsable_service", "autre"]
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
        BoxLayout:
            size_hint_y: None
            height: dp(48) if app.is_admin else 0
            Button:
                text: app.tr('administration', app.lang)
                opacity: 1 if app.is_admin else 0
                disabled: not app.is_admin
                on_release: root.manager.current = 'admin'
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

<AdminScreen>:
    on_pre_enter: root.open()
    BoxLayout:
        orientation: 'vertical'
        padding: dp(8)
        spacing: dp(6)
        BoxLayout:
            size_hint_y: None
            height: dp(44)
            spacing: dp(6)
            Spinner:
                id: kind
                text: root.kind_labels[0]
                values: root.kind_labels
                on_text: root.kind_changed()
            Button:
                text: app.tr('refresh', app.lang)
                size_hint_x: None
                width: dp(110)
                on_release: root.refresh()
        WrapLabel:
            id: status
        ScrollView:
            BoxLayout:
                id: rows
                orientation: 'vertical'
                size_hint_y: None
                height: self.minimum_height
                spacing: dp(2)
        ScrollView:
            size_hint_y: None
            height: dp(110)
            ListLabel:
                id: detail
        BoxLayout:
            size_hint_y: None
            height: dp(46)
            spacing: dp(6)
            Button:
                id: new_btn
                text: app.tr('admin_new', app.lang)
                on_release: root.create()
            Button:
                id: edit_btn
                text: app.tr('admin_edit', app.lang)
                disabled: True
                on_release: root.edit()
            Button:
                id: archive_btn
                text: app.tr('admin_archive', app.lang)
                disabled: True
                on_release: root.archive()
        BoxLayout:
            size_hint_y: None
            height: dp(46) if root.show_user_actions else 0
            opacity: 1 if root.show_user_actions else 0
            Button:
                id: activate_btn
                text: app.tr('admin_activate', app.lang)
                disabled: True
                on_release: root.activate()
        BoxLayout:
            size_hint_y: None
            height: dp(46) if root.show_meol_actions else 0
            opacity: 1 if root.show_meol_actions else 0
            spacing: dp(6)
            Button:
                id: approve_btn
                text: app.tr('admin_approve', app.lang)
                disabled: True
                on_release: root.approve()
            Button:
                id: reject_btn
                text: app.tr('admin_reject', app.lang)
                disabled: True
                on_release: root.reject()
        Button:
            text: app.tr('back', app.lang)
            size_hint_y: None
            height: dp(44)
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


def _wrap_label(text=""):
    """Étiquette multiligne à hauteur automatique (même comportement que `<WrapLabel@Label>`)."""
    lbl = Label(text=text, halign="center", valign="middle", size_hint_y=None)
    lbl.bind(width=lambda w, v: setattr(w, "text_size", (max(dp(20), v - dp(8)), None)))
    lbl.bind(texture_size=lambda w, v: setattr(w, "height", max(dp(32), v[1] + dp(8))))
    return lbl


def _field_label(text):
    lbl = Label(text=text, halign="left", valign="middle", size_hint_y=None, height=dp(20),
                font_size="13sp")
    lbl.bind(width=lambda w, v: setattr(w, "text_size", (max(dp(20), v - dp(4)), None)))
    return lbl


def _text_input(hint="", text="", password=False, multiline=False):
    return TextInput(text=text or "", hint_text=hint, password=password, multiline=multiline,
                     write_tab=False, size_hint_y=None,
                     height=dp(80) if multiline else dp(42))


def _spinner(values, text=""):
    sp = Spinner(values=list(values), text=text or (values[0] if values else ""),
                 size_hint_y=None, height=dp(42))
    return sp


class LoginScreen(Screen):
    def do_login(self, email, password):
        app = App.get_running_app()
        try:
            app.api.login(email.strip(), password)
            app.refresh_user()                 # rôle courant : l'espace d'administration dépend de `superadmin`
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
        app.current_user, app.is_admin = None, False
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


class AdminScreen(Screen):
    """Espace d'administration du SuperAdministrateur : créer, lire, modifier et ARCHIVER
    (jamais supprimer définitivement) les utilisateurs, églises, événements et inscriptions MEOL."""

    KINDS = ("users", "events", "meol")
    show_user_actions = BooleanProperty(False)
    show_meol_actions = BooleanProperty(False)

    def __init__(self, **kw):
        super().__init__(**kw)
        self.kind = "users"
        self.rows = []
        self.selected = None
        self.selected_id = None
        self._row_buttons = {}
        self._flash = ""
        self._syncing_kind = False
        self._kv_ready = False
        self._roles = None
        self._church_choices = None
        self._org_choices = None

    @property
    def kind_labels(self):
        app = App.get_running_app()
        return [app.tr("admin_users"), app.tr("admin_events"), app.tr("admin_meol")]

    # ------------------------------------------------------------------ cycle de vie
    def open(self):
        app = App.get_running_app()
        if app.current_user is None and getattr(app.api, "token", None):
            app.refresh_user()
        labels = self.kind_labels
        self._syncing_kind = True
        self.ids.kind.values = labels
        self.ids.kind.text = labels[self.KINDS.index(self.kind)]
        self._syncing_kind = False
        self._kv_ready = True
        self.refresh()

    def kind_changed(self):
        if not getattr(self, "_kv_ready", False) or self._syncing_kind:
            return
        labels = self.kind_labels
        try:
            self.kind = self.KINDS[labels.index(self.ids.kind.text)]
        except ValueError:
            return
        self.refresh()

    # ------------------------------------------------------------------ liste
    def refresh(self):
        app = App.get_running_app()
        flash, self._flash = self._flash, ""
        self.selected = self.selected_id = None
        self._clear_rows()
        self.ids.detail.text = ""
        self.show_user_actions = self.kind == "users"
        self.show_meol_actions = self.kind == "meol"
        self._set_actions(False)
        self.rows = []
        if not app.is_admin:
            self.ids.status.text = app.tr("admin_only")
            self.ids.new_btn.disabled = True
            return
        self.ids.new_btn.disabled = False
        try:
            if self.kind == "users":
                self.rows = app.api.admin_users()
            elif self.kind == "events":
                self.rows = app.api.events()
            else:
                self.rows = app.api.meol_pending("all")
        except NetworkError:
            self.ids.status.text = app.tr("offline")
            return
        except ApiError as e:
            self.ids.status.text = detail_text(e)
            return
        if not self.rows:
            self.ids.status.text = app.tr("admin_none")
        else:
            self._render()
            self.ids.status.text = f"{app.tr('admin_count')}: {len(self.rows)}"
        if flash:
            self.ids.status.text += f"\n{flash}"

    def _clear_rows(self):
        self.ids.rows.clear_widgets()
        self._row_buttons = {}

    def _render(self):
        for row in self.rows:
            btn = Button(text=self._row_text(row), halign="left", valign="middle", font_size="13sp",
                         size_hint_y=None, height=dp(38))
            btn.bind(width=lambda w, v: setattr(w, "text_size", (max(dp(20), v - dp(12)), None)))
            btn.bind(on_release=lambda b, r=row: self.select(r))
            self.ids.rows.add_widget(btn)
            self._row_buttons[row.get("id")] = btn

    def _row_text(self, row):
        app = App.get_running_app()
        if self.kind == "users":
            parts = [row.get("full_name") or row.get("email") or "?",
                     row.get("role") or "", row.get("department") or ""]
            label = " · ".join(p for p in parts if p)
            if "document:share" in (row.get("permissions") or []):
                label += " · " + app.tr("perm_share_short")
            return "• " + label + ("" if row.get("is_active", True) else f" ({app.tr('admin_inactive')})")
        if self.kind == "events":
            start = (row.get("starts_at") or "")[:16].replace("T", " ")
            return (f"• {row.get('title') or '?'} — {start or '?'} · "
                    f"{self._vs(row.get('validation_status'))}")
        return (f"• {row.get('name') or '?'} — {row.get('commune') or '?'} "
                f"({row.get('department') or '?'}) · {app.tr('ot_' + (row.get('org_type') or 'autre'))} · "
                f"{self._vs(row.get('validation_status'))}")

    def _vs(self, code):
        return App.get_running_app().tr("vs_" + code) if code else "?"

    def select(self, row):
        self.selected, self.selected_id = row, row.get("id")
        for rid, btn in self._row_buttons.items():
            btn.bold = rid == self.selected_id
        self.ids.detail.text = self._detail_text(row)
        self._set_actions(True)

    def _set_actions(self, selected):
        app = App.get_running_app()
        ok = app.is_admin and selected and self.selected
        self.ids.edit_btn.disabled = not ok
        self.ids.archive_btn.disabled = not ok
        active = bool(self.selected.get("is_active", True)) if self.selected else True
        self.ids.activate_btn.disabled = not (ok and self.kind == "users" and not active)
        self.ids.approve_btn.disabled = not (ok and self.kind == "meol")
        self.ids.reject_btn.disabled = not (ok and self.kind == "meol")
        if not app.is_admin:
            self.ids.new_btn.disabled = True

    def _detail_text(self, row):
        app = App.get_running_app()
        if self.kind == "users":
            lines = [f"{app.tr('admin_full_name')}: {row.get('full_name') or '?'}",
                     f"{app.tr('admin_email')}: {row.get('email') or '?'}"]
            if row.get("username"):
                lines.append(f"{app.tr('admin_username')}: {row['username']}")
            lines.append(f"{app.tr('admin_role')}: {row.get('role') or '?'}")
            for key, label in (("department", "department"), ("church_id", "admin_church"),
                               ("organization_id", "admin_org")):
                if row.get(key):
                    lines.append(f"{app.tr(label)}: {row[key]}")
            if not row.get("is_active", True):
                lines.append(app.tr("admin_inactive"))
            extras = row.get("extra_permissions") or []
            if extras:
                labels = {"document:share": "perm_share", "document:read": "perm_read",
                          "document:organize": "perm_organize", "print:use": "perm_print"}
                lines.append(f"{app.tr('admin_permissions')}:")
                for code in extras:
                    lines.append("  • " + app.tr(labels.get(code, code)))
            return "\n".join(lines)
        if self.kind == "events":
            lines = [f"{app.tr('admin_title')}: {row.get('title') or '?'}",
                     f"{app.tr('admin_starts')}: {fmt_dt(row.get('starts_at')) or '?'}"]
            if row.get("ends_at"):
                lines.append(f"{app.tr('admin_ends')}: {fmt_dt(row['ends_at'])}")
            for key, label in (("location", "admin_location"), ("department", "department"),
                               ("capacity", "admin_capacity")):
                if row.get(key):
                    lines.append(f"{app.tr(label)}: {row[key]}")
            if row.get("description"):
                lines.append(str(row["description"])[:300])
            lines.append(f"{self._vs(row.get('validation_status'))} · v{row.get('version', 0)}")
            return "\n".join(lines)
        lines = [f"{app.tr('admin_org_type')}: "
                 f"{app.tr('ot_' + (row.get('org_type') or 'autre'))} · {row.get('name') or '?'}",
                 f"{app.tr('department')}: {row.get('department') or '?'} · {app.tr('commune')}: {row.get('commune') or '?'}",
                 self._vs(row.get("validation_status"))]
        for key, label in (("address", "admin_address"), ("contact_email", "admin_contact_email"),
                           ("contact_phone", "admin_contact_phone")):
            if row.get(key):
                lines.append(f"{app.tr(label)}: {row[key]}")
        leader = row.get("leader") or {}
        if leader.get("full_name"):
            lines.append(f"{app.tr('admin_leader_name')}: {leader['full_name']} · "
                         f"{app.tr('lf_' + (leader.get('function') or 'autre'))}")
        programs = row.get("programs") or []
        if programs:
            lines.append(f"{app.tr('admin_programs_title')}:")
            for p in programs[:6]:
                lines.append(f"  {p.get('year')} · {p.get('title') or ''}")
            if len(programs) > 6:
                lines.append(f"  +{len(programs) - 6}")
        return "\n".join(lines)

    # ------------------------------------------------------------------ référentiels
    def _roles_list(self):
        if self._roles is None:
            try:
                self._roles = App.get_running_app().api.admin_roles()
            except (ApiError, NetworkError):
                return []
        return self._roles

    def _choices(self, attr, loader, labeler):
        cached = getattr(self, attr)
        if cached:
            return cached
        try:
            rows = loader()
        except (ApiError, NetworkError):
            return {}
        mapping = {labeler(r): r["id"] for r in rows}
        setattr(self, attr, mapping)
        return mapping

    def _picker(self, choices, current, empty_label, hint):
        if choices:
            values = [empty_label] + list(choices)
            sp = _spinner(values, empty_label)
            label = next((lbl for lbl, i in choices.items() if i == current), None)
            if label is None and current:
                choices = dict(choices)
                choices[current] = current
                sp.values = [empty_label] + list(choices)
                label = current
            sp.text = label or empty_label
            return sp, choices, True
        return _text_input(hint, current or ""), {}, False

    def _picker_value(self, widget, mapping, is_spinner, empty_label):
        if is_spinner:
            return mapping.get(widget.text) if widget.text and widget.text != empty_label else None
        return widget.text.strip() or None

    # ------------------------------------------------------------------ formulaires
    def _open_form(self, title, fields, on_submit):
        app = App.get_running_app()
        form = GridLayout(cols=1, size_hint_y=None, spacing=dp(4))
        form.bind(minimum_height=form.setter("height"))
        for label, widget in fields:
            if label:
                form.add_widget(_field_label(label))
            form.add_widget(widget)
        scroll = ScrollView(size_hint=(1, 1))
        scroll.add_widget(form)
        msg = _wrap_label("")
        buttons = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(6))
        save, cancel = Button(text=app.tr("save")), Button(text=app.tr("cancel"))
        buttons.add_widget(save)
        buttons.add_widget(cancel)
        content = BoxLayout(orientation="vertical", padding=dp(8), spacing=dp(6))
        content.add_widget(scroll)
        content.add_widget(msg)
        content.add_widget(buttons)
        pop = Popup(title=title, content=content, size_hint=(0.95, 0.92))

        def do_save(*_):
            try:
                error = on_submit()
            except ApiError as e:
                error = detail_text(e)
            except NetworkError:
                error = app.tr("offline")
            except (ValueError, TypeError) as e:
                error = str(e)
            if error:
                msg.text = str(error)
                return
            pop.dismiss()
            self.refresh()

        save.bind(on_release=do_save)
        cancel.bind(on_release=lambda *_: pop.dismiss())
        pop.open()

    def create(self):
        app = App.get_running_app()
        if not app.is_admin:
            return
        if self.kind == "users":
            self._form_user(None)
        elif self.kind == "events":
            self._form_event(None)
        else:
            self._form_meol(None)

    def edit(self):
        app = App.get_running_app()
        if not (app.is_admin and self.selected):
            return
        if self.kind == "users":
            self._form_user(self.selected)
        elif self.kind == "events":
            self._form_event(self.selected)
        else:
            self._form_meol(self.selected)

    def _form_user(self, row):
        app = App.get_running_app()
        editing = row is not None
        roles = self._roles_list()
        role_map = {f"{r.get('label', r['code'])} ({r['code']})": r["code"] for r in roles}
        if editing:
            current = row.get("role") or ""
            values = list(role_map)
            if current and current not in role_map.values():
                values.append(current)
                role_map[current] = current
            role_text = next((k for k, v in role_map.items() if v == current), current)
        else:
            if not roles:
                self.ids.status.text = app.tr("admin_roles_failed")
                return
            values = list(role_map)
            role_text = next((k for k, v in role_map.items() if v == "employee"),
                             values[-1] if values else "")
        full = _text_input(app.tr("admin_full_name"), row.get("full_name") if editing else "")
        email = _text_input(app.tr("admin_email"), row.get("email") if editing else "")
        email.disabled = editing
        username = _text_input(app.tr("admin_username"), row.get("username") if editing else "")
        username.disabled = editing
        pwd = _text_input(app.tr("admin_password_reset") if editing else app.tr("admin_password"),
                          password=True)
        role = _spinner(values, role_text)
        dept = _spinner([""] + DEPARTMENTS,
                        row.get("department") if editing and row.get("department") in DEPARTMENTS else "")
        churches = self._choices("_church_choices", lambda: app.api.list_churches(limit=200),
                                 lambda c: f"{c.get('official_name')} — {c.get('commune')}")
        orgs = self._choices("_org_choices", lambda: app.api.list_organizations(max_rows=400),
                             lambda o: f"{o.get('name')} — {o.get('commune') or '?'}")
        empty = app.tr("admin_none_option")
        church_w, church_map, church_sp = self._picker(
            churches, row.get("church_id") if editing else None, empty, "church_id")
        org_w, org_map, org_sp = self._picker(
            orgs, row.get("organization_id") if editing else None, empty, "organization_id")
        active = CheckBox(active=bool(row.get("is_active", True)) if editing else True,
                          size_hint_x=None, width=dp(40))
        active_row = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(6))
        active_row.add_widget(active)
        active_lbl = Label(text=app.tr("admin_active"), halign="left", valign="middle")
        active_lbl.bind(width=lambda w, v: setattr(w, "text_size", (max(dp(20), v - dp(4)), None)))
        active_row.add_widget(active_lbl)

        extra_current = set(row.get("extra_permissions") or []) if editing else set()

        def permission_row(key, code):
            box = BoxLayout(size_hint_y=None, height=dp(38), spacing=dp(6))
            check = CheckBox(active=code in extra_current, size_hint_x=None, width=dp(40))
            label = Label(text=app.tr(key), halign="left", valign="middle")
            label.bind(width=lambda w, v: setattr(w, "text_size", (max(dp(20), v - dp(4)), None)))
            box.add_widget(check)
            box.add_widget(label)
            return check, box

        share_box, share_row = permission_row("perm_share", "document:share")
        read_box, read_row = permission_row("perm_read", "document:read")
        organize_box, organize_row = permission_row("perm_organize", "document:organize")
        print_box, print_row = permission_row("perm_print", "print:use")
        permissions_heading = _wrap_label(app.tr("admin_permissions"))

        def chosen_permissions():
            pairs = ((share_box, "document:share"), (read_box, "document:read"),
                     (organize_box, "document:organize"), (print_box, "print:use"))
            return [code for box, code in pairs if box.active]

        def on_submit():
            name = full.text.strip()
            if len(name) < 2 or not role.text:
                return app.tr("admin_required")
            code = role_map.get(role.text, role.text)
            p = pwd.text
            if p and (len(p) < 10 or p.isdigit() or p.isalpha()):
                return app.tr("admin_password_rule")
            cid = self._picker_value(church_w, church_map, church_sp, empty)
            oid = self._picker_value(org_w, org_map, org_sp, empty)
            dep = dept.text if dept.text in DEPARTMENTS else None
            if editing:
                payload = {"role_code": code, "is_active": bool(active.active),
                           "department": dep, "church_id": cid, "organization_id": oid,
                           "extra_permissions": chosen_permissions()}
                if name:
                    payload["full_name"] = name
                if p:
                    payload["password"] = p
                app.api.update_user(row["id"], payload)
                self._flash = app.tr("admin_updated")
            else:
                mail = email.text.strip()
                if "@" not in mail or len(mail) < 5 or not p:
                    return app.tr("admin_required")
                payload = {"email": mail, "full_name": name, "password": p, "role_code": code,
                           "extra_permissions": chosen_permissions()}
                if username.text.strip():
                    payload["username"] = username.text.strip()
                if dep:
                    payload["department"] = dep
                if cid:
                    payload["church_id"] = cid
                if oid:
                    payload["organization_id"] = oid
                app.api.create_user(payload)
                self._flash = app.tr("admin_created")
            return None

        self._open_form(app.tr("admin_users") + ((" · " + (row.get("full_name") or "")) if editing else ""), [
            (app.tr("admin_full_name"), full),
            (app.tr("admin_email"), email),
            (app.tr("admin_username"), username),
            (app.tr("admin_password_reset") if editing else app.tr("admin_password"), pwd),
            (app.tr("admin_role"), role),
            (app.tr("department"), dept),
            (app.tr("admin_church"), church_w),
            (app.tr("admin_org"), org_w),
            (app.tr("admin_active"), active_row),
            ("", permissions_heading),
            ("", share_row),
            ("", read_row),
            ("", organize_row),
            ("", print_row),
        ], on_submit)

    def _form_event(self, row):
        app = App.get_running_app()
        editing = row is not None
        now_iso = datetime.now().astimezone().replace(microsecond=0).isoformat()
        title = _text_input(app.tr("admin_title"), row.get("title") if editing else "")
        desc = _text_input(app.tr("admin_description"), (row.get("description") or "") if editing else "",
                           multiline=True)
        starts = _text_input(app.tr("admin_starts"),
                             (row.get("starts_at") or now_iso) if editing else now_iso)
        ends = _text_input(app.tr("admin_ends"), (row.get("ends_at") or "") if editing else "")
        location = _text_input(app.tr("admin_location"), row.get("location") if editing else "")
        dept = _spinner(DEPARTMENTS, row.get("department")
                        if editing and row.get("department") in DEPARTMENTS else DEPARTMENTS[0])
        capacity = _text_input(app.tr("admin_capacity"),
                               str(row.get("capacity") or "") if editing else "")
        capacity.input_filter = "int"
        dept.disabled = editing          # EventUpdate n'accepte pas le département

        def on_submit():
            if len(title.text.strip()) < 3:
                return app.tr("admin_required")
            start = self._iso(starts.text)
            if not start:
                return app.tr("admin_required")
            end = self._iso(ends.text) if ends.text.strip() else None
            try:
                cap = int(capacity.text) if capacity.text.strip() else None
            except ValueError:
                return app.tr("admin_required")
            payload = {"title": title.text.strip(), "starts_at": start}
            if desc.text.strip():
                payload["description"] = desc.text.strip()
            if end:
                payload["ends_at"] = end
            if location.text.strip():
                payload["location"] = location.text.strip()
            if cap:
                payload["capacity"] = cap
            if editing:
                payload["version"] = row.get("version", 0)
                payload["description"] = desc.text.strip() or None
                payload["ends_at"] = end
                payload["location"] = location.text.strip() or None
                payload["capacity"] = cap
                app.api.update_event(row["id"], payload)
                self._flash = app.tr("admin_updated")
            else:
                if dept.text in DEPARTMENTS:
                    payload["department"] = dept.text
                app.api.create_event(payload)
                self._flash = app.tr("admin_created")
            return None

        fields = [
            (app.tr("admin_title"), title),
            (app.tr("admin_description"), desc),
            (app.tr("admin_starts"), starts),
            (app.tr("admin_ends"), ends),
            (app.tr("admin_location"), location),
            (app.tr("department"), dept),
            (app.tr("admin_capacity"), capacity),
        ]
        self._open_form(app.tr("admin_events") + ((" · " + (row.get("title") or "")) if editing else ""),
                        fields, on_submit)

    def _form_meol(self, row):
        app = App.get_running_app()
        editing = row is not None
        name = _text_input(app.tr("admin_name"), row.get("name") if editing else "")
        type_map = {app.tr("ot_" + code): code for code in MEOL_TYPES}
        current_type = row.get("org_type") if editing and row.get("org_type") in MEOL_TYPES else MEOL_TYPES[0]
        type_text = next((k for k, v in type_map.items() if v == current_type), list(type_map)[0])
        org_type = _spinner(list(type_map), type_text)
        dept = _spinner(DEPARTMENTS, row.get("department")
                        if editing and row.get("department") in DEPARTMENTS else DEPARTMENTS[0])
        commune = _text_input(app.tr("commune"), row.get("commune") if editing else "")
        address = _text_input(app.tr("admin_address"), row.get("address") if editing else "",
                              multiline=True)
        email = _text_input(app.tr("admin_contact_email"), row.get("contact_email") if editing else "")
        phone = _text_input(app.tr("admin_contact_phone"), row.get("contact_phone") if editing else "")
        leader_name = _text_input(app.tr("admin_leader_name"), "")
        fn_map = {app.tr("lf_" + code): code for code in LEADER_FUNCTIONS}
        fn = _spinner(list(fn_map), next(iter(fn_map)))
        programs = _text_input(app.tr("admin_programs"), "", multiline=True)

        def on_submit():
            if len(name.text.strip()) < 2 or dept.text not in DEPARTMENTS:
                return app.tr("admin_required")
            payload = {"name": name.text.strip(), "org_type": type_map.get(org_type.text, MEOL_TYPES[0]),
                       "department": dept.text}
            for key, widget in (("commune", commune), ("address", address),
                                ("contact_email", email), ("contact_phone", phone)):
                if widget.text.strip():
                    payload[key] = widget.text.strip()
            if editing:
                payload["version"] = row.get("version", 0)
                for key, widget in (("commune", commune), ("address", address),
                                    ("contact_email", email), ("contact_phone", phone)):
                    payload[key] = widget.text.strip() or None
                app.api.update_org(row["id"], payload)
                self._flash = app.tr("admin_updated")
            else:
                if len(leader_name.text.strip()) < 2:
                    return app.tr("admin_required")
                payload["leader"] = {"full_name": leader_name.text.strip(),
                                     "function": fn_map.get(fn.text, "responsable_principal")}
                payload["programs"] = self._parse_programs(programs.text)
                app.api.meol_register(payload)
                self._flash = app.tr("admin_created")
            return None

        fields = [
            (app.tr("admin_name"), name),
            (app.tr("admin_org_type"), org_type),
            (app.tr("department"), dept),
            (app.tr("commune"), commune),
            (app.tr("admin_address"), address),
            (app.tr("admin_contact_email"), email),
            (app.tr("admin_contact_phone"), phone),
        ]
        if editing:
            fields.append(("", _wrap_label(app.tr("admin_edit_note"))))
        else:
            fields += [
                (app.tr("admin_leader_section"), _field_label(app.tr("admin_leader_section"))),
                (app.tr("admin_leader_name"), leader_name),
                (app.tr("admin_leader_function"), fn),
                (app.tr("admin_programs"), programs),
            ]
        self._open_form(app.tr("admin_meol") + ((" · " + (row.get("name") or "")) if editing else ""),
                        fields, on_submit)

    def _iso(self, value):
        app = App.get_running_app()
        value = (value or "").strip()
        if not value:
            return None
        try:
            dt = datetime.fromisoformat(value)
        except ValueError:
            raise ValueError(app.tr("admin_bad_date"))
        if dt.tzinfo is None:
            dt = dt.astimezone()      # l'heure saisie sans fuseau est comprise comme heure locale
        return dt.replace(microsecond=0).isoformat()

    def _parse_programs(self, text):
        app = App.get_running_app()
        out = []
        for raw in (text or "").splitlines():
            line = raw.strip()
            if not line:
                continue
            parts = [p.strip() for p in line.split("|")]
            try:
                year = int(parts[0])
            except (ValueError, IndexError):
                raise ValueError(app.tr("admin_bad_program"))
            if len(parts) < 2 or not (2000 <= year <= 2100) or len(parts[1]) < 2:
                raise ValueError(app.tr("admin_bad_program"))
            item = {"year": year, "title": parts[1]}
            if len(parts) > 2 and parts[2]:
                item["description"] = parts[2]
            out.append(item)
        return out

    # ------------------------------------------------------------------ mutations
    def _run(self, call, success_key):
        app = App.get_running_app()
        try:
            call()
        except NetworkError:
            self.ids.status.text = app.tr("offline")
            return
        except ApiError as e:
            self.ids.status.text = detail_text(e)
            return
        self._flash = app.tr(success_key)
        self.refresh()

    def archive(self):
        app = App.get_running_app()
        if not (app.is_admin and self.selected_id):
            return
        oid = self.selected_id
        content = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(8))
        content.add_widget(_wrap_label(app.tr("admin_confirm_archive")))
        content.add_widget(_wrap_label(app.tr("admin_archive_note")))
        buttons = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(6))
        yes, no = Button(text=app.tr("admin_archive")), Button(text=app.tr("cancel"))
        buttons.add_widget(yes)
        buttons.add_widget(no)
        content.add_widget(buttons)
        pop = Popup(title=app.tr("admin_archive"), content=content, size_hint=(0.9, 0.5))
        no.bind(on_release=lambda *_: pop.dismiss())

        def do(*_):
            pop.dismiss()
            if self.kind == "users":
                call = lambda: app.api.archive_user(oid)
            elif self.kind == "events":
                call = lambda: app.api.transition_event(oid, "archive")
            else:
                call = lambda: app.api.org_transition(oid, "archive")
            self._run(call, "admin_archived")

        yes.bind(on_release=do)
        pop.open()

    def activate(self):
        app = App.get_running_app()
        if not (app.is_admin and self.selected_id and self.kind == "users"):
            return
        uid = self.selected_id
        self._run(lambda: app.api.activate_user(uid), "admin_activated")

    def approve(self):
        app = App.get_running_app()
        if not (app.is_admin and self.selected_id and self.kind == "meol"):
            return
        oid = self.selected_id
        self._run(lambda: app.api.meol_approve(oid), "admin_approved")

    def reject(self):
        app = App.get_running_app()
        if not (app.is_admin and self.selected_id and self.kind == "meol"):
            return
        oid = self.selected_id
        reason = _text_input(app.tr("admin_reason"), "")
        content = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(8))
        content.add_widget(_wrap_label(app.tr("admin_reject")))
        content.add_widget(reason)
        buttons = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(6))
        yes, no = Button(text=app.tr("admin_reject")), Button(text=app.tr("cancel"))
        buttons.add_widget(yes)
        buttons.add_widget(no)
        content.add_widget(buttons)
        pop = Popup(title=app.tr("admin_reject"), content=content, size_hint=(0.9, 0.5))
        no.bind(on_release=lambda *_: pop.dismiss())

        def do(*_):
            pop.dismiss()
            self._run(lambda: app.api.meol_reject(oid, reason.text.strip() or None), "admin_rejected")

        yes.bind(on_release=do)
        pop.open()


class FPHConnectApp(App):
    lang = StringProperty(os.environ.get("FPH_LANG", "fr"))
    # Résolu à l'import : le KV lie `source: app.logo_source` dès le chargement de la chaîne.
    logo_source = StringProperty(LOGO)
    # Vrai uniquement si `GET /auth/me` a confirmé le rôle `superadmin` : l'espace d'administration
    # n'apparaît (et n'agit) que dans ce cas.
    is_admin = BooleanProperty(False)

    def __init__(self, api=None, data_dir=None, **kw):
        super().__init__(**kw)
        self._api_injected, self._data_dir = api, data_dir
        self.current_user = None

    def tr(self, key, lang=None):
        return t(lang or self.lang, key)

    def refresh_user(self):
        """Recharge le compte courant et recalcule `is_admin`. Un échec réseau ne casse pas l'écran :
        l'utilisateur reste connecté mais l'administration demeure masquée."""
        try:
            self.current_user = self.api.me()
        except (ApiError, NetworkError):
            self.current_user = None
        self.is_admin = bool(self.current_user and self.current_user.get("role") == "superadmin")
        return self.current_user

    def build(self):
        self.title = "FPH Connect"
        if self.logo_source:
            self.icon = self.logo_source       # icône de la fenêtre (bureau) ; sur Android c'est icon.filename de buildozer.spec
        self.data_dir = self._data_dir or self.user_data_dir
        os.makedirs(self.data_dir, exist_ok=True)
        self.api = self._api_injected or ApiClient(os.environ.get("FPH_API_URL", "https://127.0.0.1:8000"),
                                                   ca_file=os.environ.get("FPH_CA_CERT"),
                                                   storage_path=os.path.join(self.data_dir, "auth_token.json"))
        self.api.device = DeviceIdentity(os.path.join(self.data_dir, "device.json"))
        self.db = LocalDB(os.path.join(self.data_dir, "fph_cache.db"))
        Builder.load_string(KV)
        sm = ScreenManager()
        for name, cls in (("login", LoginScreen), ("churches", ChurchesScreen), ("church_form", ChurchFormScreen),
                          ("meol", MeolScreen), ("admin", AdminScreen),
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
    # Espace d'administration : sans compte superadmin confirmé, l'écran doit s'ouvrir sans agir.
    app.root.current = "admin"
    for _ in range(5):
        EventLoop.idle()
    admin = app.root.get_screen("admin")
    if app.tr("admin_only") not in admin.ids.status.text:
        problems.append(f"administration : garde superadmin absente ({admin.ids.status.text!r})")
    app.root.current = "login"
    for _ in range(5):
        EventLoop.idle()
    if sorted(app.root.screen_names) != sorted(["login", "churches", "church_form", "meol", "admin",
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
