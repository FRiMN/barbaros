# Хранение API-ключей: типизированная граница (BAR-11, issue #9)

Статус: реализовано 2026-11-15 в ветке `fix/bar-11-keyring-crash`, PR #24. Режим хранения — системный keyring (Secret Service / KWallet / WinVault / macOS Keychain). Opt-in-режим незашифрованного файла из согласованного дизайна в это изменение **не входит** — это follow-up [#23](https://github.com/FRiMN/barbaros/issues/23). Жизненный цикл ключей (удаление при удалении провайдера, «удалить сохранённый ключ») остаётся за **BAR-02 / [#8](https://github.com/FRiMN/barbaros/issues/8)**.

Интерактивная диаграмма архитектуры: [diagrams/secret-storage.html](diagrams/secret-storage.html) — откройте файл в браузере (светлая и тёмная темы). Диаграмма построена по коммиту `096d49c`, на котором зафиксировано поведение; подписи и карточки дублируют ключевые инварианты ниже.

Исходная находка аудита: `docs/security/owasp-audit.md` §3 BAR-11; журнал исправления: `.github/security/owasp-findings/BAR-11.md`.

## 1. Задача и границы

До исправления `security.py` вызывал `keyring.get_password()`/`set_password()`/`delete_password()` напрямую, а `ProvidersCard` читал ключ в конструкторе. На машине без Secret Service первое чтение бросало `NoKeyringError` и приложение падало на старте. Кроме падения были и контрактные дыры:

