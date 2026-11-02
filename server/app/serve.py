"""Lanceur du serveur : python -m app.serve

TLS : FPH_TLS_CERT + FPH_TLS_KEY (ensemble). En production (FPH_ENV=prod), le serveur REFUSE de
démarrer sans TLS, sauf si un proxy TLS est placé devant et que FPH_BEHIND_TLS_PROXY=1 le déclare.
"""
import os
import sys


def plan(env: dict) -> tuple[dict, list[str]]:
    """Retourne (options uvicorn, avertissements) ou lève SystemExit avec un message clair."""
    cert, key = env.get("FPH_TLS_CERT"), env.get("FPH_TLS_KEY")
    warnings: list[str] = []
    kw = {"host": env.get("FPH_HOST", "0.0.0.0"), "port": int(env.get("FPH_API_PORT", "8000"))}
    if bool(cert) != bool(key):
        raise SystemExit("FPH_TLS_CERT et FPH_TLS_KEY doivent être définis ENSEMBLE")
    if cert:
        for label, path in (("certificat", cert), ("clé privée", key)):
            if not os.path.isfile(path):
                raise SystemExit(f"Fichier introuvable ({label}) : {path}")
        if os.name == "posix" and os.stat(key).st_mode & 0o077:
            warnings.append(f"La clé privée {key} est lisible par d'autres utilisateurs : chmod 600")
        kw.update(ssl_certfile=cert, ssl_keyfile=key)
    elif env.get("FPH_BEHIND_TLS_PROXY") == "1":
        # Le proxy chiffre le trafic des postes ; reste à empêcher de le CONTOURNER en parlant directement au serveur.
        if kw["host"] not in ("127.0.0.1", "::1", "localhost"):
            warnings.append("Proxy TLS déclaré mais le serveur écoute sur toutes les interfaces : il peut être joint en "
                            "HTTP clair sans passer par le proxy. Utiliser FPH_HOST=127.0.0.1 (ou, sous Docker, ne publier "
                            "le port que sur 127.0.0.1)")
    elif env.get("FPH_ENV") == "prod":
        raise SystemExit("Production sans TLS refusée : définir FPH_TLS_CERT/FPH_TLS_KEY, ou placer un proxy TLS "
                         "devant et déclarer FPH_BEHIND_TLS_PROXY=1 (voir docs/TLS_GUIDE.md)")
    else:
        warnings.append("HTTP non chiffré : mots de passe, messages et documents circulent en clair sur le réseau")
    return kw, warnings


def main() -> None:
    kw, warnings = plan(dict(os.environ))
    for w in warnings:
        print(f"AVERTISSEMENT : {w}", file=sys.stderr, flush=True)
    import uvicorn
    uvicorn.run("app.main:app", **kw)


if __name__ == "__main__":
    main()
