"""Identité de l'appareil (id + jeton secret), conservée localement, hors du cache effacé
à la déconnexion. Le fichier est créé en mode 0600."""
import json
import os


class DeviceIdentity:
    def __init__(self, path: str):
        self.path = path
        self.id: str | None = None
        self.token: str | None = None
        self.load()

    def load(self):
        try:
            with open(self.path) as f:
                d = json.load(f)
            self.id, self.token = d["id"], d["token"]
        except (OSError, ValueError, KeyError):
            self.id = self.token = None

    def save(self, device_id: str, token: str):
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump({"id": device_id, "token": token}, f)
        self.id, self.token = device_id, token

    def clear(self):
        try:
            os.remove(self.path)
        except OSError:
            pass
        self.id = self.token = None

    @property
    def header(self) -> str | None:
        return f"{self.id}:{self.token}" if self.id and self.token else None
