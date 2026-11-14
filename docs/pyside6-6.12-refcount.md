# PySide6 6.12.0 на CPython < 3.12: утечка ссылок на `None`/`True` и временный пин 6.11 (BAR-29)

**Статус:** временный пин (вариант A) реализован в `pyproject.toml`; снимается
после выхода PySide6 6.12.1 (см. §7).
**Связано:** issue FRiMN/barbaros#20; BAR-28 (#15) — `docs/settings-migration.md`;
upstream PYSIDE-3474, PYSIDE-3424, CPython GH-134989.
**Затрагиваемые файлы:** `pyproject.toml` (`[project].dependencies`,
`[dependency-groups].dev`), `uv.lock`; новый
`tests/system/test_pyside_refcount_pin.py`; `tests/system/test_legacy_settings.py`
(version-aware миграционные тесты); `docs/settings-migration.md`;
`docs/security/owasp-audit.md` и `.github/security/owasp-findings/BAR-28.md`
(актуализация ссылок на пин).

## 1. Симптом

Под `uv run barbaros` на CPython 3.10/3.11 приложение аварийно завершается в
произвольный момент (barbaros поддерживает `requires-python = ">=3.11"`):

```text
Fatal Python error: none_dealloc: deallocating None: bug likely caused by a refcount error in a C extension
Python runtime state: initialized
```

или, при завершении интерпретатора, `bool_dealloc: deallocating True or False`.
Падает «где попало»: трейсбек называет невиновный код. Чаще всего это
`GradientRainbowLabel` (`setHueOffset` → `update` → `get_gradient` в
`paintEvent`) — анимация перестраивает градиент ~100 вызовами `setColorAt` на
кадр и быстрее всех исчерпывает `None`, — но виджет не причина.

## 2. Причина (upstream)

- **PYSIDE-3474** — `Signal.emit()` уменьшает refcount `Py_True`; тот же
  дефект распространяется на `Py_None` в обычных `void`-вызовах Qt.
- **PYSIDE-3424** — сборочные машины PySide6 6.12 перевели на Python ≥ 3.12,
  поэтому пути `Py_RETURN_NONE` / `Py_RETURN_TRUE` скомпилированы в
  предположении, что синглтоны immortal. Колёса при этом по-прежнему
  `cp310-abi3` с `Requires-Python: >=3.10,<3.16`, т.е. ставятся на 3.10/3.11
  без предупреждения — вместо ошибки установки получается SIGABRT в рантайме.
- **CPython GH-134989** — поведение `Py_RETURN_*` для интерпретаторов без
  immortal-объектов; PySide6 6.12.1 собирается на Python ≥ 3.13.5 с этой
  правкой (исправление только сборочное, API PySide6 не меняется).
- На CPython 3.12+ синглтоны immortal (PEP 683), и дефектный `Py_DECREF` —
  no-op: утечка не видна, приложение «здорово». На 3.10/3.11 `None` и `True`
  не immortal, refcount доходит до нуля — отсюда авария. Поэтому проблема
  **версионная, а не виджетная**.
- **Обходного пути в коде приложения нет**: утечка происходит на каждом
  `void`-вызове Qt, значит «не трогать падающий API» = не использовать PySide6.

## 3. Воспроизведение

Замеры на этой машине (2026-11-14): CPython **3.11.14** + PySide6 **6.12.0**,
offscreen-Qt. Кэнари: вызов прогревается, затем 100 вызовов, разница
`sys.getrefcount(None)` / `sys.getrefcount(True)`:

| Вызов (×100) | `None` | `True` |
|---|---|---|
| `QLabel.setText` | 5235 → 5135 | 580 → 580 |
| `QColor.setAlpha` | 5134 → 5034 | 580 → 580 |
| `QWidget.resize` | 5133 → 5033 | 580 → 580 |
| `Signal.emit` | 5033 → 5033 | 579 → 479 |

То есть каждый `void`-вызов теряет ровно одну ссылку на `None`, каждый
`emit()` — на `True`, после чего интерпретатор падает на исчерпании синглтона
(`none_dealloc`, а при финализации — `bool_dealloc`).

`GradientRainbowLabel` с `show()` + `start_animation()` под тем же runtime
падает на первой отрисовке с exit code **134** (SIGABRT, `none_dealloc` на
коротких прогонах, `bool_dealloc` при финализации):

