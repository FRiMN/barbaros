# Легаси-pickle в QSettings: миграция и защита старта (BAR-01)

**Статус:** реализовано.
**Связано:** OWASP-аудит `docs/security/owasp-audit.md` §3 BAR-01 и §8.1; `docs/model-cache-storage.md`.
**Затрагиваемые файлы:** новые `src/barbaros/settings_sanitize.py`, `tests/unit/test_settings_sanitize.py`, `tests/unit/test_model_selection.py`, `tests/system/test_legacy_settings.py`; `src/barbaros/common.py`; `src/barbaros/main.py`; `src/barbaros/main_window.py`; `src/barbaros/features/ocr.py`; `src/barbaros/features/settings.py`; `src/barbaros/widgets/filterable_combobox.py`; `tests/conftest.py`.

## 1. Симптом

После обновления пакетов приложение не стартует:

```text
RuntimeError: Failed to deserialize Python object from QDataStream.
Only builtin types (dict, list, str, int, ...) are supported.
  ... restore_target_languages -> self.settings.value(...)
```

Падение происходит на первом чтении настроек, хотя падающий ключ — обычная
строка (`main_window/target_language_list`).

## 2. Причина

- PySide6 < 6.12 сериализовал Python-объект из `QSettings.setValue()` в
  `@Variant(...PySide::PyObjectWrapper...)` с pickle. Barbaros так сохранял
  выбор модели: `main_window/model` и `ocr_feature/model`.
- PySide6 6.12 больше не десериализует pickle: значение отклоняется, а
  `QSettings.value()` кидает `RuntimeError` (safe-unpickle).
- QSettings разбирает секцию INI при первом обращении к её ключу. Флаг
  «pickle отклонён» проверяется в glue-коде PySide при возврате `value()` и
  сбрасывается, поэтому падает именно **первое** чтение каждой секции с
  отклонённым значением, даже если читается соседний ключ. В
  `MainWindow.__init__` первым читается `main_window/target_language_list` —
  отсюда трейс.
- QSettings снимает снимок содержимого файла в конструкторе, поэтому удалять
  легаси-значения через `QSettings.remove()` поздно; до 6.12 это ещё и
  запускало unpickle (BAR-01). Чистить файл нужно **до** создания QSettings.

## 3. Решение

1. **Санация сырого INI до QSettings** — `src/barbaros/settings_sanitize.py`.
   `settings_file_path()` вычисляет путь так же, как Qt для
   `QSettings.Scope.UserScope` + `IniFormat` на Unix
   (`$XDG_CONFIG_HOME/<organization>/<application>.conf`), затем
   `sanitize_pickled_settings()` удаляет строки, значение которых начинается с
   `@Variant(` и содержит `PySide::PyObjectWrapper`. Остальные строки не
   меняются. Это вызывается из `App.__init__` перед созданием QSettings;
   расхождение вычисленного и фактического пути (`fileName()`) выводится
   предупреждением.
   - Чтение и запись — через `barbaros.atomic_file`: regular file без symlink,
     потолок 1 МиБ, атомарная запись. Оригинал сохраняется рядом как
     `barbaros.conf.bak-<UTC>-<random>` (0600) — если значение подменили, его
     можно разобрать; случайный суффикс не даёт перезаписать более ранний бэкап.
   - Функция fail-safe: при ошибке (каталог только для чтения, симлинк,
     слишком большой файл) старт продолжается, а не падает.
2. **JSON вместо pickle для выбора модели.** `ModelSelection.to_dict()` /
   `from_dict()` (`filterable_combobox.py`) + существующий
   `SettingsProxy.setValueAsJson`. `main_window/model` и `ocr_feature/model`
   теперь JSON-строки; `from_dict` валидирует типы и пустые значения.
