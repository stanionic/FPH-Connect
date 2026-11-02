import os
import sys
import tempfile

_tmp = tempfile.mkdtemp()
os.environ["FPH_DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["FPH_BOOTSTRAP_ADMIN_EMAIL"] = "root@fph.org"
os.environ["FPH_BOOTSTRAP_ADMIN_PASSWORD"] = "Root-Password-123"
os.environ["FPH_BOOTSTRAP_ADMIN_USERNAME"] = "test-admin"
os.environ["FPH_BOOTSTRAP_FORCE_CHANGE"] = "0"
os.environ["FPH_MAX_FAILED_LOGINS"] = "3"
os.environ["FPH_STORAGE_DIR"] = os.path.join(_tmp, "storage")
os.environ["FPH_MAX_UPLOAD_MB"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, os.path.join(_root, "client"))
sys.path.insert(0, os.path.join(_root, "connectors", "flask"))
sys.path.insert(0, os.path.join(_root, "agent"))
sys.path.insert(0, os.path.join(_root, "scripts"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app, seed  # noqa: E402


@pytest.fixture()
def client():
    import shutil
    shutil.rmtree(os.environ["FPH_STORAGE_DIR"], ignore_errors=True)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed(db)
    with TestClient(app) as c:
        yield c


def login(client, email, password):
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def root(client):
    return login(client, "root@fph.org", "Root-Password-123")


def make_user(client, root_headers, email, role, **extra):
    r = client.post("/api/v1/users", headers=root_headers, json={
        "email": email, "full_name": "Test User", "password": "Passw0rd-long-1",
        "role_code": role, **extra})
    assert r.status_code == 201, r.text
    return r.json()


CHURCH = {"official_name": "Église Baptiste de Pétion-Ville", "department": "Ouest",
          "commune": "Pétion-Ville", "address": "Rue 1", "contact_phone": "+509 0000 0000",
          "contact_email": "contact@eglise.org", "main_leader_name": "Pasteur X"}


def make_church(client, headers, **over):
    r = client.post("/api/v1/churches", headers=headers, json={**CHURCH, **over})
    assert r.status_code == 201, r.text
    return r.json()


def device_for(client, root_headers, user_headers, name="PC bureau", approve=True, **approve_kw):
    """Enregistre un appareil pour l'utilisateur, l'approuve (admin), retourne les en-têtes complets."""
    r = client.post("/api/v1/devices/register", headers=user_headers, json={"name": name, "platform": "linux"})
    assert r.status_code == 201, r.text
    d = r.json()
    if approve:
        a = client.post(f"/api/v1/devices/{d['id']}/approve", headers=root_headers, json=approve_kw)
        assert a.status_code == 200, a.text
    return {**user_headers, "X-FPH-Device": f"{d['id']}:{d['token']}"}, d


PDF = b"%PDF-1.4\n% test document\n" + b"x" * 200
