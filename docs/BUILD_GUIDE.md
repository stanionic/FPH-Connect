# Guide de construction des exécutables

Un exécutable se construit **sur le système où il servira** (PyInstaller ne compile pas en croisé). Tout passe par un seul script,
qui construit puis **fait démarrer le résultat en mode auto-test** : on ne livre rien qui n'ait pas démarré.

    pip install pyinstaller kivy httpx
    python scripts/build_executables.py --target all --out dist

| Résultat | Contenu |
|---|---|
| `dist/FPHConnect/FPHConnect` | client (interface Kivy), dossier autonome à copier en entier |
| `dist/fph-agent` | agent d'impression, fichier unique |

Contrôle manuel : `FPHConnect --selftest [capture.png]` (affiche l'interface sans réseau, teste les 3 langues, quitte avec le code 0 si tout va bien)
et `fph-agent --selftest`. Sans configuration, `fph-agent` affiche son mode d'emploi et quitte avec le code 2.

## Ce qui a été fait et vérifié
- **Linux (Ubuntu 24.04, construit ici)** : client et agent construits ; les deux auto-tests réussissent, y compris lancés **depuis un autre
  dossier, dans un environnement vide** (le client utilise sa propre copie de Kivy). Taille : client ≈ 105 Mo (dossier), agent ≈ 37 Mo.
  Le premier essai faisait 557 Mo (tout Kivy, dont GStreamer) : réduit en ne gardant que fenêtre/texte/images/presse-papiers et en excluant
  numpy et Pillow, inutiles. Ces binaires **ne sont pas fournis dans l'archive** (ils dépendent de la version de glibc de la machine de
  construction : construire sur la plus ancienne distribution Linux à prendre en charge).

## Ce qui N'A PAS été fait
- **Windows (.exe)** : même script, à lancer **sous Windows** après `pip install kivy_deps.sdl2 kivy_deps.glew`. **Jamais essayé.** À prévoir :
  les `.exe` non signés déclenchent souvent SmartScreen ou des antivirus (faux positifs) ; aucune signature de code n'est faite. L'agent comme
  service Windows (NSSM, planificateur de tâches) et l'impression via SumatraPDF n'ont pas été testés.
- **Android (APK)** : `client/buildozer.spec` existe mais **n'a jamais été exécuté** (il faut Linux et des gigaoctets de SDK/NDK Android, non
  téléchargeables dans l'environnement de développement). Problèmes déjà identifiés, non résolus :
  le sélecteur de fichiers part de `~`, qui n'est pas accessible tel quel sous Android (stockage partagé et autorisations) ; la variable
  `FPH_CA_CERT` n'existe pas sur téléphone (il faut embarquer ou choisir `ca.pem`) ; aucune intégration au service d'impression Android ;
  la compatibilité des recettes python-for-android avec `httpx`/`anyio` n'est pas vérifiée.
- **macOS, iOS** : non tentés.
- Pas de **mise à jour automatique**, pas d'installateur (MSI, .deb), pas de signature.
