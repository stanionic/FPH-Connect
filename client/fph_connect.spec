# -*- mode: python ; coding: utf-8 -*-
# Description PyInstaller du client FPH Connect (dossier autonome). Utilisée par scripts/build_executables.py.
# Un exécutable se construit SUR le système cible : Linux -> binaire Linux, Windows -> .exe (PyInstaller ne compile pas en croisé).
import os

from kivy.tools.packaging.pyinstaller_hooks import get_deps_minimal, hookspath, runtime_hooks

here = os.path.abspath(SPECPATH)

# Windows seulement : bibliothèques SDL2 / GLEW fournies par les paquets kivy_deps (absents sous Linux)
extra_trees = []
try:
    from kivy_deps import glew, sdl2
    extra_trees = [Tree(p) for p in sdl2.dep_bins + glew.dep_bins]
except ImportError:
    pass

# Strict nécessaire : fenêtre, texte, images, presse-papiers. Sans audio/vidéo/caméra/orthographe
# (get_deps_all() embarquait tout GStreamer : 557 Mo). numpy et Pillow ne sont pas utilisés par l'application
# (Kivy lit les images avec SDL2) mais s'invitaient dans le paquet s'ils étaient installés : exclus.
deps = get_deps_minimal(video=None, audio=None, camera=None, spelling=None)
deps["excludes"] = list(deps.get("excludes", [])) + ["numpy", "PIL", "matplotlib", "scipy", "pandas"]

# Le logo (client/assets) doit voyager dans le dossier construit : main.py le cherche dans sys._MEIPASS/assets.
datas = []
if os.path.isdir(os.path.join(here, "assets")):
    datas.append((os.path.join(here, "assets"), "assets"))

a = Analysis([os.path.join(here, "main.py")], pathex=[here], datas=datas, hookspath=hookspath(),
             runtime_hooks=runtime_hooks(), noarchive=False, **deps)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="FPHConnect",
          console=True,        # garde la sortie texte (journal, --selftest) ; passer à False pour un lancement sans fenêtre noire
          upx=False)
coll = COLLECT(exe, a.binaries, a.datas, *extra_trees, strip=False, upx=False, name="FPHConnect")
