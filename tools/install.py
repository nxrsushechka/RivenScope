"""Unprivileged, staged installation; refuses unrelated files, retains data and releases."""
import argparse
import hashlib
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import uuid
import zipfile

ROOT=Path(__file__).resolve().parents[1]
MARKER="RivenScope managed installation v1"


def atomic_text(path,text,mode=0o644):
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+"."+uuid.uuid4().hex+".tmp")
    temporary.write_text(text); temporary.chmod(mode); os.replace(temporary,path)


def install(wheel,home):
    from PySide6.QtCore import qVersion
    if tuple(map(int,qVersion().split("."))) < (6,8,0): raise ValueError("Qt 6.8 or later is required")
    wheel=wheel.resolve(); home=home.resolve()
    app_root=home/".local/share/rivenscope-app"; marker=app_root/"INSTALLATION"
    if app_root.exists() and (not marker.exists() or marker.read_text().strip()!=MARKER):
        raise ValueError(f"Refusing to replace unrelated directory: {app_root}")
    binary=home/".local/bin/rivenscope"; desktop=home/".local/share/applications/rivenscope.desktop"
    icon=home/".local/share/icons/hicolor/scalable/apps/rivenscope.svg"
    for path in (binary,desktop):
        if path.exists() and MARKER not in path.read_text(): raise ValueError(f"Unmanaged file already exists: {path}")
    if icon.exists() and not marker.exists(): raise ValueError(f"Unmanaged icon already exists: {icon}")
    digest=hashlib.sha256(wheel.read_bytes()).hexdigest()
    checksums=wheel.parent/"SHA256SUMS"
    if not checksums.exists() or f"{digest}  {wheel.name}" not in checksums.read_text().splitlines():
        raise ValueError("Wheel checksum does not match local SHA256SUMS")
    app_root.mkdir(parents=True,exist_ok=True)
    atomic_text(marker,MARKER+"\n")
    releases=app_root/"releases"; releases.mkdir(exist_ok=True)
    release=releases/(wheel.name.split("-")[1]+"-"+digest[:12])
    stage=Path(tempfile.mkdtemp(prefix=".stage-",dir=releases))
    try:
        lib=stage/"lib"; lib.mkdir()
        with zipfile.ZipFile(wheel) as archive:
            for member in archive.infolist():
                name=Path(member.filename)
                if name.is_absolute() or ".." in name.parts or (member.external_attr>>16)&0o170000==0o120000:
                    raise ValueError("Unsafe wheel entry")
                if member.file_size>20_000_000: raise ValueError("Unexpected oversized package file")
            archive.extractall(lib)
        launch="""#!/usr/bin/env python3
# RivenScope managed installation v1
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent/'lib'))
from rivenscope.app import main
raise SystemExit(main())
"""
        (stage/"launch.py").write_text(launch)
        (stage/"WHEEL_SHA256").write_text(digest+"\n")
        shutil.copy2(ROOT/"tools/uninstall.py",stage/"uninstall.py")
        bundled_docs=list(lib.glob("*.data/data/share/rivenscope/docs"))
        if bundled_docs: shutil.copytree(bundled_docs[0],stage/"docs")
        subprocess.run([sys.executable,"-I",str(stage/"launch.py"),"--version"],check=True)
        with tempfile.TemporaryDirectory(prefix="rivenscope-install-test-",dir="/tmp/opencode" if Path("/tmp/opencode").exists() else None) as temporary:
            subprocess.run([sys.executable,"-I",str(stage/"launch.py"),"--data-dir",temporary,"--smoke-seconds","1"],
                env=os.environ|{"QT_QPA_PLATFORM":"offscreen"},timeout=20,check=True)
        if release.exists():
            if (release/"WHEEL_SHA256").read_text().strip()!=digest: raise ValueError("Release directory collision")
            shutil.rmtree(stage)
        else: os.replace(stage,release)
        # Retain the runtime that passed the staged Qt check, including a venv.
        launcher=f'#!/bin/sh\n# {MARKER}\nexec {shlex.quote(sys.executable)} -I {shlex.quote(str(app_root / "current/launch.py"))} "$@"\n'
        if any(c in str(app_root) for c in ('"','$','`','\n')): raise ValueError("Unsupported characters in installation path")
        # Validate desktop content before switching the active release.
        entry=f'''[Desktop Entry]
# {MARKER}
Type=Application
Name=RivenScope
GenericName=Riven Research
Comment=Warframe Riven catalog, saved searches and local market analytics
Exec="{binary}"
TryExec={binary}
Icon=rivenscope
Terminal=false
Categories=Network;
Keywords=Warframe;Riven;Market;Analytics;
StartupNotify=true
StartupWMClass=rivenscope
'''
        with tempfile.TemporaryDirectory(prefix="rivenscope-desktop-",dir="/tmp/opencode" if Path("/tmp/opencode").exists() else None) as temporary:
            test_entry=Path(temporary)/"rivenscope.desktop"; test_entry.write_text(entry)
            if shutil.which("desktop-file-validate"): subprocess.run(["desktop-file-validate",str(test_entry)],check=True)
        current=app_root/"current"; previous=app_root/"previous"
        if current.is_symlink() and current.resolve() != release.resolve():
            previous.unlink(missing_ok=True); previous.symlink_to(current.readlink())
        new=app_root/".current-new"; new.unlink(missing_ok=True); new.symlink_to(release.relative_to(app_root)); os.replace(new,current)
        atomic_text(binary,launcher,0o755)
        atomic_text(desktop,entry)
        icon.parent.mkdir(parents=True,exist_ok=True)
        temporary_icon=icon.with_suffix(".svg.tmp"); shutil.copy2(release/"lib/rivenscope/assets/rivenscope.svg",temporary_icon); os.replace(temporary_icon,icon)
        if shutil.which("update-desktop-database"): subprocess.run(["update-desktop-database",str(desktop.parent)],check=True)
        print(f"Installed: {release}\nCommand: {binary}\nDesktop entry: {desktop}\nUser data preserved.")
        return release
    finally:
        if stage.exists(): shutil.rmtree(stage)


def main():
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument("--wheel",type=Path); parser.add_argument("--home",type=Path,default=Path.home())
    args=parser.parse_args(); wheels=sorted((ROOT/"dist").glob("rivenscope-*.whl"))
    wheel=args.wheel or (wheels[-1] if wheels else None)
    if wheel is None: parser.error("Build a release first: .venv/bin/python tools/build_release.py")
    install(wheel,args.home)


if __name__=="__main__": main()
