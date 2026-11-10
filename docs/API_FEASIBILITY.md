# Обновление 0.2.0: подтверждённый пользовательский ответ

10 ноября 2026 пользователь предоставил HTTP/2 200 application/json с 100
Torid-аукционами от `/v1/auctions/search?type=riven&weapon_url_name=torid`.
Реализован экспериментальный opt-in adapter. Поддержка v1, полнота/пагинация и
контекст rolled values остаются непроверенными. Cloud получает challenge.
Схема, checksum, проверки и ограничения: [READINESS_0.2.0](READINESS_0.2.0.md).
Следующий отчёт описывает предыдущее исследование, до получения этого ответа.

---

# API feasibility — 2026-11-09

**Новое исследование 10 ноября 2026:** найден конкретный legacy-кандидат через
QuantFrame и закреплённую Git-ревизию wf-market: `GET /v1/auctions/search`.
Поиск реализован в клиенте; production support/live schema пока не подтверждены,
поскольку текущая cloud-среда блокирует соединение proxy-ответом `CONNECT 403`.
Отсутствие страницы v2 не означает отсутствия технического пути. Подробности,
точные версии и следующий шаг: [QUANTFRAME_REVIEW](QUANTFRAME_REVIEW.md).

**Повторно проверено 2026-11-10:** подтверждённого публичного contract search/detail
API по-прежнему не найдено. Проверены актуальный developer portal, ToS, OAuth,
subscriptions и дерево официального `42bytes-team/wfm-docs`. Свежие источники и
результаты: [CONTRACT_ACCESS_STATUS](CONTRACT_ACCESS_STATUS.md).
Запрос команде WFM подготовлен в [CONTRACT_ACCESS_REQUEST](CONTRACT_ACCESS_REQUEST.md),
но не отправлен; подтверждение доступа не получено.

## Вывод первого этапа

**Публичный поддерживаемый доступ к объявлениям Riven contracts не подтверждён.**
В документации v2 версии 0.25.0, её оглавлении, sitemap и моделях отсутствуют
маршруты поиска/получения контрактов и модель Riven contract. Это не доказывает,
что внутреннего API нет; это означает отсутствие подтверждённого разрешённого
контракта интеграции. Нельзя использовать угаданные маршруты как production API.

v1 прямо объявлен deprecated and unsupported. Старые `/v1/auctions/...` из
сторонних проектов не использованы. Веб-сайт не скрейпится для сбора объявлений.
Проверка ToS читает только официальный документ правил.

Разрешённая ближайшая возможность — публичные справочники оружия/атрибутов.
Они **не содержат объявлений или цен** и не заменяют мониторинг рынка.

## Источники

1. https://docs.warframe.market/
2. https://docs.warframe.market/docs/intro/ — статус v1 и постепенное развитие v2.
3. https://docs.warframe.market/docs/api/overview/ — v0.25.0, headers, 3 req/s, 429/509.
4. https://docs.warframe.market/docs/rules/overview/ — UA, caching, restrictions, 10–20/min expectation.
5. https://docs.warframe.market/docs/websockets/subscriptions/ — newOrders payload = Order.
6. https://warframe.market/tos — API limit **10/min for contracts**, message format/app name.
7. https://docs.warframe.market/docs/api/manifests — public Riven collections.
8. https://docs.warframe.market/docs/data-models — RivenItem, RivenAttribute, Order, User.
9. https://docs.warframe.market/docs/api/orders — ordinary orders, not unveiled Rivens.
10. https://docs.warframe.market/sitemap.xml — no documented contract endpoint page.

ToS HTML returned HTTP 200. Its visible text is JS-rendered; terms were read from
the page's `application-locale-messages` JSON, including `app.tos.api.*`,
`app.tos.contracts.*`, `app.tos.trading.copyPaste`. No browser impersonation.

## Подтверждённые HTTP routes

Base: `https://api.warframe.market`; GET only; no authentication.

