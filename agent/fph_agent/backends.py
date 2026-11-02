"""Accès au système d'impression local. Aucun shell : les commandes reçoivent des listes d'arguments
validées (pas d'injection). Chaque backend dit honnêtement ce qu'il sait suivre.

  FileBackend    : « imprimante virtuelle » qui écrit dans un dossier (démonstration, tests, archivage).
  CupsBackend    : Linux/macOS, commandes lp / lpstat / cancel.        NON testé contre un vrai CUPS.
  WindowsBackend : SumatraPDF en ligne de commande. Fin d'impression NON suivie.   NON testé sous Windows.

status() retourne : queued | processing | completed | error | transmitted | unknown
  transmitted = envoyé à la file, aucun moyen de confirmer la fin ; unknown = travail introuvable.
"""
import json
import re
import shutil
import subprocess
import uuid
from pathlib import Path

SIDES = ("one-sided", "two-sided-long-edge", "two-sided-short-edge")
_SAFE_PAPER = re.compile(r"^[A-Za-z0-9_.-]{1,20}$")
_SAFE_QUEUE = re.compile(r"^[A-Za-z0-9_.@ -]{1,200}$")

DEFAULT_CAPS = {"duplex": False, "color": False, "paper": ["A4", "Letter"], "max_copies": 10}


class BackendError(Exception):
    """Message destiné à l'utilisateur : ne jamais y mettre de chemin de fichier ni de détail interne."""


def safe_title(title: str) -> str:
    t = re.sub(r"[^A-Za-z0-9 ._-]", "_", title or "document")
    return (t.strip() or "document")[:60]


def check_options(copies: int, options: dict) -> dict:
    if not isinstance(copies, int) or not 1 <= copies <= 99:
        raise BackendError("Nombre de copies invalide")
    duplex = options.get("duplex", "one-sided")
    paper = str(options.get("paper", "A4"))
    if duplex not in SIDES or not _SAFE_PAPER.match(paper):
        raise BackendError("Options d'impression invalides")
    return {"duplex": duplex, "paper": paper, "color": bool(options.get("color", False))}


class Backend:
    name = "base"
    tracking = "full"

    def __init__(self, caps_override: dict | None = None):
        self.caps_override = caps_override or {}

    def caps_for(self, queue: str) -> dict:
        caps = {**DEFAULT_CAPS, "tracking": self.tracking}
        caps.update(self.caps_override.get(queue, {}))
        return caps

    def list_printers(self, share: list[str]) -> list[dict]:
        raise NotImplementedError

    def submit(self, path: str, queue: str, copies: int, options: dict, title: str) -> str:
        raise NotImplementedError

    def status(self, backend_job_id: str, queue: str) -> str:
        raise NotImplementedError

    def cancel(self, backend_job_id: str, queue: str) -> bool:
        return False


class FileBackend(Backend):
    name = "file"

    def __init__(self, out_dir: str, caps_override: dict | None = None):
        super().__init__(caps_override)
        self.out = Path(out_dir)

    def list_printers(self, share):
        return [{"system_name": q, "name": q, "backend": "file", "capabilities": self.caps_for(q)} for q in share]

    def submit(self, path, queue, copies, options, title):
        opts = check_options(copies, options)
        d = self.out / re.sub(r"[^A-Za-z0-9_.-]", "_", queue)
        d.mkdir(parents=True, exist_ok=True)
        jid = "FILE-" + uuid.uuid4().hex[:10]
        shutil.copyfile(path, d / f"{jid}.bin")
        (d / f"{jid}.json").write_text(json.dumps({"title": safe_title(title), "copies": copies, **opts}))
        return jid

    def status(self, backend_job_id, queue):
        d = self.out / re.sub(r"[^A-Za-z0-9_.-]", "_", queue)
        return "completed" if (d / f"{backend_job_id}.bin").exists() else "unknown"


class CupsBackend(Backend):
    name = "cups"

    def __init__(self, caps_override=None, lp="lp", lpstat="lpstat", cancel_cmd="cancel", timeout=20):
        super().__init__(caps_override)
        self.lp, self.lpstat, self.cancel_cmd, self.timeout = lp, lpstat, cancel_cmd, timeout

    def _run(self, args):
        try:
            return subprocess.run(args, capture_output=True, text=True, timeout=self.timeout, check=False)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise BackendError("Le système d'impression local ne répond pas") from e

    def list_printers(self, share):
        out = self._run([self.lpstat, "-a"]).stdout
        present = {m.group(1) for m in re.finditer(r"^(\S+) accepting requests", out, re.M)}
        return [{"system_name": q, "name": q, "backend": "cups", "capabilities": self.caps_for(q)}
                for q in share if q in present]

    def submit(self, path, queue, copies, options, title):
        if not _SAFE_QUEUE.match(queue):
            raise BackendError("Nom de file invalide")
        o = check_options(copies, options)
        args = [self.lp, "-d", queue, "-n", str(copies), "-t", safe_title(title),
                "-o", f"sides={o['duplex']}", "-o", f"media={o['paper']}",
                "-o", f"print-color-mode={'color' if o['color'] else 'monochrome'}", path]
        r = self._run(args)
        m = re.search(r"request id is (\S+)", r.stdout)
        if r.returncode != 0 or not m:
            raise BackendError("L'impression a été refusée par le système local")
        return m.group(1)

    def status(self, backend_job_id, queue):
        active = self._run([self.lpstat, "-o", queue]).stdout
        if any(line.split(" ", 1)[0] == backend_job_id for line in active.splitlines()):
            now_printing = self._run([self.lpstat, "-p", queue]).stdout
            return "processing" if f"now printing {backend_job_id}" in now_printing else "queued"
        done = self._run([self.lpstat, "-W", "completed", "-o", queue]).stdout
        if any(line.split(" ", 1)[0] == backend_job_id for line in done.splitlines()):
            return "completed"
        return "unknown"     # annulé, purgé de l'historique ou introuvable : on ne prétend rien

    def cancel(self, backend_job_id, queue):
        return self._run([self.cancel_cmd, backend_job_id]).returncode == 0


class WindowsBackend(Backend):
    name = "windows"
    tracking = "none"

    def __init__(self, sumatra_path: str, caps_override=None, timeout=60):
        super().__init__(caps_override)
        self.sumatra, self.timeout = sumatra_path, timeout

    def list_printers(self, share):
        # La liste vient de la configuration : on ne sonde pas les imprimantes Windows (non vérifié).
        return [{"system_name": q, "name": q, "backend": "windows", "capabilities": self.caps_for(q)} for q in share]

    def submit(self, path, queue, copies, options, title):
        o = check_options(copies, options)
        settings = [f"{copies}x", "color" if o["color"] else "monochrome", f"paper={o['paper']}",
                    {"one-sided": "simplex", "two-sided-long-edge": "duplexlong",
                     "two-sided-short-edge": "duplexshort"}[o["duplex"]]]
        try:
            r = subprocess.run([self.sumatra, "-print-to", queue, "-print-settings", ",".join(settings),
                                "-silent", path], capture_output=True, text=True, timeout=self.timeout, check=False)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise BackendError("SumatraPDF est introuvable ou ne répond pas") from e
        if r.returncode != 0:
            raise BackendError("L'impression a été refusée par Windows")
        return "win-" + uuid.uuid4().hex[:10]

    def status(self, backend_job_id, queue):
        return "transmitted"      # aucun suivi possible : on le dit, on ne devine pas
