"""Verify the actual installed release, native launcher, persistence and clean close.

Explicitly launches the application and enables its approved catalog sync once.
Closes only the window started by this check. No Hyprland configuration is modified.
"""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]


def clients():
    result = subprocess.run(["hyprctl", "clients", "-j"], capture_output=True, text=True, check=True)
    return [c for c in json.loads(result.stdout) if c.get("class", "").lower() == "rivenscope"]


def alive(pid):
    try:
        return Path(f"/proc/{pid}/stat").read_text().split(") ", 1)[1].split()[0] != "Z"
    except FileNotFoundError:
        return False


def main():
    home = Path.home()
    launcher = home / ".local/bin/rivenscope"
    desktop = home / ".local/share/applications/rivenscope.desktop"
    current = home / ".local/share/rivenscope-app/current"
    if clients():
        raise SystemExit("Close the existing RivenScope window before installation verification.")
    subprocess.run(["desktop-file-validate", str(desktop)], check=True)
    version = subprocess.run([str(launcher), "--version"], capture_output=True, text=True, check=True).stdout.strip()
    subprocess.run([str(launcher), "--sync", "--smoke-seconds", "40"],
                   env=os.environ | {"QT_QPA_PLATFORM": "wayland"}, check=True, timeout=55)
    database = Path(os.getenv("XDG_DATA_HOME", home / ".local/share")) / "rivenscope/rivenscope.sqlite"
    con = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
    try:
        data = {"version": version, "release": str(current.resolve()),
                "database": str(database), "integrity": con.execute("PRAGMA integrity_check").fetchone()[0],
                "catalogs": dict(con.execute("SELECT kind,COUNT(*) FROM catalogs GROUP BY kind").fetchall()),
                "contracts": con.execute("SELECT COUNT(*) FROM listings").fetchone()[0],
                "requests": [list(r) for r in con.execute("SELECT route,status FROM request_log ORDER BY id DESC LIMIT 3")]}
    finally:
        con.close()
    if not data["catalogs"].get("weapons") or not data["catalogs"].get("attributes"):
        raise RuntimeError("Installed application did not populate the real API catalogs")
    # Desktop-launched children inherit descriptors; capture_output would wait for
    # EOF from the running GUI instead of just waiting for gtk-launch to exit.
    subprocess.run(["gtk-launch", "rivenscope"], check=True, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL, timeout=10)
    own_window = None
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            matches = clients()
            if matches:
                own_window = matches[0]
                break
            time.sleep(.1)
        if own_window is None:
            raise RuntimeError("Desktop launcher did not create a window")
        data["menu_window"] = {k: own_window.get(k) for k in ("class", "title", "pid", "xwayland")}
        pid = own_window["pid"]
        data["process_command"] = Path(f"/proc/{pid}/cmdline").read_bytes().decode().replace("\0", " ").strip()
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                data["native_rss_mb"] = int(line.split()[1]) / 1024
        assert not own_window["xwayland"], "Menu launched XWayland instead of native Wayland"
        assert "rivenscope-app/current/launch.py" in data["process_command"], "Menu must launch installed code"
    finally:
        if own_window:
            selector = json.dumps("address:" + own_window["address"])
            close = subprocess.run(["hyprctl", "dispatch", "hl.dsp.window.close({ window = " + selector + " })"], capture_output=True)
            if close.returncode:  # Older Hyprland without Lua dispatchers.
                subprocess.run(["hyprctl", "dispatch", "closewindow", "address:" + own_window["address"]], check=True, capture_output=True)
    deadline = time.monotonic() + 10
    while alive(pid) and time.monotonic() < deadline:
        time.sleep(.1)
    data["closed_cleanly"] = not alive(pid)
    assert data["closed_cleanly"], "Installed process remained alive after window close"
    data["source_matches_installed"] = all(
        (current / "lib/rivenscope" / path.relative_to(ROOT / "src/rivenscope")).read_bytes() == path.read_bytes()
        for path in (ROOT / "src/rivenscope").rglob("*.py"))
    assert data["source_matches_installed"], "Release is older than the working source"
    report = ROOT / "test-artifacts/installed.json"
    report.parent.mkdir(exist_ok=True)
    report.write_text(json.dumps(data, indent=2) + "\n")
    print(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()
