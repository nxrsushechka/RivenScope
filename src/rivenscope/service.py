"""Database worker and UI-facing controller; all heavy work stays off the GUI thread."""
from dataclasses import asdict
import logging
from pathlib import Path
import time
import hashlib
from threading import Event
from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot
from .storage import Store, dumps
from .network import Transport, decode_response
from .scheduler import Scheduler
from .valuation import estimate, PreparedComparables, check_cancelled
from .filters import matches
from .analysis import AnalysisEngine
from .domain import MARKET_PAGE_SIZE
from .contracts import PREFIX, contract_key, contract_weapon, parse_auctions

log = logging.getLogger(__name__)


class Worker(QObject):
    result = Signal(str, object)
    failed = Signal(str, str)

    def __init__(self, path):
        super().__init__()
        self.path, self.store = Path(path), None
        self.estimate_cache = {}
        self.cancelled = Event()

    @Slot(str, str, object)
    def execute(self, token, operation, args):
        try:
            if operation not in ("close", "budget") and self.cancelled.is_set():
                self.result.emit(token, None)
                return
            value = self._execute(operation, args)
            self.result.emit(token, value)
        except InterruptedError as error:
            if self.cancelled.is_set():
                self.result.emit(token, None)
            else:
                self.failed.emit(token, f"InterruptedError: {error}")
        except Exception as error:
            log.exception("Worker operation %s failed", operation)
            self.failed.emit(token, f"{type(error).__name__}: {error}")

    def bootstrap(self):
        return {"settings": self.store.settings(), "weapons": self.store.catalog("weapons"),
                "attributes": self.store.catalog("attributes"), "watchlists": self.store.watchlists(),
                "summary": self.store.summary(), "notifications": self.store.notifications(),
                "budget": self.store.state("budget", {}), "database": str(self.path)}

    def ingest_auctions(self, payload, weapon, observed_at):
        listings = parse_auctions(payload, weapon, observed_at,
            {w["slug"]:w for w in self.store.catalog("weapons")},
            {a["slug"]:a for a in self.store.catalog("attributes")})
        result = AnalysisEngine(self.store).observe(listings, contract_key(weapon), observed_at,
                                                   complete=False, weapon=weapon)
        self.estimate_cache.clear()
        return result

    def planned_queries(self, now):
        settings = self.store.settings()
        if not settings["legacy_contracts"] or not self.store.catalog("attributes"):
            return []
        weapons = {w["slug"]:w for w in self.store.catalog("weapons")}
        selected = set(weapons) if "*" in settings["contract_weapons"] else set(settings["contract_weapons"]) & weapons.keys()
        priorities = {w:settings["global_priority"] for w in selected}
        for rule in self.store.watchlists():
            if not rule["enabled"]: continue
            scope = set(rule["weapons"]) if rule["weapons"] else set(weapons)
            for slug in scope & weapons.keys():
                if not rule["category"] or weapons[slug]["rivenType"] == rule["category"]:
                    priorities[slug] = max(priorities.get(slug, 0), rule["priority"])
        jobs = []
        for weapon, priority in sorted(priorities.items(), key=lambda p:(-p[1],p[0])):
            key = contract_key(weapon)
            last = self.store.state("attempt:"+key, 0)
            if now-last >= settings["contract_interval_minutes"]*60:
                jobs.append({"key":key, "priority":priority})
        return jobs

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
            if not self.store.settings()["legacy_contracts"] or args.get("complete"):
                raise ValueError("Legacy search must be enabled and treated as a partial response")
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
            catalogs = []
            if version is None or now - version["at"] >= interval:
                if now-self.store.state("attempt:versions",0) >= interval:
                    catalogs = ["versions"]
            else:
                catalogs = [key for key in ("weapons", "attributes") if not self.store.cache_get(key)
                            and now-self.store.state("attempt:"+key,0) >= interval]
            return [{"key":key,"priority":10} for key in catalogs] + self.planned_queries(now)
        if operation == "response":
            outcome = args
            now = time.time()
            self.store.log_request(outcome.key, outcome.status, outcome.error, now)
            self.store.save_state("attempt:"+outcome.key, now)
            if outcome.status != 200:
                return {"refresh": self.bootstrap(), "enqueue": []}
            try:
                data = decode_response(outcome)
            except ValueError as error:
                self.store.log_request(outcome.key, 0, str(error), now)
                raise
            if outcome.key.startswith(PREFIX):
                if not self.store.settings()["legacy_contracts"]:
                    return {"refresh":self.bootstrap(), "enqueue":[]}
                result = self.ingest_auctions(data, contract_weapon(outcome.key), now)
                return {"refresh":self.bootstrap(), "enqueue":[], "notifications":result["notifications"], "market_changed":True}
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
            page = self.store.listings(limit=MARKET_PAGE_SIZE, offset=args.get("offset", 0), weapon=args.get("weapon", ""))
            settings = self.store.settings()
            groups = {}
            now = time.time()
            for row in page:
                check_cancelled(self.cancelled.is_set)
                item = row["listing"]
                if item.comparable_group not in groups:
                    groups[item.comparable_group] = self.store.comparables(item, now, settings["risk_thresholds"]["max_age_hours"])
            stamps = {key: hashlib.sha256(dumps([c.to_dict() for c in items]).encode()).hexdigest() for key, items in groups.items()}
            pools = {key: PreparedComparables(items, now, self.cancelled.is_set) for key, items in groups.items()}
            settings_stamp = dumps(settings)
            output = []
            retained = {}
            for row in page:
                check_cancelled(self.cancelled.is_set)
                item = row["listing"]
                key = (item.id, dumps(item.to_dict()), stamps[item.comparable_group], settings_stamp, int(now // 60))
                result = self.estimate_cache.get(key)
                if result is None:
                    result = estimate(item, pools[item.comparable_group], now, settings["risk_profile"], settings["risk_thresholds"], self.cancelled.is_set)
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
        self.interval.setInterval(6000)
        self.interval.timeout.connect(self.plan)
        self.thread.start()
        self.submit("initialize", None, self._initialized)

    def submit(self, operation, args=None, callback=None):
        if self.closing and operation != "close":
            return
        if operation in ("settings", "watchlist", "delete_watchlist") and self.scheduler.running:
            self.stop()  # Discard searches for stale scope/settings before reconfiguration.
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
        self.submit("plan", None, lambda jobs: [self.scheduler.enqueue(job["key"],job["priority"]) for job in jobs])

    def stop(self):
        self.interval.stop()
        self.scheduler.stop()

    def _response(self, response):
        def received(value):
            self.priority = value["refresh"]["settings"]["global_priority"]
            self.updated.emit(value["refresh"])
            if value.get("market_changed"):
                self.observations_changed.emit()
            for message in value.get("notifications",[]):
                self.notification.emit(message)
            for key in value["enqueue"]:
                self.scheduler.enqueue(key, self.priority)
        self.submit("response", response, received)

    def ingest_contract_batch(self, batch):
        """Canonical extension point; requires legacy opt-in and partial semantics."""
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
        self.worker.cancelled.set()
        self.submit("close")
