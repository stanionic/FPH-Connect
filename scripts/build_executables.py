#!/usr/bin/env python3
"""Construit les exécutables FPH Connect avec PyInstaller, puis LES FAIT DÉMARRER en mode auto-test.

  python scripts/build_executables.py --target all --out dist

  client : dossier autonome  dist/FPHConnect/FPHConnect[.exe]   (interface Kivy)
  agent  : fichier unique    dist/fph-agent[.exe]               (agent d'impression)

IMPORTANT : un exécutable se construit SUR le système où il servira (Linux -> Linux, Windows -> .exe).
PyInstaller ne compile pas en croisé. Android = autre chaîne (Buildozer), voir docs/BUILD_GUIDE.md.
Prérequis : pip install pyinstaller kivy httpx   (Windows : pip install kivy_deps.sdl2 kivy_deps.glew)
Sous Linux sans écran, le contrôle du client utilise xvfb-run s'il est installé.
"""
import argparse
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXE = ".exe" if os.name == "nt" else ""


def run(cmd, **kw):
    print("  $", " ".join(cmd), flush=True)
    return subprocess.run(cmd, **kw)


def pyinstaller(args, workdir):
    return run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--log-level", "WARN", *args], cwd=workdir)


def build_client(out: str, work: str) -> str:
    r = pyinstaller(["--distpath", out, "--workpath", os.path.join(work, "client"), os.path.join(ROOT, "client", "fph_connect.spec")], ROOT)
    if r.returncode != 0:
        sys.exit("ÉCHEC de la construction du client")
    return os.path.join(out, "FPHConnect", "FPHConnect" + EXE)


def build_agent(out: str, work: str) -> str:
    r = pyinstaller(["--onefile", "--name", "fph-agent", "--distpath", out, "--workpath", os.path.join(work, "agent"),
                     "--specpath", work, "--paths", os.path.join(ROOT, "agent"), os.path.join(ROOT, "agent", "run_agent.py")], ROOT)
    if r.returncode != 0:
        sys.exit("ÉCHEC de la construction de l'agent")
    return os.path.join(out, "fph-agent" + EXE)


def check(label: str, cmd, expect: str, timeout: int = 120) -> bool:
    """Lance l'exécutable construit et exige un code de sortie 0 ET la phrase attendue."""
    if os.name != "nt" and "DISPLAY" not in os.environ and label.startswith("client") and shutil.which("xvfb-run"):
        cmd = ["xvfb-run", "-a", *cmd]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    ok = r.returncode == 0 and expect in r.stdout
    print(f"  {'OK   ' if ok else 'ÉCHEC'} contrôle {label} : code={r.returncode}, "
          f"{'« ' + expect + ' » trouvé' if expect in r.stdout else 'phrase attendue absente'}")
    if not ok:
        print((r.stdout + r.stderr)[-1500:])
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--target", choices=("client", "agent", "all"), default="all")
    ap.add_argument("--out", default="dist")
    a = ap.parse_args()
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller est absent : pip install pyinstaller")
        return 2
    out, work = os.path.abspath(a.out), os.path.abspath(os.path.join(a.out, "_build"))
    os.makedirs(out, exist_ok=True)
    ok = True
    if a.target in ("client", "all"):
        exe = build_client(out, work)
        seen, size = set(), 0
        for d, _, fs in os.walk(os.path.dirname(exe)):
            for f in fs:
                st = os.lstat(os.path.join(d, f))
                if not os.path.islink(os.path.join(d, f)) and (st.st_dev, st.st_ino) not in seen:
                    seen.add((st.st_dev, st.st_ino))
                    size += st.st_size
        size /= 1e6
        print(f"  client construit : {exe} ({size:.0f} Mo, dossier complet)")
        ok &= check("client (--selftest)", [exe, "--selftest", os.path.join(out, "selftest.png")], "SELFTEST OK")
    if a.target in ("agent", "all"):
        exe = build_agent(out, work)
        print(f"  agent construit : {exe} ({os.path.getsize(exe) / 1e6:.0f} Mo)")
        ok &= check("agent (--selftest)", [exe, "--selftest"], "AGENT SELFTEST OK")
    print("\nRÉSULTAT :", "exécutables construits ET vérifiés" if ok else "ÉCHEC d'un contrôle")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
