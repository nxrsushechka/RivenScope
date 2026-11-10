# Запрос о поддерживаемом доступе к Riven contracts

Дата подготовки: 2026-11-10. **Статус: черновик, не отправлен. Ответ WFM не получен.**

## Куда обратиться

Официальная документация направляет вопросы сторонних разработчиков в Discord:
**https://discord.gg/M7BHnPS**.

Подтверждение канала: https://docs.warframe.market/docs/intro/#questions-and-support
и https://docs.warframe.market/docs/rules/overview/#questions.
Конкретное имя developer-канала не установлено; его следует выбрать по правилам сервера.

У текущей среды разработки нет подключённого инструмента отправки сообщений в
Discord от пользователя. Пароль или токен Discord для этой задачи не требуется
передавать агенту. Ни сообщения, ни issues, ни исходники проекта не публиковались.

## Готовый текст для отправки

```text
Hi! I'm developing RivenScope, a personal, unpublished Linux desktop app for
Riven research: saved searches, local asking-price comparisons and optional
notifications while its window is open. It does not automate trades, bids or
messages, mirror the website, or use other pricing services.

I reviewed the current v0.25.0 docs, rules, ToS and the public wfm-docs repository
on 2026-11-10. The public Riven weapon/attribute manifests work, but I could not
find a supported public contract search/detail route or Riven-contract schema.
I understand that v1 is deprecated/unsupported, newOrders is not a contract
feed, and public OAuth client registration is not open.

Could you clarify:
1. Is there a currently supported and permitted read-only API for third-party
   access to unveiled Riven contracts? If so, where are its exact routes,
   request/response schema and access requirements documented?
2. If this is not public yet, is there an approved integration/access process,
   or should contract monitoring remain disabled until it is documented?
3. What search coverage, pagination/cursor semantics and refresh/cache policy
   are supported? Is the ToS limit of 10 contract requests/minute the applicable
   cap, and is that limit shared by IP, app, token or endpoint?
4. Are contract IDs, created/updated timestamps, fixed prices, highest bids,
   buyout prices and seller platform/crossplay/status available? Is there a
   documented contract-specific WebSocket feed or historical data source?
5. What is the current supported copy/trade-message format for Riven contracts,
   including the required third-party application identification?

The application currently leaves contract monitoring disabled. It uses a
descriptive RivenScope/0.1.0 User-Agent, cached public manifests, one request at
a time, no more than 10 HTTP starts/minute, and backoff/Retry-After handling.
The intended market is PC with crossplay. No authentication is currently used.
Please point me to the permitted integration path; I do not want to rely on
undocumented routes or treat ordinary orders as Riven contracts. Thank you!
```

## Что сохранить из ответа

Нужны ссылка на официальную документацию либо конкретное подтверждение владельцев
API с точными маршрутами, доступом и ограничениями. Ссылка на чужой проект, работающий
HTTP 200 или наличие scope `contracts` сами по себе не решают эти вопросы.
Если команда разрешит временный legacy-путь, нужно уточнить точные разрешённые
операции, срок/статус поддержки и требования к клиенту; нельзя подразумевать это
разрешение из общего текста ToS.

После ответа следует:
1. Обновить `API_FEASIBILITY.md` с источником и датой подтверждения.
2. Проверить разрешённый read-only маршрут с собственным UA и общим request budget.
3. Записать настоящий ответ как fixture и проверить поля/пропуски/пагинацию.
4. Реализовать adapter к локальной analysis pipeline и серверно-локальный план поиска.
5. Прогнать live acquisition → storage → filtering → valuation → alerts → shutdown.
6. Активировать только фактически подтверждённые возможности и обновить установленный release.
