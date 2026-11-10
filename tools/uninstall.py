"""Remove only the managed RivenScope installation. All user data is retained."""
import argparse
from pathlib import Path
import shutil
import subprocess

MARKER="RivenScope managed installation v1"


def main():
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument("--home",type=Path,default=Path.home()); args=parser.parse_args()
    root=args.home/".local/share/rivenscope-app"
    if not (root/"INSTALLATION").is_file() or (root/"INSTALLATION").read_text().strip()!=MARKER:
        raise SystemExit("No managed RivenScope installation found; nothing removed.")
    for path in (args.home/".local/bin/rivenscope",args.home/".local/share/applications/rivenscope.desktop"):
        if path.is_file() and MARKER in path.read_text(): path.unlink()
    icon=args.home/".local/share/icons/hicolor/scalable/apps/rivenscope.svg"
    installed_icon=root/"current/lib/rivenscope/assets/rivenscope.svg"
    if icon.is_file() and installed_icon.is_file() and icon.read_bytes()==installed_icon.read_bytes(): icon.unlink()
    shutil.rmtree(root)
    if shutil.which("update-desktop-database"): subprocess.run(["update-desktop-database",str(args.home/".local/share/applications")],check=True)
    print("RivenScope application removed. Database, backups, logs and settings retained.")


if __name__=="__main__": main()
