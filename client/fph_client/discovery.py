"""Recherche du serveur FPH sur le réseau local (broadcast UDP)."""
import json
import socket
import time

PROBE = b"FPH-DISCOVER/1"
DEFAULT_PORT = 50505


def discover(timeout: float = 2.0, port: int = DEFAULT_PORT, target: str = "255.255.255.255") -> list[dict]:
    """Retourne [{'name', 'url', 'address'}]. Trouver un serveur n'autorise rien."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    s.settimeout(0.2)
    found, seen = [], set()
    try:
        s.sendto(PROBE, (target, port))
        end = time.time() + timeout
        while time.time() < end:
            try:
                data, (addr, _) = s.recvfrom(1024)
            except socket.timeout:
                continue
            try:
                info = json.loads(data)
                if info.get("service") != "fph-connect" or addr in seen:
                    continue
                seen.add(addr)
                found.append({"name": str(info.get("name", ""))[:80], "address": addr,
                              "url": f"{info.get('scheme', 'http')}://{addr}:{int(info['api_port'])}"})
            except (ValueError, KeyError, TypeError):
                continue   # réponse invalide : ignorée
    finally:
        s.close()
    return found
