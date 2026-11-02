# Matrice de compatibilité (preuves)

| Composant | Linux (dev) | Windows | Android | Preuve |
|---|---|---|---|---|
| Serveur FastAPI + SQLite | Testé (137 tests) | **Testé** (128 passent, 7 échouent : voir « Échecs attendus sous Windows ») | n/a | pytest |
| Serveur réel (uvicorn) + découverte UDP | Testé en boucle locale | Non testé | n/a | scripts/lan_smoke_test.py |
| Plusieurs machines réelles sur un LAN | **Non testé** | Non testé | Non testé | — |
| Migrations 0001-0005 | Testées sur SQLite | Non testé | n/a | alembic upgrade/downgrade/check |
| PostgreSQL / Docker | Non testé | Non testé | n/a | — |
| Récepteur Flask | Testé (en mémoire) | Non testé | n/a | pytest |
| Plugin WordPress (événements, inscriptions) | **Non testé** (PHP absent, syntaxe non validée) | Non testé | n/a | — |
| Client : files hors ligne, sync (sans UI) | Testé | Partiellement (test exécuté ici ; seule l'assertion `0600` est propre à POSIX) | Non testé | pytest |
| Inscription signée site → FPH (HTTP réel) | Testé en boucle locale | Non testé | n/a | scripts/lan_smoke_test.py |
| TLS : certificats, vérification, refus HTTP clair / autorité inconnue / mauvais nom | Testé en boucle locale (pytest + serveur réel + curl) | Partiellement (pytest exécuté ici ; deux assertions POSIX, serveur réel non testé) | Non testé | pytest, scripts/lan_smoke_test.py |
| Proxy TLS (nginx/Caddy) | Non testé | Non testé | n/a | — |
| Interface Kivy (écrans, clics, langue, hors ligne, registre MEOL) | **Testée en fenêtre virtuelle** (47 contrôles + captures) | Non testé | **Non testé** | scripts/ui_check.py, pytest |
| Serveur d'impression + agent (imprimante virtuelle « fichier ») | Testé (pytest + serveur réel) | Non testé | n/a | pytest, scripts/lan_smoke_test.py |
| Backend CUPS (`lp`/`lpstat`/`cancel`) | **Faux exécutables seulement** ; vrai CUPS non testé | n/a | n/a | pytest |
| Backend Windows (SumatraPDF) | n/a | **Non testé** (commande simulée) | n/a | pytest |
| Reprise d'un registre externe (PDF MEOL → base) | Non testé | **Testé** : 308 entrées lues = 308 annoncées, 307 organisations et 553 responsables écrits, relance idempotente (0 créée) | n/a | scripts/import_meols.py, docs/MEOL_COMPARE.md, docs/MEOL_A_VERIFIER.md |
| Impression depuis Android / intégration système | Non implémenté | Non implémenté | Non implémenté | — |
| Exécutable client (PyInstaller) + auto-test | **Construit et démarré** (Ubuntu 24.04, ≈105 Mo) | **Jamais construit** | n/a | scripts/build_executables.py |
| Exécutable agent d'impression (PyInstaller) + auto-test | **Construit et démarré** (≈37 Mo) | **Jamais construit** | n/a | scripts/build_executables.py |
| APK Android (Buildozer) | n/a | n/a | **Jamais construit** | — |

## Échecs attendus sous Windows

`cd server; python -m pytest -q` sur cette machine (Windows 22H2, NTFS, console cp437/cp1252) donne
**7 échecs sur 137**. Aucun ne porte sur la logique métier : ce sont des assertions qui décrivent un
environnement POSIX, ou qui dépendent de l'encodage de la console.

| Test | Ce qu'il affirme | Pourquoi il échoue ici |
|---|---|---|
| `test_agent.py` × 3 (`test_cups_*`) | le backend CUPS parle à `lp`/`lpstat`/`cancel` | ces commandes sont des scripts shell : `OSError [WinError 193]`, CUPS n'existe pas sur Windows |
| `test_client_lan.py::test_full_lan_flow_with_offline_queues` | le fichier-jeton est en `0600` | NTFS ne porte pas les bits POSIX : `st_mode` rend `0666` (`assert 438 == 384`) |
| `test_tls.py::test_private_keys_are_not_readable_by_others` | les clés privées sont en `0600` | même raison |
| `test_tls.py::test_dev_mode_warns_about_plain_http_...` | l'avertissement « chmod 600 » est émis | `serve.py` ne le produit que si `os.name == "posix"` : la vérification est volontairement désactivée ici |
| `test_packaging.py::test_build_script_has_help_...` | lire la sortie `--help` du script de build | `subprocess(text=True)` décode avec la page de codes du système ; la sortie contient des accents français. Passe avec `PYTHONIOENCODING=utf-8` |

**À lire avant d'utiliser ces résultats** : un échec attendu ici n'est pas une preuve de bon
fonctionnement sur Windows. Les deux tests `0600` disent seulement que **l'exigence de permission n'est
pas appliquée sur NTFS** — la protection réelle des jetons et des clés sur cette plateforme n'est pas
démontrée. Le comportement validé reste celui de Linux ; voir docs/LIMITATIONS.md.
