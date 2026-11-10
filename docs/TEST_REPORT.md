# Актуальная проверка 0.2.0

71 passed, 0 failed, 0 skipped. Включены parser на 100 реальных записях и Qt HTTP →
SQLite → GUI replay. Записанный HTTP 200 получен пользователем на Omarchy;
cloud live search всё ещё получает challenge. Подробности: [READINESS_0.2.0](READINESS_0.2.0.md).
Ниже — исторические отчёты 0.1.x.

---

# Актуальная проверка 0.1.1

Новый полный прогон из восстановленных исходников: **63 passed, 0 failed,
0 skipped**, включая packaging. Среда: cloud Linux / Python 3.12 / Qt 6.8.3.
Детали: [READINESS_0.1.1](READINESS_0.1.1.md). Следующий отчёт исторический,
относится к 0.1.0 и прежней машине Omarchy; native-результаты здесь не повторены.

---

# Отчёт о проверках

Дата завершения проверок: **2026-11-10**. Среда: Omarchy 4.0.6, Hyprland 0.56.2,
Wayland, Python 3.14.8, PySide6/Qt 6.12.0. Проверки контрактов отделены от справочников.

## Итог

**53 автоматических теста: 53 passed, 0 failed, 0 skipped.**

| Группа | Количество | Проверка |
|---|---:|---|
| Unit | 21 | Parsing подтверждённых fixtures, domain/input validation, nested filters, valuation, limits/fairness |
| Integration | 23 | SQLite/migrations/backup/import/export, локальная analysis pipeline, Qt scheduler/worker, настоящий Qt HTTP против контролируемого localhost server |
| UI | 5 | Навигация/каталог, визуальные фильтры, watchlist, start/stop/close, resize, 100 000 строк |
| Packaging | 4 | Reproducibility, содержимое wheel, install/update/uninstall/paths with spaces, защита чужих файлов |

Команда полного прогона:

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=src RIVENSCOPE_PACKAGING=1 \
  python -m unittest discover -s tests -t . -v
```

Сохранённый журнал: `test-artifacts/test-suite.log` (53 теста, 12,865 с).
Packaging tests отключены по умолчанию и включаются переменной выше.
Тест повреждённой БД намеренно создаёт повреждение в `/tmp/opencode`; это проверка
восстановления, а не обнаруженная ошибка пользовательской базы.

## Уже подтверждено

- Исследование четырёх документированных API routes: HTTP 200 с собственным UA.
- Нативное окно на Wayland: три последовательных HTTP 200 через production QtNetwork,
  420 оружий, 50 атрибутов, ноль контрактов, корректное закрытие worker.
- Parsing fixtures, вложенные фильтры, signed attribute matching, missing values,
  risk/valuation/auction separation, request limits/fairness/backoff.
- SQLite migration v1→v2 с backup, persistence, snapshot dedup, повторные циклы цены,
  потенциальное исчезновение только при complete snapshot, импорт/экспорт/restore.
- Реальный Qt HTTP transport против локального контролируемого сервера: 429,
  Retry-After, 503, timeout, cancellation, response-size limit, reconnection.
- UI: navigation, visual filter roundtrip, watchlist save, настройки, resize,
  start/stop/close и виртуализированная таблица 100 000 контролируемых строк.
- 3-минутный controlled soak: 721 refresh, 0 ошибок, RSS после прогрева +0,024 МБ,
  heartbeat p99 23,9 мс, max 131,8 мс; worker завершён.
- 10-минутный controlled soak: 2 399 refresh, 0 ошибок, RSS 271,9→277,9 МБ,
  разброс RSS после прогрева 1,09 МБ; CPU 57,45 с за 600 с нагрузки;
  heartbeat p99 26,71 мс, max 142,51 мс. Worker завершён.
- Контролируемая локальная цепочка ingestion → snapshots → estimate → notifications:
  baseline подавляет уведомления; новые/ценовые события не дублируются; пересечение
  пресетов даёт одно уведомление; для пресета применяется его собственный age cutoff.
- Настоящее системное уведомление принято freedesktop-сервисом через libnotify;
  тестовый WAV прошёл loading/play/finish, статус Ready, предупреждений нет.

## Проверка установленной версии

`tools/verify_installation.py` проверил настоящий пользовательский release:
- Команда `rivenscope --version` возвращает `0.1.0`.
- Installed application запрашивает только versions/weapons/attributes; HTTP 200.
- База `~/.local/share/rivenscope/rivenscope.sqlite`: 420 weapons, 50 attributes,
  0 contracts, `PRAGMA integrity_check = ok`.
- `gtk-launch rivenscope` открывает окно класса `rivenscope`; `xwayland=false`.
- Процесс запускается из `~/.local/share/rivenscope-app/current/launch.py`, а не из source tree.
- Закрытие окна завершает процесс; сторонние окна/настройки Hyprland не затрагиваются.
- Native RSS при проверке окна: около 283 МБ (Qt/аудиобиблиотеки включены).
- Python sources совпадают с установленным release.
- Ярлык проходит `desktop-file-validate`; единственная основная категория — Network.
- Установка/обновление сохраняют пользовательские данные; schema migration и restore
  создают предварительные backup-файлы.

Артефакты диагностики:
`test-artifacts/installed.json`, `channels.json`, `soak.json`, `soak-10min.json`.
Native screenshots: `/tmp/opencode/rivenscope-native-live-fixed/dashboard.png`
и `catalog.png`. Записанные API ответы и их provenance: `tests/fixtures/live/`.

Повторная сборка wheel и source archive на одинаковых исходниках/toolchain дала
одинаковые SHA256. Финальные суммы находятся в `dist/SHA256SUMS`.

## Найденные и исправленные дефекты

1. Реальные API slugs содержат скобки и `/`: парсер исправлен по fixtures.
2. Ошибка передачи layout вместо sidebar widget при первом GUI запуске: исправлена;
   добавлено безопасное завершение worker при startup exception.
3. 100k строк: Qt/Python comparator давал ~2,9 с на сортировку. Переведено на
   однократную key-оценку строки; регрессионный тест проходит.
4. Qt 6.12 `QNetworkReply.rawHeader` требует `str`: исправлено, повторный live smoke успешен.
5. Python QtDBus не предоставляет ожидаемые typed-marshalling методы. Вместо
   непроверенной реализации используется установленный libnotify через асинхронный
   ограниченный QProcess; реальная доставка проверена успешно.
6. Проверочный скрипт menu launch ждал унаследованный stdout открытого GUI;
   вывод `gtk-launch` перенаправлен в DEVNULL. Учтён новый Lua dispatch синтаксис
   Hyprland 0.56. После исправлений полный installed-launch check прошёл.

Известных невыполненных исправлений по обнаруженным тестовым сбоям нет.

## Не подтверждено из-за API

Live Riven contracts, реальные сделки/цены/ставки, полный/частичный contract search,
live pricing accuracy и trading-message format. Они не засчитываются как пройденные
на основании синтетических тестов. Подробнее: [LIMITATIONS](LIMITATIONS.md).

Soak длился 10 минут на контролируемых данных, а не дни реального рынка.
Он выполнен на этапе QA до последних локальных UI/pipeline изменений; финальные
изменения покрыты полным автоматическим прогоном и installed-launch проверкой.
Автотест не подтверждает, что пользователь действительно услышал звук/увидел popup.
