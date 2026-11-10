"""Release checks, opt-in via RIVENSCOPE_PACKAGING=1 after build tools are installed."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile

ROOT=Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.getenv("RIVENSCOPE_PACKAGING")=="1","Opt-in packaging tests: set RIVENSCOPE_PACKAGING=1")
class PackagingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        subprocess.run([str(ROOT/".venv/bin/python"),"tools/build_release.py"],cwd=ROOT,check=True,capture_output=True,text=True)
        cls.wheel=ROOT/"dist/rivenscope-0.1.0-py3-none-any.whl"

    def test_reproducible_artifacts(self):
        before=(ROOT/"dist/SHA256SUMS").read_text()
        subprocess.run([str(ROOT/".venv/bin/python"),"tools/build_release.py"],cwd=ROOT,check=True,capture_output=True,text=True)
        self.assertEqual(before,(ROOT/"dist/SHA256SUMS").read_text())

    def test_wheel_has_no_synthetic_data_and_includes_docs(self):
        with zipfile.ZipFile(self.wheel) as archive:
            names=archive.namelist()
            self.assertIn("rivenscope/assets/rivenscope.svg",names)
            self.assertTrue(any(name.endswith("docs/API_FEASIBILITY.md") for name in names))
            self.assertFalse(any("fixtures" in name or name.endswith(".sqlite") or "tests/" in name for name in names))

    def test_install_upgrade_launch_and_uninstall_preserve_data(self):
        with tempfile.TemporaryDirectory(prefix="rivenscope-package-",dir="/tmp/opencode") as directory:
            home=Path(directory)/"home with spaces"; home.mkdir()
            command=["python","tools/install.py","--wheel",str(self.wheel),"--home",str(home)]
            subprocess.run(command,cwd=ROOT,check=True,capture_output=True,text=True,timeout=30)
            launcher=home/".local/bin/rivenscope"
            result=subprocess.run([str(launcher),"--version"],check=True,capture_output=True,text=True)
            self.assertEqual(result.stdout.strip(),"0.1.0")
            data=home/".local/share/rivenscope"; data.mkdir(); sentinel=data/"keep.txt"; sentinel.write_text("user data")
            subprocess.run(command,cwd=ROOT,check=True,capture_output=True,text=True,timeout=30)
            self.assertTrue((home/".local/share/rivenscope-app/previous").is_symlink())
            subprocess.run([str(launcher),"--data-dir",str(home/"test-profile"),"--smoke-seconds","1"],env=os.environ|{"QT_QPA_PLATFORM":"offscreen"},check=True,timeout=20)
            subprocess.run(["python","tools/uninstall.py","--home",str(home)],cwd=ROOT,check=True,capture_output=True,text=True)
            self.assertFalse(launcher.exists()); self.assertEqual(sentinel.read_text(),"user data")

    def test_unmanaged_collision_is_preserved(self):
        with tempfile.TemporaryDirectory(prefix="rivenscope-collision-",dir="/tmp/opencode") as directory:
            home=Path(directory); binary=home/".local/bin/rivenscope"; binary.parent.mkdir(parents=True); binary.write_text("unrelated user file")
            result=subprocess.run(["python","tools/install.py","--home",str(home)],cwd=ROOT,capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0); self.assertEqual(binary.read_text(),"unrelated user file")
