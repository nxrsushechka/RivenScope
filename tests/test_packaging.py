"""Opt-in clean-source release/install tests; no prebuilt artifacts are required."""
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile

from rivenscope import __version__
from rivenscope.storage import Store, new_watchlist

ROOT = Path(__file__).resolve().parents[1]


def run(*args, **kwargs):
    result = subprocess.run(*args, capture_output=True, text=True, timeout=60, **kwargs)
    if result.returncode:
        raise AssertionError(f"Command failed ({result.returncode}): {args[0]}\n{result.stdout}\n{result.stderr}")
    return result


@unittest.skipUnless(os.getenv("RIVENSCOPE_PACKAGING") == "1", "Opt-in packaging tests: set RIVENSCOPE_PACKAGING=1")
class PackagingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="rivenscope-release-")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.dist = Path(cls.temp.name) / "dist"
        cls.build(cls.dist)
        cls.wheel = cls.dist / f"rivenscope-{__version__}-py3-none-any.whl"

    @classmethod
    def build(cls, destination, root=ROOT):
        run([sys.executable, str(root / "tools/build_release.py"), "--output-dir", str(destination)], cwd=root)

    def test_reproducible_artifacts(self):
        before = (self.dist / "SHA256SUMS").read_text()
        self.build(self.dist)
        self.assertEqual(before, (self.dist / "SHA256SUMS").read_text())

    def test_wheel_has_full_source_no_synthetic_data_and_includes_docs(self):
        with zipfile.ZipFile(self.wheel) as archive:
            names = archive.namelist()
            for path in (ROOT / "src/rivenscope").rglob("*"):
                if path.is_file() and "__pycache__" not in path.parts:
                    name = "rivenscope/" + path.relative_to(ROOT / "src/rivenscope").as_posix()
                    self.assertIn(name, names)
                    self.assertEqual(path.read_bytes(), archive.read(name))
            self.assertTrue(any(name.endswith("docs/API_FEASIBILITY.md") for name in names))
            self.assertFalse(any("fixtures" in name or name.endswith((".sqlite", ".pyc")) or "tests/" in name for name in names))

    def test_source_archive_rebuild_ignores_stale_build_output(self):
        with tempfile.TemporaryDirectory(prefix="rivenscope-clean-source-") as directory:
            source = self.dist / f"rivenscope-{__version__}-source.tar.gz"
            with tarfile.open(source) as archive:
                archive.extractall(directory, filter="data")
            root = Path(directory) / f"rivenscope-{__version__}"
            self.assertFalse((root / "dist").exists())
            stale = root / "build/lib/rivenscope/deleted_module.py"
            stale.parent.mkdir(parents=True)
            stale.write_text("raise RuntimeError('stale build leaked')\n")
            output = Path(directory) / "rebuilt"
            self.build(output, root)
            with zipfile.ZipFile(output / self.wheel.name) as wheel:
                self.assertNotIn("rivenscope/deleted_module.py", wheel.namelist())
            self.assertEqual((self.dist / "SHA256SUMS").read_text(), (output / "SHA256SUMS").read_text())

    def test_install_upgrade_launch_and_uninstall_preserve_data(self):
        with tempfile.TemporaryDirectory(prefix="rivenscope-package-") as directory:
            home = Path(directory) / "home with spaces"
            home.mkdir()
            command = [sys.executable, "tools/install.py", "--wheel", str(self.wheel), "--home", str(home)]
            run(command, cwd=ROOT)
            launcher = home / ".local/bin/rivenscope"
            self.assertEqual(run([str(launcher), "--version"]).stdout.strip(), __version__)
            data = home / ".local/share/rivenscope"
            data.mkdir(parents=True, exist_ok=True)
            sentinel = data / "keep.txt"
            sentinel.write_text("user data")
            run(command, cwd=ROOT)
            self.assertFalse((home / ".local/share/rivenscope-app/previous").exists())
            # Explicit profile must not attempt to create the default XDG paths.
            blocked = Path(directory) / "not-a-directory"
            blocked.write_text("do not touch")
            runtime = os.environ | {"QT_QPA_PLATFORM": "offscreen", "XDG_DATA_HOME": str(blocked)}
            run([str(launcher), "--data-dir", str(home / "test-profile"), "--smoke-seconds", "1"], env=runtime)
            self.assertTrue((home / "test-profile/data/rivenscope.sqlite").is_file())
            run([sys.executable, "tools/uninstall.py", "--home", str(home)], cwd=ROOT)
            self.assertFalse(launcher.exists())
            self.assertEqual(sentinel.read_text(), "user data")

    def test_unmanaged_collision_is_preserved(self):
        with tempfile.TemporaryDirectory(prefix="rivenscope-collision-") as directory:
            home = Path(directory)
            binary = home / ".local/bin/rivenscope"
            binary.parent.mkdir(parents=True)
            binary.write_text("unrelated user file")
            result = subprocess.run([sys.executable, "tools/install.py", "--wheel", str(self.wheel), "--home", str(home)],
                                    cwd=ROOT, capture_output=True, text=True, timeout=30)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(binary.read_text(), "unrelated user file")

    def test_version_upgrade_and_reinstall_keep_previous_release_and_database(self):
        with tempfile.TemporaryDirectory(prefix="rivenscope-upgrade-") as directory:
            root=Path(directory)
            with tarfile.open(self.dist/f"rivenscope-{__version__}-source.tar.gz") as archive:
                archive.extractall(root,filter="data")
            source=root/f"rivenscope-{__version__}"
            # Controlled prior-version fixture, not a claim to reproduce old code.
            for path in (source/"pyproject.toml",source/"src/rivenscope/__init__.py"):
                path.write_text(path.read_text().replace(f'"{__version__}"','"0.0.0"'))
            old_dist=root/"old-dist"
            self.build(old_dist,source)
            home=root/"home"
            old_wheel=old_dist/"rivenscope-0.0.0-py3-none-any.whl"
            base=[sys.executable,"tools/install.py","--home",str(home),"--wheel"]
            run(base+[str(old_wheel)],cwd=ROOT)
            app=home/".local/share/rivenscope-app"
            previous=(app/"current").resolve()
            launcher=home/".local/bin/rivenscope"
            self.assertEqual(run([str(launcher),"--version"]).stdout.strip(),"0.0.0")
            profile=home/"profile"
            store=Store(profile/"data/rivenscope.sqlite")
            preset=new_watchlist(); preset["name"]="Keep this preset"
            store.save_watchlist(preset); store.close()
            for _ in range(2):
                run(base+[str(self.wheel)],cwd=ROOT)
                self.assertEqual((app/"previous").resolve(),previous)
                self.assertNotEqual((app/"current").resolve(),previous)
                self.assertEqual(run([str(launcher),"--version"]).stdout.strip(),__version__)
            run([str(launcher),"--data-dir",str(profile),"--smoke-seconds","1"],
                env=os.environ|{"QT_QPA_PLATFORM":"offscreen"})
            store=Store(profile/"data/rivenscope.sqlite")
            self.assertEqual(store.watchlists(),[preset]); store.close()
