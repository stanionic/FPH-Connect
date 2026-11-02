from .conftest import login, make_user


def test_login_logout_and_session_revocation(client, root):
    assert client.get("/api/v1/auth/me", headers=root).json()["role"] == "superadmin"
    assert client.post("/api/v1/auth/logout", headers=root).status_code == 204
    assert client.get("/api/v1/auth/me", headers=root).status_code == 401


def test_no_token_rejected(client):
    assert client.get("/api/v1/churches").status_code == 401
    assert client.get("/api/v1/auth/me", headers={"Authorization": "Bearer junk"}).status_code == 401


def test_wrong_password_generic_error(client):
    r = client.post("/api/v1/auth/login", json={"email": "root@fph.org", "password": "bad"})
    assert r.status_code == 401
    r2 = client.post("/api/v1/auth/login", json={"email": "nobody@fph.org", "password": "bad"})
    assert r.json() == r2.json()  # n'indique pas si le compte existe


def test_lockout_after_repeated_failures(client):
    for _ in range(3):
        client.post("/api/v1/auth/login", json={"email": "root@fph.org", "password": "bad"})
    r = client.post("/api/v1/auth/login",
                    json={"email": "root@fph.org", "password": "Root-Password-123"})
    assert r.status_code == 423


def test_deactivation_revokes_sessions_immediately(client, root):
    make_user(client, root, "emp@fph.org", "national_admin")
    h = login(client, "emp@fph.org", "Passw0rd-long-1")
    uid = client.get("/api/v1/auth/me", headers=h).json()["id"]
    assert client.post(f"/api/v1/users/{uid}/deactivate", headers=root).status_code == 204
    assert client.get("/api/v1/auth/me", headers=h).status_code == 401
    r = client.post("/api/v1/auth/login", json={"email": "emp@fph.org", "password": "Passw0rd-long-1"})
    assert r.status_code == 401


def test_password_policy_and_hash_not_plain(client, root):
    r = client.post("/api/v1/users", headers=root, json={
        "email": "a@fph.org", "full_name": "A B", "password": "short",
        "role_code": "national_admin"})
    assert r.status_code == 422
    from app.db import SessionLocal
    from app.models import User
    with SessionLocal() as db:
        assert db.query(User).first().password_hash.startswith("scrypt$")


def test_change_password_revokes_other_sessions(client, root):
    make_user(client, root, "n@fph.org", "national_admin")
    h1 = login(client, "n@fph.org", "Passw0rd-long-1")
    h2 = login(client, "n@fph.org", "Passw0rd-long-1")
    r = client.post("/api/v1/auth/change-password", headers=h1,
                    json={"current_password": "Passw0rd-long-1", "new_password": "New-Passw0rd-22"})
    assert r.status_code == 204
    assert client.get("/api/v1/auth/me", headers=h1).status_code == 200
    assert client.get("/api/v1/auth/me", headers=h2).status_code == 401


def test_cannot_grant_higher_role(client, root):
    make_user(client, root, "n@fph.org", "national_admin")
    h = login(client, "n@fph.org", "Passw0rd-long-1")
    r = client.post("/api/v1/users", headers=h, json={
        "email": "x@fph.org", "full_name": "X Y", "password": "Passw0rd-long-1",
        "role_code": "superadmin"})
    assert r.status_code == 403