```text
Fatal Python error: none_dealloc: deallocating None: bug likely caused by a refcount error in a C extension
  File "src/barbaros/widgets/progress_label.py", line 43 in get_gradient
  File "src/barbaros/widgets/progress_label.py", line 53 in paintEvent
```

Контроль из issue #20 (CPython 3.11.11 + PySide6 6.11.3) — refcount-дельта
равна нулю на всех четырёх вызовах, reproducer печатает `OK: no crash` и
выходит с 0. Числа issue #20 (3.11.11) и этой машины (3.11.14) совпадают по
характеру — утечка не зависит от patch-версии CPython, важен только признак
immortal. PySide6 6.11.x не затронут.

## 4. Решение: вариант A, пин по маркерам

`requires-python` остаётся `">=3.11"`; зависимости делятся по версии
интерпретатора. Пин `~=6.11.0` разрешает только patch-обновления 6.11.x и не
пропускает 6.12; смена minor, как и раньше, — отдельное ревью.

`[project].dependencies`:

```toml
"pyside6-essentials~=6.11.0; python_version < '3.12'",
"pyside6-essentials~=6.12.0; python_version >= '3.12'",
```

`[dependency-groups].dev`:

```toml
"pyside6~=6.11.0; python_version < '3.12'",
"pyside6~=6.12.0; python_version >= '3.12'",
```

Почему A, а не альтернативы из issue #20:

- **B — поднять `requires-python` до `>=3.12`.** Сохраняет 6.12 и настройки
  везде, но отбрасывает 3.11 (заявленный минимум), а после 6.12.1 условие
  пришлось бы откатывать — лишняя миграция для пользователей и для lock.
- **C — ждать 6.12.1.** На 2026-11-14 её нет на PyPI; приложение на 3.11
  остаётся сломанным на неопределённый срок, тогда как 6.11.x — проверенная
  рабочая линия.
- A — минимальное изменение, обратимое удалением маркеров, с прецедентом:
  PyMemoryEditor, PR #125.

## 5. Последствия для настроек (BAR-28, #15)

На CPython < 3.12 установленный PySide6 теперь < 6.12, поэтому включается
fail-closed путь из `docs/settings-migration.md` (§3, §4):

- существующий конфиг-файл `QSettings` уносится рядом как
  `barbaros.conf.unsafe-<UTC>-<random>` (0600), приложение использует
  `MemoryBackedSettings`: настройки сессии живут только в памяти и **не
  сохраняются**, после перезапуска — дефолты;
