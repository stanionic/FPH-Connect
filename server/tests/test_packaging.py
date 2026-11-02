"""Auto-tests embarqués (utilisés aussi pour contrôler les exécutables construits avec PyInstaller)."""
import importlib.util
import os
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))


def test_agent_selftest_runs_and_checks_its_refusals():
    r = subprocess.run([sys.executable, "-m", "fph_agent", "--selftest"], cwd=os.path.join(ROOT, "agent"),
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and "AGENT SELFTEST OK" in r.stdout, r.stdout + r.stderr


def test_agent_without_configuration_prints_usage_and_exits_2():
    r = subprocess.run([sys.executable, "-m", "fph_agent"], cwd=os.path.join(ROOT, "agent"), capture_output=True, text=True, timeout=60,
                       env={k: v for k, v in os.environ.items() if not k.startswith("FPH_")})
    assert r.returncode == 2 and "FPH_AGENT_SHARE" in r.stdout


@pytest.mark.skipif(importlib.util.find_spec("kivy") is None or shutil.which("xvfb-run") is None, reason="Kivy et xvfb-run requis")
def test_client_selftest_from_source_and_it_can_fail(tmp_path):
    cmd = ["xvfb-run", "-a", sys.executable, os.path.join(ROOT, "client", "main.py"), "--selftest", str(tmp_path / "s.png")]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0 and "SELFTEST OK" in r.stdout, r.stdout[-1500:]
    assert any(f.endswith(".png") and os.path.getsize(tmp_path / f) > 2000 for f in os.listdir(tmp_path))
    # un auto-test qui ne peut jamais échouer ne prouve rien : on casse une traduction et il doit le détecter
    broken = tmp_path / "client"
    shutil.copytree(os.path.join(ROOT, "client"), broken, ignore=shutil.ignore_patterns("__pycache__", "tests"))
    i18n = broken / "fph_client" / "i18n.py"
    i18n.write_text(i18n.read_text().replace('"sign_in": "Antre"', '"sign_in": "CASSE"', 1))
    r2 = subprocess.run(["xvfb-run", "-a", sys.executable, str(broken / "main.py"), "--selftest"], capture_output=True, text=True, timeout=120)
    assert r2.returncode == 1 and "SELFTEST ÉCHEC" in r2.stdout and "Antre" in r2.stdout


def test_build_script_has_help_and_refuses_unknown_target():
    ok = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "build_executables.py"), "--help"], capture_output=True, text=True, timeout=60)
    assert ok.returncode == 0 and "PyInstaller" in ok.stdout
    bad = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "build_executables.py"), "--target", "autre"], capture_output=True, text=True, timeout=60)
    assert bad.returncode == 2
