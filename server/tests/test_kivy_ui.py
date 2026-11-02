"""Pilote l'application Kivy RÉELLE dans une fenêtre virtuelle (voir scripts/ui_check.py).
Ignoré si Kivy ou xvfb-run sont absents (ex. Windows, intégration continue minimale)."""
import importlib.util
import os
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("kivy") is None or shutil.which("xvfb-run") is None,
    reason="Kivy et xvfb-run requis pour piloter l'interface réelle")


def test_real_kivy_app_end_to_end(tmp_path):
    r = subprocess.run(["xvfb-run", "-a", sys.executable, os.path.join(ROOT, "scripts", "ui_check.py"), str(tmp_path / "captures")],
                       capture_output=True, text=True, timeout=240)
    out = r.stdout
    assert "TOUT EST OK" in out, out[-3000:]
    assert r.returncode == 0
    assert out.count("  OK ") >= 35 and "ÉCHEC" not in out
    shots = sorted(os.listdir(tmp_path / "captures"))
    assert len(shots) >= 10 and all(f.endswith(".png") for f in shots)
    assert all(os.path.getsize(tmp_path / "captures" / f) > 2000 for f in shots)   # pas de captures vides
