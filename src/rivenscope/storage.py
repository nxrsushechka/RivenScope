"""Transactional, thread-confined storage and validated portable data tools."""
from dataclasses import asdict
import csv
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
import uuid

from .config import DEFAULTS, validate_settings
from .domain import Listing
from .filters import validate

SCHEMA_VERSION = 2
APP_ID = 0x52565343


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def validate_watchlist(value, attributes=None, weapons=None):
    if not isinstance(value, dict):
        raise ValueError("Watchlist must be an object")
    required = {"id", "name", "enabled", "priority", "weapons", "category", "filter", "settings"}
    if set(value) != required:
        raise ValueError("Invalid watchlist fields")
    if not isinstance(value["id"], str) or not 1 <= len(value["id"]) <= 100:
        raise ValueError("Invalid watchlist identifier")
    if not isinstance(value["name"], str) or not 1 <= len(value["name"].strip()) <= 100:
        raise ValueError("Watchlist name is required (100 characters maximum)")
    if type(value["enabled"]) is not bool or type(value["priority"]) is not int or not 1 <= value["priority"] <= 10:
        raise ValueError("Invalid watchlist priority or enabled state")
    if not isinstance(value["weapons"], list) or len(value["weapons"]) > 1000 or any(not isinstance(w, str) or len(w) > 120 for w in value["weapons"]):
        raise ValueError("Invalid weapon group")
    if not isinstance(value["category"], str) or len(value["category"]) > 100:
        raise ValueError("Invalid category")
    if weapons:
        for slug in value["weapons"]:
            if slug not in weapons:
                raise ValueError(f"Unknown weapon: {slug}")
            if value["category"] and weapons[slug].get("rivenType") != value["category"]:
                raise ValueError(f"{slug} is not a {value['category']} weapon")
            validate(value["filter"], attributes, weapons[slug].get("rivenType"))
    validate(value["filter"], attributes, value["category"] or None)
    validate_settings(value["settings"])
    return value


