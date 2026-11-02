from app.db import SessionLocal
from app.models import User

from .conftest import login


def test_login_by_username_case_insensitive_and_by_email(client):
    for ident in ("test-admin", "TEST-ADMIN", "root@fph.org"):
        r = client.post("/api/v1/auth/login", json={"identifier": ident, "password": "Root-Password-123"})
        assert r.status_code == 200, ident
    r = client.post("/api/v1/auth/login", json={"identifier": "test-admin", "password": "wrong"})
    assert r.status_code == 401


def test_username_must_be_unique_and_valid(client, root):
    body = {"username": "agent-1", "email": "a1@fph.org", "full_name": "Agent Un",
            "password": "Passw0rd-long-1", "role_code": "national_admin"}
    assert client.post("/api/v1/users", headers=root, json=body).status_code == 201
    dup = client.post("/api/v1/users", headers=root, json={**body, "email": "other@fph.org"})
    assert dup.status_code == 409
    bad = client.post("/api/v1/users", headers=root, json={**body, "username": "a b", "email": "x@fph.org"})
    assert bad.status_code == 422
    h = client.post("/api/v1/auth/login", json={"identifier": "AGENT-1", "password": "Passw0rd-long-1"})
    assert h.status_code == 200


def test_forced_password_change_blocks_everything_else(client):
    with SessionLocal() as db:
        u = db.query(User).filter(User.username == "test-admin").one()
        u.must_change_password = True
        db.commit()
    h = login(client, "test-admin", "Root-Password-123")
    assert client.get("/api/v1/auth/me", headers=h).json()["must_change_password"] is True
    assert client.get("/api/v1/churches", headers=h).status_code == 403
    assert client.post("/api/v1/devices/register", headers=h,
                       json={"name": "PC", "platform": "linux"}).status_code == 403
    same = client.post("/api/v1/auth/change-password", headers=h,
                       json={"current_password": "Root-Password-123", "new_password": "Root-Password-123"})
    assert same.status_code == 422                                    # doit être différent
    weak = client.post("/api/v1/auth/change-password", headers=h,
                       json={"current_password": "Root-Password-123", "new_password": "court"})
    assert weak.status_code == 422
    ok = client.post("/api/v1/auth/change-password", headers=h,
                     json={"current_password": "Root-Password-123", "new_password": "Nouveau-Mdp-2026-x"})
    assert ok.status_code == 204
    assert client.get("/api/v1/churches", headers=h).status_code == 200      # débloqué
    assert client.post("/api/v1/auth/login", json={"identifier": "test-admin",
                       "password": "Root-Password-123"}).status_code == 401  # l'ancien ne marche plus