- приложение при этом всегда стартует (AGENTS.md #14);
- это **сознательный принятый trade-off**: native-пользователи на 3.11 теряют
  персистентность настроек до 6.12.1. Это **безопасно**: на PySide6 < 6.12
  приложение вообще не читает `QSettings`, поэтому pickle-RCE путь,
  закрытый в BAR-28, остаётся закрытым — защита обеспечивается fail-closed
  путём, а не самим пином версии;
- **Flatpak не затронут**: BaseApp 6.11 несёт CPython 3.13 (синглтоны
  immortal), а манифест по-прежнему ставит явный `pyside6-essentials==6.12.0`
  из PyPI (требование build-guard `flatpak/bar28_guard.py`, BAR-28);
- это **не уязвимость**, а доступность/надёжность: барбарос на 3.11 просто не
  должен ставиться с 6.12.0.

## 6. Тесты

`tests/system/test_pyside_refcount_pin.py`:

1. **Refcount-кэнари в процессе** — `sys.getrefcount(None)` и
   `sys.getrefcount(True)` не меняются на представительных `void`-вызовах Qt и
   `Signal.emit()`; ловит утечку, если на < 3.12 окажется 6.12.x.
2. **Subprocess с `GradientRainbowLabel`** — виджет показывается и
   анимируется ~2 с; тест требует чистого выхода дочернего процесса
   (exit code 0) и **неотрицательных** refcount-дельт `None`/`True` внутри
   него (потеря ссылки — провал; `0` — идеал, но исправное старое колесо может
   кэшировать несколько ссылок), любая авария/дамп — провал. Около 2 с на
   тест, т.е. дёшево.
3. **Проверка контракта окружения** — сверяет маркеры `pyproject.toml` с
   установленными метаданными: на CPython < 3.12 установлен PySide6 < 6.12
   (и наоборот). Ловит ручную установку 6.12 на 3.11, которую кэнари на
   immortal-интерпретаторе не увидит.

В `tests/system/test_legacy_settings.py` миграционные тесты, специфичные для
PySide6 ≥ 6.12, помечены `skipif(not QT_REJECTS_PICKLED_OBJECTS)`, а для
реального старого рантайма добавлен тест «конфиг унесён, настройки в памяти».
Поэтому набор проходит по обе стороны маркера без маскировки падений.

Набор гоняется по обе стороны маркера: CPython 3.11 + PySide6 6.11.x и
CPython 3.12 + PySide6 6.12.x. Тесты 1–2 обязаны быть невакуумными: на
pre-fix control (CPython 3.11 + PySide6 6.12.0) они падают (утечка и авария
subprocess), на 6.11 — проходят. Маркер `slow` не ставится, чтобы тесты
входили в обычный прогон. На 3.12 утечка не наблюдаема в принципе, поэтому
там поведенческий контроль даёт только subprocess (чистый выход), а
рассинхрон маркеров ловит тест 3.

### Как прогнать обе ветки маркера

`.python-version` фиксирует 3.11, поэтому `uv run` без `--python` всегда
работает на 3.11; чтобы не пересоздать чужое окружение, версию интерпретатора
и каталог окружения задают явно:

```bash
UV_PROJECT_ENVIRONMENT=.venv311 uv sync --python 3.11 --locked
UV_PROJECT_ENVIRONMENT=.venv312 uv sync --python 3.12 --locked

UV_PROJECT_ENVIRONMENT=.venv311 uv run --python 3.11 pytest
UV_PROJECT_ENVIRONMENT=.venv312 uv run --python 3.12 pytest
```

В репозитории нет тестового CI (BAR-16), а по умолчанию `.python-version`
даёт только ветку 6.11 — вторая ветка пока проверяется ручным прогоном;
матрица обеих веток в CI — кандидат в отдельную задачу вместе с BAR-16.

## 7. Снятие пина, когда PySide6 6.12.1 появится на PyPI

1. Поставить 6.12.1 и проверить на CPython 3.11: refcount-кэнари показывает
   нулевую дельту, subprocess с `GradientRainbowLabel` выходит с 0.
2. Объединить зависимости обратно, без маркеров:
   `pyside6-essentials~=6.12.0` (и `pyside6~=6.12.0` в dev); убрать или
   поправить комментарий BAR-29 в `pyproject.toml`.
3. `uv lock`; убедиться, что на 3.11 резолвится 6.12.1, а не 6.11.
4. Прогнать полный набор на CPython 3.11 и 3.12.
5. Убрать из этого документа раздел о временном пине, оставив короткую
   историческую заметку со ссылкой на issue #20; вернуть формулировки
   `docs/settings-migration.md` к «native/pip на PySide6 ≥ 6.12» (без
   оговорки про 3.11).

## 8. Остаточные риски и ограничения

- Native-пользователи на CPython 3.11 теряют персистентность настроек до
  6.12.1; если 6.12.1 задержится — крайний вариант B (поднять
  `requires-python` до 3.12), но это отбрасывает 3.11.
- 6.11.3 — последний patch линии 6.11; новых Qt-исправлений в ней ждать не
  стоит, только security/критичные patch-релизы, если они выйдут.
- Пин-развилка стареет: её нужно снять после 6.12.1, иначе 3.11 навсегда
  останется на 6.11 и разойдётся с 3.12 по поведению Qt.
- Тесты требуют правильного окружения: тест контракта падает, если на 3.11
  установить 6.12 (так и задумано), поэтому CI/локальный прогон должен
  покрывать обе ветки маркера.
- Flatpak и native на CPython 3.12+ не затронуты: там 6.12.0 работает
  корректно (immortal-синглтоны).

## 9. Ссылки

- Issue FRiMN/barbaros#20 (BAR-29) — симптом, воспроизведение, варианты:
  https://github.com/FRiMN/barbaros/issues/20
- Issue FRiMN/barbaros#15 (BAR-28) — fail-closed `QSettings`, последствия
  пина: https://github.com/FRiMN/barbaros/issues/15
- PYSIDE-3474 (upstream, fix target 6.12.1):
  https://qt-project.atlassian.net/browse/PYSIDE-3474
- PYSIDE-3424 (сборочные машины переведены на Python ≥ 3.12):
  https://qt-project.atlassian.net/browse/PYSIDE-3424
- CPython GH-134989 (`Py_RETURN_*` и immortal-синглтоны):
  https://github.com/python/cpython/issues/134989
- PyMemoryEditor PR #125 (прецедент пина по маркерам):
  https://github.com/JeanExtreme002/PyMemoryEditor/pull/125
