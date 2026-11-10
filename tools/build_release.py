"""Deterministic wheel + source release with explicit local build tools."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile

ROOT=Path(__file__).resolve().parents[1]
EPOCH=1794182400  # 2026-11-09 00:00:00 UTC; fixed release timestamp


def main():
    dist=ROOT/"dist"; dist.mkdir(exist_ok=True)
    environment=os.environ.copy(); environment["SOURCE_DATE_EPOCH"]=str(EPOCH)
    subprocess.run([sys.executable,"-m","build","--wheel","--no-isolation"],cwd=ROOT,env=environment,check=True)
    version="0.1.0"
    archive=dist/f"rivenscope-{version}-source.tar.gz"
    files=[]
    for path in ROOT.rglob("*"):
        relative=path.relative_to(ROOT)
        if not path.is_file() or any(p in {".venv","build","dist",".git","__pycache__","test-artifacts"} or p.endswith(".egg-info") for p in relative.parts): continue
        if path.suffix in {".pyc",".sqlite"}: continue
        files.append(path)
    with archive.open("wb") as stream:
        with gzip.GzipFile(filename="",mode="wb",fileobj=stream,mtime=EPOCH) as compressed:
            with tarfile.open(fileobj=compressed,mode="w") as tar:
                for path in sorted(files):
                    info=tar.gettarinfo(path,arcname=f"rivenscope-{version}/"+str(path.relative_to(ROOT)))
                    info.mtime=EPOCH; info.uid=info.gid=0; info.uname=info.gname=""; info.mode=0o644
                    with path.open("rb") as data: tar.addfile(info,data)
    artifacts=[dist/f"rivenscope-{version}-py3-none-any.whl",archive]
    checksums={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in artifacts}
    (dist/"SHA256SUMS").write_text("".join(f"{digest}  {name}\n" for name,digest in checksums.items()))
    print(json.dumps(checksums,indent=2))


if __name__=="__main__": main()
