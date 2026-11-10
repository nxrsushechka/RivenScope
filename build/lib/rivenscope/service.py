"""Database worker and UI-facing controller; all heavy work stays off the GUI thread."""
from dataclasses import asdict
import logging
from pathlib import Path
import time
import hashlib
from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot
from .storage import Store, dumps
from .network import Transport, decode_response
from .scheduler import Scheduler
from .valuation import estimate
from .filters import matches
from .analysis import AnalysisEngine
from . import CONTRACTS_AVAILABLE, CONTRACT_LIMITATION

log = logging.getLogger(__name__)


class Worker(QObject):
    result = Signal(str, object)
    failed = Signal(str, str)

    def __init__(self, path):
        super().__init__()
        self.path, self.store = Path(path), None
        self.estimate_cache = {}

    @Slot(str, str, object)
    def execute(self, token, operation, args):
        try:
            value = self._execute(operation, args)
            self.result.emit(token, value)
        except Exception as error:
            log.exception("Worker operation %s failed", operation)
            self.failed.emit(token, f"{type(error).__name__}: {error}")

    def bootstrap(self):
        return {"settings": self.store.settings(), "weapons": self.store.catalog("weapons"),
                "attributes": self.store.catalog("attributes"), "watchlists": self.store.watchlists(),
                "summary": self.store.summary(), "notifications": self.store.notifications(),
                "budget": self.store.state("budget", {}), "database": str(self.path)}

    def _execute(self, operation, args):
        if operation == "initialize":
            self.store = Store(self.path)
            return self.bootstrap()
        if operation == "close":
            if self.store: self.store.close()
            QThread.currentThread().quit()
            return None
        if operation == "restore" and self.store is None:
            self.store, preserved = Store.recover(self.path, args["source"], args.get("confirmed", False))
            return {"message": f"Recovered. Original damaged files preserved in {preserved}", "refresh": self.bootstrap()}
        if self.store is None:
            raise ValueError("Database unavailable. Restore a valid backup from recovery.")
        if operation == "refresh":
            return self.bootstrap()
        if operation == "contract_batch":
            if not CONTRACTS_AVAILABLE:
                raise ValueError(CONTRACT_LIMITATION)
            result = AnalysisEngine(self.store).observe(**args)
            self.estimate_cache.clear()
            return {"refresh": self.bootstrap(), "notifications": result["notifications"]}
        if operation == "budget":
            self.store.save_state("budget", args)
            return None
        if operation == "settings":
            self.store.save_settings(args)
            return self.bootstrap()
        if operation == "watchlist":
            self.store.save_watchlist(args)
            return self.bootstrap()
        if operation == "delete_watchlist":
            self.store.delete_watchlist(args)
            return self.bootstrap()
        if operation == "plan":
            now = time.time()
            version = self.store.cache_get("versions")
            interval = self.store.settings()["catalog_interval_minutes"] * 60
            if version is None or now - version["at"] >= interval:
                return ["versions"]
            return [key for key in ("weapons", "attributes") if not self.store.cache_get(key)]
        if operation == "response":
            outcome = args
            now = time.time()
            self.store.log_request(outcome.key, outcome.status, outcome.error, now)
            if outcome.status != 200:
                return {"refresh": self.bootstrap(), "enqueue": []}
            try:
                data = decode_response(outcome)
            except ValueError as error:
                self.store.log_request(outcome.key, 0, str(error), now)
                raise
            old = self.store.cache_get(outcome.key)
            if outcome.key != "versions":
                self.store.save_catalog(outcome.key, data, now)
            self.store.cache_put(outcome.key, data, now)
            requests = []
            if outcome.key == "versions":
                changed = old is None or old["data"]["collections"].get("rivens") != data["collections"].get("rivens")
                requests = [key for key in ("weapons", "attributes") if changed or not self.store.cache_get(key)]
            return {"refresh": self.bootstrap(), "enqueue": requests}
        if operation == "market":
            page = self.store.listings(limit=10000, offset=args.get("offset", 0), weapon=args.get("weapon", ""))
            settings = self.store.settings()
            groups = {}
            def group(item):
                return (item.weapon, item.category, item.rank, item.disposition, item.measurement, item.signature)
            for row in page: groups.setdefault(group(row["listing"]), []).append(row["listing"])
            stamps = {key: hashlib.sha256(dumps([c.to_dict() for c in items]).encode()).hexdigest() for key, items in groups.items()}
            settings_stamp = dumps(settings)
            now, output = time.time(), []
            retained = {}
            for row in page:
                item = row["listing"]
                key = (item.id, stamps[group(item)], settings_stamp, int(now // 60))
                result = self.estimate_cache.get(key)
                if result is None:
                    result = estimate(item, groups[group(item)], now, settings["risk_profile"], settings["risk_thresholds"])
                    self.store.save_estimate(item.id, result, now)
                retained[key] = result
                if args.get("expression") and not matches(args["expression"], item, result): continue
                output.append(row | {"estimate": result})
            self.estimate_cache = retained  # bounded to the current page, not all queries ever visited
            status_order = {s:i for i,s in enumerate(settings["seller_priority"])}
            output.sort(key=lambda r:(not r["estimate"].qualifies, -r["estimate"].confidence,
                                     -(r["estimate"].profit or 0), status_order.get(r["listing"].seller_status, 10)))
            return output
        if operation == "details":
            return self.store.history(args)
        if operation == "analytics":
            return self.store.analytics(args)
        if operation == "backup":
            self.store.backup(**args)
            return "Database backup completed and integrity checked."
        if operation == "restore":
            path = self.store.restore(**args)
            return {"message": f"Database restored. Previous database backup: {path}", "refresh": self.bootstrap()}
        if operation == "export":
            self.store.export_file(**args)
            return "Export completed."
        if operation == "import":
            self.store.import_file(**args)
            return self.bootstrap()
        if operation == "prune":
            return self.store.prune(**args, now=time.time())
        raise ValueError("Unknown worker operation")


class Controller(QObject):
    command = Signal(str, str, object)
    ready = Signal(object)
    updated = Signal(object)
    error = Signal(str)
    scheduler_changed = Signal(object)
    notification = Signal(object)
    observations_changed = Signal()
    stopped = Signal()

    def __init__(self, database, parent=None, transport=None):
        super().__init__(parent)
        self.thread = QThread(self)
        self.worker = Worker(database)
        self.worker.moveToThread(self.thread)
        self.command.connect(self.worker.execute)
        self.worker.result.connect(self._result)
        self.worker.failed.connect(self._failure)
        self.thread.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.stopped)
        self.pending = {}
        self.counter = 0
        self.closing = False
        self.transport = transport or Transport(self)
        self.scheduler = Scheduler(self.transport, self)
        self.scheduler.changed.connect(self.scheduler_changed)
        self.scheduler.persist.connect(lambda value: self.submit("budget", value))
        self.scheduler.outcome.connect(self._response)
        self.interval = QTimer(self)
        self.interval.setInterval(3600 * 1000)
        self.interval.timeout.connect(self.plan)
        self.thread.start()
        self.submit("initialize", None, self._initialized)

    def submit(self, operation, args=None, callback=None):
        if self.closing and operation != "close":
            return
        self.counter += 1
        token = str(self.counter)
        self.pending[token] = (operation, callback)
        self.command.emit(token, operation, args)
        return token

    def _initialized(self, value):
        self.scheduler.budget.restore(value["budget"], time.time())
        self.priority = value["settings"]["global_priority"]
        self.ready.emit(value)

    @Slot(str, object)
    def _result(self, token, value):
        _, callback = self.pending.pop(token, ("", None))
        if callback and not self.closing:
            callback(value)

    @Slot(str, str)
    def _failure(self, token, text):
        operation, _ = self.pending.pop(token, ("", None))
        self.error.emit(f"{operation}: {text}")

    def start(self):
        self.scheduler.start()
        self.interval.start()
        self.plan()

    def plan(self):
        self.submit("plan", None, lambda keys: [self.scheduler.enqueue(key, getattr(self, "priority", 3)) for key in keys])

    def stop(self):
        self.interval.stop()
        self.scheduler.stop()

    def _response(self, response):
        def received(value):
            self.priority = value["refresh"]["settings"]["global_priority"]
            self.updated.emit(value["refresh"])
            for key in value["enqueue"]:
                self.scheduler.enqueue(key, self.priority)
        self.submit("response", response, received)

    def ingest_contract_batch(self, batch):
        """Adapter extension point; the worker refuses this while capability is unavailable."""
        def received(value):
            self.updated.emit(value["refresh"])
            self.observations_changed.emit()
            for message in value["notifications"]:
                self.notification.emit(message)
        self.submit("contract_batch", batch, received)

    def shutdown(self):
        if self.closing:
            return
        self.stop()
        self.closing = True
        self.submit("close")
