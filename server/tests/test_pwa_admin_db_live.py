"""Tests en live : PWA affiche toutes les donnees de la base avec compte admin (superadmin)."""
from urllib.parse import urlsplit
from unittest.mock import patch

from pwa.app import create_app

from .conftest import make_user, make_church


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


def test_admin_superadmin_voit_toutes_les_eglises_de_la_base(client, root):
    """L'admin superadmin voit toutes les eglises, y compris non publiees."""
    make_church(client, root, official_name="Eglise Publique", validation_status="published",
                affiliation_status="affiliated")
    make_church(client, root, official_name="Eglise Brouillon", validation_status="draft",
                affiliation_status="pending")
    make_church(client, root, official_name="Eglise En Attente", validation_status="pending",
                affiliation_status="pending")

    pwa = create_app().test_client()
    with patch("pwa.app.urlopen", side_effect=_pwa_client_to_api(client)):
        login = pwa.post("/api/login", json={"identifier": "test-admin", "password": "Root-Password-123"})
        assert login.status_code == 200, login.json
        headers = {"Authorization": f"Bearer {login.json['access_token']}"}

        churches = pwa.get("/api/admin/churches", headers=headers)
        assert churches.status_code == 200, churches.json
        noms = {c["official_name"] for c in churches.json}
        assert "Eglise Publique" in noms
        assert "Eglise Brouillon" in noms
        assert "Eglise En Attente" in noms

        draft_churches = pwa.get("/api/admin/churches?status=draft", headers=headers)
        assert draft_churches.status_code == 200
        assert all(c["validation_status"] == "draft" for c in draft_churches.json)

        ouest_churches = pwa.get("/api/admin/churches?department=Ouest", headers=headers)
        assert ouest_churches.status_code == 200
        assert all(c["department"] == "Ouest" for c in ouest_churches.json)


def test_admin_superadmin_voit_tous_les_evenements_de_la_base(client, root):
    """L'admin superadmin voit tous les evenements, y compris non publies."""
    base = {"title": "Test Event", "starts_at": "2026-12-01T10:00:00+00:00",
            "location": "Test", "department": "Ouest"}

    client.post("/api/v1/events", headers=root, json={**base, "title": "Evenement Publié",
                "validation_status": "published"})
    client.post("/api/v1/events", headers=root, json={**base, "title": "Evenement Brouillon",
                "validation_status": "draft"})
    client.post("/api/v1/events", headers=root, json={**base, "title": "Evenement En Attente",
                "validation_status": "pending"})

    pwa = create_app().test_client()
    with patch("pwa.app.urlopen", side_effect=_pwa_client_to_api(client)):
        login = pwa.post("/api/login", json={"identifier": "test-admin", "password": "Root-Password-123"})
        assert login.status_code == 200, login.json
        headers = {"Authorization": f"Bearer {login.json['access_token']}"}

        events = pwa.get("/api/admin/events", headers=headers)
        assert events.status_code == 200, events.json
        titres = {e["title"] for e in events.json}
        assert "Evenement Publié" in titres
        assert "Evenement Brouillon" in titres
        assert "Evenement En Attente" in titres


def test_admin_peut_filtrer_eglises_par_statut(client, root):
    """L'admin peut filtrer les eglises par statut de validation."""
    make_church(client, root, official_name="Eglise Publiée", validation_status="published")
    make_church(client, root, official_name="Eglise Archivée", validation_status="archived")

    pwa = create_app().test_client()
    with patch("pwa.app.urlopen", side_effect=_pwa_client_to_api(client)):
        login = pwa.post("/api/login", json={"identifier": "test-admin", "password": "Root-Password-123"})
        assert login.status_code == 200, login.json
        headers = {"Authorization": f"Bearer {login.json['access_token']}"}

        published = pwa.get("/api/admin/churches?status=published", headers=headers)
        assert published.status_code == 200
        assert all(c["validation_status"] == "published" for c in published.json)

        archived = pwa.get("/api/admin/churches?status=archived", headers=headers)
        assert archived.status_code == 200
        assert all(c["validation_status"] == "archived" for c in archived.json)


def test_non_admin_ne_peut_pas_acceder_aux_donnees_admin(client, root):
    """Un compte public (aucune permission) ne peut pas acceder aux endpoints admin churches/events."""
    make_user(client, root, "public@fph.org", "public")

    pwa = create_app().test_client()
    with patch("pwa.app.urlopen", side_effect=_pwa_client_to_api(client)):
        login = pwa.post("/api/login", json={"identifier": "public@fph.org", "password": "Passw0rd-long-1"})
        assert login.status_code == 200, login.json
        headers = {"Authorization": f"Bearer {login.json['access_token']}"}

        churches = pwa.get("/api/admin/churches", headers=headers)
        assert churches.status_code == 403, churches.json

        events = pwa.get("/api/admin/events", headers=headers)
        assert events.status_code == 403, events.json