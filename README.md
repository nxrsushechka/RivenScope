# RivenScope

Локальное десктопное приложение для исследования Riven Mods на Warframe Market.
Python + PySide6, SQLite, нативный Wayland-интерфейс. Интерфейс — на английском.

## Важный статус версии 0.2.0

Есть экспериментальный read-only legacy v1 поиск уникальных Riven-объявлений.
Пользователь подтвердил маршрут HTTP 200 / JSON со 100 Torid-аукционами; ответ
используется в тестах. Режим выключен по умолчанию: WFM объявляет v1 unsupported.

Чтобы включить: **Settings → Preferences → Monitoring → Enable experimental legacy
v1 searches**, укажите weapon slugs (например `torid`, либо `*` для каталога),
сохраните и нажмите **Start monitoring**. Включённые watchlists добавляют области
поиска. Общий лимит — 10 запросов/мин; ответы частичные, полного охвата не обещаем.

Объявления, ставки, продавцы и собственная история отображаются. Контекст числовых
roll values ещё не подтверждён, поэтому legacy valuation возвращает **Insufficient
data**. Все 100 предоставленных записей — аукционы без выкупа: начальные ставки
не выдаются за цену покупки. Искусственные контракты в рабочую базу не добавляются.

Подробности: [READINESS_0.2.0](docs/READINESS_0.2.0.md),
[API_FEASIBILITY](docs/API_FEASIBILITY.md), [LIMITATIONS](docs/LIMITATIONS.md).

## Запуск после установки

```bash
rivenscope
```

Или выберите **RivenScope** в меню приложений Omarchy.
Нажмите **Start monitoring**. Закрытие окна останавливает задачи и сетевые запросы.
Автозапуска и фонового сервиса нет. Авторизация не нужна.

## Сборка и установка

Архивы версии 0.2.0 и контрольные суммы доступны в
[GitHub Releases](https://github.com/nxrsushechka/RivenScope/releases/tag/v0.2.0).

На Omarchy с системными PySide6 и Qt6 Wayland используйте venv с
`--system-site-packages` и `requirements-build.txt`, как описано в INSTALLATION.
Для воспроизводимой разработки в Linux проверен Python 3.12 + PySide6 6.8.3
(закреплённый dev runtime поддерживает Python 3.12/3.13):

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
QT_QPA_PLATFORM=offscreen PYTHONPATH=src RIVENSCOPE_PACKAGING=1 .venv/bin/python -m unittest discover -s tests -t . -v
.venv/bin/python tools/build_release.py
.venv/bin/python tools/install.py
```

Установка выполняется только в домашний каталог, без `sudo`.
Инструкции: [INSTALLATION](docs/INSTALLATION.md), [UPDATING](docs/UPDATING.md).

## Данные

- База: `$XDG_DATA_HOME/rivenscope/rivenscope.sqlite`, обычно `~/.local/share/rivenscope/rivenscope.sqlite`.
- Настройки интерфейса: `~/.config/rivenscope/interface.ini`.
- Журналы с ротацией: `~/.local/state/rivenscope/rivenscope.log`.
- Preferences, watchlists и история хранятся в SQLite.
- Резервная копия: **Settings → Data & backup → Back up database…**.

## Проверки

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -t . -v
QT_QPA_PLATFORM=wayland .venv/bin/python tools/live_smoke.py --directory /tmp/rivenscope-live-check
QT_QPA_PLATFORM=offscreen .venv/bin/python tools/soak.py --seconds 600 --output test-artifacts/soak.json
```

Полный прогон, включая build/install/update/uninstall тесты: добавьте
`RIVENSCOPE_PACKAGING=1` перед командой unittest. Для 0.2.0 в облачной Linux-среде
подтверждено **71 passed, 0 skipped**, включая чистую сборку и установку.
Нативный Wayland/menu launch ранее проверялся для 0.1.0; для 0.2.0 здесь не проверен.
Новые результаты: [проверка 0.2.0](docs/READINESS_0.2.0.md).

Live smoke тест запрашивает только документированные справочники, с тем же
ограничителем 10 запросов/минуту. Не запускайте одновременно несколько live-прогонов.
Fixtures настоящего API находятся в `tests/fixtures/live/`; искусственные случаи
используются только в изолированных тестах локальных алгоритмов.

Отчёт: [TEST_REPORT](docs/TEST_REPORT.md). Руководство: [USER_GUIDE](docs/USER_GUIDE.md).
Архитектура: [ARCHITECTURE](docs/ARCHITECTURE.md). Этапы: [TASKS](TASKS.md).

Удалённый источник релизов не настроен. Телеметрии, автоматической торговли и запросов к
сторонним оценочным сервисам нет. Предполагаемая выгода не гарантирует прибыль.
