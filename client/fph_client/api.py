"""Client HTTP de l'API FPH. Le jeton n'est gardé qu'en mémoire (jamais écrit sur disque
dans ce prototype). Aucun identifiant de base de données n'existe côté client."""
import httpx

from .tls import make_verify


class ApiError(Exception):
    def __init__(self, status: int, detail):
        super().__init__(f"HTTP {status}: {detail}")
        self.status, self.detail = status, detail


class NetworkError(Exception):
    pass


class ApiClient:
    def __init__(self, base_url: str, http=None, timeout: float = 10.0, ca_file: str | None = None):
        self.http = http or httpx.Client(base_url=base_url, timeout=timeout, verify=make_verify(ca_file))
        self.token: str | None = None
        self.device = None   # DeviceIdentity (facultatif)

    def _req(self, method, path, **kw):
        headers = kw.pop("headers", {})
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if self.device is not None and self.device.header:
            headers["X-FPH-Device"] = self.device.header
        try:
            r = self.http.request(method, path, headers=headers, **kw)
        except (httpx.TransportError, httpx.TimeoutException) as e:
            raise NetworkError(str(e)) from e
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail")
            except Exception:
                detail = r.text
            raise ApiError(r.status_code, detail)
        return r.json() if r.content else None

    def login(self, email, password, device_label="FPH Connect client"):
        data = self._req("POST", "/api/v1/auth/login",
                         json={"identifier": email, "password": password, "device_label": device_label})
        self.token = data["access_token"]
        return data

    def logout(self):
        try:
            self._req("POST", "/api/v1/auth/logout")
        finally:
            self.token = None

    def me(self):
        return self._req("GET", "/api/v1/auth/me")

    def list_churches(self, limit=200, offset=0):
        return self._req("GET", "/api/v1/churches", params={"limit": limit, "offset": offset})

    def create_church(self, payload: dict, op_id: str):
        return self._req("POST", "/api/v1/churches", json=payload,
                         headers={"Idempotency-Key": op_id})

    def update_church(self, church_id: str, payload: dict):
        return self._req("PATCH", f"/api/v1/churches/{church_id}", json=payload)

    # ---- registre MEOL (organisations affiliées) ----
    def list_organizations(self, department: str | None = None, status: str | None = None,
                           q: str | None = None, max_rows: int = 2000):
        """Le serveur plafonne une page à 200 fiches et le registre MEOL en compte davantage : les pages
        sont empilées jusqu'à la dernière (une page courte signe la fin). Un plafond `max_rows` évite
        qu'une réponse jamais courte ne boucle ici."""
        rows, offset = [], 0
        params = {k: v for k, v in (("department", department), ("status", status), ("q", q)) if v}
        while len(rows) < max_rows:
            page = self._req("GET", "/api/v1/organizations", params={**params, "limit": 200, "offset": offset})
            rows += page
            if len(page) < 200:
                break
            offset += 200
        return rows

    # ---- appareils et réseau local ----
    def register_device(self, name: str, platform: str):
        data = self._req("POST", "/api/v1/devices/register", json={"name": name, "platform": platform})
        if self.device is not None:
            self.device.save(data["id"], data["token"])
        return {"id": data["id"], "status": data["status"]}

    def device_status(self):
        return self._req("GET", "/api/v1/devices/status")

    def heartbeat(self):
        return self._req("POST", "/api/v1/devices/heartbeat")

    def presence(self):
        return self._req("GET", "/api/v1/network/presence")

    def directory(self):
        return self._req("GET", "/api/v1/network/directory")

    # ---- messagerie ----
    def send_message(self, body: str, recipient_id: str | None = None, audience: str = "direct",
                     client_ref: str | None = None):
        return self._req("POST", "/api/v1/messages", json={
            "body": body, "recipient_id": recipient_id, "audience": audience, "client_ref": client_ref})

    def messages(self, after_id: int = 0):
        return self._req("GET", "/api/v1/messages", params={"after_id": after_id})

    # ---- documents ----
    def upload_document(self, filename: str, content: bytes, church_id=None, doc_type=None):
        data = {k: v for k, v in (("church_id", church_id), ("doc_type", doc_type)) if v}
        return self._req("POST", "/api/v1/documents/inbox", data=data,
                         files={"file": (filename, content)})

    def inbox(self, status=None):
        return self._req("GET", "/api/v1/documents/inbox", params={"status": status} if status else None)

    def organize(self):
        return self._req("POST", "/api/v1/documents/inbox/organize")

    def undo_batch(self, batch_id: str):
        return self._req("POST", f"/api/v1/documents/inbox/batches/{batch_id}/undo")

    # ---- impression réseau ----
    def printers(self):
        return self._req("GET", "/api/v1/printers")

    def print_document(self, printer_id: str, filename: str, content: bytes, copies: int = 1,
                       duplex: str = "one-sided", color: bool = False, paper: str = "A4",
                       idempotency_key: str | None = None):
        """Envoie un document à une imprimante FPH autorisée. La clé d'idempotence évite une double
        impression si la réponse se perd (réutilisez la MÊME clé pour renvoyer)."""
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else {}
        return self._req("POST", "/api/v1/print-jobs", headers=headers, files={"file": (filename, content)},
                         data={"printer_id": printer_id, "copies": str(copies), "duplex": duplex,
                               "color": "true" if color else "false", "paper": paper})

    def print_jobs(self, status=None):
        return self._req("GET", "/api/v1/print-jobs", params={"status": status} if status else None)

    def print_job(self, job_id: str):
        return self._req("GET", f"/api/v1/print-jobs/{job_id}")

    def cancel_print_job(self, job_id: str):
        return self._req("POST", f"/api/v1/print-jobs/{job_id}/cancel")

    # ---- événements et inscriptions (personnel) ----
    def events(self):
        return self._req("GET", "/api/v1/events")

    def event_stats(self, event_id: str):
        return self._req("GET", f"/api/v1/events/{event_id}/stats")

    def add_participant(self, event_id: str, full_name: str, email: str | None = None,
                        phone: str | None = None, consent: bool = False):
        return self._req("POST", f"/api/v1/events/{event_id}/registrations", json={
            "full_name": full_name, "email": email or None, "phone": phone or None, "consent": consent})
