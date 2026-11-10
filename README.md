# RivenScope

Локальное десктопное приложение для исследования Riven Mods на Warframe Market.
Python + PySide6, SQLite, нативный Wayland-интерфейс. Интерфейс — на английском.

## Важный статус версии 0.1.0

**Это установленная версия с ограниченными источником возможностями, а не завершённый
живой монитор рынка.** На 9 ноября 2026 года поддерживаемый публичный API поиска
Riven contracts не документирован. v1 объявлен неподдерживаемым; обычные orders
не являются Riven contracts.

Приложение получает реальные справочники WFM: **420 оружий и 50 характеристик** в
проверенном ответе. Сохраняет пресеты с вложенными фильтрами, настройки и базу;
предоставляет резервное копирование, экспорт, диагностику и инструменты локальной
аналитики. Данные контрактов, реальные ценовые оценки и торговые оповещения сейчас
**недоступны**. В рабочую базу не добавляются примеры или искусственная история.

Подробное исследование: [API_FEASIBILITY](docs/API_FEASIBILITY.md).
Все ограничения: [LIMITATIONS](docs/LIMITATIONS.md).

## Запуск после установки

```bash
rivenscope
```

Или выберите **RivenScope** в меню приложений Omarchy.
Нажмите **Start catalog sync**. Закрытие окна останавливает задачи и сетевые запросы.
Автозапуска и фонового сервиса нет. Авторизация не нужна.

## Сборка и установка

На проверенной системе уже установлены Python, PySide6, Qt6 Wayland и libnotify.

```bash
python -m venv --system-site-packages .venv
.venv/bin/python -m pip install -r requirements-build.txt
.venv/bin/python tools/build_release.py
python tools/install.py
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
QT_QPA_PLATFORM=offscreen PYTHONPATH=src python -m unittest discover -s tests -t . -v
QT_QPA_PLATFORM=wayland python tools/live_smoke.py --directory /tmp/opencode/rivenscope-live-check
QT_QPA_PLATFORM=offscreen python tools/soak.py --seconds 600 --output test-artifacts/soak.json
```

Полный прогон, включая build/install/update/uninstall тесты: добавьте
`RIVENSCOPE_PACKAGING=1` перед командой unittest. Подтверждено **53 passed**,
нативный запуск установленной версии из меню и 10-минутный контролируемый soak.

Live smoke тест запрашивает только документированные справочники, с тем же
ограничителем 10 запросов/минуту. Не запускайте одновременно несколько live-прогонов.
Fixtures настоящего API находятся в `tests/fixtures/live/`; искусственные случаи
используются только в изолированных тестах локальных алгоритмов.

Отчёт: [TEST_REPORT](docs/TEST_REPORT.md). Руководство: [USER_GUIDE](docs/USER_GUIDE.md).
Архитектура: [ARCHITECTURE](docs/ARCHITECTURE.md). Этапы: [TASKS](TASKS.md).

Проект не опубликован в GitHub. Телеметрии, автоматической торговли и запросов к
сторонним оценочным сервисам нет. Предполагаемая выгода не гарантирует прибыль.
