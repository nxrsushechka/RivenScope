# Итог разработки RivenScope 0.1.0

Дата: 2026-11-10.

## Результат

Приложение собрано, установлено в пользовательский каталог и проверено на Omarchy
в нативном Wayland. **Полная готовность исходного ТЗ не заявляется:** поддерживаемая
живая интеграция Riven contracts не подтверждена официальным API. Это блокирует
основную задачу поиска недооценённых рыночных Riven, несмотря на готовые локальные модули.

## Стек

Python 3.14, PySide6/Qt6 Widgets + QtNetwork, SQLite, стандартная статистика Python,
виртуализированные QTableView, CPU-painted charts, libnotify и QSoundEffect.
Без браузерного runtime, токенов, телеметрии, daemon и Linux autostart.

## Реализовано и проверено

- Настоящие v2 справочники: 420 оружий / 50 атрибутов в проверенной выборке.
- Асинхронная сеть, кэш, единый бюджет 10 запросов/мин, backoff/jitter/Retry-After,
  cancellation и перезапуск, остановка вместе с окном.
- Английский тёмный UI, каталог/детали, Dashboard, Watchlists, Analytics,
  Notifications, Settings, сохраняемая раскладка и плотность таблиц.
- Визуальные вложенные AND/OR/NOT-фильтры, сохранение/редактирование/копирование/
  включение/импорт/экспорт пресетов, атрибутная валидация и missing-value semantics.
- SQLite с миграциями, наблюдениями/snapshots/events/valuation/notification history,
  CSV/JSON, согласованными backup/restore и восстановлением после повреждения.
- Локальные статистика/дедупликация/risk/notification pipeline проверены на явно
  контролируемых сценариях. При отсутствии данных цена не генерируется.
- Desktop/in-app/sound channels, duplicate suppression, per-preset thresholds.
- Wheel/source release, checksum verification, staged install, безопасное обновление,
  desktop launcher/icon, удаление с сохранением пользовательских данных.

## Тестирование

53 автоматических теста прошли. Live manifest smoke прошёл. Реальный installed
terminal/menu launch проверен, `xwayland=false`, после закрытия процесс завершается.
10-минутный controlled soak: 2 399 обновлений, 0 ошибок, ~1,1 МБ разброса памяти после
прогрева, UI heartbeat p99 ~26,7 мс. Подробности: `TEST_REPORT.md`.

## Ограничено / не проверено

- Нет поддерживаемого контрактного маршрута: live global/watchlist monitoring,
  настоящие объявления/продавцы/ставки/цены, deal alerts и рыночная точность valuation
  остаются заблокированными. Показанный охват — 0 контрактов, не «полный рынок».
- Нет официального Riven WebSocket feed, исторических исполненных Riven-сделок и
  подтверждённого актуального trade-message template.
- Remote update feed не настроен — проект не опубликован.
- Нет многодневной реальной рыночной эксплуатации; аудиопайплайн проверен без
  подтверждения субъективной слышимости.
- Неисправленных обнаруженных критических ошибок после выполненных проверок нет;
  отсутствие контрактной интеграции является существенным функциональным ограничением.

## Запуск и данные

```bash
rivenscope
```

Или **RivenScope** в меню Omarchy. **Start catalog sync** включает доступную
синхронизацию. Исходники: `/home/nxrsu/Work/RivenScope_AI`.
База: `/home/nxrsu/.local/share/rivenscope/rivenscope.sqlite`.
Release artifacts: `/home/nxrsu/Work/RivenScope_AI/dist/`.

Backup: **Settings → Data & backup → Back up database…**.
Обновление: `docs/UPDATING.md`; собрать локальные исходники и запустить
`python tools/install.py`, предварительно закрыв приложение и сделав backup.

## Следующий полезный этап

Получить официальный поддерживаемый доступ к contracts, реализовать проверенный
adapter и реальные fixtures, затем проверить поиск/оценки/оповещения целиком на
накопленных наблюдениях. Для этого не следует включать старый неподдерживаемый v1
или выдавать обычные orders за контракты.
