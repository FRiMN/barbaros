# Кэш списка моделей: вынос из QSettings в отдельный JSON-файл

**Статус:** план рефакторинга, код ещё не менялся.
**Аудит:** [docs/security/owasp-audit.md](security/owasp-audit.md) — BAR-01, BAR-09, BAR-10, BAR-14, BAR-17, §8.
**Затрагиваемые файлы:** новый `src/barbaros/model_cache.py`; `src/barbaros/model_manager.py`; `src/barbaros/main_window.py`; `tests/conftest.py`; новые тесты.

## 1. Цель

1. Убрать кэш списка LLM-моделей из `QSettings` (`main_window/llm_by_providers`) в отдельный JSON-файл.
2. Ввести отдельный класс хранилища `ModelCacheStore`: валидация недоверенного JSON, атомарная запись, права `0600`, fail-safe чтение.
3. Оставить в `QSettings` только пользовательскую конфигурацию (провайдеры, язык, геометрия, выбор модели).
4. Не менять UX, кроме места хранения кэша: при отсутствии/порче кэша приложение стартует как обычно, список моделей пуст до ручного обновления (как и сейчас при пустом кэше).

### 1.1. Что этот рефакторинг НЕ делает (важно)

- **Не закрывает BAR-01** (pickle-RCE) — он делается отдельным PR. Кэш и сейчас хранится как обычная JSON-строка (`common.py:29-31`, `main_window.py:121-123`), а pickle — в двух других ключах: `main_window/model` (`main_window.py:105-106,200-206`) и `ocr_feature/model` (`features/ocr.py:94-102`). В кэше нет `PyObjectWrapper`. Перенос кэша удаляет **0 из 2** pickle-ключей; более того, обычный старт уже вызывает unpickle, читая соседние ключи группы `main_window` (`main_window.py:39,44,61,202`). BAR-01 остаётся в P0 другого PR: санация сырого INI **до** первого обращения к `QSettings` + перевод выборов модели в JSON (аудит `:64,:257,:279`). В PR/чанглоге нельзя писать, что BAR-01 исправлен.
- **Не закрывает BAR-09, BAR-10, BAR-17.** Валидация `llm_providers`/`api_base`, `chmod 0600` для QSettings и переход на `logging` остаются отдельными задачами. Здесь закрывается только «кэш как недоверенный вход» и права нового файла.
- Не переносит список провайдеров и выбранную модель; **не добавляет автозагрузку моделей** ни при пустом кэше, ни при старте: часть провайдеров (например, OpenRouter) может отдавать список моделей долго, поэтому обновление остаётся явным действием пользователя. Формат данных, которыми обмениваются `ListModelWorker`/`ModelManager`, не меняется.

## 2. Текущее состояние

```
QSettings (~/.config/io.github.frimn/barbaros.conf)
├── main_window/llm_providers      JSON-строка  ← список провайдеров (конфиг)
├── main_window/llm_by_providers   JSON-строка  ← легаси-кэш; удаляется при старте (§4.7)
├── main_window/model              pickled ModelSelection  ← BAR-01, отдельный PR
├── main_window/geometry, language, ...
└── ocr_feature/model              pickled ModelSelection  ← BAR-01, отдельный PR
```

- Запись кэша: `MainWindow.save_models_list()` → `ModelManager.to_models_dict()` (`main_window.py:121-123`, `model_manager.py:103-108`).
- Чтение: `MainWindow._restore_models_lists()` (`main_window.py:89-99`), пропускает провайдеров, которых нет в конфиге.
- Сигнал `ModelManager.loaded_list_models` (`model_manager.py:65`) одновременно обновляет UI и сохраняет кэш (`main_window.py:43`).
- Формат элемента: `{id, created, object, owned_by}` (`workers.py:114`); `any_llm`-модель — `openai.types.model.Model` (pydantic 2, `extra="allow"`).
- На машине разработчика кэш занимает ~4.4 КБ на 40 моделей/3 провайдера; 25k моделей ≈ 2.1 МБ (замер).
- Кэш читается в GUI-потоке при старте; пишется из потока воркера (см. §3, п. 3).

## 3. Проверенные факты (эксперименты на PySide6 6.11.1 / any-llm-sdk 1.15.0)

| Факт | Следствие для дизайна |
|---|---|
| `QSettings` в реальных native- и Flatpak-конфигах содержит `main_window/model` и `ocr_feature/model` с `PyObjectWrapper`; чтение соседнего ключа группы `main_window` (например, `llm_providers`) запускает unpickle | Удаление легаси-ключа через `QSettings` тоже триггерит unpickle. Оно допустимо только потому, что до этого в том же `MainWindow.__init__` группа `main_window` уже прочитана (unpickle уже произошёл), и добавляет ноль нового риска. Это гигиена, а не исправление BAR-01 (§4.7). |
| `llm_by_providers` — plain JSON-строка, без pickle | Для десериализации переезд ничего не меняет; выигрыш — гигиена, разделение конфига и кэша, место под будущий JSON-стор |
| `QStandardPaths.AppDataLocation` → native `~/.local/share/barbaros`, Flatpak `~/.var/app/io.github.frimn.barbaros/data/barbaros` (Linux, `<XDG_DATA_HOME>/barbaros`); по документации Qt: Windows `C:/Users/<USER>/AppData/Roaming/<APPNAME>`, macOS `~/Library/Application Support/<APPNAME>`; путь зависит от `setApplicationName` | Путь резолвить лениво после `setApplicationName` (`main.py:22-24`); пустой путь (защитно) → хранилище отключается |
| `openai.types.model.Model.model_validate` требует `id: str, created: int, object: "model", owned_by: str`; лишние поля принимает и сохраняет, `to_dict()` их возвращает; `created` приводит `1.0`/`"1"`/`True` к `int` | Нужен строгий allowlist полей и явные проверки типов в хранилище, иначе произвольный JSON из файла будет вечно перезаписываться в кэш |
| `Model.model_validate` на 25k моделях ≈ 98 мс; `json.loads` 2 МБ ≈ 19 мс; `to_dict()+dumps` ≈ 72 мс | Лимит файла 4 МБ достаточен с запасом; синхронная запись такого размера допустима (фактически она идёт в потоке воркера — см. §4.5) |
| `QSettings` кэширует базовый каталог конфига при первом создании в процессе; `QStandardPaths` — динамичен | В тестах XDG-переменные — на import-time conftest; для QSettings — только явный путь |
| Сигнал Qt, подключённый к методу не-`QObject` получателя (`ModelManager` наследует `dict`), выполняется **в потоке отправителя** (проверено) | `set_models()`/сохранение кэша выполняются в потоке воркера; два воркера могут завершиться одновременно → нужна блокировка и целостный снапшот (§4.5) |
| `MainWindow` конструируется offscreen; полный `App()` — нет (нужен stub `TrayIcon`, fake keyring) | Системные тесты через `MainWindow`/stub `App`, см. §7 |

