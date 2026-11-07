import json
from unittest.mock import patch

from pwa.app import create_app


class APIResponse:
    def __init__(self, data, status=200):
        self.data = json.dumps(data).encode()
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self):
        return self.data


def test_pwa_pages_and_manifest():
    client = create_app().test_client()

    page = client.get("/")
    manifest = client.get("/manifest.webmanifest")
    worker = client.get("/service-worker.js")

    assert page.status_code == 200
    assert b"FPH Connect" in page.data
    assert manifest.mimetype == "application/manifest+json"
    assert manifest.json["display"] == "standalone"
    assert worker.status_code == 200
    assert worker.headers["Service-Worker-Allowed"] == "/"
    assert worker.headers["Cache-Control"] == "no-cache"


def test_login_is_proxied_without_enabling_cross_origin_requests():
    client = create_app().test_client()
    captured = {}

    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data)
        captured["timeout"] = timeout
        return APIResponse({"access_token": "temporary"})

    with patch("pwa.app.urlopen", side_effect=fake_urlopen):
        response = client.post("/api/login", json={"identifier": "member", "password": "secret"})

    assert response.status_code == 200
    assert response.json["access_token"] == "temporary"
    assert response.headers["Cache-Control"] == "no-store"
    assert captured["url"].endswith("/api/v1/auth/login")
    assert captured["body"]["identifier"] == "member"
    assert captured["body"]["device_label"] == "FPH Connect PWA"
    assert captured["timeout"] == 10
    assert "Access-Control-Allow-Origin" not in response.headers


def test_authenticated_routes_forward_bearer_token():
    client = create_app().test_client()
    captured = {}

    def fake_urlopen(req, timeout):
        captured["authorization"] = req.get_header("Authorization")
        captured["url"] = req.full_url
        return APIResponse({"full_name": "Membre"})

    with patch("pwa.app.urlopen", side_effect=fake_urlopen):
        unauthorized = client.get("/api/me")
        response = client.get("/api/me", headers={"Authorization": "Bearer session-token"})

    assert unauthorized.status_code == 401
    assert response.status_code == 200
    assert response.json["full_name"] == "Membre"
    assert captured["authorization"] == "Bearer session-token"


def test_public_church_search_is_forwarded():
    client = create_app().test_client()
    captured = {}

    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        return APIResponse([])

    with patch("pwa.app.urlopen", side_effect=fake_urlopen):
        response = client.get("/api/churches?q=Église&department=Ouest")

    assert response.status_code == 200
    assert response.json == []
    assert "department=Ouest" in captured["url"]
    assert "q=%C3%89glise" in captured["url"]


def test_api_unavailable_returns_service_error():
    client = create_app().test_client()

    with patch("pwa.app.urlopen", side_effect=OSError("unavailable")):
        response = client.get("/api/events")

    assert response.status_code == 502
    assert "indisponible" in response.json["detail"]
