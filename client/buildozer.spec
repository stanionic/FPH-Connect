[app]
title = FPH Connect
package.name = fphconnect
package.domain = org.fph
source.dir = .
source.include_exts = py,png,jpg,kv,atlas
source.include_patterns = assets/*
icon.filename = assets/logo-fph.png
presplash.filename = assets/logo-fph.png
version = 0.2.0
requirements = python3,kivy,httpx,httpcore,h11,anyio,sniffio,idna,certifi
orientation = portrait
android.permissions = INTERNET,ACCESS_NETWORK_STATE
android.api = 34
android.minapi = 24
# Ligne beta : APK de debug construit par .github/workflows/android-build.yml (runner Linux).
# La compilation Android n'avait jamais ete executee ; ce workflow est la premiere tentative (voir docs/LIMITATIONS.md).
