"""Client HTTP de l'agent. Jeton d'appareil de l'agent uniquement (en-tête X-FPH-Device)."""
import httpx

from .tls import make_verify


class ApiError(Exception):
    def __init__(self, status: int, detail):
        super().__init__(f"HTTP {status}: {detail}")
        self.status, self.detail = status, detail


class NetworkError(Exception):
    pass


class AgentClient:
    def __init__(self, base_url: str, device_header: str, http=None, timeout: float = 15.0,
                 ca_file: str | None = None):
        self.http = http or httpx.Client(base_url=base_url, timeout=timeout, follow_redirects=False,
                                         verify=make_verify(ca_file))
        self.headers = {"X-FPH-Device": device_header}

    def _req(self, method, path, **kw):
        try:
            r = self.http.request(method, path, headers=self.headers, **kw)
        except (httpx.TransportError, httpx.TimeoutException) as e:
            raise NetworkError(str(e)) from e
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail")
            except Exception:
                detail = r.text[:200]
            raise ApiError(r.status_code, detail)
        return r

    def report(self, printers: list[dict]) -> dict:
        return self._req("POST", "/api/v1/agent/report", json={"printers": printers}).json()

    def claim(self) -> dict:
        return self._req("POST", "/api/v1/agent/jobs/claim").json()

    def download(self, job_id: str) -> bytes:
        return self._req("GET", f"/api/v1/agent/jobs/{job_id}/file").content

    def status(self, job_id: str, status: str, backend_job_id: str | None = None, error: str | None = None) -> dict:
        body = {"status": status}
        if backend_job_id:
            body["backend_job_id"] = backend_job_id
        if error:
            body["error"] = error[:300]
        return self._req("POST", f"/api/v1/agent/jobs/{job_id}/status", json=body).json()
