"""PWA-to-FastAPI integration tests using only the isolated test database."""

from urllib.parse import urlsplit
from unittest.mock import patch

from pwa.app import create_app

from .conftest import make_user


class APIResponse:
    def __init__(self, response):
        self.status = response.status_code
        self.payload = response.content

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self):
        return self.payload


def _pwa_client_to_api(api_client):
    def send(request, timeout):
        url = urlsplit(request.full_url)
        path = url.path + (f"?{url.query}" if url.query else "")
        response = api_client.request(
            request.method,
            path,
            headers=dict(request.header_items()),
            content=request.data,
        )
        return APIResponse(response)

    return send


def test_admin_credentials_display_database_users_and_organizations(client, root):
    organization = client.post(
        "/api/v1/organizations",
        headers=root,
        json={"name": "Organisation de test", "org_type": "association", "department": "Ouest"},
    )
    assert organization.status_code == 201, organization.text

    pwa = create_app().test_client()
    with patch("pwa.app.urlopen", side_effect=_pwa_client_to_api(client)):
        login = pwa.post(
            "/api/login",
            json={"identifier": "test-admin", "password": "Root-Password-123"},
        )
        assert login.status_code == 200, login.json
        headers = {"Authorization": f"Bearer {login.json['access_token']}"}

        current_user = pwa.get("/api/me", headers=headers)
        users = pwa.get("/api/admin/users", headers=headers)
        organizations = pwa.get("/api/organizations", headers=headers)

    assert current_user.status_code == 200
    assert current_user.json["role"] == "superadmin"
    assert users.status_code == 200
    assert any(user["username"] == "test-admin" for user in users.json)
    assert all("password_hash" not in user for user in users.json)
    assert organizations.status_code == 200
    assert any(row["id"] == organization.json()["id"] for row in organizations.json)


def test_non_admin_credentials_cannot_display_admin_database_views(client, root):
    make_user(client, root, "public@fph.org", "public")
    pwa = create_app().test_client()

    with patch("pwa.app.urlopen", side_effect=_pwa_client_to_api(client)):
        login = pwa.post(
            "/api/login",
            json={"identifier": "public@fph.org", "password": "Passw0rd-long-1"},
        )
        assert login.status_code == 200, login.json
        headers = {"Authorization": f"Bearer {login.json['access_token']}"}

        users = pwa.get("/api/admin/users", headers=headers)
        organizations = pwa.get("/api/organizations", headers=headers)

    assert users.status_code == 403
    assert organizations.status_code == 403
