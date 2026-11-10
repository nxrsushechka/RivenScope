# RivenScope 0.2.0 — экспериментальный legacy search

## Новое доказательство доступа

Пользователь предоставил ответ собственного read-only curl-запроса на Omarchy:
`GET https://api.warframe.market/v1/auctions/search?type=riven&weapon_url_name=torid`.
Headers: HTTP/2 200, application/json, Date 2026-11-10T12:25:11Z.
В `payload.auctions` — 100 различных открытых объявлений Torid, все с
`is_direct_sell=false`, `buyout_price=null`; у 21 есть `top_bid`.
SHA256 тела: `155a76adfcc53e41afd6203b4cc39fe6b9e69ddc86fb33f32bfca91da9f03ca0`.

Это подтверждает ответ маршрута на машине пользователя в момент съёмки. Не
подтверждает полноту выдачи, pagination, постоянную доступность и официальную
поддержку v1. В cloud прямые запросы всё ещё получают Cloudflare challenge.

Исходное тело сохранено без изменений в `tests/fixtures/live/torid-auctions-2026-11-10.json`;
метаданные и checksum — в `torid-auctions-evidence.json`. Полные headers с cookies
не включены в репозиторий. Fixtures не входят в wheel и автоматически не загружаются
в рабочую базу.

## Реализовано

- Парсер всего envelope с проверкой IDs, дубликатов, оружия, атрибутов, чисел,
  boolean flags, timezone timestamps, seller/platform/crossplay. Неизвестная схема
  отклоняется до сохранения каких-либо наблюдений.
- Сетевой запрос только read-only GET к фиксированному search route с параметрами
  type и weapon_url_name. Собственный User-Agent, общий существующий budget 10/мин,
  Retry-After/backoff, отмена запросов и остановка вместе с окном.
- Явный opt-in в Settings: legacy searches выключены по умолчанию. Можно выбрать
  slugs оружий, `*` для всего каталога, интервал на оружие. Включённые watchlists
  добавляют оружия/категории и приоритеты. Одинаковые запросы объединяются; фильтры
  применяются локально к частичной выдаче.
- В Dashboard отображаются legacy mode, сохранённые объявления, число оружий с
  записанными поисками и непроверенные оружия. Никакого обещания полного рынка.
- Изменение scope/preferences/presets останавливает мониторинг и очищает старую
  очередь; после сохранения нажмите Start monitoring снова.
- Таблица и детали показывают starting/highest bid отдельно от цены покупки.
  Начальная ставка не используется как acquisition price; direct listing без
  явного buyout также не получает придуманной цены.
- Каждый search считается partial независимо от длины выдачи. Отсутствие строки
  в следующем ответе не переводит её в missing/closed и не означает продажу.
- Явный импорт реального сохранённого ответа через `tools/import_contract_snapshot.py`.
  Нужна исходная дата съёмки; более старый снимок не заменяет свежие наблюдения.

## Оценки стоимости

Legacy response содержит сырые rolled values, но не устанавливает однозначно
их display/normalization context и применённый disposition. Эти поля в канонической
модели остаются неизвестными. Estimator консервативно возвращает Insufficient data;
расчёт «выгодных предложений» и автоматические deal alerts для этих данных не
заявляются работающими. Кроме того, предоставленный ответ содержит только аукционы
без выкупа: определённая цена покупки отсутствует у всех 100 записей.

## Проверки

Полный прогон: **71 passed, 0 failed, 0 skipped**, включая clean packaging,
source-archive rebuild, installer, обновление/повторную установку и data retention.
Среда: cloud Linux, Python 3.12, PySide6/Qt 6.8.3, offscreen.
Лог: `test-artifacts/test-suite-0.2.0.log`.

Новые проверки: checksum/разбор всех 100 записей, 21 ставка, неизвестный roll context,
buyout/direct semantics на явно контролируемых изменениях, malformed/duplicate
records, atomicity, partial response retention, opt-out, scope/coalescing/priority,
refresh interval. Functional test выполняет настоящий Qt HTTP-запрос к локальному
серверу, отдающему записанное тело WFM, и проверяет 100 строк в GUI/SQLite и отсутствие
торговых уведомлений. Это controlled replay, а не новый live-запрос к WFM.

В отдельный cloud-профиль `/workspace/onboarding-rivenscope/torid-020-profile`
импортированы предоставленные реальные 100 объявлений с датой исходного ответа.
Integrity check: ok, 100 baseline events, 0 notifications. GUI snapshot:
`test-artifacts/torid-market-0.2.0.png` — 100 rows, 21 known bids, 0 acquisition prices.
Legacy mode в этом профиле остаётся выключенным; приложение не делает запросов
без явного запуска.

## Запуск на Omarchy

Собрать и установить текущие исходники по INSTALLATION, сохранив существующую БД.
В GUI: Settings → Preferences → Monitoring → Enable experimental legacy v1 searches;
weapon slugs `torid`, минимальный интервал 10 минут; Save preferences, затем
Dashboard → Start monitoring. В Market Monitor → Contracts видны результаты.
Для широкого обхода можно указать `*` или использовать enabled watchlists; при
420 оружиях и 10 запросах/мин полный проход занимает минимум 42 минуты плюс
catalog requests, retries и cooldown. Не запускайте одновременно отдельные probes.

При 401/403/429 клиент учитывает pause/cooldown; browser impersonation, captcha
bypass и JWT/cookie заимствование не используются. Для native runtime/Wayland,
звука и desktop notifications 0.2.0 нужны проверки на целевой машине.

## Следующие задачи

1. Запустить собственную сборку 0.2.0 на Omarchy и проверить повторный live search.
2. Проверить direct/buyout responses, предел/пагинацию выдачи и актуальные условия
   legacy-доступа. При неоднозначности уточнить поддержку у команды WFM.
3. Установить display context числовых rolled attributes и корректную нормализацию,
   прежде чем включать valuation. Затем проверить точность на реальной выборке.
4. Проверить длительное накопление настоящей истории, price changes и trade alerts.
5. Подтвердить актуальный шаблон trade message. Автоматическая торговля не реализуется.
