# Установка на Omarchy / Arch Linux

## Проверенное окружение

Исторические native-проверки ниже относятся к 0.1.0. Для 0.2.0 в cloud Linux
проверены Python 3.12.14, PySide6 6.8.3, offscreen UI и установщик.
Для такого dev-окружения: `python -m venv .venv`, затем
`.venv/bin/python -m pip install -r requirements-dev.txt`.
Закреплённый PySide6 6.8.3 требует Python <3.14; для системного Python 3.14 на
Omarchy используйте системный PySide6 и описанный ниже `--system-site-packages`.

- Omarchy 4.0.6, Hyprland, Wayland.
- Python 3.14.8, PySide6 / Qt 6.12.0, Qt6 Wayland.
- `notify-send` из libnotify, `desktop-file-validate`, `update-desktop-database`.
- Build tools фиксируются в `requirements-build.txt`.

Приложение не включает собственный Chromium или второй Qt runtime. Используется
системный Python/Qt; release wheel содержит код и иконку приложения.

Если системных зависимостей действительно нет, установите их штатным инструментом:

```bash
omarchy pkg add python pyside6 qt6-wayland libnotify desktop-file-utils
```

Это системная установка и может запросить административное подтверждение. На данной
машине она не потребовалась. Не меняйте системный Python через `sudo pip`.

## Воспроизводимая release-сборка

Из корня проекта:

```bash
python -m venv --system-site-packages .venv
.venv/bin/python -m pip install -r requirements-build.txt
QT_QPA_PLATFORM=offscreen PYTHONPATH=src RIVENSCOPE_PACKAGING=1 .venv/bin/python -m unittest discover -s tests -t . -v
.venv/bin/python tools/build_release.py
.venv/bin/python tools/install.py
```

Результаты в `dist/`: wheel, исходный архив и `SHA256SUMS`. Build задаёт фиксированные
timestamp/порядок архива. Одинаковые исходники и закреплённый toolchain дают одинаковые
артефакты. Подпись доверенного удалённого издателя не настроена; SHA256 проверяет
целостность локально собранных файлов, а не личность издателя.

Сборка использует только исходники и отдельный временный каталог, не читает старый
`build/`. Wheel включает GUI и ресурсы; source archive позволяет повторить сборку
без готовых артефактов. Контрольные суммы совпадают при повторной сборке и при
сборке из распакованного source archive. Альтернативный каталог результатов:
`.venv/bin/python tools/build_release.py --output-dir /tmp/rivenscope-release`.

Ярлык использует Python, которым выполнена установка и проверка staging.
Если это `.venv/bin/python`, сохраните этот venv по прежнему пути; после перемещения
проекта или смены runtime повторите установку. Системный Python можно использовать,
если в нём доступны совместимые PySide6/Qt.

Установщик:
1. Проверяет Qt и SHA256 wheel.
2. Распаковывает release в staging, проверяя пути архива.
3. Выполняет `--version` и изолированный GUI smoke.
4. Проверяет desktop entry.
5. Атомарно переключает ссылку `current`, сохраняя `previous` и прежние releases.
6. Устанавливает команду, иконку и desktop entry в `~/.local`.

## Расположение

| Объект | Путь по умолчанию |
|---|---|
| Команда | `~/.local/bin/rivenscope` |
| Releases | `~/.local/share/rivenscope-app/releases/<version>-<hash>/` |
| Активный release | `~/.local/share/rivenscope-app/current` |
| Ярлык | `~/.local/share/applications/rivenscope.desktop` |
| Иконка | `~/.local/share/icons/hicolor/scalable/apps/rivenscope.svg` |
| База | `~/.local/share/rivenscope/rivenscope.sqlite` |

На обычном Omarchy `~/.local/bin` уже доступен через PATH. Если в другом окружении
он отсутствует, запускайте `~/.local/bin/rivenscope` напрямую.

```bash
rivenscope
rivenscope --sync
gtk-launch rivenscope
```

Проверка установленного release (открывает окно, синхронизирует разрешённые
справочники, повторно запускает пункт меню и закрывает только собственное окно):

```bash
python tools/verify_installation.py
```

Перед этой проверкой закройте ранее открытое окно RivenScope.

`--sync` включает только синхронизацию документированных справочников на время
открытого окна. `--data-dir <dir>` и `--smoke-seconds N` предназначены для изолированной
диагностики; не запускайте несколько сетевых диагностических экземпляров одновременно.

## Удаление

Закройте окно приложения, затем:

```bash
python ~/.local/share/rivenscope-app/current/uninstall.py
```

Удаляется только помеченная управляемая установка, команда, ярлык и неизменённая
иконка. Пользовательская база, backup-файлы, настройки и журналы сохраняются.
Удаление пользовательских данных оставлено явному решению владельца.

## Диагностика

Ошибки видны в **Settings → Diagnostics & updates** и журнале приложения.
Повреждённая/слишком новая база не стирается. Восстановление доступно из GUI.
При проблеме Qt Wayland проверьте наличие `qt6-wayland`; offscreen — только тестовый
режим и не замена рабочему графическому запуску.
