"""Lancement : python -m fph_agent   (configuration par variables d'environnement)

  FPH_URL=https://fph-serveur:8000        FPH_AGENT_TOKEN=<id:jeton donné à la création de l'agent>
  FPH_AGENT_SHARE="HP-LaserJet,Brother"   OBLIGATOIRE : seules ces files sont partagées
  FPH_AGENT_BACKEND=cups|windows|file     FPH_AGENT_FILE_DIR=./sortie (backend file)
  FPH_AGENT_SUMATRA="C:\\Program Files\\SumatraPDF\\SumatraPDF.exe" (backend windows)
  FPH_AGENT_CAPS=caps.json                {"HP-LaserJet": {"duplex": true, "paper": ["A4"]}}  (capacités : configuration, pas détection)
  FPH_AGENT_POLL_SECONDS=5
  FPH_CA_CERT=/chemin/ca.pem              autorité FPH à laquelle faire confiance (réseau local en https)
"""
import json
import os
import sys

from .agent import Agent
from .backends import CupsBackend, FileBackend, WindowsBackend
from .client import AgentClient


def selftest() -> int:
    """`fph-agent --selftest` : vérifie, sans réseau, que l'installation (ou l'exécutable construit) fonctionne."""
    import ssl
    import tempfile
    from .client import AgentClient
    problems = []
    try:
        AgentClient("https://127.0.0.1:9", "id:jeton")                      # pile HTTP/TLS disponible
        Agent(AgentClient("https://127.0.0.1:9", "id:jeton"), FileBackend(tempfile.mkdtemp()), ["X"])
    except Exception as e:                                                  # noqa: BLE001
        problems.append(f"initialisation : {type(e).__name__}")
    try:
        Agent(AgentClient("https://127.0.0.1:9", "id:jeton"), FileBackend(tempfile.mkdtemp()), [])
        problems.append("un agent sans liste de partage a été accepté")      # doit être refusé
    except ValueError:
        pass
    print("AGENT SELFTEST ÉCHEC : " + "; ".join(problems) if problems else f"AGENT SELFTEST OK ({ssl.OPENSSL_VERSION})")
    return 1 if problems else 0


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    url, token = os.environ.get("FPH_URL"), os.environ.get("FPH_AGENT_TOKEN")
    share = [s for s in os.environ.get("FPH_AGENT_SHARE", "").split(",") if s.strip()]
    if not url or not token or not share:
        print(__doc__)
        return 2
    caps = {}
    if os.environ.get("FPH_AGENT_CAPS"):
        with open(os.environ["FPH_AGENT_CAPS"], encoding="utf-8") as f:
            caps = json.load(f)
    kind = os.environ.get("FPH_AGENT_BACKEND", "cups")
    if kind == "file":
        backend = FileBackend(os.environ.get("FPH_AGENT_FILE_DIR", "./sortie"), caps)
    elif kind == "windows":
        backend = WindowsBackend(os.environ["FPH_AGENT_SUMATRA"], caps)
    else:
        backend = CupsBackend(caps)
    Agent(AgentClient(url, token, ca_file=os.environ.get("FPH_CA_CERT")), backend, share).run_forever(float(os.environ.get("FPH_AGENT_POLL_SECONDS", "5")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
