# Architecture decision

## Stack comparison on the actual host

| Approach | Wayland / UI | Memory & tables | Networking / SQLite / analytics | Build cost |
|---|---|---|---|---|
| Python + PySide6 | Native Qt6 Wayland, already installed | One runtime, virtual QTableView; no embedded browser | QtNetwork asynchronous; stdlib SQLite/statistics; optional future Python ML | Small application wheel; system Qt dependency |
| Tauri + React | WebKitGTK works on Wayland | Lower than Chromium; large tables require web virtualization | Rust async/SQLite plus JS charting; Python ML needs bridge | Rust/WebKit toolchain not currently installed; more language boundaries |
| Electron + React | Chromium Ozone Wayland | Typically largest baseline RAM/package | Mature async/SQLite/chart ecosystem | Bundled Chromium, native SQLite packaging and extra attack surface |
| C++ + Qt | Excellent native support | Small runtime overhead | Equivalent Qt networking; more numerical/test implementation effort | Compiler/toolchain complexity; Python ML bridge later |

**Decision:** Python 3.14 + PySide6 6.12, Qt Widgets/QtNetwork, SQLite, standard-library
statistics and unittest. No browser/GPU scene graph needed. Qt-painted charts and virtual
tables; no pandas/NumPy required for a conservative first estimator. The distribution
already supplies PySide6 and Qt6-Wayland. A user venv is used only for build tools.

## Boundaries

- `domain.py`: canonical LOCAL observation objects, not a claimed remote contract schema.
- `filters.py`: validated nested AND/OR/NOT AST, tri-state missing-value semantics;
  attribute type/sign restrictions from the live manifest. No eval.
- `valuation.py`: exact weapon + compatible measurement context + signed attribute sets;
  numerical distance, recency and reroll weights, robust outlier rejection, weighted
  median/quantiles. No invented utility weights or cross-variant normalization.
- `storage.py`: versioned SQLite transactions, snapshots/events, catalogs, settings,
  watchlists, notification dedup, observations, valuations. XDG data/state directories.
- `analysis.py`: local observation pipeline connecting persistence, valuation and
  notification decisions. Recomputes each preset's valuation using its own observation-age
  and sample thresholds. The worker rejects incoming contract batches while the verified
  contract capability is unavailable; tests do not bypass this in the production UI.
- `scheduler.py`: weighted fair selection with aging, request coalescing, persistent cache,
  one active request, shared pacing, retry budget, global Retry-After and block cooldown.
- `network.py`: asynchronous QNetworkAccessManager, strict allowlist, bounded payload,
  timeouts, cancellation; parse/store on database worker thread.
- `service.py`: serialized worker QThread for SQLite and analytical tasks; immutable
  result messages to GUI. No daemon, subprocess workers, autostart or background tray.
- `ui/`: English native dark interface, dashboard, catalog/market, watchlists with visual
  tree builder, details, analytics, notifications and settings/data management.
- `notifications.py`: persisted event identity, thresholds, per-watchlist overrides,
  rate cap, non-blocking libnotify/freedesktop desktop notifications through a bounded
  QProcess invocation of `notify-send`, and local WAV sound. Child processes terminate on close.

## Source availability contract

Current release has no network contract adapter. `CONTRACTS_AVAILABLE=False` is a
product capability declaration, not a fake integration. Local engines can be tested
and reused, but their live-market functions remain blocked and explicitly labelled.
Only verified v2 manifest routes are on the network allowlist. No API custom-URL setting.

## SQLite layout / migration

Schema v1: metadata; settings; catalogs; watchlists; listings; snapshots; events;
notifications; valuations; observations; request_log; scheduler_state.
Indexes: weapon/last_seen, snapshot listing/time, event listing/time, notification time,
observation weapon/time, request time. JSON stores extensible domain/AST payloads;
queried selectors have indexed columns. Foreign keys + WAL + busy_timeout.
Schema v2: cached API responses plus cache age/hash; migration ledger.

Connections belong to the worker thread. Atomic transactions for each observation batch,
no dedup reset on restart. Baseline membership is query-specific; partial search absence
never means removal. Only complete validated snapshots may mark `potentially_missing`.
Reposted identity fingerprints are advisory, never evidence of sale or proof of equivalence.

Backups use SQLite backup API to temporary file, integrity/version validation and atomic
replacement with explicit confirmation. Restore validates and stages first, creates an
automatic pre-restore backup, closes DB, atomically replaces, reopens/migrates. Invalid or
newer DB is never silently erased. Corruption presents recovery UI preserving original files.

## Valuation interpretation

Estimate is comparable **asking-price** value, not executed sale/resale proceeds. Fixed-price
listings only form comparables; auction bids never enter fixed-price statistics. Buyout is
an acquisition option, not a confirmed sale. Same weapon, rank, attribute-count/signature,
measurement context/disposition required; unknown context => Insufficient data. Same
negative attribute is matched, rather than inventing a utility score. Effective sample
count, weighted quantiles, robust spread, age and similarity determine confidence capped
below certainty. Cross-relist duplicates are conservatively collapsed by seller/fingerprint.

## Performance / lifetime

QtNetwork and timers are event driven. DB, filtering/export/valuation run in worker thread.
Virtual models materialize only bounded page results. Cache/request logs are bounded;
history retention is configurable with explicit data-management actions. One application
instance per data directory prevents separate request budgets. Stop aborts active replies,
clears pending tasks and retry timers. Close waits for bounded worker completion and flushes DB.

## Verification policy

Unit tests: domain/filter/statistics/limits. Integration: real SQLite/migrations/export,
controlled transport faults, scheduler and worker lifecycles. UI: QtTest events and window
checks. Live: opt-in documented manifests only. Packaging: reproducible wheel/archive,
desktop validation, installed terminal/menu launch. Soak: timed controlled repeated updates,
heartbeat/RSS reporting. Test fixtures cannot become production data automatically.