## 4. Принятые решения

### 4.1. Расположение файла

**Решение:** `QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation) / "models.json"` — персистентное хранилище приложения, а не кэш-каталог ОС. Кэш должен переживать очистку `~/.cache` и не требовать от пользователя ручного «Reload models» после каждого «чистильщика».

Типичные пути (Linux — целевая платформа проекта; остальные — по документации Qt):

| Окружение | Путь к файлу |
|---|---|
| Linux, native | `$XDG_DATA_HOME/barbaros/models.json`; при пустом `XDG_DATA_HOME` → `~/.local/share/barbaros/models.json` |
| Flatpak | `~/.var/app/io.github.frimn.barbaros/data/barbaros/models.json` (Flatpak подставляет `XDG_DATA_HOME=~/.var/app/io.github.frimn.barbaros/data`) |
| Windows | `C:/Users/<USER>/AppData/Roaming/barbaros/models.json` |
| macOS | `~/Library/Application Support/barbaros/models.json` |

`<APPNAME>` Qt берёт из `applicationName` (у нас `barbaros`, задаётся в `main.py:22-24`); `organizationDomain` на Linux в этот путь не добавляется (проверено). Точный суффикс на Windows/macOS зависит от `organizationName`/`applicationName` — проекта касается только Linux. Манифест Flatpak не меняется (`flatpak/barbaros.yaml:14-25`), дополнительных разрешений не нужно: это собственный data-каталог приложения внутри sandbox.

Обоснование: данные регенерируемы, но их отсутствие ломает выбор модели до ручного обновления, поэтому храним как персистентные данные приложения. Путь инжектируется в конструктор для тестов; при пустом результате `writableLocation` хранилище отключается (`load → {}`, `save → False`), а не пишет в текущий каталог.

**Отвергнутая альтернатива:** `CacheLocation` (`~/.cache/barbaros`) — семантически «настоящий кэш», но ОС/утилиты чистки могут его удалить, а автозагрузки моделей при старте нет.

### 4.2. Формат файла

```json
{
  "version": 1,
  "models": {
    "ollama remote": [
      {"id": "llama3:8b", "created": 1710000000, "object": "model", "owned_by": "library"}
    ]
  }
}
```

- Один файл на всё приложение, один атомарный `os.replace` на обновление.
- `version` — для будущих несовместимых изменений; неизвестная версия → файл игнорируется, приложение стартует с пустым кэшем (файл не удаляется).
- Поля элемента — только allowlist `id/created/object/owned_by`; лишние ключи отбрасываются при чтении и записи (иначе `Model` сохранит произвольные поля из подменённого файла).
- Провайдеры с пустым списком моделей не пишутся; при чтении пустые/невалидные записи пропускаются.
- Лимиты: `MAX_FILE_BYTES = 4 МиБ`, `MAX_PROVIDERS = 1000`, `MAX_MODELS_PER_PROVIDER = 10_000`, `MAX_PROVIDER_NAME_LEN = 256`, `MAX_MODEL_ID_LEN = 1024`, `MAX_OWNED_BY_LEN = 256`.

### 4.3. Класс хранилища и его место

