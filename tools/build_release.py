"""Build deterministic releases from canonical sources in a clean staging tree."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib

ROOT = Path(__file__).resolve().parents[1]
EPOCH = 1794182400  # Stable archive timestamps, independent of checkout mtimes.
SOURCE_ROOTS = ("src", "tests", "tools", "docs", ".github")
SOURCE_FILES = ("pyproject.toml", "README.md", "TASKS.md", "requirements-build.txt",
                "requirements-dev.txt", ".gitignore")
REQUIRED = ("app.py", "analysis.py", "ui/window.py", "assets/rivenscope.svg")


def source_files(root):
    files = [root / name for name in SOURCE_FILES if (root / name).is_file()]
    for name in SOURCE_ROOTS:
        for path in (root / name).rglob("*"):
            if (path.is_file() and not any(part == "__pycache__" or part.endswith(".egg-info") for part in path.parts)
                    and not path.name.endswith((".pyc", ".sqlite", ".sqlite-wal", ".sqlite-shm"))):
                files.append(path)
    return sorted(files)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    for name in REQUIRED:
        if not (ROOT / "src/rivenscope" / name).is_file():
            parser.error(f"Incomplete source checkout: missing src/rivenscope/{name}")
    version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    dist = args.output_dir.resolve()
    dist.mkdir(parents=True, exist_ok=True)
    environment = os.environ | {"SOURCE_DATE_EPOCH": str(EPOCH)}
    files = source_files(ROOT)
    with tempfile.TemporaryDirectory(prefix="rivenscope-build-") as directory:
        stage = Path(directory) / "source"
        for path in files:
            target = stage / path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            target.chmod(0o644)  # Checkout and extracted archives may have different modes.
        # Never consult ROOT/build: deleted modules in an old build must not ship.
        subprocess.run([sys.executable, "-m", "build", "--wheel", "--no-isolation",
                        "--outdir", str(dist)], cwd=stage, env=environment, check=True)
    archive = dist / f"rivenscope-{version}-source.tar.gz"
    with archive.open("wb") as stream:
        with gzip.GzipFile(filename="", mode="wb", fileobj=stream, mtime=EPOCH) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as tar:
                for path in files:
                    info = tar.gettarinfo(path, arcname=f"rivenscope-{version}/" + path.relative_to(ROOT).as_posix())
                    info.mtime = EPOCH
                    info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    info.mode = 0o644
                    with path.open("rb") as data:
                        tar.addfile(info, data)
    artifacts = [dist / f"rivenscope-{version}-py3-none-any.whl", archive]
    checksums = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in artifacts}
    (dist / "SHA256SUMS").write_text("".join(f"{digest}  {name}\n" for name, digest in checksums.items()))
    print(json.dumps(checksums, indent=2))


if __name__ == "__main__":
    main()