def new_watchlist():
    return {"id": str(uuid.uuid4()), "name": "New watchlist", "enabled": True, "priority": 3,
            "weapons": [], "category": "", "filter": {"op": "AND", "children": []}, "settings": {}}


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(self.path, timeout=5)
        self.db.row_factory = sqlite3.Row
        try:
            integrity = self.db.execute("PRAGMA quick_check").fetchone()[0]
            if integrity != "ok":
                raise ValueError("Database integrity check failed; restore a backup. Original preserved.")
            version = self.db.execute("PRAGMA user_version").fetchone()[0]
            app_id = self.db.execute("PRAGMA application_id").fetchone()[0]
            if version > SCHEMA_VERSION or (app_id not in (0, APP_ID)):
                raise ValueError("Unsupported database version or application")
            if version and app_id != APP_ID:
                raise ValueError("Not a RivenScope database")
            if version and version < SCHEMA_VERSION:
                self.backup(self.path.with_name(f"pre-migration-{time.time_ns()}.sqlite"))
            self._migrate(version)
            self.db.execute("PRAGMA foreign_keys=ON")
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA busy_timeout=5000")
        except Exception:
            self.db.close()
            raise

    def _migrate(self, version):
        if version < 1:
            self.db.executescript(f"""
                BEGIN IMMEDIATE;
                PRAGMA application_id={APP_ID};
                CREATE TABLE migrations(version INTEGER PRIMARY KEY, applied_at REAL NOT NULL);
                CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE catalogs(kind TEXT NOT NULL, slug TEXT NOT NULL, payload TEXT NOT NULL,
                    fetched_at REAL NOT NULL, PRIMARY KEY(kind,slug));
                CREATE TABLE watchlists(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE listings(id TEXT PRIMARY KEY, weapon TEXT NOT NULL, payload TEXT NOT NULL,
                    fingerprint TEXT NOT NULL, first_seen REAL NOT NULL, last_seen REAL NOT NULL,
                    state TEXT NOT NULL, price REAL, kind TEXT NOT NULL);
                CREATE INDEX listings_weapon_seen ON listings(weapon,last_seen);
                CREATE INDEX listings_price ON listings(price);
                CREATE TABLE snapshots(id INTEGER PRIMARY KEY, listing_id TEXT NOT NULL REFERENCES listings(id),
                    observed_at REAL NOT NULL, payload TEXT NOT NULL, digest TEXT NOT NULL);
                CREATE INDEX snapshots_listing_time ON snapshots(listing_id,observed_at);
                CREATE TABLE events(id TEXT PRIMARY KEY, listing_id TEXT NOT NULL REFERENCES listings(id),
                    kind TEXT NOT NULL, at REAL NOT NULL, payload TEXT NOT NULL);
                CREATE INDEX events_listing_time ON events(listing_id,at);
                CREATE TABLE notifications(id TEXT PRIMARY KEY, event_id TEXT NOT NULL,
                    watchlist_id TEXT NOT NULL, at REAL NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL,
                    UNIQUE(event_id,watchlist_id));
                CREATE INDEX notifications_time ON notifications(at);
                CREATE TABLE valuations(listing_id TEXT PRIMARY KEY REFERENCES listings(id), at REAL NOT NULL,
                    payload TEXT NOT NULL);
                CREATE TABLE observations(id INTEGER PRIMARY KEY, query_key TEXT NOT NULL, at REAL NOT NULL,
                    weapon TEXT NOT NULL, count INTEGER NOT NULL, complete INTEGER NOT NULL);
                CREATE INDEX observations_weapon_time ON observations(weapon,at);
                CREATE TABLE request_log(id INTEGER PRIMARY KEY, at REAL NOT NULL, route TEXT NOT NULL,
                    status INTEGER NOT NULL, message TEXT NOT NULL);
                CREATE INDEX requests_time ON request_log(at);
                CREATE TABLE scheduler_state(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                INSERT INTO migrations VALUES(1,strftime('%s','now'));
                PRAGMA user_version=1;
                COMMIT;
            """)
        if version < 2:
            self.db.executescript("""
                BEGIN IMMEDIATE;
                CREATE TABLE cache(key TEXT PRIMARY KEY, at REAL NOT NULL, payload TEXT NOT NULL);
                INSERT INTO migrations VALUES(2,strftime('%s','now'));
                PRAGMA user_version=2;
                COMMIT;
            """)

    def close(self):
        if self.db:
            self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self.db.close()
            self.db = None

    def settings(self):
        row = self.db.execute("SELECT value FROM settings WHERE key='preferences'").fetchone()
        return validate_settings(json.loads(row[0]) if row else {})

    def save_settings(self, data):
        validated = validate_settings(data)
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO settings VALUES('preferences',?)", (dumps(validated),))

    def state(self, key, default=None):
        row = self.db.execute("SELECT value FROM scheduler_state WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def save_state(self, key, value):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO scheduler_state VALUES(?,?)", (key, dumps(value)))

    def catalog(self, kind):
        return [json.loads(row[0]) for row in self.db.execute("SELECT payload FROM catalogs WHERE kind=? ORDER BY slug", (kind,))]

    def save_catalog(self, kind, records, now):
        # Parse/validate before deleting anything; swap a collection atomically.
        from .network import parse_manifest
        records = parse_manifest({"data": records, "error": None}, kind)
        with self.db:
            self.db.execute("DELETE FROM catalogs WHERE kind=?", (kind,))
            self.db.executemany("INSERT INTO catalogs VALUES(?,?,?,?)", ((kind, r["slug"], dumps(r), now) for r in records))

    def watchlists(self):
        return [json.loads(row[0]) for row in self.db.execute("SELECT payload FROM watchlists ORDER BY rowid")]

    def save_watchlist(self, value):
        validate_watchlist(value, {a["slug"]: a for a in self.catalog("attributes")} or None,
                           {w["slug"]: w for w in self.catalog("weapons")} or None)
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO watchlists VALUES(?,?)", (value["id"], dumps(value)))

    def delete_watchlist(self, id_):
        with self.db:
            self.db.execute("DELETE FROM watchlists WHERE id=?", (id_,))

    def observe(self, listings, query_key, now, complete=False, weapon=""):
        """Ingest validated local observations from an approved adapter. None ships today."""
        if len(listings) > 50000 or len({x.id for x in listings}) != len(listings):
            raise ValueError("Oversized observation or duplicate IDs in response")
        baseline = not self.state("baseline:" + query_key, False)
        previous_members = set(self.state("members:" + query_key, []))
        events = []
        with self.db:
            for item in listings:
                payload = item.to_dict()
                stable = dict(payload)
                stable.pop("observed_at")
                digest = hashlib.sha256(dumps(stable).encode()).hexdigest()
                row = self.db.execute("SELECT * FROM listings WHERE id=?", (item.id,)).fetchone()
                old = json.loads(row["payload"]) if row else None
                kinds = []
                if old is None:
                    kinds = ["existing" if baseline else "new"]
                else:
                    if any(old[k] != payload[k] for k in ("price", "buyout", "starting_bid")):
                        kinds.append("price_changed")
                    if old["highest_bid"] != payload["highest_bid"]:
                        kinds.append("bid_changed")
                    if old["status"] != payload["status"] or old["seller_status"] != payload["seller_status"] or row["state"] != item.status:
                        kinds.append("status_changed")
                self.db.execute("""INSERT INTO listings VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                    payload=excluded.payload, fingerprint=excluded.fingerprint, last_seen=excluded.last_seen,
                    state=excluded.state, price=excluded.price, kind=excluded.kind""",
                    (item.id, item.weapon, dumps(payload), item.fingerprint, now, now, item.status, item.acquisition, item.kind))
                last = self.db.execute("SELECT digest FROM snapshots WHERE listing_id=? ORDER BY id DESC LIMIT 1", (item.id,)).fetchone()
                if last is None or last[0] != digest:
                    sid = self.db.execute("INSERT INTO snapshots(listing_id,observed_at,payload,digest) VALUES(?,?,?,?)",
                                          (item.id, now, dumps(payload), digest)).lastrowid
                    if old and not kinds:
                        kinds = ["updated"]
                    for kind in kinds:
                        event = {"id": f"{sid}:{kind}", "listing_id": item.id, "kind": kind, "at": now,
                                 "previous_price": old.get("price") if old else None,
                                 "repost_candidate": bool(self.db.execute("SELECT 1 FROM listings WHERE fingerprint=? AND id!=? LIMIT 1", (item.fingerprint, item.id)).fetchone())}
                        self.db.execute("INSERT INTO events VALUES(?,?,?,?,?)", (event["id"], item.id, kind, now, dumps(event)))
                        events.append(event)
            members = {x.id for x in listings}
            if complete:
                for missing in previous_members - members:
                    row = self.db.execute("SELECT state,last_seen FROM listings WHERE id=?", (missing,)).fetchone()
                    if row and row["state"] == "active" and row["last_seen"] < now:
                        self.db.execute("UPDATE listings SET state='potentially_missing' WHERE id=?", (missing,))
                        eid = f"missing:{query_key}:{missing}:{now}"
                        event = {"id": eid, "listing_id": missing, "kind": "potentially_missing", "at": now}
                        self.db.execute("INSERT INTO events VALUES(?,?,?,?,?)", (eid, missing, "potentially_missing", now, dumps(event)))
                        events.append(event)
            self.db.execute("INSERT OR REPLACE INTO scheduler_state VALUES(?,?)", ("members:" + query_key, dumps(sorted(members if complete else previous_members | members))))
            self.db.execute("INSERT OR REPLACE INTO scheduler_state VALUES(?,?)", ("baseline:" + query_key, "true"))
            self.db.execute("INSERT INTO observations(query_key,at,weapon,count,complete) VALUES(?,?,?,?,?)", (query_key, now, weapon, len(listings), complete))
        return events

    def listings(self, limit=10000, offset=0, weapon=""):
        where, params = ("WHERE weapon=?", [weapon]) if weapon else ("", [])
        rows = self.db.execute(f"SELECT payload,state,first_seen,last_seen FROM listings {where} ORDER BY last_seen DESC LIMIT ? OFFSET ?", (*params, limit, offset))
        result = []
        for row in rows:
            data = json.loads(row[0]); data["status"] = row[1]
            result.append({"listing": Listing.from_dict(data), "first_seen": row[2], "last_seen": row[3]})
        return result

    def save_estimate(self, id_, result, now):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO valuations VALUES(?,?,?)", (id_, now, dumps(asdict(result))))

    def history(self, id_):
        return {"snapshots": [dict(r) | {"payload": json.loads(r["payload"])} for r in self.db.execute("SELECT * FROM snapshots WHERE listing_id=? ORDER BY observed_at DESC LIMIT 1000", (id_,))],
                "events": [json.loads(r[0]) for r in self.db.execute("SELECT payload FROM events WHERE listing_id=? ORDER BY at DESC LIMIT 1000", (id_,))]}

    def cache_get(self, key):
        row = self.db.execute("SELECT at,payload FROM cache WHERE key=?", (key,)).fetchone()
        return {"at": row[0], "data": json.loads(row[1])} if row else None

    def cache_put(self, key, data, now):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO cache VALUES(?,?,?)", (key, now, dumps(data)))

    def log_request(self, route, status, message, now):
        with self.db:
            self.db.execute("INSERT INTO request_log(at,route,status,message) VALUES(?,?,?,?)", (now, route, status, message[:500]))
            self.db.execute("DELETE FROM request_log WHERE id < (SELECT COALESCE(MAX(id),0)-2000 FROM request_log)")

    def summary(self):
        counts = {name: self.db.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0] for name in ("listings", "snapshots", "events", "notifications", "watchlists")}
        counts["new"] = self.db.execute("SELECT COUNT(*) FROM events WHERE kind='new'").fetchone()[0]
        counts["catalog_time"] = self.db.execute("SELECT MAX(fetched_at) FROM catalogs").fetchone()[0]
        counts["last_market_update"] = self.db.execute("SELECT MAX(at) FROM observations").fetchone()[0]
        counts["requests"] = [dict(r) for r in self.db.execute("SELECT * FROM request_log ORDER BY id DESC LIMIT 100")]
        return counts

    def notifications(self):
        return [dict(r) for r in self.db.execute("SELECT * FROM notifications ORDER BY at DESC LIMIT 1000")]

    def add_notification(self, event, watchlist_id, title, body, now, max_per_minute=5):
        with self.db:
            if self.db.execute("SELECT 1 FROM notifications WHERE event_id=? LIMIT 1", (event["id"],)).fetchone():
                return False
            count = self.db.execute("SELECT COUNT(*) FROM notifications WHERE at>?", (now - 60,)).fetchone()[0]
            if count >= max_per_minute:
                return False
            cursor = self.db.execute("INSERT OR IGNORE INTO notifications VALUES(?,?,?,?,?,?)",
                (str(uuid.uuid4()), event["id"], watchlist_id, now, title[:200], body[:2000]))
            return cursor.rowcount == 1

    def analytics(self, weapon=""):
        where, params = ("WHERE l.weapon=?", [weapon]) if weapon else ("", [])
        snapshots = self.db.execute(f"SELECT s.observed_at,s.payload FROM snapshots s JOIN listings l ON l.id=s.listing_id {where} ORDER BY s.observed_at DESC LIMIT 20000", params)
        series, bids = [], []
        for row in snapshots:
            item = Listing.from_dict(json.loads(row[1]))
            if item.kind == "direct" and item.price is not None:
                series.append((row[0], item.price, item.id))
            elif item.highest_bid is not None:
                bids.append((row[0], item.highest_bid, item.id))
        obs = [dict(r) for r in self.db.execute("SELECT * FROM observations WHERE (?='' OR weapon=?) ORDER BY at DESC LIMIT 2000", (weapon, weapon))]
        current = [x["listing"].price for x in self.listings(10000, weapon=weapon) if x["listing"].kind == "direct" and x["listing"].price is not None]
        return {"asking": series, "bids": bids, "observations": obs, "prices": current,
                "qualified": self.db.execute("SELECT COUNT(*) FROM valuations WHERE json_extract(payload,'$.qualifies')=1").fetchone()[0]}

    def backup(self, destination, overwrite=False):
        destination = Path(destination)
        if destination.resolve() == self.path.resolve():
            raise ValueError("Backup must use a different file")
        if destination.exists() and not overwrite:
            raise ValueError("File exists; confirm overwrite")
        temp = destination.with_name(destination.name + "." + uuid.uuid4().hex + ".tmp")
        try:
            connection = sqlite3.connect(temp)
            try:
                self.db.backup(connection)
                if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("Backup integrity check failed")
            finally:
                connection.close()
            os.chmod(temp, 0o600)
            os.replace(temp, destination)
        finally:
            temp.unlink(missing_ok=True)

    @staticmethod
    def check_backup(path):
        path = Path(path).resolve()
        if not path.is_file() or path.stat().st_size > 5_000_000_000:
            raise ValueError("Invalid backup file")
        con = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
        try:
            if con.execute("PRAGMA application_id").fetchone()[0] != APP_ID or not 1 <= con.execute("PRAGMA user_version").fetchone()[0] <= SCHEMA_VERSION:
                raise ValueError("Unsupported backup format/version")
            if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("Corrupt backup")
            for table in ("settings", "watchlists", "listings", "snapshots", "migrations", "scheduler_state"):
                con.execute(f"SELECT 1 FROM {table} LIMIT 1")
            for row in con.execute("SELECT payload FROM watchlists"):
                validate_watchlist(json.loads(row[0]))
            for row in con.execute("SELECT value FROM settings WHERE key='preferences'"):
                validate_settings(json.loads(row[0]))
            for row in con.execute("SELECT payload FROM listings"):
                Listing.from_dict(json.loads(row[0]))
        finally:
            con.close()

    def restore(self, source, confirmed=False):
        if not confirmed:
            raise ValueError("Restore requires confirmation")
        source = Path(source)
        if source.resolve() == self.path.resolve():
            raise ValueError("Cannot restore the active database onto itself")
        self.check_backup(source)
        before = self.path.with_name(f"before-restore-{time.time_ns()}.sqlite")
        self.backup(before)
        stage = self.path.with_suffix(".restore.tmp")
        con = sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)
        dest = sqlite3.connect(stage)
        try:
            con.backup(dest)
        finally:
            con.close(); dest.close()
        self.check_backup(stage)
        self.close()
        os.replace(stage, self.path)
        self.__init__(self.path)
        return str(before)

    @classmethod
    def recover(cls, target, source, confirmed=False):
        """Restore when the original cannot be opened; preserve corrupt files verbatim."""
        if not confirmed:
            raise ValueError("Recovery requires confirmation")
        target, source = Path(target), Path(source)
        if target.resolve() == source.resolve():
            raise ValueError("Recovery source cannot be the damaged database")
        cls.check_backup(source)
        stage = target.with_name(target.name + ".recovery-" + uuid.uuid4().hex)
        original = sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)
        temporary = sqlite3.connect(stage)
        try:
            original.backup(temporary)
        finally:
            original.close(); temporary.close()
        cls.check_backup(stage)
        preserved = target.parent / ("damaged-" + str(time.time_ns()))
        preserved.mkdir(mode=0o700)
        for suffix in ("", "-wal", "-shm"):
            file = Path(str(target) + suffix)
            if file.exists(): os.replace(file, preserved / file.name)
        os.replace(stage, target)
        return cls(target), preserved

    def export_file(self, destination, kind, overwrite=False):
        destination = Path(destination)
        if destination.exists() and not overwrite:
            raise ValueError("File exists; confirm overwrite")
        if destination.resolve() == self.path.resolve():
            raise ValueError("Cannot overwrite the database")
        if kind not in {"watchlists", "settings", "listings", "csv"}:
            raise ValueError("Unknown export kind")
        temporary = destination.with_name(destination.name + "." + uuid.uuid4().hex + ".tmp")
        try:
            with temporary.open("w", encoding="utf-8", newline="") as stream:
                if kind in {"listings", "csv"}:
                    cursor = self.db.execute("SELECT payload,first_seen,last_seen,state FROM listings ORDER BY id")
                    if kind == "csv":
                        fields = ["id", "weapon", "kind", "price", "starting_bid", "highest_bid", "buyout", "seller", "seller_status", "published_at", "first_seen", "last_seen", "state", "attributes"]
                        writer = csv.DictWriter(stream, fields, extrasaction="ignore"); writer.writeheader()
                    else:
                        stream.write('{"format":"rivenscope","version":1,"kind":"listings","data":[')
                    first = True
                    for row in cursor:
                        data = json.loads(row[0]) | {"first_seen": row[1], "last_seen": row[2], "state": row[3]}
                        if kind == "csv":
                            data["attributes"] = dumps(data["attributes"])
                            data = {k: "'" + v if isinstance(v, str) and v.startswith(("=", "+", "-", "@", "\t", "\r")) else v for k, v in data.items()}
                            writer.writerow(data)
                        else:
                            if not first: stream.write(",")
                            stream.write(dumps(data)); first = False
                    if kind == "listings": stream.write("]}\n")
                else:
                    data = self.watchlists() if kind == "watchlists" else self.settings()
                    json.dump({"format": "rivenscope", "version": 1, "kind": kind, "data": data}, stream, indent=2, allow_nan=False)
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)

    def import_file(self, source, kind, confirmed=False):
        source = Path(source)
        if source.stat().st_size > 10_000_000:
            raise ValueError("Import exceeds 10 MB")
        value = json.loads(source.read_text())
        if not isinstance(value, dict) or value.get("format") != "rivenscope" or value.get("version") != 1 or value.get("kind") != kind:
            raise ValueError("Unsupported import format/version/kind")
        data = value.get("data")
        if kind == "settings":
            validate_settings(data)
            if not confirmed:
                raise ValueError("Replacing settings requires confirmation")
            self.save_settings(data)
        elif kind == "watchlists":
            if not isinstance(data, list) or len(data) > 10000:
                raise ValueError("Invalid watchlist import")
            attrs = {a["slug"]: a for a in self.catalog("attributes")} or None
            weapons = {w["slug"]: w for w in self.catalog("weapons")} or None
            for item in data:
                validate_watchlist(item, attrs, weapons)
            # Import creates new IDs, never overwrites an existing preset.
            with self.db:
                for item in data:
                    item = dict(item, id=str(uuid.uuid4()))
                    self.db.execute("INSERT INTO watchlists VALUES(?,?)", (item["id"], dumps(item)))
        else:
            raise ValueError("Only settings and watchlists can be imported")

    def prune(self, days, now, confirmed=False):
        if not confirmed or not 7 <= days <= 3650:
            raise ValueError("Valid retention and confirmation required")
        cutoff = now - days * 86400
        with self.db:
            # Preserve latest snapshots and event identities for deduplication.
            self.db.execute("DELETE FROM snapshots WHERE observed_at<? AND id NOT IN (SELECT MAX(id) FROM snapshots GROUP BY listing_id)", (cutoff,))
            self.db.execute("DELETE FROM observations WHERE at<?", (cutoff,))
        return "Old snapshots pruned; current listings and notification identities preserved."
