# RivenScope — итог этапов, 2026-11-10

## Текущий этап — экспериментальный поиск 0.2.0

- [x] Проверить пользовательские HTTP headers и 100 реальных Torid-аукционов.
- [x] Реализовать строгий parser и opt-in read-only legacy search.
- [x] Подключить scope/watchlists, общий budget, interval/coalescing и partial semantics.
- [x] Импортировать реальный snapshot в отдельный профиль и проверить GUI.
- [x] Полный прогон: 71 passed, 0 skipped, включая packaging.
- [ ] Проверить повторный live search сборкой 0.2.0 на Omarchy; cloud получает challenge.
- [ ] Подтвердить direct/buyout, pagination и raw-roll normalization перед valuation.

Подробности: [READINESS_0.2.0](docs/READINESS_0.2.0.md).
Следующий этап 0.1.1 и остальные отчёты ниже сохранены как история.

## Текущий этап — восстановление и исправления 0.1.1

- [x] Восстановить исходники GUI/app/analysis/assets из сверенного старого релиза.
- [x] Удалить из дерева отслеживаемые build/dist/bytecode с сохранением старых файлов вне checkout.
- [x] Собирать в чистом staging; проверить source archive → идентичный release.
- [x] Исправить возврат исчезнувших объявлений и аналитику неактивных/устаревших цен.
- [x] Отвязать valuation comparables от открытой страницы таблицы; проверить кэш.
- [x] Ускорить повторяемые comparisons; ограничить страницу 250 строками, проверить базу 10 000 объявлений.
- [x] Проверить отмену активного расчёта и очереди при закрытии; сохранять previous при повторной установке.
- [x] Исправить HTTP header-case test, runtime установщика и изолированные профили.
- [x] Закрепить dev Qt, добавить CI; выполнить локально полный прогон: 63 passed, 0 skipped.
- [x] Controlled soak 180 с: 682 refreshes, 0 ошибок, RSS после прогрева 0,56 МБ, heartbeat p99 69 мс.
- [x] Проверить свежий официальный docs Git HEAD: новых contract routes нет.
- [ ] Выполнить native menu/audio/notifications checks 0.1.1 на Omarchy.
- [ ] Подключить и проверить реальный contract adapter после подтверждения доступа WFM.

Подробности и оставшиеся ограничения: [READINESS_0.1.1](docs/READINESS_0.1.1.md).
Отчёты ниже описывают **историческую проверку 0.1.0**, а не новый native-прогон.

Status keys: DONE = implemented and checked; BLOCKED = upstream capability absent;
IN PROGRESS = active work; PENDING = not yet verified. No blocked feature counts as done.

| Phase | Tasks | Status |
|---|---|---|
| 1 API feasibility | Official docs, rules, ToS, live manifest evidence, capability matrix | DONE; contract access BLOCKED |
| 2 Architecture | Stack comparison, module boundaries, SQLite schema, limitations | DONE |
| 3 Foundation | Package, Qt GUI, XDG storage, logging, migrations | DONE; initial launch and SQLite checks passed |
| 4 Integration | Public v2 catalog, async transport, fair scheduler, retry/cache | DONE для справочников, включая установленный native Wayland release; contracts BLOCKED |
| 5 Monitoring & filters | Capability-aware controls, watchlists, nested visual filters, discovery | Local engines and visual preset checks DONE; live contracts BLOCKED |
| 6 Valuation | Robust comparable estimator, risk, insufficient-data behavior | Controlled statistical tests DONE; real market validation BLOCKED |
| 7 Analytics | Local observation charts and price distributions | DONE для локальных данных; реальные contract observations BLOCKED |
| 8 Notifications & trading | Persistent deduplication, channels, explicit user actions | DONE для каналов/suppression; реальная доставка и аудиопайплайн проверены; live deals / official message BLOCKED |
| 9 Advanced UI | Virtual tables, saved layout, settings, data tools | DONE; native visual inspection, resize и 100k-row checks passed |
| 10 QA | Unit/integration/UI/live/packaging/soak checks and defect fixes | DONE в доступном объёме: 53 tests, 10-min controlled soak; реальные contract tests BLOCKED |
| 11 Installation | Release artifact, per-user launcher/icon, installed launch, manuals | DONE; terminal/menu native Wayland launch and clean shutdown confirmed |

