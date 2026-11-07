"""Flask entry point for the FPH Connect progressive web app."""

import json
import logging
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from flask import Flask, jsonify, make_response, render_template, request, send_from_directory


BASE_DIR = Path(__file__).resolve().parent
logger = logging.getLogger(__name__)


def create_app() -> Flask:
    app = Flask(__name__, static_folder=str(BASE_DIR / "static"),
                template_folder=str(BASE_DIR / "templates"))
    app.config.update(
        API_URL=os.environ.get("FPH_API_URL", "http://127.0.0.1:8000").rstrip("/"),
        PWA_NAME="FPH Connect",
        PWA_THEME_COLOR="#174a7e",
        MAX_CONTENT_LENGTH=16 * 1024,
    )

    @app.after_request
    def add_response_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-Frame-Options"] = "DENY"
        if request.path.startswith("/api/"):
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
                return (json.loads(payload) if payload else None), response.status
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
            "icons": [{
                "src": "/static/icons/icon.svg",
                "sizes": "any",
                "type": "image/svg+xml",
                "purpose": "any maskable",
            }],
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
        body = request.get_json()
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
        body = request.get_json()
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

    @app.errorhandler(404)
    def not_found(_error):
        return render_template("404.html"), 404

    @app.errorhandler(413)
    def request_too_large(_error):
        return jsonify(detail="La requête est trop volumineuse."), 413

    return app


app = create_app()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=False)
