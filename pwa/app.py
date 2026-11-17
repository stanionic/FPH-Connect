"""Flask entry point for the FPH Connect progressive web app."""

import json
import logging
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from flask import Flask, jsonify, make_response, render_template, request, send_from_directory


BASE_DIR = Path(__file__).resolve().parent
logger = logging.getLogger(__name__)


def create_app() -> Flask:
    app = Flask(__name__, static_folder=str(BASE_DIR / "static"),
                template_folder=str(BASE_DIR / "templates"))
    max_upload_mb = int(os.environ.get("FPH_MAX_UPLOAD_MB", "20"))
    app.config.update(
        API_URL=os.environ.get("FPH_API_URL", "http://127.0.0.1:8000").rstrip("/"),
        PWA_NAME="FPH Connect",
        PWA_THEME_COLOR="#174a7e",
        MAX_UPLOAD_MB=max_upload_mb,
        # Marge pour l'enveloppe multipart au-dessus du fichier lui-même.
        MAX_CONTENT_LENGTH=max_upload_mb * 1024 * 1024 + 1024 * 1024,
    )

    @app.after_request
    def add_response_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-Frame-Options"] = "DENY"
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        elif request.path.startswith("/static/"):
            # Les fichiers de l'interface changent souvent : on laisse le service worker
            # gérer son cache, mais le cache HTTP du navigateur ne doit pas servir une version périmée.
            response.headers["Cache-Control"] = "no-store"
        return response

    def api_request(path: str, method: str = "GET", token: str | None = None,
                    body: dict | None = None, query: dict | None = None):
        url = f"{app.config['API_URL']}{path}"
        if query:
            url = f"{url}?{urlencode(query)}"
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        if data is not None:
            headers["Content-Type"] = "application/json"
        api_request = Request(url, data=data, headers=headers, method=method)
        try:
            with urlopen(api_request, timeout=10) as response:
                payload = response.read()
                try:
                    result = json.loads(payload) if payload else None
                except json.JSONDecodeError:
                    logger.exception("FPH API returned invalid JSON for %s", path)
                    return {"detail": "Le serveur FPH a renvoyé une réponse invalide."}, 502
                return result, response.status
        except HTTPError as error:
            payload = error.read()
            try:
                result = json.loads(payload) if payload else {"detail": "La requête a échoué."}
            except json.JSONDecodeError:
                result = {"detail": "La requête a échoué."}
            return result, error.code
        except (URLError, TimeoutError, OSError):
            logger.exception("FPH API request failed")
            return {"detail": "Le serveur FPH est temporairement indisponible."}, 502

    def api_request_bytes(path: str, token: str | None = None, query: dict | None = None):
        """Comme `api_request`, mais renvoie le corps binaire (documents à imprimer)."""
        url = f"{app.config['API_URL']}{path}"
        if query:
            url = f"{url}?{urlencode(query)}"
        headers = {"Accept": "*/*"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        api_request = Request(url, headers=headers, method="GET")
        try:
            with urlopen(api_request, timeout=30) as response:
                return response.read(), response.status, response.headers.get_content_type()
        except HTTPError as error:
            payload = error.read()
            try:
                result = json.loads(payload) if payload else {"detail": "La requête a échoué."}
            except json.JSONDecodeError:
                result = {"detail": "La requête a échoué."}
            return result, error.code, "application/json"
        except (URLError, TimeoutError, OSError):
            logger.exception("FPH API binary request failed")
            return {"detail": "Le serveur FPH est temporairement indisponible."}, 502, "application/json"

    def api_download(path: str, token: str):
        """Télécharge un fichier de la bibliothèque en conservant ses en-têtes."""
        url = f"{app.config['API_URL']}{path}"
        headers = {"Accept": "*/*", "Authorization": f"Bearer {token}"}
        api_request = Request(url, headers=headers, method="GET")
        try:
            with urlopen(api_request, timeout=60) as response:
                return (response.read(), response.status,
                        response.headers.get("Content-Type", "application/octet-stream"),
                        response.headers.get("Content-Disposition"))
        except HTTPError as error:
            payload = error.read()
            try:
                result = json.loads(payload) if payload else {"detail": "La requête a échoué."}
            except json.JSONDecodeError:
                result = {"detail": "La requête a échoué."}
            return result, error.code, "application/json", None
        except (URLError, TimeoutError, OSError):
            logger.exception("FPH API download failed")
            return ({"detail": "Le serveur FPH est temporairement indisponible."}, 502,
                    "application/json", None)

    def api_upload(path: str, token: str, data: bytes, content_type: str):
        """Transmet un corps multipart tel quel à l'API (partage de fichiers)."""
        url = f"{app.config['API_URL']}{path}"
        headers = {"Accept": "application/json", "Content-Type": content_type,
                   "Authorization": f"Bearer {token}"}
        api_request = Request(url, data=data, headers=headers, method="POST")
        try:
            with urlopen(api_request, timeout=120) as response:
                payload = response.read()
                try:
                    result = json.loads(payload) if payload else None
                except json.JSONDecodeError:
                    result = {"detail": "Le serveur FPH a renvoyé une réponse invalide."}
                return result, response.status
        except HTTPError as error:
            payload = error.read()
            try:
                result = json.loads(payload) if payload else {"detail": "La requête a échoué."}
            except json.JSONDecodeError:
                result = {"detail": "La requête a échoué."}
            return result, error.code
        except (URLError, TimeoutError, OSError):
            logger.exception("FPH API upload failed")
            return {"detail": "Le serveur FPH est temporairement indisponible."}, 502

    def bearer_token():
        authorization = request.headers.get("Authorization", "")
        scheme, separator, token = authorization.partition(" ")
        if separator and scheme.lower() == "bearer" and token.strip():
            return token.strip()
        return None

    def token_required():
        token = bearer_token()
        if not token:
            return None, (jsonify(detail="Authentification requise."), 401)
        return token, None

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/offline")
    def offline():
        return render_template("offline.html")

    @app.get("/manifest.webmanifest")
    def manifest():
        response = jsonify({
            "name": app.config["PWA_NAME"],
            "short_name": "FPH Connect",
            "description": "L'annuaire des églises et les événements de la Fédération Protestante d'Haïti.",
            "start_url": "/",
            "scope": "/",
            "display": "standalone",
            "orientation": "portrait",
            "theme_color": app.config["PWA_THEME_COLOR"],
            "background_color": "#f4f7fb",
            "icons": [
                {
                    "src": "/static/icons/icon-192.png",
                    "sizes": "192x192",
                    "type": "image/png",
                    "purpose": "any",
                },
                {
                    "src": "/static/icons/icon-512.png",
                    "sizes": "512x512",
                    "type": "image/png",
                    "purpose": "any",
                },
                {
                    "src": "/static/icons/apple-touch-icon.png",
                    "sizes": "180x180",
                    "type": "image/png",
                    "purpose": "any",
                },
            ],
        })
        response.headers["Content-Type"] = "application/manifest+json"
        return response

    @app.get("/service-worker.js")
    def service_worker():
        response = make_response(send_from_directory(app.static_folder, "service-worker.js"))
        response.headers["Service-Worker-Allowed"] = "/"
        response.headers["Cache-Control"] = "no-cache"
        return response

    @app.get("/api/config")
    def public_config():
        return jsonify({"name": app.config["PWA_NAME"], "offline_support": True})

    @app.post("/api/login")
    def login():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify(detail="Le corps JSON est requis."), 400
        identifier = body.get("identifier")
        password = body.get("password")
        if not isinstance(identifier, str) or not identifier.strip() or not isinstance(password, str) or not password:
            return jsonify(detail="Identifiant et mot de passe requis."), 400
        result, status = api_request(
            "/api/v1/auth/login",
            method="POST",
            body={"identifier": identifier.strip(), "password": password, "device_label": "FPH Connect PWA"},
        )
        return jsonify(result), status

    @app.get("/api/me")
    def me():
        token, error = token_required()
        if error:
            return error
        result, status = api_request("/api/v1/auth/me", token=token)
        return jsonify(result), status

    @app.post("/api/logout")
    def logout():
        token, error = token_required()
        if error:
            return error
        result, status = api_request("/api/v1/auth/logout", method="POST", token=token)
        return (jsonify(result), status) if result is not None else ("", status)

    @app.post("/api/change-password")
    def change_password():
        token, error = token_required()
        if error:
            return error
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify(detail="Le corps JSON est requis."), 400
        current = body.get("current_password")
        new = body.get("new_password")
        if not isinstance(current, str) or not isinstance(new, str) or not current or not new:
            return jsonify(detail="Les deux mots de passe sont requis."), 400
        result, status = api_request(
            "/api/v1/auth/change-password",
            method="POST",
            token=token,
            body={"current_password": current, "new_password": new},
        )
        return (jsonify(result), status) if result is not None else ("", status)

    @app.get("/api/churches")
    def churches():
        query = {
            key: value for key, value in {
                "q": request.args.get("q", "").strip(),
                "department": request.args.get("department", "").strip(),
                "limit": "100",
            }.items() if value
        }
        result, status = api_request("/api/v1/public/churches", query=query)
        return jsonify(result), status

    @app.get("/api/events")
    def events():
        department = request.args.get("department", "").strip()
        query = {"limit": "100"}
        if department:
            query["department"] = department
        result, status = api_request("/api/v1/public/events", query=query)
        return jsonify(result), status

    @app.get("/api/organizations")
    def organizations():
        token, error = token_required()
        if error:
            return error

        try:
            limit = int(request.args.get("limit", "100"))
            offset = int(request.args.get("offset", "0"))
        except ValueError:
            return jsonify(detail="Les paramètres de pagination doivent être des nombres entiers."), 400
        if not 1 <= limit <= 200 or offset < 0:
            return jsonify(detail="Pagination invalide."), 400

        query = {"limit": str(limit), "offset": str(offset)}
        for key in ("q", "department", "org_type"):
            value = request.args.get(key, "").strip()
            if value:
                query[key] = value
        if len(query.get("q", "")) > 100:
            return jsonify(detail="La recherche ne peut pas dépasser 100 caractères."), 400

        result, status = api_request("/api/v1/organizations", token=token, query=query)
        return jsonify(result), status

    @app.get("/api/admin/users")
    def admin_users():
        token, error = token_required()
        if error:
            return error
        # Note: In a real app, we would verify the role here too, but the backend will check the token.
        result, status = api_request("/api/v1/users", token=token)
        return jsonify(result), status

    @app.get("/api/admin/churches")
    def admin_churches():
        token, error = token_required()
        if error:
            return error
        query = {
            key: value for key, value in {
                "q": request.args.get("q", "").strip(),
                "department": request.args.get("department", "").strip(),
                "status": request.args.get("status", "").strip(),
                "limit": request.args.get("limit", "100"),
                "offset": request.args.get("offset", "0"),
            }.items() if value
        }
        result, status = api_request("/api/v1/churches", token=token, query=query)
        return jsonify(result), status

    @app.get("/api/admin/events")
    def admin_events():
        token, error = token_required()
        if error:
            return error
        query = {
            key: value for key, value in {
                "department": request.args.get("department", "").strip(),
                "status": request.args.get("status", "").strip(),
                "limit": request.args.get("limit", "100"),
                "offset": request.args.get("offset", "0"),
            }.items() if value
        }
        result, status = api_request("/api/v1/events", token=token, query=query)
        return jsonify(result), status

    # ---------------- console d'administration (SuperAdmin) ----------------
    def proxy_json(path: str, method: str = "GET", token: str | None = None,
                   query: dict | None = None, body: dict | None = None):
        result, status = api_request(path, method=method, token=token, query=query, body=body)
        if result is None:
            return ("", status)
        return jsonify(result), status

    def admin_token():
        token, error = token_required()
        return token, error

    def json_body():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return None
        return body

    @app.get("/admin")
    def admin_page():
        return render_template("admin.html")

    @app.get("/api/admin/roles")
    def admin_roles():
        token, error = admin_token()
        if error:
            return error
        return proxy_json("/api/v1/users/roles", token=token)

    @app.get("/api/admin/organizations")
    def admin_organizations():
        token, error = admin_token()
        if error:
            return error
        return proxy_json("/api/v1/organizations", token=token, query={"limit": "200"})

    @app.get("/api/admin/permissions")
    def admin_permissions():
        token, error = admin_token()
        if error:
            return error
        return proxy_json("/api/v1/users/permissions/catalog", token=token)

    # -- utilisateurs --
    @app.post("/api/admin/users")
    def admin_create_user():
        token, error = admin_token()
        if error:
            return error
        body = json_body()
        if body is None:
            return jsonify(detail="Le corps JSON est requis."), 400
        return proxy_json("/api/v1/users", method="POST", token=token, body=body)

    @app.patch("/api/admin/users/<user_id>")
    def admin_update_user(user_id: str):
        token, error = admin_token()
        if error:
            return error
        body = json_body()
        if body is None:
            return jsonify(detail="Le corps JSON est requis."), 400
        return proxy_json(f"/api/v1/users/{user_id}", method="PATCH", token=token, body=body)

    @app.delete("/api/admin/users/<user_id>")
    def admin_archive_user(user_id: str):
        token, error = admin_token()
        if error:
            return error
        return proxy_json(f"/api/v1/users/{user_id}", method="DELETE", token=token)

    @app.post("/api/admin/users/<user_id>/activate")
    def admin_activate_user(user_id: str):
        token, error = admin_token()
        if error:
            return error
        return proxy_json(f"/api/v1/users/{user_id}/activate", method="POST", token=token, body={})

    # -- églises --
    @app.post("/api/admin/churches")
    def admin_create_church():
        token, error = admin_token()
        if error:
            return error
        body = json_body()
        if body is None:
            return jsonify(detail="Le corps JSON est requis."), 400
        return proxy_json("/api/v1/churches", method="POST", token=token, body=body)

    @app.patch("/api/admin/churches/<church_id>")
    def admin_update_church(church_id: str):
        token, error = admin_token()
        if error:
            return error
        body = json_body()
        if body is None:
            return jsonify(detail="Le corps JSON est requis."), 400
        return proxy_json(f"/api/v1/churches/{church_id}", method="PATCH", token=token, body=body)

    @app.post("/api/admin/churches/<church_id>/transition")
    def admin_transition_church(church_id: str):
        token, error = admin_token()
        if error:
            return error
        body = json_body()
        if body is None:
            return jsonify(detail="Le corps JSON est requis."), 400
        return proxy_json(f"/api/v1/churches/{church_id}/transition", method="POST", token=token, body=body)

    # -- événements --
    @app.post("/api/admin/events")
    def admin_create_event():
        token, error = admin_token()
        if error:
            return error
        body = json_body()
        if body is None:
            return jsonify(detail="Le corps JSON est requis."), 400
        return proxy_json("/api/v1/events", method="POST", token=token, body=body)

    @app.patch("/api/admin/events/<event_id>")
    def admin_update_event(event_id: str):
        token, error = admin_token()
        if error:
            return error
        body = json_body()
        if body is None:
            return jsonify(detail="Le corps JSON est requis."), 400
        return proxy_json(f"/api/v1/events/{event_id}", method="PATCH", token=token, body=body)

    @app.post("/api/admin/events/<event_id>/transition")
    def admin_transition_event(event_id: str):
        token, error = admin_token()
        if error:
            return error
        body = json_body()
        if body is None:
            return jsonify(detail="Le corps JSON est requis."), 400
        return proxy_json(f"/api/v1/events/{event_id}/transition", method="POST", token=token, body=body)

    # -- MEOL --
    @app.get("/api/admin/meol")
    def admin_meol():
        token, error = admin_token()
        if error:
            return error
        query = {
            "status": request.args.get("status", "all").strip() or "all",
            "limit": request.args.get("limit", "200"),
        }
        if request.args.get("q", "").strip():
            query["q"] = request.args["q"].strip()
        return proxy_json("/api/v1/meol/pending", token=token, query=query)

    @app.post("/api/admin/meol/register")
    def admin_register_meol():
        body = json_body()
        if body is None:
            return jsonify(detail="Le corps JSON est requis."), 400
        return proxy_json("/api/v1/public/meol/register", method="POST", body=body)

    @app.patch("/api/admin/meol/<oid>")
    def admin_update_meol(oid: str):
        token, error = admin_token()
        if error:
            return error
        body = json_body()
        if body is None:
            return jsonify(detail="Le corps JSON est requis."), 400
        return proxy_json(f"/api/v1/organizations/{oid}", method="PATCH", token=token, body=body)

    @app.post("/api/admin/meol/<oid>/approve")
    def admin_approve_meol(oid: str):
        token, error = admin_token()
        if error:
            return error
        return proxy_json(f"/api/v1/meol/{oid}/approve", method="POST", token=token,
                          body=request.get_json(silent=True) or {})

    @app.post("/api/admin/meol/<oid>/reject")
    def admin_reject_meol(oid: str):
        token, error = admin_token()
        if error:
            return error
        return proxy_json(f"/api/v1/meol/{oid}/reject", method="POST", token=token,
                          body=request.get_json(silent=True) or {})

    @app.post("/api/admin/meol/<oid>/archive")
    def admin_archive_meol(oid: str):
        token, error = admin_token()
        if error:
            return error
        return proxy_json(f"/api/v1/organizations/{oid}/transition", method="POST", token=token,
                          body={"action": "archive"})

    @app.post("/api/admin/meol/<oid>/programs")
    def admin_add_meol_program(oid: str):
        token, error = admin_token()
        if error:
            return error
        body = json_body()
        if body is None:
            return jsonify(detail="Le corps JSON est requis."), 400
        return proxy_json(f"/api/v1/meol/{oid}/programs", method="POST", token=token, body=body)

    # ---------------- impression depuis le dossier connecté ----------------
    @app.get("/impression")
    def print_page():
        return render_template("print.html")

    @app.get("/api/print-folder")
    def print_folder():
        token, error = token_required()
        if error:
            return error
        query = {}
        search = request.args.get("q", "").strip()
        if search:
            query["q"] = search
        return proxy_json("/api/v1/print-folder", token=token, query=query)

    @app.get("/api/print-folder/file")
    def print_folder_file():
        token, error = token_required()
        if error:
            return error
        name = request.args.get("name", "").strip()
        if not name:
            return jsonify(detail="Le nom du document est requis."), 400
        payload, status, content_type = api_request_bytes(
            f"/api/v1/print-folder/{quote(name, safe='')}", token=token)
        if status != 200:
            return jsonify(payload), status
        response = make_response(payload)
        response.headers["Content-Type"] = content_type
        response.headers["Content-Disposition"] = f"inline; filename*=UTF-8''{quote(name)}"
        return response

    @app.post("/api/print-folder/<path:name>/print")
    def print_folder_mark(name: str):
        token, error = token_required()
        if error:
            return error
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            body = {}
        return proxy_json(f"/api/v1/print-folder/{quote(name, safe='')}/print",
                          method="POST", token=token, body=body)

    # ---------------- partage de fichiers sur le réseau FPH ----------------
    @app.get("/partage")
    def documents_page():
        return render_template("documents.html")

    @app.get("/api/documents")
    def documents_list():
        token, error = token_required()
        if error:
            return error
        query = {}
        for key in ("doc_type", "church_id"):
            value = request.args.get(key, "").strip()
            if value:
                query[key] = value
        return proxy_json("/api/v1/documents", token=token, query=query or None)

    @app.post("/api/documents/share")
    def documents_share():
        token, error = token_required()
        if error:
            return error
        content_type = request.content_type or ""
        if not content_type.startswith("multipart/form-data"):
            return jsonify(detail="Un fichier multipart/form-data est requis."), 400
        body = request.get_data(cache=False)
        if not body:
            return jsonify(detail="Le fichier est requis."), 400
        return api_upload("/api/v1/documents/share", token, body, content_type)

    @app.get("/api/documents/<doc_id>/download")
    def documents_download(doc_id: str):
        token, error = token_required()
        if error:
            return error
        payload, status, content_type, disposition = api_download(
            f"/api/v1/documents/{quote(doc_id, safe='')}/download", token)
        if status != 200:
            return jsonify(payload), status
        response = make_response(payload)
        response.headers["Content-Type"] = content_type
        if disposition:
            response.headers["Content-Disposition"] = disposition
        return response

    @app.delete("/api/documents/<doc_id>")
    def documents_unshare(doc_id: str):
        token, error = token_required()
        if error:
            return error
        return proxy_json(f"/api/v1/documents/{quote(doc_id, safe='')}",
                          method="DELETE", token=token)

    @app.errorhandler(404)
    def not_found(_error):
        return render_template("404.html"), 404

    @app.errorhandler(413)
    def request_too_large(_error):
        return jsonify(detail=f"Fichier trop volumineux (max {app.config['MAX_UPLOAD_MB']} Mo)."), 413

    return app


app = create_app()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    debug = os.environ.get("FLASK_DEBUG") == "1"
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=debug)