3. **Терпимое чтение как страховка** — `read_setting()` (`common.py`) ловит
   `RuntimeError` при `QSettings.value()`. Нужен, если санация невозможна
   (read-only, symlink) или путь Qt не совпал. После сбоя флаг уже сброшен,
   поэтому `read_setting` **повторяет чтение**: соседние значения секции
   (языки, провайдеры, геометрия) восстанавливаются; default получает только
   сам отклонённый ключ (повторное чтение вернёт `None`).
4. `SettingsProxy.valueFromJson()` больше не падает на повреждённом JSON,
   включая `RecursionError` от глубоко вложенного значения: пишет WARNING и
   возвращает default.

## 4. Миграция и поведение

- Старый выбор модели **не импортируется**: безопасно прочитать отклонённый
  pickle нельзя, поэтому после первого старта выбор пуст. Сырая санация
  удаляет только pickled-строки, остальные строки остаются байт-в-байт;
  последующая запись QSettings (sync/закрытие) перекодирует файл штатно.
- При миграции в консоль печатается, сколько значений удалено; оригинал
  сохранён рядом как `barbaros.conf.bak-<UTC>-<random>` (0600) — это данные
  пользователя, поэтому бэкап не удаляется автоматически, в отличие от кэша.
- Повторные запуски ничего не переписывают: pickled-строк нет — файл не
  трогается, второй бэкап не создаётся.
- Flatpak: путь берётся через `QStandardPaths`, поэтому
  `~/.var/app/io.github.frimn.barbaros/config/...` подхватывается так же.
- Симлинк на конфиг (dotfiles): чтение без follow отказывается от санации,
  поэтому pickle в первый раз остаётся на месте. `read_setting` не даёт
  упасть и восстанавливает соседние значения повторным чтением; QSettings при
  следующей записи сам перезапишет целевой файл без pickle (самолечение), но
  бэкапа в этом случае не будет. Полноценная поддержка симлинков — отдельная
  задача, если понадобится.

## 5. Тесты

- `tests/unit/test_settings_sanitize.py` — удаление pickle с сохранением
  соседних строк, бэкап с правами 0600, идемпотентность, отсутствие файла,
  слишком большой файл, симлинк не трогается, строка с упоминанием класса не
  трогается, контракт «до санации QSettings падает, после — читает»,
  восстановление значения повторным чтением и default для отклонённого ключа,
  `RecursionError` на глубоко вложенном JSON.
- `tests/unit/test_model_selection.py` — JSON-кодек `ModelSelection`.
- `tests/system/test_legacy_settings.py` — реальный `App` в subprocess на
  старом конфиге: старт без трейсбека, конфиг очищен, бэкап на месте, соседние
  ключи живы, повторный старт; fail-safe старт с симлинком на конфиг; сброс
  выбора модели (`None`); `MainWindow` пишет/читает выбор как JSON и не падает
  на битом/глубоко вложенном JSON.
- Фикстура легаси-конфига — `tests/conftest.py`
  (`legacy_pickled_config`); payload — безобидный pickle `ModelSelection`,
  десериализация в тестах не выполняется.

## 6. Ограничения

- QSettings не заменён на отдельный JSON-стор (вариант из аудита) — это
  отдельное большое изменение; здесь только санация и смена формата выбора.
- BAR-09/BAR-10/BAR-17 не закрываются: после санации файл заменяется с
  правами 0600, но дальнейшие перезаписи Qt идут с его собственными правами
  (BAR-10); `llm_providers`/`api_base` не валидируются; переход на `logging`
  в старых модулях — отдельная задача (новый модуль логирует через `logging`).
- Санация заменяет файл целиком по схеме read → replace. Одновременный запуск
  второго экземпляра ровно в этот момент может потерять его параллельную
  запись настроек; событие однократное (пока в файле есть pickle), блокировки
  на QSettings-файл в приложении нет.
- Эвристика удаления общая: вырезаются любые значения `PySide::PyObjectWrapper`,
  а не только два известных ключа выбора модели.
- Правило для ревью: в `QSettings.setValue()` — только примитивы и типы Qt
  (`str`/`int`/`bool`/`QByteArray`); Python-объекты — через JSON.
