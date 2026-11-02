# FPH Connect — prototype v0.1

Serveur FastAPI + client Kivy pour la Fédération Protestante d'Haïti. Voir `docs/`.

## Lancer les tests
    cd server && pip install -r requirements.txt && python -m pytest tests -q

## Lancer le serveur (dev, SQLite)
    cd server
    export FPH_BOOTSTRAP_ADMIN_USERNAME=Admin
    export FPH_BOOTSTRAP_ADMIN_PASSWORD='<à saisir, jamais dans un fichier>'
    alembic upgrade head
    uvicorn app.main:app --reload     # docs OpenAPI : http://127.0.0.1:8000/docs
    python -m app.discovery           # (autre terminal) annonce le serveur sur le réseau local
    # HTTPS : voir docs/TLS_GUIDE.md (scripts/make_lan_certs.py, FPH_TLS_CERT / FPH_TLS_KEY, python -m app.serve)

## Production
    cp .env.example .env   # remplir les secrets
    docker compose up -d   # puis placer un proxy HTTPS devant

## Construire les exécutables
    pip install pyinstaller && python scripts/build_executables.py --target all --out dist   # voir docs/BUILD_GUIDE.md

## Vérifier l'interface (Linux)
    pip install -r client/requirements.txt && xvfb-run -a python scripts/ui_check.py captures/
    # pilote l'application réelle avec un vrai serveur en mémoire et enregistre des captures d'écran

## Client
    cd client && pip install -r requirements.txt && FPH_API_URL=http://127.0.0.1:8000 python main.py

## Connecteurs site web
Voir `docs/WEBSITE_GUIDE.md` (WordPress puis Flask) et `docs/WEB_CONNECTOR_PROTOCOL.md`.
Worker d'envoi : `python -m app.worker`.

## Réseau local et documents
Voir `docs/LAN_GUIDE.md` et `docs/DOCUMENTS_GUIDE.md`. Vérification : `scripts/lan_smoke_test.py`.

## Base institutionnelle
Voir `docs/INSTITUTIONAL_DATA.md` (qui voit quoi, minimisation, règles métier).

## Impression réseau
Voir `docs/PRINTING_GUIDE.md`. Agent : `agent/` (`python -m fph_agent`).

## Chiffrement
Voir `docs/TLS_GUIDE.md`. En production le serveur refuse de démarrer sans TLS.
