"""Répondeur de découverte LAN (UDP). Lancer : python -m app.discovery
Une machine qui reçoit cette réponse sait OÙ est le serveur FPH. Cela ne lui donne AUCUN droit :
il faut encore un appareil approuvé et un utilisateur authentifié.
La réponse ne contient ni secret, ni donnée institutionnelle."""
import json
import os
import socket

PROBE = b"FPH-DISCOVER/1"
DEFAULT_PORT = 50505


def build_reply() -> bytes:
    return json.dumps({"service": "fph-connect", "name": os.environ.get("FPH_SERVER_NAME", "FPH Connect"),
                       "api_port": int(os.environ.get("FPH_API_PORT", "8000")),
                       "scheme": os.environ.get("FPH_API_SCHEME", "http"), "protocol": 1}).encode()


def handle(data: bytes) -> bytes | None:
    """Ne répond qu'à une sonde exacte ; tout le reste est ignoré en silence."""
    return build_reply() if data.strip() == PROBE else None


def serve(port: int = DEFAULT_PORT, bind: str = "0.0.0.0", stop=lambda: False, ready=None):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((bind, port))
    s.settimeout(0.3)
    if ready:
        ready(s.getsockname()[1])
    try:
        while not stop():
            try:
                data, addr = s.recvfrom(256)   # petite taille : pas d'amplification
            except socket.timeout:
                continue
            reply = handle(data)
            if reply:
                s.sendto(reply, addr)
    finally:
        s.close()


if __name__ == "__main__":
    serve(int(os.environ.get("FPH_DISCOVERY_PORT", DEFAULT_PORT)))
