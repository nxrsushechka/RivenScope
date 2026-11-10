"""Persistent notification decisions and non-blocking Wayland desktop channels."""
from pathlib import Path
import shutil
from PySide6.QtCore import QObject, QUrl, QProcess, QTimer, Signal
from PySide6.QtMultimedia import QSoundEffect
from .config import validate_settings
from .filters import matches


def eligible(event, listing, estimate, settings, watchlist=None):
    if listing.status != "active":
        return False
    settings = validate_settings(settings | ((watchlist or {}).get("settings", {})))
    if not any(settings[c] for c in ("in_app", "desktop", "sound", "highlight")):
        return False
    if watchlist:
        if not watchlist["enabled"] or (watchlist["weapons"] and listing.weapon not in watchlist["weapons"]):
            return False
        if watchlist["category"] and listing.category != watchlist["category"]:
            return False
        if not matches(watchlist["filter"], listing, estimate):
            return False
    switches = {"new": "notify_new", "existing": "notify_existing", "price_changed": "notify_price"}
    if event["kind"] not in switches or not settings[switches[event["kind"]]]:
        return False
    if listing.seller_status not in settings["notification_statuses"] or not estimate.qualifies:
        return False
    rules = settings["risk_thresholds"]
    return (estimate.value is not None and estimate.profit is not None and estimate.discount is not None
            and estimate.profit >= rules["profit"] and estimate.discount >= rules["discount"]
            and estimate.confidence >= rules["confidence"] and estimate.sample_size >= rules["samples"]
            and estimate.freshness_hours is not None and estimate.freshness_hours <= rules["max_age_hours"])


def record_notification(store, event, listing, estimate, settings, watchlist=None, now=0):
    if not eligible(event, listing, estimate, settings, watchlist):
        return None
    global_limit = settings["notification_limit"]
    settings = validate_settings(settings | ((watchlist or {}).get("settings", {})))
    title = f"{listing.weapon.replace('_', ' ').title()} · potential opportunity"
    body = f"Ask {listing.acquisition:g}p · estimate {estimate.value:g}p · confidence {estimate.confidence:g}% (asking prices)"
    if store.add_notification(event, watchlist["id"] if watchlist else "global", title, body, now, min(global_limit, settings["notification_limit"])):
        return {"title": title, "body": body, "settings": settings, "listing_id": listing.id}
    return None


class Channels(QObject):
    in_app = Signal(str, str)
    highlight = Signal(str)
    warning = Signal(str)
    desktop_result = Signal(bool, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.sound = QSoundEffect(self)
        self.sound.setVolume(.35)
        self.processes = set()

    def deliver(self, message):
        settings = message["settings"]
        if settings["in_app"]:
            self.in_app.emit(message["title"], message["body"])
        if settings["highlight"]:
            self.highlight.emit(message.get("listing_id", ""))
        if settings["desktop"]:
            executable = shutil.which("notify-send")
            if not executable:
                self.warning.emit("Desktop notifications require notify-send (libnotify)")
                self.desktop_result.emit(False, "notify-send unavailable")
            else:
                process = QProcess(self); self.processes.add(process)
                timer = QTimer(process); timer.setSingleShot(True); timer.timeout.connect(process.kill)
                def completed(code, status):
                    timer.stop()
                    detail = bytes(process.readAllStandardOutput()).decode("utf-8", "replace").strip()
                    error = bytes(process.readAllStandardError()).decode("utf-8", "replace").strip()
                    success = code == 0 and status == QProcess.ExitStatus.NormalExit
                    if not success: self.warning.emit("Desktop notification failed: " + error)
                    self.desktop_result.emit(success, detail if success else error)
                    self.processes.discard(process); process.deleteLater()
                process.finished.connect(completed)
                process.start(executable, ["--app-name=RivenScope", "--icon=rivenscope", "--expire-time=7000", "--print-id", "--", message["title"], message["body"]])
                timer.start(5000)
        if settings["sound"]:
            sound_path = Path(settings["sound_path"])
            if sound_path.is_file() and sound_path.suffix.lower() == ".wav":
                self.sound.setSource(QUrl.fromLocalFile(str(sound_path.resolve())))
                self.sound.play()
            else:
                self.warning.emit("Choose a local WAV file in notification settings")

    def close(self):
        self.sound.stop()
        for process in list(self.processes):
            if process.state() != QProcess.ProcessState.NotRunning:
                process.kill()
                process.waitForFinished(1000)
