# QuantFrame и альтернативная ревизия wf-market — 10 ноября 2026

**Обновление 0.2.0:** пользователь предоставил HTTP 200 / JSON со 100 Torid-аукционами.
Добавлен opt-in Python-adapter и проверен controlled replay в GUI/БД. Live-запросы
из cloud по-прежнему получают challenge. См. [READINESS_0.2.0](READINESS_0.2.0.md).
Ниже — предшествующее исследование.

## Обновление после включения public Internet access

Текущая cloud-политика подтверждена как `unrestricted`, `enforced`, observations
current. Повторный запрос найденного auction search установил CONNECT-туннель,
но получил upstream HTTP 403, `cf-mitigated: challenge`, HTML `Just a moment...`.
Отдельные запросы к `/v2/versions`, intro docs и ToS вернули такой же challenge.
Следовательно, прежний запрет cloud-allowlist снят; текущий блокер — проверка
Cloudflare. Это не доказывает, что v1-поиск удалён или требует авторизации.
Проверки ниже с `CONNECT 403` относятся к предыдущей политике.

Нужна проверка одного read-only запроса с обычной машины/сети, например Omarchy,
с собственным User-Agent. Если вернётся JSON, следует сохранить исходный ответ и
headers для валидации схемы. Пароли, JWT и browser cookies для этой проверки не нужны.
Защита не обходилась; production capability по-прежнему выключена.

## Существенное уточнение

Ранее проверенный опубликованный `wf-market` 0.3.3 (docs.rs / crates.io) содержит
Riven weapon/attribute manifests, но не auction search. Это заключение нельзя
переносить на все Git-ревизии репозитория.

`Kenya-DK/quantframe-react`, HEAD `a37a9885b9737cfd7c8a5b986aa510cc544efa8a`,
закрепляет в Cargo.toml и Cargo.lock другую ревизию `KibbeWater/wf-market`:
`1d9f79aa80406acc6bc8e30878e499ebf75d5409` (версия пакета 0.1.11).
Эта ревизия получена и прочитана непосредственно через Git. В ней реализованы
`get_recent_auctions()` и `search_auctions()` с реальными HTTP-запросами к v1.

## Подтверждённые кодом маршруты-кандидаты

Base URL: `https://api.warframe.market/v1`.

- `GET /auctions` — список последних аукционов по реализации клиента.
- `GET /auctions/search` — поиск по `type=riven`, `weapon_url_name`, positive/negative
  stats, polarity, mastery/reroll ranges, buyout policy и сортировке.
- Поиск объявлений доступен у клиента без авторизации по типам API и его тестам.
  Это свойство реализации, а не новая live-проверка требований сервера.

В модели ответа есть auction ID, starting/buyout price, top bid, created/updated,
closed, owner и характеристики конкретного ривена. Формат ожидается как
`payload.auctions`. User activity и similarity фильтруются клиентом локально.
У similarity используются множества имён/знаков атрибутов (Jaccard), без учёта
числовых roll values. Не следует переносить эту метрику в оценку как подтверждённую
рыночную модель.

QuantFrame вызывает `search_auctions()` при обработке собственных stock rivens и
показе MarketInfo. Это не доказательство полноты глобального охвата рынка.

## Официальная документация

Свежий Git fetch `42bytes-team/wfm-docs/master` дал
`c76d86937c0aabf6269b7f44f1d32761eeee3030`.
`docs/intro.md` прямо говорит, что документация некоторых областей отсутствует или
неполна; legacy v1 deprecated and unsupported. Отсутствие страницы v2 не доказывает
отсутствия работающего v1-маршрута и не является отдельным запретом на любой v1 GET.
Официальная поддержка конкретного legacy-поиска при этом не подтверждена.

Правила: собственный User-Agent, кэш, общий лимит 3/с с более строгими лимитами
contract search около 10–20/мин. Для RivenScope сохраняется консервативный общий
лимит 10/мин и остановка/ожидание при отказах, без browser impersonation.

## Что проверено по сети

Сделан один read-only запрос с собственным User-Agent к найденному в коде маршруту:
`GET /v1/auctions/search?type=riven&weapon_url_name=torid&buyout_policy=direct&sort_by=price_asc`.
Cloud proxy вернул `CONNECT 403`, HTTP code upstream отсутствует (`000`).
Это блокировка среды до подключения к WFM, не ответ WFM о состоянии endpoint.
Прямая страница docs.warframe.market также блокируется proxy; текст документации
прочитан из её официального Git-репозитория. Обходов ограничений не выполнялось.

Для live-проверки нужен разрешённый домен `api.warframe.market` в настройках cloud
или выполнение на машине с разрешённым доступом. Ключи/пароли для первого
анонимного read-only запроса не требуются по исследованной реализации.

## Применимость к RivenScope

Это первый из рассмотренных примеров с реализованным поиском уникальных Riven
объявлений. Его имеет смысл использовать как технический reference для отдельного
Python-адаптера. Для этого не нужно переносить Tauri/React или подключать Rust.

До включения production capability необходимо проверить live status, фактическую
схему и семантику полей (включая значения/знаки атрибутов, rank/display context,
platform/crossplay), предел выдачи/пагинацию, кэш/частоту, 429 и актуальные условия.
При неоднозначных условиях нужно уточнение команды WFM. Из кода чужого клиента
нельзя вывести гарантию поддержки или доступности.

QuantFrame также использует `https://api.quantframe.app`: собственные market/riven
price endpoints, скачиваемые caches и локальную ONNX-модель `price_model.onnx`.
Это отдельный сторонний источник и не входит в исходный scope RivenScope
(только WFM + собственная история). Числовые roll values не передаются в показанный
ONNX predict input; готовую модель нельзя считать подходящей нам без валидации.
QuantFrame умеет автоматически создавать/менять объявления, содержит analytics и
авторизацию/Patreon-функции; эти механизмы не нужны нашему read-only приложению.
Лицензия проекта GPL v3, зависимость объявлена GPL-3.0-only; копирование кода требует
соблюдения лицензии.

## Первичные ссылки

- Official intro: https://github.com/42bytes-team/wfm-docs/blob/c76d86937c0aabf6269b7f44f1d32761eeee3030/docs/intro.md
- Official rules: https://github.com/42bytes-team/wfm-docs/blob/c76d86937c0aabf6269b7f44f1d32761eeee3030/docs/rules/overview.md
- Pinned dependency: https://github.com/Kenya-DK/quantframe-react/blob/a37a9885b9737cfd7c8a5b986aa510cc544efa8a/src-tauri/Cargo.toml
- Actual search caller: https://github.com/Kenya-DK/quantframe-react/blob/a37a9885b9737cfd7c8a5b986aa510cc544efa8a/src-tauri/src/live_scraper/modules/riven.rs
- Search implementation: https://github.com/KibbeWater/wf-market/blob/1d9f79aa80406acc6bc8e30878e499ebf75d5409/src/endpoints/auction.rs
- Filter schema: https://github.com/KibbeWater/wf-market/blob/1d9f79aa80406acc6bc8e30878e499ebf75d5409/src/types/auction_filter.rs
- Auction schema: https://github.com/KibbeWater/wf-market/blob/1d9f79aa80406acc6bc8e30878e499ebf75d5409/src/types/auction.rs