| Route | Live result | Contents | Use |
|---|---|---|---|
| `/v2/versions` | 200, 0.25.0 | collection hashes, app versions, updatedAt | cached manifest invalidation |
| `/v2/riven/weapons` | 200, 420 records | id, slug, gameRef, group, rivenType, disposition, reqMasteryRank, English i18n | weapon catalog |
| `/v2/riven/weapon/torid` | 200, Torid | same weapon shape | individual lookup verified; normally use cached collection |
| `/v2/riven/attributes` | 200, 50 records | id, slug, group, prefix/suffix, exclusiveTo, unit, positiveOnly/negativeOnly/positiveIsNegative, i18n | attribute validation |

Evidence: `tests/fixtures/live/evidence.json`, exact responses and SHA-256 hashes
in that directory. Requests were sequential, with at least 6.1 seconds delay
after each response. Header: `RivenScope/0.1.0 (Linux desktop; API feasibility investigation)`.
`Platform: pc`, `Crossplay: true`, `Language: en`. Platform headers do not turn
catalog manifests into PC/crossplay listing coverage.

## Таблица возможностей (все 12 вопросов)

| Question / feature | Status | Confirmed facts / consequence |
|---|---|---|
| 1. Public Riven endpoints | Partial | Four manifest routes above; no confirmed contract route |
| 2. Contract response fields | Unavailable | No public documented contract schema; do not infer from Order |
| 3. Entire market or search | Unavailable | Neither full-market nor per-weapon contract search confirmed; coverage = 0 observed contracts, total unknown |
| 4. IDs / creation / update | Partial | Weapon/attribute IDs available; contract IDs/timestamps unconfirmed |
| 5. Price-change tracking | Blocked live | Local snapshot engine can compare observations, but has no live contract source |
| 6. Highest bids / buyout | Unavailable | No confirmed public contract response |
| 7. Riven properties | Partial | Weapon category/disposition and attribute definitions; no rolled per-contract values, rank/rerolls/MR/polarity |
| 8. Seller data / status | Blocked for contracts | User models exist, but no supported link from contract to seller; status is self-reported per ToS |
| 9. Rate limits | Confirmed | General 3/s; stricter ToS contract 10/min wins over rules' approximate 10–20/min; 429/509, Retry-After, adaptive cooldown |
| 10. Riven WebSocket | Unavailable | Only documented newOrders subscription, explicitly Order payload. Not used |
| 11. Historical data | Blocked upstream | No confirmed Riven historical/transaction route; accumulate local observations only when source becomes available |
| 12. Anonymous use | Partial | All tested manifests public, no token needed; no authorization flow implemented |

## Consequences and implementation policy

- Global and watchlist contract monitoring show `Unavailable: no documented contract API`.
- Catalog sync is an independent, working capability. No catalog success is reported as market scan success.
- Market data, valuations, deals, price graphs and trade actions stay empty/unavailable in a fresh installation.
- Local filter, storage, valuation, risk and notification engines are tested with explicitly synthetic
  controlled cases. Synthetic listings are never shipped into the user's database/UI.
- Contract source is a capability interface. Activating it requires a newly documented route,
  live response fixtures, review of access/ToS and adapter tests. There is no hidden switch
  for speculative v1 access or custom URL injection.
- Use one request scheduler, no concurrent API requests, >=6.1 seconds between starts
  (conservative for all routes), persistent cooldown, bounded exponential retry with jitter.
- Cache manifests and check versions at most hourly. Stop network work on Stop/window close.
- No verified transaction price claims, sell-through estimates, guaranteed profit, or sold inference.
- ToS requires the website's current copy-message format plus application name. Without a
  verified contract message template, automatic message generation is disabled; website navigation
  remains available. No automatic trading, bids, messages, login, telemetry or publication.

## Phase acceptance

DONE: primary sources reviewed, ToS extracted, allowed routes live-tested, fixtures recorded,
capability decision made before main development. Contract access is BLOCKED, not a passed feature.
