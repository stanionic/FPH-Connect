"""Boucle de l'agent. Sans mémoire propre : le serveur lui redonne à chaque cycle les travaux à
reprendre ou à annuler, donc un redémarrage ne perd ni ne duplique rien."""
import hashlib
import os
import shutil
import tempfile
import time

from .backends import Backend, BackendError, check_options
from .client import AgentClient, ApiError, NetworkError

EXT = {"application/pdf": ".pdf", "image/png": ".png", "image/jpeg": ".jpg", "text/plain": ".txt"}
OBSERVED = {"processing": "in_progress", "completed": "completed", "error": "error",
            "transmitted": "transmitted", "unknown": "unknown"}


class Agent:
    def __init__(self, client: AgentClient, backend: Backend, share: list[str], tmp_root: str | None = None, log=print):
        share = [s.strip() for s in share if s and s.strip()]
        if not share:
            raise ValueError("Aucune imprimante à partager : renseigner explicitement la liste (rien n'est partagé par défaut)")
        self.client, self.backend, self.share, self.log = client, backend, share, log
        self.tmp_root = tmp_root

    # -- un cycle --
    def run_once(self) -> dict:
        stats = {"printed": 0, "errors": 0, "network_error": False}
        try:
            self.client.report(self.backend.list_printers(self.share))
            work = self.client.claim()
            cancelled = set()
            for c in work.get("cancel", []):
                if self._cancel(c):
                    cancelled.add(c["job_id"])
            for r in work.get("resume", []):
                if r["job_id"] not in cancelled:    # annulé avec succès : rien d'autre à suivre
                    self._track(r["job_id"], r["backend_job_id"], r["system_name"])
            for j in work.get("new", []):
                ok = self._handle_new(j)
                stats["printed" if ok else "errors"] += 1
        except NetworkError:
            stats["network_error"] = True       # le serveur est injoignable : on réessaiera, rien n'est perdu
        except ApiError as e:
            self.log(f"Erreur API {e.status}")
            stats["errors"] += 1
        return stats

    def _cancel(self, c) -> bool:
        try:
            if self.backend.cancel(c["backend_job_id"], c["system_name"]):
                self.client.status(c["job_id"], "cancelled")
                return True
            # sinon : déjà imprimé ou impossible à annuler ; le suivi normal dira ce qui s'est passé
        except (BackendError, ApiError):
            pass
        return False

    def _fail(self, job_id: str, message: str):
        try:
            self.client.status(job_id, "error", error=message)
        except (ApiError, NetworkError):
            pass

    def _handle_new(self, j) -> bool:
        job_id, queue = j["job_id"], j["system_name"]
        if queue not in self.share:             # contrôle local, indépendant du serveur
            self._fail(job_id, "Imprimante non partagée par cet agent")
            return False
        try:
            data = self.client.download(job_id)
        except ApiError as e:
            if e.status == 409:                 # annulé par l'utilisateur avant impression
                self.client.status(job_id, "cancelled")
            else:
                self._fail(job_id, "Fichier indisponible")
            return False
        if len(data) != j["size"] or hashlib.sha256(data).hexdigest() != j["sha256"]:
            self._fail(job_id, "Fichier corrompu pendant le transfert")
            return False
        work_dir = tempfile.mkdtemp(prefix="fph-", dir=self.tmp_root)
        try:
            os.chmod(work_dir, 0o700)
            path = os.path.join(work_dir, "job" + EXT.get(j.get("mime"), ".bin"))
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            opts = check_options(j["copies"], j.get("options", {}))
            bid = self.backend.submit(path, queue, j["copies"], opts, j.get("title", "document"))
        except BackendError as e:
            self._fail(job_id, str(e))
            return False
        except OSError:
            self._fail(job_id, "Erreur locale pendant la préparation du document")
            return False
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)    # le document ne reste pas sur le poste
        self.client.status(job_id, "accepted", backend_job_id=bid)   # confirme : plus de reprise automatique
        self._track(job_id, bid, queue)
        return True

    def _track(self, job_id: str, bid: str, queue: str):
        try:
            st = self.backend.status(bid, queue)
        except BackendError:
            return
        if st in OBSERVED:
            self.client.status(job_id, OBSERVED[st], backend_job_id=bid)

    def run_forever(self, poll_seconds: float = 5.0):
        while True:
            self.run_once()
            time.sleep(poll_seconds)