**Решение:** новый модуль `src/barbaros/model_cache.py` с классом `ModelCacheStore`. Хранилище «тупое»: принимает/возвращает `dict[str, list[dict]]` (сырой JSON), не импортирует `any_llm`, `QSettings`, `keyring` и не знает про `Model`. Преобразование в `Model` остаётся в `ModelManager`: это разделение «механизм хранения ↔ доменная политика» (AGENTS #10) и позволяет тестировать хранилище без Qt/any_llm.

**Решение по интеграции (политика загрузки):** `ModelManager(cache: ModelCacheStore | None = None)` — конструктор принимает **только хранилище**. Гидратация управляется политикой на уровне `add()`: `CachePolicy.RESTORE` — поднять модели из кэша (старт), `CachePolicy.IGNORE` — добавить с пустым списком (runtime: диалог, `update`; **дефолт**). Отдельного `add_all`/`restore_cache()` нет. `set_models`/`remove` сохраняют всегда, без флага `persist`. `default_providers()` — фабрика (доступна как `ModelManager.default_providers()`), composition root использует её как fallback, но конструктор дефолтов не добавляет. Создаётся всё в `MainWindow` — composition root окна (AGENTS #12). Без зависимости `ModelManager` работает как раньше, в памяти.

| Вариант | Плюсы | Минусы | Вердикт |
|---|---|---|---|
| **A. Политика в `add()`: `constructor(cache)` + `CachePolicy`** | Нет `restore_cache()`, `add_all` и публичного `persist`; безопасный дефолт `IGNORE` для runtime; гидратация явная на месте вызова; минимальный diff; `MainWindow` не знает формат; тесты с fake store | I/O остаётся в домене (менеджер вызывает `load`/`save`, но не знает путей/JSON); `RESTORE` читает файл на каждый `add` (провайдеров немного); `add()` получает параметр-политику | **Зафиксировано** |
| B. Initial state + save-порт: `constructor(providers, cached_models, save)` | Полностью убирает I/O из домена: `load()` делает composition root, менеджер только вызывает `save`-порт | Больше diff и меняется конструктор/порядок в `MainWindow`; отложено до момента, когда разделение I/O станет важным | Возможное развитие |
| C. `restore_cache()` + публичный `persist=False` (первый вариант плана) | Привычный lifecycle | Публичный флаг — деталь реализации; две фазы вместо одной | Заменено политикой в `add()` |
| D. Оркестрация в `MainWindow` (как сейчас) | Минимальный diff, `ModelManager` чистый | Хранение/формат остаются в UI-классе; сложнее тестировать; при втором потребителе (BAR-01) переписывать | Допустимо, но хуже |
| E. `ModelManager` сам создаёт store | Меньше кода | Скрытая зависимость и путь; нельзя подменить в тестах; нарушает composition | Отклонить |

Почему политика, а не `add_all`: не появляется новый публичный метод, дефолтное поведение `add()` остаётся безопасным (пустой список), а стартовая гидратация выражается явно в месте вызова. `update()` — это `remove + add` с дефолтным `IGNORE`, поэтому модели старого endpoint не воскресают. `add(RESTORE)` читает `cache.load()` и берёт только запись своего провайдера; промежуточного снимка (`_pending_models`) и consume-once нет. Повторный `add(RESTORE)` просто снова прочитает актуальный файл; после `remove()` запись уже вычищена сохранённым снапшотом. Это предсказуемое поведение (AGENTS #17), и его легко проверить тестом «`add()` без политики не гидратирует».

API хранилища (контракт замораживается до реализации):

```python
class ModelCacheStore:
    VERSION = 1
    def __init__(self, path: Path | None = None) -> None: ...
    @property
    def path(self) -> Path | None: ...          # None, если хранилище отключено
    def load(self) -> dict[str, list[dict]]: ...  # никогда не бросает; порча → {}
    def save(self, models: Mapping[str, Sequence[Mapping[str, object]]]) -> bool: ...  # никогда не бросает
```

### 4.4. Жизненный цикл

- `MainWindow.__init__`: создать `ModelManager(cache=ModelCacheStore())`; прочитать провайдеров из `QSettings` (`default=None`); если ключа нет — взять `ModelManager.default_providers()`; для каждого вызвать `model_manager.add(provider, cache_policy=CachePolicy.RESTORE)`. Отдельного `restore_cache()`/`add_all` нет. Обновлять кэш при старте не нужно: `add` не пишет.
- `ModelManager.__init__`: только сохраняет ссылку на хранилище; никакого чтения файла, сети и записи на диск (лениво и предсказуемо).
- `add(provider, *, cache_policy=CachePolicy.IGNORE)`: при `RESTORE` — **до** захвата `RLock` вызвать `cache.load()`, взять `data.get(provider.name, [])` и провалидировать через `Model.model_validate` (невалидные пропустить со счётчиком в `DEBUG`); при `IGNORE` — пустой список и никакого I/O. Под `RLock` — создать `ProviderClient`, затем испустить `added`. Ничего не пишет на диск.
- `add(RESTORE)` читает актуальный файл на каждый вызов; consume-once нет. После `remove()` (который сохраняет снапшот без провайдера) повторный `add(RESTORE)` уже не найдёт запись.
- `set_models()`: обновить модели, снять целостный снапшот, сохранить, затем испустить `loaded_list_models`. Флага `persist` нет — сохранение безусловное.
- `remove(name)`: остановить воркер, удалить провайдера, сохранить снапшот (запись провайдера исчезает из файла), испустить `removed`. Никакой очереди/снимка чистить не нужно. При `update()` (`remove + add` с дефолтным `IGNORE`) модели старого endpoint не поднимутся.
- Записи кэша для провайдеров вне конфига остаются в файле, но не читаются (`add(RESTORE)` берёт только своё имя) и исчезнут при первом `save()` (полный снапшот). Отдельный `prune`/`discard` **не нужен** — осознанно не вводим.
- `shutdown()`: без изменений; запись не нужна — кэш обновляется по факту событий.

#### 4.4.1. Где именно происходит load/save

| Операция | Кто вызывает | Поток / момент |
|---|---|---|
| `ModelCacheStore.load()` | `ModelManager.add(..., cache_policy=RESTORE)` (`self._cache.load()`) | main thread на стартовом цикле `add` (или GUI-поток при явном runtime-`RESTORE`), **до** `RLock`; одно чтение на каждого `RESTORE`-провайдера; ошибки → `{}`, путь резолвится лениво в `ModelCacheStore.path` |
| `ModelCacheStore.save()` | `ModelManager._persist()` → `cache.save(self.to_models_dict())` | вызывается только из `set_models()` (поток воркера) и `remove()` (GUI-поток), **под `RLock`**; внутри store — свой `Lock`, полный снапшот, атомарный `os.replace` |
| I/O нет | `add(..., IGNORE)`, `to_models_dict()`, `to_list()`, `shutdown()` | `IGNORE` — дефолт, runtime-добавления не читают и не пишут файл |
| Удаление легаси-ключа | `MainWindow._drop_legacy_model_cache()` | main thread, после чтения провайдеров; это `QSettings`, не `ModelCacheStore` |

Файл `models.json` читает/пишет только `ModelCacheStore`; `ModelManager` знает лишь методы `load`/`save` переданного хранилища, `MainWindow` — не знает ни пути, ни формата.

Цена чтения на каждый `RESTORE`-add: типичный файл — единицы КБ (доли миллисекунды), при 2 МБ/25k моделей — ~20 мс на чтение; провайдеров обычно 1–10, так что на старте это десятки миллисекунд на фоне текущих ~1.3 с. Если битый кэш — `WARNING` будет на каждый `RESTORE`-add (N невелико; при необходимости store сможет логировать один раз). Если когда-нибудь станет много провайдеров и большой кэш — можно вернуть одноразовый снимок или кешировать разбор в store, но сейчас это преждевременно.

### 4.5. Потоки и блокировки

**Принято: lock включаем в этом PR.**

Поскольку `set_models()` вызывается из потоков воркеров, а `remove()`/`add()` — из GUI-потока:

- `ModelCacheStore` сериализует записи собственным `threading.Lock` (внутри `save`). Чтение не блокируется: атомарный `os.replace` даёт читателю либо старый, либо новый целый файл.
- `ModelManager` получает `threading.RLock`; под ним выполняются мутации словаря (`add`, `remove`, `set_models`) и снятие снапшота (`to_models_dict`). Сохранение выполняется **под тем же lock** — это гарантирует, что порядок записей соответствует порядку изменений (иначе два одновременных fetch могут записать устаревший снапшот последним). Запись 4 КБ + `fsync` — единицы миллисекунд, удержание lock на это время допустимо.
- `loaded_list_models.emit()` — после отпускания lock (UI-слоты не должны работать под нашим lock). Заметка: psygnal-сигналы сейчас синхронно вызываются в потоке воркера — это существующая особенность (обновление виджетов из чужого потока), не расширяем её; исправление — отдельная задача.

**Гарантия при двух одновременных fetch (в одном процессе).** Каждый `save` пишет полный снапшот под lock, а не патч файла. Второй воркер снимает снапшот уже после того, как первый применил свои модели, поэтому итоговый файл содержит **оба списка целиком**; промежуточный файл между двумя записями — валидный JSON с первым обновлением (не «половина»). Если запись второго воркера упала (`ENOSPC`, read-only), в файле останется первое обновление, а в памяти — оба; следующий успешный `save` (reload/remove/set_models) запишет полный снапшот. Между **разными процессами** гарантии слияния нет — last-writer-wins; для кэша это осознанно допустимо (§4.5.1). Проверяется component-тестом «два `set_models` из разных потоков» (§7.2).

### 4.5.1. Сторонние библиотеки для lock/атомарной записи не нужны

Это три разные задачи, и все закрываются stdlib:

1. **Mutual exclusion потоков** — `threading.RLock` (состояние `ModelManager`) и `threading.Lock` (`save` в store). Файловые локи для этого не подходят: они не защищают in-memory-словарь и добавляют syscall/IO на каждую мутацию.
2. **Атомарная/durable запись** — `tempfile.mkstemp` в том же каталоге + `os.replace` + опционально `os.fsync`. Это ~15 строк; сверху всё равно нужны наши требования: `0600`, allowlist полей, лимиты, fail-safe — библиотека их не даёт, её пришлось бы оборачивать.
3. **Межпроцессная блокировка** — единственное, для чего реально нужны `filelock`/`portalocker`. Нам не нужна: пишем полный снапшот и заменяем файл атомарно, поэтому файл всегда валиден, а два экземпляра приложения дают last-writer-wins (потеря части кэша не критична — регенерируется). App и так обычно один (IPC).

Кандидаты (PyPI, ноябрь 2026; скачивания — pypistats за неделю, порядок величины, не число пользователей):

| Пакет | Что делает | Вердикт |
|---|---|---|
| `durablewrite` 1.0.0 (окт. 2026) | Ровно temp-same-dir + `os.replace` + fsync файла/каталога, 0 зависимостей | Технически ближе всего, но пакету недели, ~15 скачиваний/нед.; дублирует наш `_atomic_write`. Не брать: непроверенная зависимость ради 15 строк (AGENTS #4, #8) |
| `atomicwriter` 0.3.0 (авг. 2025) | Кросс-платформенный atomic writer, 0 зависимостей, ~1.1k/нед. | Разумен, но не даёт 0600/валидацию/лимиты; дублирует stdlib-код. Не нужен |
| `atomicwrites` 1.4.1 (2022) | Классический atomic write context manager, ~0.9M/нед. | Не обновляется с 2022, нет fsync каталога, старые классификаторы. Не брать |
| `filelock` 4.2.9 | Межпроцессный файловый lock, ~145M/нед., зрелый | Уже стоит транзитивно (3.29.0 через `huggingface-hub`/`together`), но для потоков не подходит. Не нужен |
| `portalocker` 4.4.2 | Межпроцессные файловые/semaphore-локи, ~11.7M/нед. | Overkill для кэша |
| `atomicio` 1.0.1 (янв. 2026) | Atomic file ops + форматы; тянет `filelock`, `pyyaml`, `tomli_w` | Лишние зависимости ради кэша |
| `fs-transaction` 0.2.0 | Транзакции для batch-обработки ФС | Не наш сценарий |
| `atio` 3.1.0 | Atomic-запись pandas/polars/numpy и т.п.; тянет pandas, pyarrow, polars, sqlalchemy, connectorx… | Dependency bomb, не брать |
| `cryolock` 1.2.0 | «Systemwide pseudo-atomic lock», Python 2.7, ~9/нед. | Не поддерживаемый/непроверенный механизм |

**Итог:** остаёмся на stdlib. Ноль новых зависимостей = не растёт supply-chain-поверхность (BAR-08/BAR-16), не меняется `flatpak/requirements-flatpak.txt`, поведение явное и покрывается нашими тестами (включая инъекцию ошибок `os.replace`/`ENOSPC`). Если когда-нибудь понадобится слияние кэшей между одновременно работающими экземплярами — тогда `filelock`/`portalocker` (или `fcntl.flock` на Linux), но это отдельное требование, не текущее.

### 4.6. Ошибки и логирование

- `load()`/`save()` **никогда не бросают** наружу: `OSError`, `ValueError`, `UnicodeDecodeError`, `RecursionError`, ошибки `json` ловятся, логируются и превращаются в `{}`/`False`.
- Ошибка записи кэша не блокирует перевод и не показывает модальное окно: `WARNING` в `logging` (не `print` — BAR-17), путь и класс/errno исключения; без содержимого файла и без имён ключей.
- Внешние строки (имя провайдера, id модели) логируются только через `%r` и с усечением до 64 символов — защита от log injection (BAR-17).
- Битый/слишком большой/чужой файл **не удаляется**: следующий успешный `save()` заменит его атомарно; пользователь/разработчик может посмотреть файл. Это осознанный отказ от «тихого» удаления данных (AGENTS #27).
- Хранилище не читает keyring и не пишет секреты; в кэше не должно быть `api_base`/ключей (BAR-02, BAR-03, BAR-11).

### 4.7. Легаси-ключ (без миграции)

**Решение: данные не переносить; старый ключ `main_window/llm_by_providers` удаляется при старте.**

- Удаляем только значение `main_window/llm_by_providers` (это и есть «ключ» в терминах QSettings); остальные ключи группы `main_window` (провайдеры, язык, геометрия, выбор модели) не трогаем.
- Место: в `MainWindow.__init__` там, где раньше был `_restore_models_lists()` (`main_window.py:51`) — т.е. **после** чтения `target_language_list`/`llm_providers` из той же группы. К этому моменту unpickle pickled-соседей уже произошёл при штатном чтении, поэтому `QSettings.remove()` не создаёт нового риска. В коде — комментарий: «гигиена, не исправление BAR-01; удалить после BAR-01».
- `remove()` идемпотентен: на конфиге без ключа — no-op. Ничего не читаем и не парсим из старого значения; `PyObjectWrapper`/подменённое содержимое не разбираются.
- Кэш регенерируем: после обновления пользователь один раз нажмёт «Reload models» у нужных провайдеров. Даунгрейд на старую версию тоже увидит пустой кэш — допустимо.
- **Автозагрузку моделей намеренно не добавляем.** Конструктор и `add()` (в т.ч. с `RESTORE`) не делают сетевых запросов; пустой кэш — это явное состояние UI (иконка-предупреждение в `providers_card.py:139` и tooltip «Models are not loaded…» в `:144-152`), а обновление — только по кнопке. Причина: OpenRouter и другие провайдеры могут отвечать на `/v1/models` долго, и старт не должен зависеть от сети и блокировать пользователя; скрытый сетевой запрос при пустом кэше — неявное поведение (AGENTS #17).
- Когда будет сделан BAR-01 (сырой INI до первого `QSettings`), эта строка удаляется: санация и так уберёт легаси-ключ вместе с pickle-ключами. Импорт старого значения в новый JSON-кэш **не делаем** (решение команды).

## 5. Дизайн изменений

### 5.1. `src/barbaros/model_cache.py` (новый, ~120–150 строк)

Ключевые инварианты в docstring: *недоверенные данные, регенерируемо, без секретов, без QSettings*.

Чтение (`load`):

1. Путь: если `path` не передан — лениво `QStandardPaths.AppDataLocation` (импорт Qt внутри property); пустая строка (защитно) → store disabled, `{}`.
2. Открыть `os.open(path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC)` (флаги через `getattr`, fallback для не-POSIX); `fstat`: только `S_ISREG`; прочитать не более `MAX_FILE_BYTES + 1`; больше — `WARNING`, `{}`. Это отсекает symlink/FIFO/устройства и гигантские файлы без загрузки в память.
3. `json.loads` после `decode("utf-8")`; ошибки — `WARNING` (путь + класс исключения), `{}`.
4. Проверить `dict`, `version == 1`, `models: dict`; иначе `WARNING`, `{}`.
5. По каждому провайдеру (лимит): имя — непустая `str` ≤ 256; значение — `list`; каждый элемент — `dict`; `id` — непустая `str` ≤ 1024; `created` — `type(...) is int` (не `bool`); `object == "model"`; `owned_by` — `str` ≤ 256. Ключи вне allowlist отбросить. Невалидные элементы пропустить (счётчик — в `DEBUG`), валидные соседи сохранить.
6. Вернуть `dict` без пустых списков.

Запись (`save`):

1. store disabled → `False`.
2. Санитизировать вход теми же правилами/лимитами (защита от неожиданной формы/будущих полей `any_llm`).
3. Сериализовать `{"version": 1, "models": ...}` через `json.dumps(..., ensure_ascii=False, allow_nan=False, separators=(",", ":"))`; `UnicodeEncodeError`/`ValueError` → `WARNING`, `False`; превышение `MAX_FILE_BYTES` → `WARNING`, `False`.
4. `path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)`; best-effort ужесточить существующий каталог до `0700` (ошибка — только лог, запись продолжается).
5. `tempfile.mkstemp(prefix=".models-", suffix=".tmp", dir=parent)`; `os.fchmod(fd, 0o600)`; write/flush/`os.fsync`; close; `os.replace(tmp, path)`; best-effort `fsync` каталога. При любой ошибке — `unlink` временного файла, `WARNING`, `False`; старый файл остаётся целым.
6. Под `threading.Lock` (см. §4.5). `os.replace` заменяет symlink, а не его цель (проверено); ровно поэтому запись не следует по ссылке.

`fsync` — «Should»: кэш одноразовый, атомарности `replace` достаточно для отсутствия «рваного» чтения; `fsync` дешёвый (запись редкая, ≤4 КБ) и сохраняет кэш при внезапном выключении. Если появятся жалобы на задержки UI — убрать `fsync` первым.

### 5.2. `ModelManager` (правки)

```python
class CachePolicy(Enum):
    IGNORE = "ignore"      # добавить с пустым списком (runtime, дефолт)
    RESTORE = "restore"    # поднять модели из кэша (старт)

class ModelManager(dict):
    @staticmethod
    def default_providers() -> list[ProviderMeta]:
        return [ProviderMeta("ollama", LLMProvider.OLLAMA)]

    def __init__(self, cache: ModelCacheStore | None = None):
        super().__init__()
        self._cache = cache
        self._lock = threading.RLock()
        self._fetching_models_workers = {}

    def add(self, provider: ProviderMeta, *,
            cache_policy: CachePolicy = CachePolicy.IGNORE) -> None:
        models = []
        if cache_policy is CachePolicy.RESTORE and self._cache is not None:
            cached = self._cache.load().get(provider.name, [])   # вне lock
            models = self._parse_models(cached)
        with self._lock:
            self._put(provider, models)
        self.added.emit(self[provider])

    def set_models(self, provider, models) -> None: ...   # всегда сохраняет
    def remove(self, name: str) -> None: ...
    # set_models/remove/to_models_dict — под self._lock
```

`_parse_models` (валидация `Model`, пропуск битых) и `_persist` (вызов `cache.save(to_models_dict())`) — приватные. Промежуточного снимка кэша в менеджере нет. `_on_fetching_finished` не меняется (по-прежнему `json.loads` + `Model.model_validate`). `to_list()`/`to_models_dict()` остаются публичными; `to_models_dict` берёт lock.

### 5.3. `MainWindow` (правки)

- `self.model_manager = ModelManager(cache=ModelCacheStore())`.
- Провайдеры читать с `default=None`, fallback — `ModelManager.default_providers()`, затем добавлять со стартовой политикой:
  ```python
  raw = self.settings.valueFromJson(self.settings_llm_providers_key, default=None)
  raw = raw if raw is not None else ModelManager.default_providers()
  for p in raw:
      self.model_manager.add(
          ProviderMeta.from_dict(p),
          cache_policy=CachePolicy.RESTORE,
      )
  ```
  `ProviderMeta.from_dict` принимает и dict, и `ProviderMeta` (проверено).
- Удалить `_restore_models_lists()` (`:89-99`), `save_models_list()` (`:121-123`) и подключение `loaded_list_models → save_models_list` (`:43`).
- Добавить `_drop_legacy_model_cache()`: `self.settings.remove(self.settings_llm_providers_key)` в том же месте, где был `_restore_models_lists()` (`:51`), после чтения провайдеров/языка. Константу `settings_llm_by_providers_key` оставить только для этого удаления (переименовать в `settings_legacy_llm_by_providers_key`), с комментарием «гигиена, не BAR-01; убрать после BAR-01».
- `save_providers()`/`llm_providers` не трогаем — это конфиг, а не кэш.
- Побочный выигрыш: исчезает запись в `QSettings` из потока воркера (`save_models_list` вызывался из `loaded_list_models`, а тот — из потока воркера); запись кэша остаётся в потоке воркера, но становится потокобезопасной (§4.5).

### 5.4. Последовательность

```
App.__init__: setOrganizationDomain/setApplicationName, QSettings
MainWindow.__init__:
  ModelManager(cache=ModelCacheStore())        # без I/O
  raw ← QSettings.valueFromJson("llm_providers", default=None)
        или ModelManager.default_providers()
  for p in raw:
      model_manager.add(ProviderMeta.from_dict(p), cache_policy=CachePolicy.RESTORE)
      # до lock: cache.load() → выборка по имени → Model.model_validate
      # под lock: ProviderClient → added
  settings.remove("main_window/llm_by_providers")  # легаси-ключ, без миграции
  features/widgets строятся и видят модели

fetch (воркер):
  worker.finished → ModelManager._on_fetching_finished  (поток воркера)
    set_models(provider, models)
      lock: models = ...; snapshot = to_models_dict(); store.save(snapshot)
    loaded_list_models.emit()          # UI обновляется как раньше
```

## 6. Сверка с OWASP-аудитом

| Находка | Влияние рефакторинга | Что остаётся / что писать в PR |
|---|---|---|
| **BAR-01** pickle-RCE (`:48-66`) | **Не закрывается.** Убираем чтение/запись plain-JSON ключа и удаляем его (сам по себе он не pickle); pickle-ключи не трогаем; обычный старт всё равно unpickle'ит группу `main_window` | Обязательный отдельный P0 (другой PR): санация сырого INI до `QSettings`, перевод `main_window/model` и `ocr_feature/model` в JSON, тест «нет `PyObjectWrapper`». В PR: «BAR-01 не исправлен» |
| **BAR-09** недоверенный конфиг (`:127-133`) | **Частично, только для кэша:** битый/огромный/чужой файл не роняет старт; записи валидируются; ошибка записи не фатальна | `llm_providers`, `api_base`, `language` и `QSettings.status()` не валидируются — отдельная задача |
| **BAR-10** права по umask (`:135-141`) | **Частично:** новый файл `0600`, каталог `0700`, независимо от umask | QSettings-файл остаётся `0644/0664`; `chmod 0600` — отдельная задача |
| **BAR-14** нет лимитов (`:167-173`) | **Да, для кэша:** потолки на размер файла/провайдеров/моделей/строк; враждебный `/v1/models` не создаёт неограниченный файл | Лимиты текста/изображения/ответа LLM — отдельно |
| **BAR-17** `print` (`:191-197`) | **Да, в новом модуле:** `logging`, без содержимого файла/ключей, `%r` + усечение | Полный переход на `logging` — отдельно |
| **BAR-13** rich text (`:159-165`) | Нет изменений; кэш хранит `model.id`/имя провайдера, которые затем рендерятся в `QLabel.setText` (`filterable_combobox.py:70,358`) | Уже существует; рекомендуется закрыть вместе с BAR-13, т.к. кэш закрепляет данные из внешнего endpoint |
| **BAR-02/BAR-11** keyring | Хранилище не импортирует `keyring`/`security`, не сериализует `ProviderMeta`/`ProviderClient` | Ключи остаются в keyring; plaintext-fallback не появляется |
| **BAR-03** `http` endpoint | Хранилище не содержит `api_base` и не может его подменить; restore не создаёт провайдеров | Валидация URL — отдельно |
| **§8 тесты** (`:277-288`) | Появляются: #4 (битый конфиг → старт), #10 (нет ключей в сериализованных данных) для кэша; #1 (нет pickle) — нет, это BAR-01 | См. §7 |

**Нельзя утверждать:** «BAR-01 исправлен», «BAR-09/BAR-10 закрыты», «0600 защищает от same-uid» (модель угроз аудита включает локального процесса того же uid — права лишь defense-in-depth, корректность даёт валидация недоверенного файла).

## 7. Тест-план

### 7.1. Инфраструктура (`tests/conftest.py`)

- На import-time (до любых Qt/QSettings) выставить `XDG_CONFIG_HOME`, `XDG_CACHE_HOME`, `XDG_DATA_HOME` во временный каталог (как сейчас `QT_QPA_PLATFORM=offscreen`); иначе тесты читают реальный `~/.config`.
- Session-fixture `qapp` (`QApplication.instance() or QApplication([])`, один раз задать `organizationDomain`/`applicationName`, никогда не уничтожать).
- Autouse `fake_keyring` (подкласс `keyring.backend.KeyringBackend` с dict; сохранить/восстановить исходный backend) — `ProvidersCard` читает keyring в конструкторе, без fake бэкенда `MainWindow` падает на `NoKeyringError` (BAR-11). Отдельная fixture `no_keyring` для проверки fail-backend.
- `FakeApp` с явным `QSettings(str(tmp_path/...), IniFormat)` — QSettings кэширует базовый каталог, поэтому per-test XDG для него не работает.
- Хелперы: `make_models(n)`, `write_cache(path, data)`, `wait_until(pred)` с `processEvents` (pytest-qt **не установлен**, добавлять не обязательно).
- Не вызывать `QSystemTrayIcon.isSystemTrayAvailable()` до `QApplication` (segfault); для `App()` — monkeypatch `barbaros.main.TrayIcon` на stub.

### 7.2. Матрица тестов

**Unit — `tests/unit/test_model_cache.py`** (store с инжектированным `tmp_path`, без Qt/any_llm):

1. Round-trip произвольных валидных данных (unicode, пустые списки, allowlist-поля) → `load() == sanitized(save(data))`.
2. Нет файла/каталога → `{}`, исключений нет, файл не создаётся.
3. Битый JSON: обрезанный, мусор, пустой файл, BOM, не-UTF8 → `{}`, старый файл не удалён.
4. Неверная схема: список/строка/`null` на верхнем уровне; `models` не dict; запись не list; невалидные элементы → валидные соседи восстанавливаются, невалидные пропускаются, исключений нет.
5. Неизвестная `version` → `{}`, файл не удалён/не перезаписан.
6. Файл больше `MAX_FILE_BYTES` → `{}` без парсинга.
7. Атомарность: после `save` в каталоге только `models.json` (нет `*.tmp`); monkeypatch `os.replace`/`json.dumps` → исключение, старый файл цел, временных файлов нет.
8. Права: после `save` файл `0o600`, каталог `0o700`, при umask `0o022` и `0o077`; предварительно `0644`-файл ужесточается; `skipif(os.name != "posix")`.
9. Symlink на файл → `save` заменяет ссылку, цель не тронута; `load` symlink не читает (fail-safe) — зафиксировать поведение.
10. Пустые/NaN/дубликаты ключей, огромные ints → контракт: `{}` или валидная часть, без исключений (`allow_nan=False`).
11. Store disabled (path `None` при пустом `AppDataLocation` через monkeypatch `QStandardPaths.writableLocation`) → `load == {}`, `save == False`, нет записи в CWD.
12. Импорт-гигиена: модуль не импортирует `QSettings`, `keyring`, `barbaros.security` (AST/`sys.modules`-проверка).
13. Путь по умолчанию: при заданном `applicationName` `path == AppDataLocation/models.json`; инжектированный в конструктор путь имеет приоритет (никакого Qt-резолва).

**Component — `tests/components/test_model_manager_cache.py`** (fake store + `tmp_path`):

1. Конструктор **не** вызывает `load()`/`save()` — никакого I/O при создании.
2. `add(provider)` с дефолтным `IGNORE` не читает и не пишет файл, даже если запись есть в кэше.
3. `add(provider, cache_policy=RESTORE)` вызывает `load()` один раз на вызов, поднимает модели только своего провайдера; чужие записи кэша игнорируются.
4. Повторный `add(RESTORE)` снова читает актуальный файл; после `remove()` (сохранён снапшот без провайдера) запись не воскресает, `update()` (`remove+add` с `IGNORE`) — тоже.
5. `remove()` не требует чистки промежуточного состояния: удаляет провайдера и сохраняет снапшот.
6. `set_models()` сохраняет полный снапшот; `remove()` убирает провайдера из следующего снапшота; `add()` записи не вызывает.
7. `ModelManager()` без store → `load`/`save` не вызывались, файл не появляется.
8. `save()` бросает `OSError`/возвращает `False` → модели в памяти обновлены, `loaded_list_models` испущен, исключения нет.
9. Потоки: два `set_models` из разных потоков → итоговый файл — валидный JSON, содержащий модели обоих провайдеров (проверка lock/снапшота).
10. Если fake store вернул записи, не проходящие `Model.model_validate` (`created=True`/`None`), — `add(RESTORE)` их отбрасывает, валидные соседи поднимаются.
11. Записи кэша для провайдеров вне конфига не добавляются; первый `save()` записывает файл без них (самопрунинг полного снапшота, отдельного `prune` нет).
12. `ModelManager.default_providers()` возвращает новый список инстансов (не общий мутабельный объект).

**Integration/system — `tests/system/test_model_cache_flow.py`:**

1. `MainWindow` с битым кэшем (и с гигантским файлом) стартует, провайдеры загружены, модели пусты, traceback нет.
2. Валидный кэш известного провайдера → модели восстановлены в `model_manager` (и видны в `ProviderModelTreePopup`).
3. Запись в кэше для неизвестного провайдера игнорируется; записи для известного — нет.
4. «Restart»: `set_models` → файл обновлён → второй `MainWindow`/`ModelManager` с тем же путём видит модели.
5. Легаси-ключ `main_window/llm_by_providers` удаляется при старте: после `MainWindow.__init__` его нет, остальные ключи `main_window/*` (провайдеры, язык, геометрия) на месте; новое значение в QSettings не пишется; старые данные в новый кэш не переносятся (файл пуст).
6. `App()` со stub `TrayIcon` и fake keyring: битый кэш → старт без исключения; валидный кэш → модели восстановлены.
7. Flatpak-подобное окружение (`XDG_DATA_HOME=$tmp/.var/app/<id>/data`): файл создаётся в `$XDG_DATA_HOME/barbaros/models.json`, за пределы sandbox-каталога записей нет.
8. Старт **не инициирует сетевых запросов**: после `MainWindow.__init__` нет активных воркеров (`fetching_models_active_workers == []`), fake-провайдер не получил вызовов `list_models`; при пустом кэше модели появляются только после явного нажатия «Reload models».

**Security — `tests/system/test_model_cache_security.py`:**

1. Байты файла: нет `b"PyObjectWrapper"`/`b"@Variant"`, это валидный JSON; лишние поля из «подменённого» файла не попадают в файл после сохранения.
2. Ключ из fake keyring не встречается в тексте кэша и в логах.
3. Файл `0600`, каталог `0700` (POSIX).
4. Подменённый кэш с провайдером `evil`, `api_base`, `api_key` → провайдер не добавлен, keyring/сеть не вызывались, конфиг провайдеров не изменён.
5. Имя провайдера с `\n`/HTML в логах — одна экранированная запись, без инъекции.
6. `tests/ui/...`: cached `model.id` с HTML рендерится как plain text — **не в этом рефакторинге** (BAR-13), зафиксировать в follow-up; иначе тест упадёт.

**NFR (медленные, `@pytest.mark.slow`):**

1. `load()` 25k моделей/2 МБ < 500 мс; `save()` того же < 500 мс (замеры: ~19+98 / ~72+31 мс).
2. Старт `MainWindow` с 25k моделями медленнее пустого не более чем на 1.5 с (замер: +0.58 с).

### 7.3. Ограничения и известные ловушки

- Тест на BAR-01 (pickle → RCE) **не добавляем** — он сейчас падает; он принадлежит шагу BAR-01 (subprocess, marker-файл). Можно оформить `xfail(reason="BAR-01, отдельный шаг")` как документацию, но не как критерий готовности этого рефакторинга.
- QApplication — синглтон; не создавать второй; не уничтожать.
- `QSettings`-состояние глобально на процесс; использовать только явные временные файлы.
- Права файлов проверять только на POSIX; тайминги — только с широкими границами.

## 8. Этапы и оценка

| Шаг | Содержание | Оценка |
|---|---|---|
| 0 | Зафиксировать решения §4 (путь, схема, `CachePolicy`, легаси) | 1–2 ч |
| 1 | `model_cache.py` + unit-тесты (§7.2 unit) | 0.5–0.75 дня |
| 2 | `ModelManager`: `CachePolicy` в `add` (чтение кэша в `RESTORE`), `set_models`/`remove`, lock + component-тесты | 0.25–0.5 дня |
| 3 | `MainWindow`: удаление старых методов, wiring, system/security-тесты, conftest | 0.25–0.5 дня |
| 4 | Ревью, ruff, прогон полного набора, PR-описание («BAR-01 не исправлен», старый ключ удаляется без миграции) | 0.25 дня |

Итого ~1.5 рабочих дня. Один PR с 3–4 коммитами (store → ModelManager → MainWindow/tests → docs).

**Definition of Done:** новые/изменённые тесты зелёные (`uv run pytest`), `uv run ruff check` чистый, новых runtime-зависимостей нет, в `MainWindow` нет чтения/записи `llm_by_providers` (только однократное удаление), при битом кэше приложение стартует, файл `0600`, README/changelog отражают переезд кэша, удаление старого ключа и отсутствие миграции данных.

## 9. Риски и откат

| Риск | Вероятность/влияние | Смягчение |
|---|---|---|
| Пользователи после обновления видят пустой список моделей до ручного reload | Высокая/низкое | Осознанное решение: данные не мигрируем, старый ключ удаляем; записать в release notes |
| Пустой кэш после обновления создаёт соблазн «тихо» дообновить модели при старте | Средняя/среднее | Решение: автозагрузки нет (OpenRouter и др. могут отвечать долго); пустое состояние явно показывается, обновление — только кнопкой; тест «старт без сетевых вызовов» |
| Сохранение из потока воркера даёт гонку/потерянные записи | Средняя/среднее | Lock в store + снапшот/запись под lock `ModelManager`; тест с двумя потоками |
| `fsync`/атомарная запись подтормаживает UI на медленном диске | Низкая/низкое | Запись редкая, ≤4 КБ; при жалобах убрать `fsync`, оставив `replace` |
| Рост файла от «болтливого» провайдера | Низкая/низкое | Лимиты + отказ от записи больше 4 МБ; кэш регенерируем |
| Кто-то посчитает, что BAR-01 исправлен | Средняя/высокое (ложное чувство защиты) | Явные пометки в PR/чанжлоге/докстринге; отдельный P0-пункт в аудите |
| Тесты не изолированы и трогают реальный конфиг | Средняя/среднее | XDG на import-time conftest; QSettings только с явным путём |

**Откат:** изменения локальны; данные не мигрируют. Revert коммитов возвращает прежний код; удалив `models.json`, получим старую версию с пустым кэшем моделей (легаси-ключ к этому моменту уже удалён) — список восстановится ручным «Reload models». Потери пользовательских данных нет: кэш регенерируем, а конфиг провайдеров/языка/выбора не затрагивается.

## 10. Принятые решения по открытым вопросам

Открытых вопросов нет; зафиксировано:

1. **Lock в `ModelManager` — включаем** (§4.5). Альтернатива «только lock в store» отклонена: она допускает запись устаревшего снапшота последней.
2. **Автозагрузки моделей нет** (§1.1, §4.7). Причина: провайдеры вроде OpenRouter могут отдавать список долго; старт не должен зависеть от сети. Пустой кэш — явное состояние с предупреждением в карточке провайдера, обновление — по кнопке «Reload models».
3. **Инициализация — политика в `add()`** (§4.3–4.4): `ModelManager(cache=store)` без I/O в конструкторе; `add(provider, cache_policy=...)` с дефолтом `IGNORE`, `RESTORE` читает кэш при каждом вызове; `default_providers()` — фабрика; `add_all`/`restore_cache`/`_pending_models`/`prune`/публичного `persist`-флага нет. I/O остаётся в домене через `ModelCacheStore` — осознанный компромисс; вариант с `load()` в composition root и `save`-портом оставлен как возможное развитие (§4.3, вариант B).

## 11. Приложение: псевдокод хранилища

```python
class ModelCacheStore:
    VERSION = 1
    MAX_FILE_BYTES = 4 * 1024 * 1024
    ALLOWED_MODEL_KEYS = ("id", "created", "object", "owned_by")

    def __init__(self, path: Path | None = None) -> None:
        self._explicit_path = path
        self._resolved: Path | None = None
        self._disabled = False
        self._write_lock = threading.Lock()

    @property
    def path(self) -> Path | None:
        if self._explicit_path is not None:
            return self._explicit_path
        if self._resolved is None and not self._disabled:
            from PySide6.QtCore import QStandardPaths
            base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
            self._disabled = not base
            self._resolved = Path(base) / "models.json" if base else None
        return self._resolved

    def load(self) -> dict[str, list[dict]]:
        try:
            path = self.path
            if path is None:
                return {}
            raw = _read_regular_file_limited(path, self.MAX_FILE_BYTES)  # O_NOFOLLOW, fstat, cap
            if raw is None:
                return {}
            doc = json.loads(raw.decode("utf-8"))
            if not isinstance(doc, dict) or doc.get("version") != self.VERSION:
                logger.warning("Model cache: unsupported schema, ignored: %s", path)
                return {}
            models = doc.get("models")
            if not isinstance(models, dict):
                logger.warning("Model cache: invalid 'models' section, ignored: %s", path)
                return {}
            return self._sanitize(models)
        except (OSError, ValueError, UnicodeDecodeError, RecursionError) as exc:
            logger.warning("Model cache: load failed (%r): %s", self.path, exc.__class__.__name__)
            return {}

    def save(self, models: Mapping[str, Sequence[Mapping[str, object]]]) -> bool:
        path = self.path
        if path is None:
            return False
        try:
            doc = {"version": self.VERSION, "models": self._sanitize(models)}
            payload = json.dumps(doc, ensure_ascii=False, allow_nan=False,
                                 separators=(",", ":")).encode("utf-8")
            if len(payload) > self.MAX_FILE_BYTES:
                logger.warning("Model cache: payload too large, not saved: %s", path)
                return False
            with self._write_lock:
                _atomic_write(path, payload)  # mkstemp 0600 + fsync + os.replace
            return True
        except (OSError, ValueError, UnicodeEncodeError, RecursionError) as exc:
            logger.warning("Model cache: save failed (%s): %s", path, exc.__class__.__name__)
            return False
```

`_sanitize()` — единая функция для чтения и записи: dict провайдеров, allowlist полей, проверки типов/длин, лимиты. `_atomic_write()` — каталог `0700` (создать/уточнить), `mkstemp` в том же каталоге, `fchmod 0600`, `write`, `fsync`, `replace`, best-effort `fsync` каталога; `unlink` temp при ошибке.