## Phase 1 report
- Omarchy 4.0.6, Hyprland/Wayland, Python 3.14.8, PySide6/Qt 6.12 already installed.
- Official v2 docs describe Riven weapon and attribute manifests, not contract search.
- v1 explicitly deprecated and unsupported. New-orders WebSocket is not a contract feed.
- Probing only documented public routes with an explicit RivenScope User-Agent.
- Four HTTP 200 responses recorded: versions, 420 weapons, 50 attributes, Torid.
- ToS returned HTTP 200; embedded official terms inspected; stricter contract limit 10/min.
- `docs/API_FEASIBILITY.md` completed before application development.

## Phase 2 report
- Selected installed native Python/PySide6 + asynchronous QtNetwork + SQLite.
- `docs/ARCHITECTURE.md` compares alternatives and defines thread, source and storage boundaries.
- Source-dependent features stay BLOCKED; local functionality will be implemented and tested explicitly.

## Phases 3–6 report
- 31 initial parsing, SQLite, migration, backup, discovery, filtering, pricing and scheduler tests passed.
- Real fixtures exposed parentheses/slashes in WFM slugs; corrected parsing to accept the verified source.
- Initial GUI construction defect found by offscreen launch and fixed; startup exceptions now stop worker safely.
- Controlled Qt integration verifies reconnection, Retry-After, 25 repeated start/stop cycles, persistent cache and corrupted-database recovery.
- Pricing uses same context/signature comparables, outlier rejection and asking-price uncertainty; no populated production contract table.

## Phases 7–9 report
- Six English UI sections, catalog details, virtual market table, visual AST editor, presets and settings are implemented.
- SQLite analytics separates fixed-price snapshots and bids; empty history is explicitly labelled.
- 100,000-row table test caught slow cross-language comparator sorting; switched to one key evaluation per row and verified the regression test passes.
- Native live/catalog, desktop notification delivery and completed audio playback pipeline passed.
- Локальная цепочка observation → valuation → alert проверяется отдельно от API. Для каждого
  пресета valuation пересчитывается с его собственным максимальным возрастом данных.

## Phases 10–11 report
- Полный прогон: **53 passed, 0 failed, 0 skipped**; журнал `test-artifacts/test-suite.log`.
- Controlled soak 600 с: 2 399 обновлений, 0 ошибок, RSS после прогрева +1,09 МБ,
  UI heartbeat p99 26,7 мс, штатное завершение worker.
- Повторная сборка одинаковых исходников даёт идентичные SHA256 wheel/source archive.
- Проверены staged install, обновление, запуск в пути с пробелами и удаление с сохранением данных.
- Реальная установка: `~/.local/bin/rivenscope`, desktop entry, SVG icon, immutable versioned releases.
- `gtk-launch rivenscope` открыл установленный Python/Qt release: `xwayland=false`.
- Закрытие адресованного окна завершило процесс. Пользовательская SQLite: integrity `ok`,
  420 weapons, 50 attributes, 0 contracts. Исходники Python совпадают с установленными.
- Полный архив и локальная установка доступны; GitHub publication/remote update source отсутствуют.

## Definition of Done — оговорка
Доступные локальные функции и установка завершены. **Исходная полная Definition of Done
не выполнена:** ключевые live-market сценарии заблокированы отсутствием подтверждённого
поддерживаемого публичного contract API. Это не засчитывается как реализованный мониторинг.
Следующий существенный этап — официально поддерживаемый contract adapter и его реальные тесты.

## Phase 12 — официальный доступ к Riven contracts

- [x] Повторно проверить live документацию, sitemap, subscriptions и регистрацию OAuth.
- [x] Найти правильный официальный репозиторий документации: `42bytes-team/wfm-docs`.
- [x] Проверить указанные в документации alternatives: groups/users и Electron example.
- [x] Сохранить свежие первичные источники с timestamp/SHA256 и заключением.
- [x] Подготовить запрос владельцам API с условиями интеграции и конкретными вопросами.
- [ ] Отправить запрос в официальный Discord — инструмента отправки в текущей среде нет.
- [ ] Получить ответ/документацию поддерживаемого доступа — внешняя зависимость.
- [ ] При подтверждённом доступе проверить route/schema/limits, написать adapter и live tests.

Статус: **исследование DONE; ожидание внешнего ответа / контрактный adapter BLOCKED**.
Упоминание contracts в rules/groups/scopes не подтверждает доступность search endpoint.

Результат: `docs/CONTRACT_ACCESS_STATUS.md`, готовый неотправленный запрос
`docs/CONTRACT_ACCESS_REQUEST.md`, восемь свежих ответов HTTP 200 с SHA256 в
`docs/evidence/2026-11-10T065639Z-contract-access/`. Установленный runtime не изменён.
