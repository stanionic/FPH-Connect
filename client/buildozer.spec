[app]
title = FPH Connect
package.name = fphconnect
package.domain = org.fph
source.dir = .
source.include_exts = py,png,jpg,kv,atlas
source.include_patterns = assets/*
icon.filename = assets/logo-fph.png
presplash.filename = assets/logo-fph.png
version = 0.1.0
requirements = python3,kivy,httpx,httpcore,h11,anyio,sniffio,idna,certifi
orientation = portrait
android.permissions = INTERNET,ACCESS_NETWORK_STATE
android.api = 34
android.minapi = 24
# Non vérifié : la compilation Android n'a pas été exécutée (voir docs/LIMITATIONS.md)