- ошибки keyring не различались («нет backend'а», «заблокировано», «нет ключа», «запись повреждена») и всплывали исключением в GUI;
- `delete()` ловил только `PasswordDeleteError`, поэтому «удалено» и «хранилище недоступно» выглядели одинаково;
- чтение при построении карточек могло провоцировать unlock-prompt, а при ошибке чтения — необработанное исключение и падение на старте.

Границы решения:

- **Единственный вход к секретам** — `SecretStorage` в `security.py`. Ни виджеты, ни воркеры не обращаются к `keyring` напрямую.
- **Нет fallback'а**: ни сессионного/памятного хранилища, ни plaintext-файла. Ключ либо сохранён в активном хранилище, либо операция завершается ошибкой.
- **Режим выбирается в composition root** (`main()`), до создания UI и потоков.
- **Старт fail-safe**: приложение запускается и остаётся работоспособным при недоступном keyring; деградируют только операции, которым нужен ключ.

## 2. Компоненты

| Компонент | Где | Роль |
| --- | --- | --- |
| `SecretStore` (Protocol) | `security.py` | Порт хранилища: `availability()`, `read()`, `write()`, `delete()`. Возвращает типизированные результаты, не бросает. |
| `KeyringSecretStore` | `security.py` | Реализация поверх `keyring`: маппинг исключений в статусы, vetting backend'а, повторное определение backend'а для `Retry`. |
| `SecretStorage` | `security.py` | Фасад приложения: проверка входных данных (имя провайдера, лимиты ключа), делегирование в активный store. |
| `ApiKeyManager` | `security.py` | Привязка одного провайдера к выбранному `SecretStorage`; `value()` — единственное место, где статус превращается в значение или в `SecretStorageError`. |
| `SecretStorageError` | `security.py` | Типизированная ошибка для путей, которым нужен сам ключ; текст стабильный, без секрета. |
| `KEYLESS_PROVIDER_TYPES` | `model_manager.py` | Данные: локальные провайдеры (ollama, llamacpp, llamafile, lmstudio, vllm), которые работают без ключа. |
| `ProviderClient.client()` | `model_manager.py` | Создаёт клиент `AnyLLM`; на `LOCKED`/`UNAVAILABLE`/`CORRUPT` идёт keyless-fallback только для локальных типов, остальные падают fail-fast. |
| `ProviderMeta.api_key_manager` | `model_manager.py` | Создаётся в `__post_init__` без I/O; `ModelManager.add()` привязывает менеджер к store приложения **до** создания клиента. |
| `ProvidersCard` | `providers_card.py` | Не читает ключ. Показывает неблокирующий баннер о недоступном keyring с кнопкой `Retry`; `Retry` вызывает `availability(refresh=True)`. |
| `ProviderDialog` / `AddProviderDialog` | `provider_dialog.py` | Явные действия: типизированный статус в таблице, предзаполнение ключа только при редактировании, запись ключа как шаг транзакции. |
| `secret_storage_ui.py` | `widgets/` | Переводимые подписи статусов (`locked`/`unavailable`/`corrupt`) для виджетов. |
| `TextFeature` / `OCRFeature` | `features/` | Строят воркер в `try/except SecretStorageError`: ошибка показывается существующим диалогом, вкладка восстанавливается, ничего не отправляется. |

## 3. Контракты

### 3.1. Статусы

| Статус | Значение |
| --- | --- |
| `FOUND` | Секрет прочитан; `value` — строка. |
| `MISSING` | Секрета нет. Это **не** ошибка хранилища: `ApiKeyManager.value()` возвращает `None`, как и раньше. |
| `LOCKED` | Коллекция/элемент заблокированы (`keyring.errors.KeyringLocked`). Retry-able; это не «ключа нет». |
| `UNAVAILABLE` | Backend недоступен: нет backend'а, D-Bus умер, ошибка secretstorage/`OSError`, любой другой `Exception` на границе I/O. |
| `CORRUPT` | Значение нельзя использовать: не строка, пустая строка, длиннее `MAX_SECRET_LEN` (16 КиБ), не UTF-8 (lone surrogate), `UnicodeDecodeError` от backend'а. |
| `PERSISTED` / `ERROR` | Исход `write()`/`delete()`. Удаление идемпотентно: `PasswordDeleteError` — это `PERSISTED`. |
| `Availability.READY` / `UNAVAILABLE` | Исход не читающего секрет probe для баннера. |

`BaseException` (`KeyboardInterrupt`) на границе **не** ловится: прерывание пользователя не должно превращаться в «хранилище недоступно».

### 3.2. Маппинг исключений

Граница шире, чем `keyring.errors.KeyringError`: при выбранном backend'е `SecretService` и умершем D-Bus `secretstorage.dbus_init()` бросает `FileNotFoundError`, а повреждённая запись — `UnicodeDecodeError`. Поэтому:

| Исключение | Результат |
| --- | --- |
| `KeyringLocked` | `LOCKED` |
| `UnicodeDecodeError` | `CORRUPT` |
| `NoKeyringError`, `KeyringError`, `FileNotFoundError`/`OSError`, `secretstorage.*`, произвольный `Exception` | `UNAVAILABLE` (для write/delete — `ERROR`) |
| `PasswordDeleteError` (delete) | `PERSISTED` (идемпотентно) |

В логи попадают только имя провайдера (`repr`, усечение до 64 символов) и **имя класса** исключения. `str(exc)` не логируется: у ошибки декодирования он может цитировать сохранённые байты.

### 3.3. Валидация и лимиты

- Имя провайдера: непустая строка, не длиннее `MAX_PROVIDER_NAME_LEN` (256).
- Ключ: непустая строка, не длиннее `MAX_SECRET_LEN` (16 КиБ), кодируемая в UTF-8.
- Невалидный вход → `MISSING`/`ERROR` + WARNING, без исключения в GUI.
- Сервисное имя `barbaros:providers_api_keys` **не менялось** — ключи, сохранённые старыми версиями, читаются без миграции.

## 4. Потоки

### 4.1. Старт приложения

`main()` создаёт `SecretStorage(KeyringSecretStore())` и передаёт его через `start_app()` → `App(secrets=...)` → `MainWindow(app=..., secrets=...)` → `ModelManager(secrets=...)`. Ключи при этом не читаются. `ProvidersCard` при построении спрашивает только `availability()` — проверку **класса** backend'а, без чтения секрета и без unlock-prompt. Если backend'а нет, показывается неблокирующий баннер; приложение работает, локальные (keyless) провайдеры доступны.

`Retry` в баннере вызывает `availability(refresh=True)`: сбрасывается кэш определения backend'ов (`keyring.backend.get_all_keyring.reset()`) и повторно выполняется `init_backend()`. Это позволяет пережить login race без перезапуска приложения. `KeyError` от `reset()` (кэш ещё не был заполнен, например после явного `keyring.set_keyring(...)`) — нормальное состояние: он не должен пропускать повторное определение.

### 4.2. Явное чтение («Manage providers»)

`ProviderDialog` — явное действие, поэтому читает ключи для таблицы: `FOUND` → маска (`truncate_key`), `MISSING` → пустая ячейка, иначе — переводимый статус и подсказка. Если не удалось прочитать хотя бы один ключ, над таблицей показывается неблокирующее предупреждение. `AddProviderDialog` при редактировании подставляет ключ и при ошибке чтения показывает inline-предупреждение, а не пустое поле без пояснений.

### 4.3. Сохранение ключа — транзакция

`ProviderDialog._apply_provider()` (его же используют тесты, чтобы не запускать модальный цикл):

1. проверить дубликат имени (для нового провайдера);
2. записать ключ в store (`api_key_manager(name).set(key)`);
3. при `ERROR` — модальная ошибка и **отмена**: провайдер не добавляется/не меняется, таблица и `QSettings` остаются прежними;
4. иначе — `add()`/`update()` и сохранение настроек.

Удаление провайдера ключ **не** удаляет — это BAR-02 (#8), а не этот PR.

### 4.4. Создание клиента и keyless-fallback

Клиент `AnyLLM` создаётся при построении воркера (`TranslationWorker`, `OCRWorker`, `ListModelWorker`) и в `ProviderClient.client()` читает ключ через `ApiKeyManager.value()`:

- `FOUND` → ключ передаётся в `AnyLLM.create`;
- `MISSING` → передаётся `None` (прежнее поведение; провайдер сам решает, нужен ли ключ);
- `LOCKED`/`UNAVAILABLE`/`CORRUPT` → store не может сказать, есть ли ключ. Для локальных типов из `KEYLESS_PROVIDER_TYPES` строится клиент без ключа (banner обещает, что keyless-провайдеры работают); для остальных — сразу `SecretStorageError`, без попытки создать клиент.

Почему для облачных типов нет keyless-попытки: конструктор без ключа уходит в AWS credential chain (bedrock, ~2 с) или Google ADC discovery (vertexai, ~12 с) и может делать сетевые запросы. На деградированном пути это замораживало бы GUI вместо быстрого отказа. Любая ошибка создания клиента без ключа (`MissingApiKeyError`, `ValueError` про `api_base`, отсутствующие cloud-credentials) превращается в исходный `SecretStorageError`, чтобы не выпустить чужое исключение в GUI-слот: обработчики вкладок и `ModelManager` ловят только типизированную ошибку.

### 4.5. Ошибки в UI

- Перевод/OCR: ошибка до отправки текста/изображения, существующий диалог ошибки, кнопки и прогресс восстановлены.
- Загрузка списка моделей: `ModelManager` ловит `SecretStorageError` и сообщает через существующий сигнал `error` (модальное окно провайдера), а не исключением в GUI-слот.
- Runtime-тексты ошибок остаются английскими, как и остальные ошибки воркеров/`any_llm`; переведены только статусы и подсказки виджетов.

## 5. Vetting keyring-backend'ов

`availability()` и **каждая** операция (`read`/`write`/`delete`) проверяют выбранный backend. Отвергаются:

- `keyring.backends.fail` — нет backend'а;
- `keyring.backends.null` — чтение всегда `None`, запись отбрасывается (тихая потеря ключа);
- любой backend из `keyrings.alt` — включая **подклассы**, определённые вне пакета (проверка идёт по MRO класса);
- `ChainerBackend`, если он включает отвергнутый backend (проверка по MRO **без импорта** `keyring.backends.chainer`: импорт регистрирует класс в глобальном реестре keyring и меняет побочные эффекты; к тому же сам keyring загружает chainer entry point при определении backend'а). Пустой chainer отвергается как `chained-empty`, потому что молча ничего не сохраняет.

Операция использует **тот же** проверенный экземпляр backend'а, поэтому подмена backend'а между проверкой и вызовом не перенаправит операцию. Если проверка сама бросает исключение (например, chainer считает priority сломанного стороннего backend'а), это трактуется как отказ (`inspection-failed`), а не как падение.

Почему это важно для записи: до ужесточения vetting проверялся только в `availability()`, и при выбранном plaintext-подобном backend'е `write()` возвращал `PERSISTED`, реально записывая секрет в plaintext (или молча теряя его у `null`). Теперь «нет plaintext без явного согласия» обеспечивается на пути сохранения, а не только баннером.

`availability()` — проверка **класса**, а не liveness: если D-Bus умрёт после probe, `availability()` может до следующего `Retry`/перезапуска отвечать `READY`, а `read()` вернёт `UNAVAILABLE(FileNotFoundError)`. Диалоги при этом уже показывают типизированную ошибку.

## 6. Композиция и внедрение

- `App`/`MainWindow`/`ModelManager` принимают `secrets: SecretStorage | None`. Реальный composition root — `main()`; тесты, создающие `MainWindow(app=FakeApp())`/`App([...])` напрямую, получают store по умолчанию (keyring).
- `ProviderMeta` остаётся dataclass'ом `dataclasses_json`: `api_key_manager` — не поле, поэтому `schema().dump()` по-прежнему содержит только `name/provider_type/api_base`, и ключ не может попасть в `QSettings`.
- `ModelManager.add()` привязывает менеджер провайдера к store **до** создания `ProviderClient`; `ModelManager.secret_storage` — точка доступа для UI.
- Активный store — один на процесс; смена режима (будущий file mode) будет выбираться там же, в composition root, без изменения call sites.

## 7. Тесты

- `tests/unit/test_secret_storage.py` — контракт границы: fake- backend'ы fail/null/`keyrings.alt`/chainer (включая двухуровневые подклассы и пустой chainer), маппинг исключений, идемпотентное удаление, валидация значений, отсутствие секрета в логах/`reason`, vetting на каждой операции, `Retry`-переопределение backend'а, subprocess-тесты «импорт модуля не трогает keyring и не регистрирует backend'ы».
- `tests/components/test_provider_client_storage.py` — keyless-fallback: allowlist, fail-fast для облачных типов, преобразование ошибок создания клиента, `MISSING`/`FOUND` без изменений.
- `tests/system/test_keyring_unavailable.py` — реальный `MainWindow` на `fail.Keyring`: 0 чтений при старте, баннер и `Retry`, типизированные статусы диалога, отмена add/edit, позитивный keyless-путь (fetch/translate/OCR), отсутствие секрета в файлах/`QSettings`/кэше/логах.
- `tests/system/test_model_cache_security.py` — старая предпосылка «ключ читается при старте» заменена явным действием диалога; утверждение «секрет не попадает в кэш/логи» сохранено.

Полный набор на ветке фикса: `615 passed, 3 deselected`; `ruff check src tests` — чисто.

## 8. Инварианты безопасности

- Keyring не читается в конструкторах виджетов и при старте; выполняется только не читающий секрет probe класса backend'а.
- Секрет не попадает в логи, тексты ошибок/диалогов, `QSettings`, JSON-кэш моделей и `ProviderMeta.schema().dump()`.
- `write()`/`delete()` не используют backend, который не прошёл vetting; «тихого» plaintext-хранилища и тихой потери ключа нет.
- Ошибка хранения отменяет транзакцию добавления/изменения провайдера; перевод/OCR не отправляются.
- Импорт `barbaros.security` не имеет побочных эффектов: 0 вызовов keyring API, 0 новых зарегистрированных backend-классов, chainer не импортируется.
- Новых зависимостей нет; `pyproject.toml`/`uv.lock`/Flatpak-манифест не менялись.

## 9. Остаточные риски и ограничения

- `availability()` — проверка класса, а не liveness (см. §5); баннер обновится после `Retry`/перезапуска.
- Если установлен `keyrings.alt`, keyring-режим работает fail-closed: keyring может выбрать plaintext-backend напрямую (без Secret Service) или chainer, включающий его (в том числе при работающем Secret Service — при двух backend'ах с `priority > 0` chainer побеждает с priority 10). Ключи не теряются (они остаются в Secret Service); лечение — удалить `keyrings.alt`; явная альтернатива — opt-in file mode (#23).
- Vetting — denylist по классам, а не sandbox: обёртка-делегат над plaintext-backend'ом не распознаётся; код в том же процессе может зарегистрировать backend. Защита — от **тихого** plaintext-fallback, не от same-uid (BAR-10).
- `KEYLESS_PROVIDER_TYPES` — захардкоженный список: локальный OpenAI-совместимый endpoint, сохранённый типом `openai`, при недоступном keyring получит типизированную ошибку (fail-closed), а не работу без ключа. Список придётся дополнять при появлении новых локальных провайдеров.
- Keyless-fallback не различает «ключ не сохранён» и «хранилище недоступно»: облачный провайдер без ключа при недоступном keyring получает ошибку хранилища, локальный — работает без ключа (секрет не читается). Создание локального клиента на деградированном пути стоит ~35–185 мс в GUI-потоке.
- `_client_without_key()` превращает **любую** ошибку создания клиента без ключа в `SecretStorageError`; в состоянии недоступного хранилища это маскирует настоящую ошибку конфигурации провайдера (например, отсутствующий `api_base`). При рабочем хранилище ошибка видна как раньше.
- `secretstorage.exceptions.LockedException` (гонка внутри `item.get_secret()`) маппится в `UNAVAILABLE`, а не `LOCKED`: контракт маппит в `LOCKED` только `keyring.errors.KeyringLocked`.
- Keyring-вызовы синхронны и блокируют GUI-поток на время операции (свойство библиотеки). Чтение при старте убрано, но keyring I/O не перенесён в воркер: зависший D-Bus-вызов может заморозить интерфейс при открытии диалога провайдеров.
- При выбранном chainer vetting перебирает вложенные backend'ы на каждой операции (несколько мс D-Bus availability-проб в такой конфигурации).
- Жизненный цикл ключей (revocation, «удалить сохранённый ключ») — BAR-02 (#8). Opt-in незашифрованный файл, consent, индикатор и миграция — #23.

## 10. Где смотреть код

- `src/barbaros/security.py` — статусы `SecretStatus`/`WriteStatus`/`Availability`/`SecretRead`, `SecretStore`, `KeyringSecretStore`, `SecretStorage`, `ApiKeyManager`, `SecretStorageError`, vetting и повторное определение backend'а.
- `src/barbaros/main.py`, `src/barbaros/main_window.py` — composition root и передача store.
- `src/barbaros/model_manager.py` — `ProviderMeta`, `ProviderClient.client()`, `KEYLESS_PROVIDER_TYPES`, `ModelManager.secret_storage`/`api_key_manager()`, batch-error path.
- `src/barbaros/widgets/providers_card.py`, `provider_dialog.py`, `secret_storage_ui.py` — баннер/`Retry`, типизированные статусы, транзакция сохранения.
- `src/barbaros/features/text.py`, `src/barbaros/features/ocr.py` — отмена операции до отправки.
- `src/barbaros/i18n/barbaros_ru.ts`/`.qm` — переводимые подписи статусов.
- Диаграмма: `docs/diagrams/secret-storage.html`; аудит: `docs/security/owasp-audit.md` §3 BAR-11; журнал: `.github/security/owasp-findings/BAR-11.md`.
