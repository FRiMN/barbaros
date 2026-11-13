# Barbaros — аудит безопасности по OWASP Cheat Sheet Series

- **Проект:** репозиторий `barbaros` (корень проекта), HEAD `ea8822c` (2026-11-13). Абсолютные пути с машины аудита в публикуемый документ не включаются (BAR-27); ссылки на строки даны на текущий HEAD.
- **Предыдущие версии отчёта:** аудит HEAD `71197f8` (2026-11-03, коммит `6dc2a4c`) и аудит HEAD `1e3d17f` (2026-11-09, коммит `77462de`). Второй аудит добавил находки `BAR-19..BAR-27`, но при мерже BAR-01 (`58c92d0`/`ea8822c`) его версия отчёта была вытеснена веткой, базой которой был первый аудит: в `main` осталась только версия `71197f8` плюс статус BAR-01. Здесь восстановлены и повторно проверены оба набора находок; новые находки — `BAR-28+`.
- **Обновление (2026-11-13):** BAR-28 исправлен: Flatpak ставит PySide6 6.12 из pip поверх BaseApp 6.11 (BaseApp 6.12 на Flathub отсутствует) с build-guard; на PySide6 < 6.12 приложение вообще не читает файл настроек (fail-closed), потому что Qt снимает escaping INI до разбора варианта и сырой скан не может быть границей безопасности. Подробности — в §4 BAR-28 и §11.
- **Обновление (2026-11-13, BAR-25):** OCR закрыт fail-closed: поддержка изображений проверяется до base64-кодирования и отправки, отсутствующий/неизвестный флаг трактуется как «не поддерживает», после `error.emit(...)` выполняется `return`; `done` не эмитится, изображение не уходит провайдеру. Подробности — §4 BAR-25, §9–§11.
- **Обновление (2026-11-13, BAR-23):** зависание GUI при остановке загрузки моделей закрыто. `QThread.terminate()` убран: `ListModelWorker` выполняет запрос как asyncio-задачу в собственном loop и отменяется кооперативно; `stop_fetching_models` ждёт поток с ограниченным бюджетом (`STOP_WAIT_MS`), `shutdown()`/batch-reload — под общим дедлайном (`SHUTDOWN_BUDGET_MS`); весь запрос `list_models` ограничен общим таймаутом (`LIST_MODELS_TIMEOUT_S = 20 с`). Подробности — §4 BAR-23, §9–§11.
- **Обновление (2026-11-13, BAR-19):** исправлен произвольный sink записи кэша. `ModelCacheStore.save()` заменяет только отсутствующий файл или файл-документ кэша моделей **любой версии**; симлинк, FIFO, устройство, каталог, нечитаемый, битый и чужой файл остаются нетронутыми (`False` + WARNING). `_tighten_directory` больше не идёт по симлинк-компонентам (любому в пути), публичный флаг `tighten_directory` убран из `ModelCacheStore`, повторный `save` своего неизменного файла не перечитывает его (identity-memo). Подробности — §4 BAR-19, §9–§11.
- **Предмет:** десктопное PySide6-приложение Barbaros: перевод текста и OCR через `any-llm-sdk`-провайдеров, системный трей, D-Bus/SIGUSR1 IPC, keyring для API-ключей, Flatpak-поставка. С предыдущего аудита главное изменение — исправление BAR-01 (санация сырого INI `settings_sanitize.py`, JSON вместо pickle для выбора модели, `read_setting`) и пиннинг зависимостей в `pyproject.toml`.
- **Источник требований:** локальная копия OWASP Cheat Sheet Series (137 читшитов; ссылки ниже — на имена файлов и разделы; путь на машине аудита не публикуется). Маппинг дан на **OWASP Top 10:2021** (для преемственности) и **OWASP Top 10:2025** (актуальная редакция; https://top10.owasp.org/2025/0x00_2025-Introduction/).
- **Методика:** статический аудит потоков данных (`source → sink`), сверка с чек-листами OWASP, эксперименты в `.venv` (PySide6 6.12.0, any-llm-sdk 1.50.0, Python 3.11): offscreen-Qt, `dbus-run-session`, временные `XDG_CONFIG_HOME`/`XDG_DATA_HOME`/`XDG_RUNTIME_DIR`, локальный fake OpenAI-совместимый endpoint, fake/in-memory keyring. Дополнительно — запуск **установленного Flatpak BaseApp `io.qt.PySide.BaseApp` 6.11.3** (`flatpak run --command=python3`), в котором PySide6 6.11.3. Исходный код в ходе аудита не изменялся.
- **Тесты:** полный набор на HEAD — `405 passed, 2 deselected` (`pytest`, slow-NFR исключены `addopts`); с прошлого аудита добавлено 939 строк тестов, в т.ч. `tests/unit/test_settings_sanitize.py`, `tests/unit/test_model_selection.py`, `tests/system/test_legacy_settings.py`. После исправления BAR-19 на ветке фикса — `481 passed, 3 deselected` (`uv run pytest`; добавлены матрица write-guard и identity-memo в `tests/unit/test_model_cache.py`, system-тесты «чужой `model_cache_path`/чужой файл в default-пути не перезаписывается», тесты «chmod не идёт по симлинк-компонентам»). После исправления BAR-25 на ветке фикса — `490 passed, 3 deselected` (`uv run pytest`; +9 тестов: unit-матрица fail-closed и system-тесты на реальном `QThread`-пути). После исправления BAR-23 на ветке фикса — `513 passed, 3 deselected` (`uv run pytest`; +23 теста: unit-контракт воркера, компонентные тесты жизненного цикла и system/NFR-тесты на реальном зависшем HTTP-endpoint).
- **Модель угроз:** локальный процесс того же пользователя (в т.ч. скомпрометированное приложение/скрипт), Flatpak-приложение в рамках выданных ему разрешений, поддельный/скомпрометированный LLM-endpoint, подмена/синхронизация файла конфигурации, случайная утечка (бэкапы, скриншоты, логи). Вне модели: root, физический доступ, удалённый сетевой атакующий, «полностью доверенный» same-uid. Права файлов `0600`/`0700` рассматриваются как defense-in-depth, а не как граница против same-uid (это же явно признаёт `atomic_file.py:40-44`).
- **Границы:** не проводились динамический фаззинг, SAST-сканирование зависимостей (CVE), полная сборка/запуск Flatpak-приложения на собственном bundle, реальные операции с системным Secret Service, проверка на реальном X11/Wayland. Выводы по Flatpak основаны на манифесте и **установленном runtime BaseApp** (для проверки версии PySide6 и поведения `QSettings`); выводы по keyring — на fake-бэкендах.

## 0. Что изменилось с предыдущей версии

С прошлого аудита (`1e3d17f`) — **13 коммитов**: исправление BAR-01 (`3e30fa3`), пиннинг зависимостей и пересборка `uv.lock` (`3e7d10d`), нормализация списков моделей (`c5364a8`, `c4388c9`), правки тестов `atomic_file` (`4d43069`) и мержи. В `src/`: 10 файлов, +478/−55; в `tests/`: 7 файлов, +939; в `docs/`: +189 (в основном `docs/settings-migration.md` и `docs/model-cache-storage.md`, плюс `docs/xerj.md` и статус BAR-01 в отчёте).

**Итог ре-проверки:**
- **BAR-01 исправлен для обычной установки** (PySide6 ≥ 6.12): pickle больше не десериализуется, легаси-значения вычищаются из сырого INI до создания `QSettings`, выбор модели хранится как JSON. Подтверждено: PySide6 6.12.0 в `.venv` на подменённом INI бросает `RuntimeError`, payload не выполняется; `tests/system/test_legacy_settings.py` поднимает реальный `App` на легаси-конфиге.
- **BAR-01 не покрывал Flatpak-поставку** — это была находка **BAR-28 (High)**: манифест собирал приложение на `io.qt.PySide.BaseApp` 6.11, т.е. на PySide6 **6.11.3**, который по-прежнему делает unpickle; санация обходилась конфигом > 1 МиБ (лимит `MAX_SETTINGS_BYTES`), симлинком или read-only каталогом, и эксперимент с реальным BaseApp 6.11.3 выполнял payload. **Исправлено:** Flatpak ставит `pyside6-essentials==6.12.0`/`shiboken6==6.12.0` из PyPI поверх BaseApp 6.11 с build-guard (BaseApp/Flathub 6.12 пока нет); на PySide6 < 6.12 приложение не читает файл настроек вообще (карантин + настройки в памяти), т.к. Qt снимает escaping INI до разбора варианта и построчный скан обходится escape-формой. Проверено на реальном BaseApp 6.11.3 и в собранном bundle (§4 BAR-28, §11).
- **BAR-19 исправлен (2026-11-13):** `save()` заменяет только отсутствующий файл или документ кэша любой версии; произвольный/битый/специальный файл не трогается, `chmod` не идёт по симлинк-компонентам. Детали — §4 BAR-19.
- **BAR-25 исправлен (2026-11-13):** `OCRWorker` проверяет поддержку изображений до base64-кодирования и отправки; клиент без флага — fail-closed; ровно один `error`, `done` не эмитится. Детали — §4 BAR-25.
- **BAR-23 исправлен (2026-11-13) для остановки и вызванного `shutdown()`:** `terminate()` и неограниченный `wait()` убраны; воркер отменяется кооперативно (asyncio-задача), остановка и `shutdown()` ограничены бюджетом, запрос `list_models` ограничен общим таймаутом. Подключение `shutdown()` к обычному выходу — отдельная находка BAR-26. Детали — §4 BAR-23.
- Остальные 23 находки (`BAR-02..BAR-27`, кроме BAR-19, BAR-23 и BAR-25) остаются открытыми. Частичные улучшения: пиннинг зависимостей до minor-линии (BAR-08/16), терпимый `valueFromJson` и `read_setting` (BAR-09), нормализация и strict-валидация списков моделей без падения слота (BAR-24), санация выставляет файлу конфига `0600` при миграции (BAR-10, разово).
- Новых находок, кроме BAR-28, не добавлено: изменения в `settings_sanitize.py`/`provider_models.py` проверены отдельно (см. §4 и §6).

## 1. Резюме

На HEAD найдено **28 проблем**: **2 High исправлены (BAR-01 для native-установки, BAR-28 для Flatpak), 9 Medium (BAR-19 исправлен), 13 Low (BAR-25 исправлен; BAR-23 — в части остановки, подключение `shutdown` к обычному выходу остаётся BAR-26), 4 Info**. Критических проблем, требующих немедленного отзыва ключей, нет; релизный Flatpak-артефакт больше не выполняется код из подменённого конфига (PySide6 ≥ 6.12 в bundle + fail-closed санация).

**Топ-3:**
1. **BAR-28 (High, A08, fixed):** Flatpak-сборка использовала BaseApp 6.11.3 с PySide6 6.11.3, который десериализует `PySide::PyObjectWrapper` через pickle; санация обходилась конфигом > 1 МиБ, симлинком или read-only каталогом. Было подтверждено на реальном runtime (payload создал файл-маркер; в PySide6 6.12.0 — `RuntimeError` без выполнения). Теперь Flatpak ставит PySide6 6.12 из pip с build-guard, а на PySide6 < 6.12 приложение не читает файл настроек вообще (карантин + настройки в памяти).
2. **BAR-19 (Medium, A04/A08, fixed):** `model_cache_path` из конфига не проверялся на «это наш файл кэша»: `os.replace` заменял **любой** user-writable файл (`.bashrc`, конфиг другого приложения, FIFO) содержимым кэша. **Исправлено:** write-guard заменяет только отсутствующий файл или документ кэша любой версии, остальные цели не трогает, `chmod` не идёт по симлинку.
3. **BAR-02 (Medium, A02/A04):** API-ключи не отзываются — `KeySecurityManager.delete()` не вызывается нигде; удаление провайдера оставляет ключ в keyring, а добавление нового провайдера с тем же именем может отправить старый ключ на новый `api_base`. Связка: **BAR-04 (Medium, латентная)** — D-Bus-метод `popup_and_translate` не проверяет вызывающего; сейчас путь падает на BAR-15 до отправки, но исправление регрессии «включит» риск без изменения дизайна.

**Отдельно по доступности:** **BAR-22 (Medium, A10:2025)** — на чистой установке (модель ещё не выбрана) нажатие «Translate» навсегда заклинивает вкладку: кнопка скрыта/disabled, прогресс крутится, Stop падает с `AttributeError`; лечится только перезапуском. Тот же fail-open — в OCR-вкладке и при отсутствующем API-ключе (`MissingApiKeyError` из `AnyLLM.create`). Это не RCE/утечка, но нарушает AGENTS.md #14 и воспроизводится без атакующего.

## 2. Сводная таблица

| ID | Severity | Статус | OWASP (cheat sheet / Top-10) | Находка | Ключевые места (HEAD) |
|---|---|---|---|---|---|
| BAR-01 | **High** | **fixed (native)**; остаток — BAR-28 | Deserialization / A08:2021, A08:2025 | pickle-десериализация `ModelSelection` из `QSettings` → RCE на PySide6 < 6.12; исправлено JSON-форматом и санацией сырого INI, но не во Flatpak | `main.py:33-56`; `settings_sanitize.py:82-200`; `main_window.py:118-125,214-223`; `features/ocr.py:94-112` |
| BAR-02 | Medium | open | Secrets Management §2.7 / A02, A04 | Нет отзыва и очистки API-ключей; stale-ключ может уйти новому endpoint | `security.py:17-25`; `provider_dialog.py:43-48,111-113,218-232`; `model_manager.py:66` |
| BAR-03 | Medium | open | Transport Layer Security / A02 | `http://` разрешён для любого хоста → ключ и текст в cleartext | `common.py:108-127`; `provider_dialog.py:96-98`; `tests/test_common.py:6-29` |
| BAR-04 | Medium\* | open | Authorization / A01, A04, A06 | D-Bus `popup_and_translate` без аутентификации вызывающего; практический риск латентный из-за BAR-15 | `ipc.py:13,164-167,207-208`; `main.py:75-89` |
| BAR-05 | Medium | open | Attack Surface / A05, A02:2025 | Flatpak: полный `--socket=session-bus` + неверный `--own-name` | `flatpak/barbaros.yaml:21,23` |
| BAR-06 | Medium | open | XSS/Injection / A03 | HTML-инъекция из ошибки провайдера в `QMessageBox` (`AutoText`, `openExternalLinks=True`) | `main_window.py:91-102`; `common.py:135-140`; `features/text.py:131`; `features/ocr.py:223` |
| BAR-07 | Medium | open | Input Validation (Regex) / A04 | Квадратичный regex `pop_think` в GUI-потоке + нет лимита ответа → зависание UI | `features/text.py:104-110,119-126`; `workers.py:83,122` |
| BAR-08 | Medium | open (partial) | Supply Chain / A06, A08, A03:2025 | Flatpak-зависимости не запинены и без хэшей; `uv.lock` в сборке не участвует (в `pyproject.toml` пиннинг появился) | `flatpak/requirements-flatpak.txt:1-5`; `flatpak/barbaros.yaml:58`; `pyproject.toml:24-33` |
| BAR-09 | Low | open (partial) | Input Validation / A04, A05, A10:2025 | Конфиг — недоверенный вход: `api_base`/схема не валидируются, JSON верной формы, но неверного типа роняет старт | `common.py:55-70`; `main_window.py:45-66,190-195`; `model_manager.py:42-48` |
| BAR-10 | Low | open (partial) | Key Management / A05 | Права QSettings-файла определяются umask; `0600` выставляется только при разовой миграции | `main.py:33-56`; `atomic_file.py:242` |
| BAR-11 | Low | open | Secrets Management §2.9 / A04, A10:2025 | `NoKeyringError` не обрабатывается: без Secret Service падение на старте | `security.py:17-25`; `providers_card.py:132-134`; `provider_dialog.py:47,180` |
| BAR-12 | Low | open | Authorization/Logging / A04, A09, A10:2025 | Хрупкий SIGUSR1-fallback: `name=None` → краш, сигнал чужому процессу, `assert`/bare `except`/`print` | `ipc.py:25,31-32,79,89,130-145,164-167,204` |
| BAR-13 | Low | open | Output encoding / A03 | Rich text из внешних имён и ответа LLM (`QLabel`, `QTextEdit.setText`); источник — `model.id` из кэша | `filterable_combobox.py:70-72,378-381`; `providers_card.py:66,106`; `features/text.py:125`; `features/ocr.py:208,213` |
| BAR-14 | Low | open | Input Validation / A04 | Нет лимитов на текст/изображение/ответ; невалидированный `ChatCompletion` (`choices=[]`, `content=None`) | `features/text.py:61-76,119-126`; `features/ocr.py:150-213`; `workers.py:83,111-115,122`; `image_manager.py:76-92,107-132` |
| BAR-15 | Low | open | Secure Code Review / A04, A09, A10:2025 | Регрессия `process_translation_request`: popup-перевод сломан, ошибка маскируется как успех | `main.py:75-89`; `features/text.py:41,45` |
| BAR-16 | Low | open (partial) | Supply Chain / A06, A08, A03:2025 | CI отключён, нет Dependabot/pip-audit/`SECURITY.md`, bundle не подписан | `.github/workflows/flatpak.yml.off`; `tasks.py:41,46,63,71` |
| BAR-17 | Info | open (частично улучшено) | Logging / A09 | Логирование через `print()`: нет структуры/экранирования; секреты не логируются; добавлены print пути конфига/бэкапа | `main.py:36,41,47,49,99`; `ipc.py:137,141,144,204`; `main_window.py:53`; в `workers.py`/`model_manager.py` новых print нет (BAR-23 перевёл затронутые сообщения на `logging`) |
| BAR-18 | Info | open | User Privacy / A04 | Скриншот (по умолчанию весь экран) и clipboard уходят провайдеру без in-app уведомления | `image_manager.py:162-173,180-181`; `workers.py:111-115`; `main.py:75-89`; `README.md:33` |
| **BAR-19** | **Medium\*\*** | **fixed** | Secure Code Review (file path sink) / A04, A08 | `model_cache_path` — произвольный sink записи; write-guard заменяет только отсутствующий файл или кэш любой версии, остальные цели не трогает; `chmod` каталога не идёт по симлинку | `main_window.py:44-50`; `model_cache.py` (`_may_replace`, `ModelCacheDocument.is_cache_document`); `atomic_file.py` (`_tighten_directory`) |
| **BAR-20** | Low | open | Denial of Service / A04 | Кэш читается/парсится заново на каждого `RESTORE`-провайдера в GUI-потоке: 100 провайдеров + 4 МиБ ≈ 7.2 с старта | `main_window.py:61-66`; `model_manager.py:162-181,483-496`; `model_cache.py:325-337` |
| **BAR-21** | Low | open | Input Validation / A08, A02:2025 | Кэш в общем каталоге читается без проверки владельца/прав (defense-in-depth, вне формальной модели) | `atomic_file.py:118-155`; `model_cache.py:299-321` |
| **BAR-22** | **Medium** | open | Error Handling/DoS / A10:2025 (A04:2021) | Исключение в GUI-слоте после установки «загрузочного» состояния → вкладка заклинена навсегда; Stop падает | `features/text.py:61-76,86-90`; `features/ocr.py:155-160,180-181`; `workers.py:73,98,145`; `model_manager.py:66` |
| **BAR-23** | Low | **fixed (shutdown ограничен; подключение `shutdown` к обычному выходу — BAR-26)** | DoS/Threading / A10:2025 (A04:2021) | `terminate()`+неограниченный `wait()`, нет app-level таймаута запроса → зависание GUI при остановке/выходе. Закрыто: кооперативная отмена asyncio-задачи, `wait(ms)` с бюджетом, общий таймаут `list_models`, общий дедлайн `shutdown()` | `model_manager.py:214-288`; `workers.py:25,129-250` |
| **BAR-24** | Low | open (partial) | LLM output validation/DoS / A06:2025 (A04:2021) | Неограниченный ответ `list_models` от endpoint (нормализация и strict-валидация добавлены, лимитов и размера ответа нет; BAR-23 добавляет только общий таймаут) | `workers.py:201-217`; `model_manager.py:401-420,483-496`; `filterable_combobox.py:263-273` |
| **BAR-25** | Low | **fixed** | LLM multimodal/Privacy / A10:2025 (A04:2021) | OCR fail-open закрыт: поддержка изображений проверяется до кодирования/отправки, неизвестный флаг — fail-closed, ровно один `error`, без `done` | `workers.py:100-126`; `tests/unit/test_workers.py`; `tests/system/test_ocr_worker_flow.py` |
| **BAR-26** | Info | open | Error Handling/Logging / A10, A09:2025 | `aboutToQuit.connect(cleanup)` внутри `save_language` → при обычном выходе shutdown не вызывается | `main.py:68-73,97-101,177-188` |
| **BAR-27** | Info | open | Privacy/Honesty / A09:2025 | Гигиена документации: README обещает «Secure API calls», хотя `http://` разрешён, а уведомлений о передаче нет | `README.md:33,273`; `docs/` |
| **BAR-28** | **High** | **fixed** | Deserialization / Supply Chain / A08, A06:2021, A03:2025 | Flatpak собирался на BaseApp 6.11.3 (PySide6 6.11.3), который unpickle-ит `QSettings`; санация обходилась конфигом > 1 МиБ, симлинком, read-only каталогом и квотированной формой значения → RCE; исправлено пином PySide6 6.12 в bundle + отказом читать файл настроек на старом PySide6 | `flatpak/barbaros.yaml`; `flatpak/bar28_guard.py`; `settings_sanitize.py`; `main.py` |

\* BAR-04 — Medium как дефект дизайна; в текущем состоянии (BAR-15 открыт) практическая severity — Low: D-Bus-вызов приводит только к показу окна и `AttributeError` до отправки. После исправления BAR-15 без изменения дизайна риск станет реальным (clipboard → облачный провайдер).
\*\* BAR-19 — Medium, потому что impact — тихая деструктивная запись (integrity/availability), отдельный класс от RCE. Прямой эскалации относительно BAR-01 нет; Medium отражает, что sink переживёт исправление BAR-01 и что «данные конфига едут между машинами» (dotfiles/sync/бэкап). Исправлено 2026-11-13 (write-guard); severity оставлена как историческая оценка.

---

## 3. Детали: повторная проверка BAR-01..BAR-18

### BAR-01. pickle-десериализация `ModelSelection` из `QSettings` → RCE

- **OWASP:** `Deserialization_Cheat_Sheet.md` → «Python / Clear-box Review»: *«Unpickling can execute arbitrary code; never unpickle untrusted data»*; «Using Alternative Data Formats»; `Secure_Code_Review_Cheat_Sheet.md` → «Deserialization Vulnerabilities». Top-10: A08:2021 / A08:2025 Software or Data Integrity Failures (CWE-502).
- **Статус (2026-11-13): исправлено для native/pip-установки; во Flatpak остаётся BAR-28.** Исправление в `3e30fa3`:
  1. `settings_sanitize.sanitize_pickled_settings()` читает сырой INI до создания `QSettings` и удаляет строки, значение которых начинается с `@Variant(` и содержит `PySide::PyObjectWrapper`; оригинал сохраняется рядом как бэкап `0600` (`settings_sanitize.py:82-200`).
  2. Выбор модели хранится как JSON (`ModelSelection.to_dict/from_dict`, `main_window.py:118-125,214-223`, `features/ocr.py:94-112`); в `QSettings.setValue` больше не передаются Python-объекты.
  3. `common.read_setting()` переживает `RuntimeError` от PySide6 6.12 (отказ от pickle) и восстанавливает соседние ключи секции (`common.py:11-43`).
  4. `pyproject.toml:27` пиннит `pyside6-essentials~=6.12.0`; `uv.lock` пересобран.
- **Место (HEAD):** запись — `main_window.py:118-125`, `features/ocr.py:106-112`; чтение — `main_window.py:214-223`, `features/ocr.py:94-104`; тип — `filterable_combobox.py:165-185`; санация — `main.py:33-46`, `settings_sanitize.py:51-200`.
- **Evidence (2026-11-13):**
  - В `.venv` (PySide6 **6.12.0**) на подменённом INI с `PySide::PyObjectWrapper` чтение `QSettings.value()` бросает `RuntimeError: Failed to deserialize Python object from QDataStream…`, pickle-payload **не выполняется** (маркер не создан).
  - Реальный `App()` на легаси-конфиге стартует, конфиг очищается, бэкап на месте, соседние ключи живы (`tests/system/test_legacy_settings.py`).
  - Ограничение: под PySide6 6.11.x `read_setting` не спасает — версия unpickle-ит, а не бросает исключение; это был путь BAR-28, теперь закрытый fail-closed санацией и пином PySide6 6.12 (см. §4).
- **Сценарий (для PySide6 < 6.12 / Flatpak):** см. BAR-28. Для native-установки с 6.12 — запись в конфиг больше не даёт выполнения кода; остаточный impact — только потеря легаси-выбора модели.
- **Остаточные замечания:** санация эвристична (вырезает любое значение с маркером после `@Variant(`, а не два известных ключа), но теперь видит и квотированную форму `"@Variant(...` (BAR-28: QSettings квотирует значения с запятой — обычным байтом pickle). При ошибке очистки на PySide6 < 6.12 файл уносится от `QSettings`; бэкап/карантин с payload остаётся на диске, но приложением не читается. См. BAR-28 и §6.
- **Рекомендация:** остаток закрыт через BAR-28 (PySide6 6.12 в Flatpak + fail-closed санация). Долгосрочно — отказаться от `QSettings` для выбора модели в пользу JSON-стора (механика уже есть в `atomic_file.py`).

### BAR-02. Неполный жизненный цикл API-ключей

- **OWASP:** `Secrets_Management_Cheat_Sheet.md` §2.7.3 «Revocation», §2.7.2 «Rotation», §2.6 «Auditing»; `Key_Management_Cheat_Sheet.md` → «Zeroization and Destruction». Top-10: A02, A04.
- **Статус:** open, Medium (без изменений).
- **Место:** `security.py:17-25` (`get`/`delete`), `provider_dialog.py:43-48` (предзаполнение ключа), `:111-113` (запись только непустого), `:218-232` (удаление провайдера), `model_manager.py:66` (чтение ключа для клиента), `model_manager.py:182-188` (`remove()`).
- **Evidence:** `KeySecurityManager.delete()` **не вызывается нигде** (`grep` по `api_key_manager.delete` даёт только определение). Fake in-memory keyring: после `ModelManager.remove("audit-provider")` ключ остаётся доступным. Очистка поля ключа в диалоге редактирования + сохранение оставляет старый ключ (`get()` возвращает старое значение). `delete()` по-прежнему ловит только `PasswordDeleteError`, не `KeyringError`.
- **Сценарий:** (1) пользователь удаляет облачного провайдера, считая, что ключ отозван, — секрет остаётся в keyring; (2) пользователь переиспользует имя провайдера для нового аккаунта/локального шлюза, не вводя ключ: `ProviderClient.client()` возьмёт старый ключ и отправит его на новый `api_base`; (3) сменить endpoint, оставив провайдера, нельзя без перезаписи ключа: «пусто» трактуется как «оставить старый».
- **Рекомендация:** вызывать `api_key_manager.delete()` при удалении провайдера (после подтверждения), но **не** при `ModelManager.update()` (иначе редактирование сотрёт ключ). Добавить явную кнопку «Удалить сохранённый ключ» с подтверждением. В `delete()` ловить `keyring.errors.KeyringError`, а не только `PasswordDeleteError`. Тест с fake backend: «удалил провайдера / очистил ключ → в хранилище пусто».

### BAR-03. `http://` допускается для любого хоста → cleartext

- **OWASP:** `Secrets_Management_Cheat_Sheet.md` §2.8 «TLS Everywhere»; `Transport_Layer_Security_Cheat_Sheet.md` → «Use TLS For All Pages». Top-10: A02.
- **Статус:** open, Medium (без изменений).
- **Место:** `common.py:108-127` (шаблон `^https?://` на `:113`), `provider_dialog.py:96-98` (единственная проверка URL), `tests/test_common.py:6-29` (тесты закрепляют `http://google.com`, `http://192.168.0.1:1234` как валидные), `model_manager.py:66` (URL уходит в `AnyLLM.create`).
- **Evidence:** `is_valid_url('http://evil.example.com') == True`, `is_valid_url('http://169.254.169.254/…') == True`, `http://192.168.0.1:1234/v1` → True. `ftp://`, `javascript:`, `user:pass@host` → False; `http://[::1]:8080` → False (IPv6-loopback не поддержан). При custom OpenAI-совместимом endpoint `api_base` становится `base_url` httpx; в открытом виде уходят `Authorization: Bearer <ключ>` и весь переводимый текст. Для `api_base=None` any-llm использует HTTPS по умолчанию.
- **Рекомендация:** один helper (например, `api_base_problem(url)`) с `urllib.parse`: разрешать `https` для любых хостов; `http` — только `localhost`/`127.0.0.0/8`/`::1`; при не-loopback `http` — отказ. Применять и в диалоге, и при загрузке из конфига (BAR-09). Обновить `tests/test_common.py`.

### BAR-04. D-Bus `popup_and_translate` без проверки вызывающего

- **OWASP:** `Authorization_Cheat_Sheet.md` → «Deny by Default», «Validate Permissions on Every Request», «Enforce Least Privileges»; `Attack_Surface_Analysis_Cheat_Sheet.md`; `User_Privacy_Protection_Cheat_Sheet.md` → «Honesty & Transparency». Top-10: A01, A04, A06.
- **Статус:** open, Medium (практическая — Low, пока BAR-15 открыт). Без изменений.
- **Место:** `ipc.py:13` (`SERVICE_NAME`), `:164-167` (`registerService`, `registerObject(..., ExportAllSlots)` на пути `/`), `:207-208` (`@Slot()` → `app.process_translation_request()`), `main.py:75-89` (чтение clipboard + программный клик «Translate»).
- **Evidence:** под `dbus-run-session` сторонний процесс вызывает экспортированный слот; сервер-заглушка реально выполнил обработчик, клиент получил `ReplyMessage` без ошибки. Никакой проверки PID/uid/имени вызывающего, токена, подтверждения или rate limit нет. `QDBusInterface(SERVICE_NAME, "/", "", bus)` на PySide6 6.11/6.12 невалиден; Qt экспортирует интерфейс, производный от Python-класса (для приложения — `local.barbaros.ipc.IPCService`), вызов делается с этим именем или через `gdbus`.
- **Сценарий:** любая программа того же пользователя (вне sandbox или Flatpak с разрешением `talk-name`) вызывает метод; запущенный экземпляр читает буфер обмена и отправляет текст облачному провайдеру без явного действия пользователя; повторные вызовы — платные API-запросы и перекрытие окна. Прямого канала «прочитать буфер атакующим» нет (`void`), но при подмене `api_base` данные можно направить на свой endpoint.
- **Оговорка:** на HEAD `process_translation_request` падает с `AttributeError` до отправки (BAR-15) — сейчас риск латентный. Если обработчик бросает исключение, клиент всё равно получает валидный ответ — сбой неотличим от успеха.
- **Рекомендация:** разделить «показать окно» и «перевести из буфера»: IPC/`--popup` должны только фокусировать окно; перевод из clipboard — только по явному действию пользователя в UI. Если автоперевод нужен — подтверждение в UI с указанием провайдера, rate limit/дедупликация, проверка вызывающего (`QDBusContext`/`GetConnectionUnixProcessID` + сверка `/proc/<pid>/exe`), узкий D-Bus-интерфейс вместо `ExportAllSlots` на `/`.

### BAR-05. Flatpak: полный `--socket=session-bus` и неверный `--own-name`

- **OWASP:** `Authorization_Cheat_Sheet.md` → «Enforce Least Privileges», «Deny by Default»; `Attack_Surface_Analysis_Cheat_Sheet.md`. Top-10: A05, A02:2025.
- **Статус:** open, Medium (без изменений).
- **Место:** `flatpak/barbaros.yaml:21` (`--socket=session-bus`), `:23` (`--own-name=org.frimn.barbaros`); `ipc.py:13`.
- **Evidence:** `--socket=session-bus` отключает фильтрацию xdg-dbus-proxy и даёт приложению нефильтрованный доступ ко всей сессии (Flatpak docs называют это security risk). Строка `--own-name=org.frimn.barbaros` не совпадает с app-id/`SERVICE_NAME` `io.github.frimn.barbaros`; имя app-id разрешено по умолчанию, это разрешение лишнее. `--talk-name=org.freedesktop.secrets` нужен для keyring и сам по себе не даёт чужих секретов.
- **Рекомендация:** убрать `--socket=session-bus`; оставить `--talk-name=org.freedesktop.secrets`; убрать `--own-name=org.frimn.barbaros`. Проверить IPC после изменения (`flatpak run --log-session-bus …`).

### BAR-06. HTML-инъекция из ошибки провайдера в `QMessageBox`

- **OWASP:** `Cross_Site_Scripting_Prevention_Cheat_Sheet.md` → «Output Encoding for HTML Contexts», «HTML Sanitization», «Safe Sinks»; `Injection_Prevention_Cheat_Sheet.md` → «Rule #3»; `LLM_Prompt_Injection_Prevention_Cheat_Sheet.md` → «HTML and Markdown Injection». Top-10: A03, A05:2025.
- **Статус:** open, Medium (без изменений).
- **Место:** `main_window.py:91-102` (`msg = url_to_html_links(msg)` → `QMessageBox.critical`), `common.py:135-140` (`url_to_html_links` **без** `html.escape`); источники ошибок: `model_manager.py:354-356`, `workers.py:87,126`; независимые sink'и: `features/text.py:131`, `features/ocr.py:223`.
- **Evidence:** `url_to_html_links('<b>quota</b> <a href="file:///etc/passwd">x</a> https://…')` сохраняет живые теги и линкификацию. `QMessageBox` использует `Qt.TextFormat.AutoText` и `openExternalLinks=True`; `<img src="file://…">` загружается, клик по `<a href="file://…">` приводит к `QDesktopServices`/`xdg-open`. Доставка недоверенного текста подтверждена локальным fake-endpoint: `any_llm` кладёт тело HTTP-ошибки в `str(exception)`, оно уходит в `error.emit(...)` и в `QMessageBox.critical` без экранирования.
- **Влияние:** UI-spoofing в системном модальном окне (поддельный текст «ключ истёк, войдите заново»), фишинговая ссылка, открытие локальных `file://`-путей. JavaScript/команд не исполняется (Qt rich text без скриптов).
- **Рекомендация:** для ошибок — plain text: `box.setTextFormat(Qt.TextFormat.PlainText)` (или `setTextInteractionFlags` без ссылок), не использовать `url_to_html_links` для недоверенных сообщений. Если ссылки нужны — сначала `html.escape(text, quote=True)`, затем линкификация по экранированному тексту с экранированием URL в `href`; ограничить длину сообщения.

### BAR-07. Квадратичный `pop_think` regex в GUI-потоке

- **OWASP:** `Input_Validation_Cheat_Sheet.md` → «Regular Expressions (Regex)»; `LLM_Prompt_Injection_Prevention_Cheat_Sheet.md` → «Output Monitoring and Validation». Top-10: A04, A06:2025.
- **Статус:** open, Medium (без изменений).
- **Место:** `features/text.py:104-110` (`re.search(r"<think>.*?<\/think>", text, MULTILINE|DOTALL)`), вызов в GUI-слоте `:119-126`; нет `max_tokens`/лимита ответа (`workers.py:83,122`).
- **Evidence (замеры):** худший случай — строка из повторяющихся `<think>` без закрывающего тега; рост ~×4 на удвоение длины: 5 КБ — 13.2 мс, 10 КБ — 54.8 мс, 20 КБ — 211.7 мс, 40 КБ — 784.7 мс, 80 КБ — 3165 мс, 160 КБ — **17.7 с** (квадратично). Regex выполняется в главном потоке; 1 МБ ≈ минуты зависания UI. Дополнительно `text = text[len(think_text):]` режет не по позиции блока, а по его длине (логическая ошибка при `<think>` не в начале).
- **Рекомендация:** заменить regex на линейный `str.find("<think>")`/`find("</think>")`; жёстко ограничить длину ответа до обработки (1–2 МБ) и reasoning; передавать `max_tokens` в `acompletion`; добавить не функциональный тест на время обработки большого ответа.

### BAR-08. Непинованные зависимости Flatpak / невоспроизводимая сборка

- **OWASP:** `Software_Supply_Chain_Security_Cheat_Sheet.md` → «Lockfile/Version Pinning»; `Vulnerable_Dependency_Management_Cheat_Sheet.md`; `Dependency_Graph_SBOM_Cheat_Sheet.md`. Top-10: A06:2021, A08:2021 / A03:2025.
- **Статус:** open, Medium, **частично улучшено.** В `pyproject.toml:24-33` зависимости запинены до minor-линии (`pyside6-essentials~=6.12.0`, `any-llm-sdk[all]~=1.50.0`, …), `uv.lock` пересобран. Но Flatpak-сборка не использует ни `pyproject.toml`, ни `uv.lock`.
- **Место:** `flatpak/requirements-flatpak.txt:1-5` (`psutil`, `any-llm-sdk[all]`, `keyring>=25.7.0`, `psygnal>=0.15.1`, `dataclasses-json>=0.6.7` — без версий/хэшей), `flatpak/barbaros.yaml:58` (`pip3 install -r requirements-flatpak.txt`), `:60` (`pip3 install --no-deps barbaros`).
- **Evidence:** `--require-hashes` нет; сборка резолвит последние версии PyPI на момент сборки. `uv.lock` фиксирует native/dev-окружение (167 пакетов, 2575 `sha256`-хэшей), но не Flatpak-сборку. `any-llm-sdk[all]` тянет SDK всех провайдеров — широкая транзитивная поверхность. Пиннинг в `pyproject.toml` на сборку не влияет.
- **Рекомендация:** генерировать hashed-requirements из `uv.lock` (`uv export --format requirements-txt --hashes` / `uv pip compile --generate-hashes`) и ставить `pip3 install --require-hashes -r …`; собирать wheel в CI из зафиксированного lock; добавить SBOM (`uv export`/Syft).

### BAR-09. Конфиг как недоверенный вход: нет валидации и fail-safe старта

- **OWASP:** `Input_Validation_Cheat_Sheet.md` → «Parse Safely, Then Validate»; `Secure_Code_Review_Cheat_Sheet.md` → «Configuration & Deployment»; `Error_Handling_Cheat_Sheet.md`. Top-10: A04, A05, A10:2025.
- **Статус:** open, Low, **частично улучшено.** `valueFromJson` теперь ловит `json.JSONDecodeError`/`TypeError`/`RecursionError` и возвращает default (`common.py:55-70`), поэтому битый JSON и глубоко вложенное значение больше не роняют старт. Схема данных по-прежнему не валидируется.
- **Место:** `common.py:55-70`; `main_window.py:45-66` (`model_cache_path`, `llm_providers`), `:190-195` (`target_language_list`), `:214-223` (выбор модели); `model_manager.py:42-48` (`ProviderMeta`).
- **Evidence (изолированный XDG):** обрезанный JSON теперь не роняет старт, но JSON **верной формы, неверного типа** — роняет: `llm_providers` = число/строка → `TypeError`/итерация по символам; `llm_providers` = объект → итерация по ключам → `ProviderMeta.from_dict(str)` → `AttributeError`; `api_base="http://evil.example.com"` из конфига принимается (валидатор URL — только в диалоге, `provider_dialog.py:96`). `api_base=123` коэрцится `dataclasses_json` в `"123"`. `model_cache_path` валидируется формально (`model_cache.py:51-100`: только непустой абсолютный путь), но это узкое улучшение (и BAR-19).
- **Влияние:** подмена конфига перенаправляет ключ/текст на чужой `api_base`; повреждённый конфиг (после некорректного завершения/заполнения диска) вызывает цикл падений при автозапуске — противоречит AGENTS.md #14.
- **Рекомендация:** валидировать **схему**, а не только JSON: `llm_providers` — список объектов с известными полями; `api_base` (`str | None` + helper из BAR-03), `name`, `language`, `target_language_list`; ограничить число провайдеров; при ошибке логировать, удалять проблемный ключ и стартовать с `default_providers`. Тест: конфиг с неверными типами → приложение стартует.

### BAR-10. Права файла настроек по umask

- **OWASP:** `Key_Management_Cheat_Sheet.md` → «Storage»; `Logging_Cheat_Sheet.md` → «Data to exclude». Top-10: A05, A02:2025.
- **Статус:** open, Low, **частично улучшено.** При разовой миграции BAR-01 файл перезаписывается атомарно с `0600` (`atomic_file.py:242`). Но последующие записи `QSettings` снова создают файл с правами по umask, и это прямо зафиксировано в `docs/settings-migration.md` §6.
- **Место:** `main.py:33-56`; в `src/` нет `chmod`/`umask` для QSettings после записи.
- **Evidence:** режим `QSettings`-файла = `0666 & ~umask`: umask 022 → `0644`, umask 002 → `0664`, umask 077 → `0600`; повторная запись не ужесточает. Новый файл кэша моделей — исключение (`0600`/`0700`, `atomic_file.py:242,250,293`), но это другой файл.
- **Влияние:** на машинах с проходимым `$HOME` и permissive-umask/общей группой другой пользователь прочитает метаданные провайдеров и внутренние адреса; запись в конфиг в связке с BAR-28/BAR-09 даёт больше. Defense-in-depth.
- **Рекомендация:** после каждой записи (или при старте после sanitize) выставлять `os.chmod(settings.fileName(), 0o600)` и при необходимости `0700` на каталог (в `try/except OSError`, no-op на Windows); сохранить инвариант «секреты никогда не пишутся в QSettings» и закрыть его тестом.

### BAR-11. `NoKeyringError` не обрабатывается

- **OWASP:** `Secrets_Management_Cheat_Sheet.md` §2.9; `Key_Management_Cheat_Sheet.md` → «Storage» (fallback в plaintext отсутствует — это хорошо). Top-10: A04, A10:2025.
- **Статус:** open, Low (без изменений).
- **Место:** `security.py:17-25`; `providers_card.py:132-134` (чтение keyring при конструировании карточки); `provider_dialog.py:47,180`.
- **Evidence:** при `keyring.set_keyring(fail.Keyring())` вызовы бросают `NoKeyringError`; реальный `App(...)` падает при старте — traceback через `security.py:19` из построения `ProvidersCard` (дефолтный `ollama`). В Flatpak доступ к `org.freedesktop.secrets` объявлен, поэтому проблема маловероятна.
- **Рекомендация:** обернуть вызовы в `try/except keyring.errors.KeyringError`, возвращать типизированный результат/`None`; при старте проверять `keyring.get_keyring()` и показывать неблокирующее предупреждение; не читать keyring в конструкторе `ProvidersCard`; в `delete()` ловить `KeyringError`. **Не** добавлять plaintext-fallback.

### BAR-12. Хрупкий SIGUSR1-fallback и обработка ошибок IPC

- **OWASP:** `Authorization_Cheat_Sheet.md` → «Deny by Default», «Exit Safely when Authorization Checks Fail»; `Logging_Cheat_Sheet.md`; `Error_Handling_Cheat_Sheet.md`. Top-10: A01, A09, A10:2025.
- **Статус:** open, Low (без изменений).
- **Место:** `ipc.py:25,31-32` (`assert` как проверка), `:79` (`contextlib.suppress(BaseException)`), `:89` (bare `except:`), `:130-145` (перебор `psutil.process_iter`, `None.lower()` на `:134`, `os.kill` по имени на `:136`, `print` на `:137,141,144`), `:164-167` (занятое имя → необработанный `Exception` на `:165`), `:204` (`print`).
- **Evidence:** `proc.info['name']` может быть `None` → `AttributeError` в `barbaros --popup`. Сравнение только по имени и первый матч: процесс, назвавшийся `Barbaros`, может получить SIGUSR1 вместо приложения (default action SIGUSR1 = terminate). Занятие `SERVICE_NAME` другим процессом → `registerService` = False → `raise Exception('')` → падение при старте, fallback не срабатывает. `assert` исчезают под `python -O`.
- **Рекомендация:** убрать сканирование процессов; для single-instance использовать lock-файл в `$XDG_RUNTIME_DIR/app/<app-id>/` (`O_CREAT|O_EXCL`, 0600) и/или `AF_UNIX`-сокет с `SO_PEERCRED`; при fallback — `name = proc.info.get("name") or ""`, проверка uid/exe/cmdline; не падать на конфликте имени, а логировать и работать без D-Bus; `assert` → явные проверки; `except:` → конкретные исключения + `logging`; `print` → `logging`.

### BAR-13. Rich text из внешних имён и ответа LLM

- **OWASP:** `Cross_Site_Scripting_Prevention_Cheat_Sheet.md` → «Output Encoding», «Safe Sinks»; `Input_Validation_Cheat_Sheet.md` → «Validating Rich User Content»; `LLM_Prompt_Injection_Prevention_Cheat_Sheet.md` → «HTML and Markdown Injection». Top-10: A03, A05:2025.
- **Статус:** open, Low (без изменений).
- **Место:** `filterable_combobox.py:70-72` (`display_label.setText(elided_text)` + tooltip), `:378-381` (выбранная модель); `providers_card.py:66,106` (`QLabel(text)`/`QLabel(name)`); `features/text.py:125` и `features/ocr.py:208,213` (`QTextEdit.setText(ответ LLM)`); промпт `resources/translation_agent_prompt.md` просит сохранять HTML. Новый источник: `model.id` из JSON-кэша (недоверенный файл, `MAX_MODEL_ID_LEN=1024`).
- **Evidence:** `QLabel`/`LinkLabel` по умолчанию `AutoText`; `QLabel('<img src="file://…"><h1>PWN</h1>…')` реально рендерится, локальный PNG грузится, `sizeHint` меняется (184×289 против 72×17). `QTextEdit.setText` тоже парсит HTML (`toHtml()` содержит `img`/`h1`). Ссылки **не кликабельны**, но не из-за `LinkLabel` (в `link_label.py` нет `mousePressEvent`), а из-за переназначения `display_label.mousePressEvent` (`filterable_combobox.py:37,342`); у read-only `QTextEdit` нет `LinksAccessibleByMouse`. Remote-картинки Qt не грузит.
- **Рекомендация:** для всех меток с внешними именами (`model.id`, `provider.name`, `api_base`, `provider_type`) — `setTextFormat(Qt.TextFormat.PlainText)`; tooltip тоже plain text; ответ LLM выводить через `setPlainText()` либо рендерить allowlist после `html.escape` (переносы, bold/italic; без `img/a/style`); согласовать с промптом отказ от «сохранять HTML».

### BAR-14. Нет лимитов и валидации ответа модели

- **OWASP:** `LLM_Prompt_Injection_Prevention_Cheat_Sheet.md` → «Input Validation and Sanitization», «Output Monitoring and Validation»; `File_Upload_Cheat_Sheet.md` → «Upload and Download Limits», «File Content Validation». Top-10: A04, A06:2025.
- **Статус:** open, Low (без изменений).
- **Место:** `features/text.py:61-76,119-126`; `features/ocr.py:150-213`; `workers.py:83,122` (`acompletion` без `max_tokens`), `:111-115` (base64 без лимита); `image_manager.py:76-92,107-132` (PNG без ограничений).
- **Evidence:** `max_tokens` не передаётся. `QImageReader.allocationLimit()` = 256 МБ — только грубая защита Qt; PNG 8192×8192 весом 64 КиБ декодируется в 64 МиБ, после чего кодируется в base64 и уходит в запрос; downscale нет. `ChatCompletion(choices=[])` → `IndexError`; `content=None` → `TypeError` в `pop_think` — слот падает до `setText`, пользователь видит пустой результат без ошибки.
- **Рекомендация:** лимиты на текст (например, 100–200 тыс. символов), изображение (≤20 Мп и ≤10 МБ после декодирования, downscale перед base64), `max_tokens`, таймауты; при превышении — понятная ошибка, а не отправка. Валидировать `resp.choices`, `content or ""`, `finish_reason`; тесты на пустой/None-ответ.

### BAR-15. Регрессия `process_translation_request`

- **OWASP:** `Secure_Code_Review_Cheat_Sheet.md`; `Authorization_Cheat_Sheet.md` → «Exit Safely when Authorization Checks Fail»; `Error_Handling_Cheat_Sheet.md`; `Logging_Cheat_Sheet.md`. Top-10: A04, A09, A10:2025.
- **Статус:** open, Low (без изменений).
- **Место:** `main.py:75-89`; у `MainWindow` атрибутов `orig_text`/`translate_button` нет (они у `TextFeature`: `features/text.py:41,45`). В v2025.9.2 `MainWindow` их имел — регрессия появилась при рефакторинге.
- **Evidence:** живой запуск: `app.process_translation_request()` → `AttributeError: 'MainWindow' object has no attribute 'orig_text'`. D-Bus-вызов слота, который бросает исключение, возвращает клиенту **валидный ответ** (`void`), сервер печатает traceback и продолжает работу: сбой неотличим от успеха. В дереве нет тестов IPC (остался только `__pycache__`).
- **Влияние:** заявленный popup-перевод не работает; ошибка маскируется (вызывающий считает вызов успешным). Security-последствие: пока путь сломан, BAR-04 не эксплуатируется; при исправлении — включится, если не поменять дизайн.
- **Рекомендация:** вынести операцию в публичный метод `App`/`MainWindow` (например, `App.translate_from_text(text)`); D-Bus-метод должен возвращать явный статус/ошибку, а не `void`; добавить тест `process_translation_request` с подменённым clipboard и мок-провайдером.

### BAR-16. CI/supply-chain: отключённый workflow, отсутствие мониторинга, неподписанный bundle

- **OWASP:** `Software_Supply_Chain_Security_Cheat_Sheet.md` → «Harden Build Tools», «Enforce Code Signing», «Leverage Security Automation»; `CI_CD_Security_Cheat_Sheet.md`; `Vulnerable_Dependency_Management_Cheat_Sheet.md`. Top-10: A06:2021, A08:2021 / A03:2025.
- **Статус:** open, Low, **частично улучшено** (появился пиннинг зависимостей в `pyproject.toml`, но CI/подписи/monitoring не появились).
- **Место:** `.github/workflows/flatpak.yml.off`; `tasks.py:41` (pytest), `:46` (ruff), `:63` (ccache), `:71` (bundle без `--gpg-sign`); отсутствуют `SECURITY.md`, `.github/dependabot.yml`, pip-audit/renovate.
- **Evidence:** workflow отключён суффиксом `.off`, ссылается на несуществующий `flatpak/io.github.frimn.barbaros.yml`; actions — mutable major-теги (`actions/checkout@v4`, `actions/setup-python@v5`, `svenstaro/upload-release-action@v2`); `pip install build` без версии; `overwrite: true` для release-ассетов. Автоматической сборки/проверки нет.
- **Рекомендация:** включить workflow и исправить путь манифеста; пинить actions по полному SHA; пинить build-tools; подписывать bundle (`--gpg-sign`) и публиковать SHA256/SLSA-provenance; не перезаписывать release-ассеты; для релизных сборок — чистый эфемерный раннер без `--ccache`; Dependabot/Renovate + `pip-audit`/`uv audit` в `tasks.py` и CI; `SECURITY.md`.

### BAR-17. Логирование через `print()` (Info)

- **OWASP:** `Logging_Cheat_Sheet.md` → «Log Injection», «Data to exclude», «Event attributes». Top-10: A09.
- **Статус:** open (частично улучшено в новом коде), Info. Добавление BAR-01 добавило print'ы пути конфига и бэкапа.
- **Место:** `main.py:36,41,47,49,99`; `ipc.py:137,141,144,204`; `main_window.py:53,211,222`; `workers.py` больше не печатает через `print()` (BAR-23 перевёл `ListModelWorker` на `logging`); `features/ocr.py:101`; `features/settings.py:109`; `filterable_combobox.py:60,401,406,413`. Новые `model_cache.py`/`atomic_file.py`/`settings_sanitize.py` и часть `model_manager.py` используют `logging` с `%r`+truncate.
- **Evidence:** служебные сообщения без уровней/времени; имя провайдера из пользовательского ввода/конфига может содержать CR/LF (log injection). Содержимое буфера, OCR-текст, ответы LLM и ключи **не** печатаются — утечки нет. Путь к конфигу/кэшу (имя пользователя, приватные каталоги) уходит в journald/терминал; `!r` экранирует CR/LF.
- **Рекомендация:** `logging` вместо `print`, структурированные записи, `%r`/truncate для внешних строк, уровни, исключение недоверенных значений из шаблонов; путь к кэшу/конфигу — `DEBUG`, не INFO; не логировать содержимое перевода/OCR/clipboard.

### BAR-18. Приватность: скриншот/clipboard уходят провайдеру без in-app уведомления (Info)

- **OWASP:** `User_Privacy_Protection_Cheat_Sheet.md` → «Honesty & Transparency»; `LLM_Prompt_Injection_Prevention_Cheat_Sheet.md` → «Multimodal Injection», «Data Exfiltration». Top-10: A04.
- **Статус:** open, Info (без изменений).
- **Место:** `image_manager.py:162-173` (`_take_screenshot` — весь экран), `:180-181`; `workers.py:111-115` (PNG → base64 → провайдер); `main.py:75-89` (clipboard → перевод); `README.md:33` (честное раскрытие, но не в UI).
- **Evidence:** по коду скриншот по умолчанию — весь экран, уведомлений/подтверждения перед отправкой нет; автоперевод из clipboard по IPC/`--popup` вызывается без явного действия пользователя в UI. Вредоносной телеметрии не найдено: сеть только через `any_llm` к настроенному провайдеру.
- **Рекомендация:** уведомление при первом запуске и при отправке («текст/изображение уходит в <provider> (<api_base>)»), предупреждение о полноэкранном захвате, локальный провайдер по умолчанию, возможность отключить автоперевод из clipboard, показ того, что именно отправляется (превью кропа уже есть).

---

## 4. Новые находки (BAR-19..BAR-28)

### BAR-19. `model_cache_path` — произвольный sink записи: замена/уничтожение чужого файла

- **OWASP:** `Secure_Code_Review_Cheat_Sheet.md` → «Injection Vulnerabilities» (unsafe file path construction), «Data Flow Analysis» (sink: file write); `Input_Validation_Cheat_Sheet.md` → «Parse Safely, Then Validate»; `Attack_Surface_Analysis_Cheat_Sheet.md`. Top-10: A04, A08 (CWE-73, CWE-15).
- **Severity:** Medium\*\* (см. сноску в §2). Статус: **fixed** (2026-11-13); на момент находки — open.
- **Место:** `main_window.py:45-56` — путь из `QSettings` передаётся в `ModelCacheStore(path=...)`; `model_cache.py:51-100` (`cache_path_from_config`) — принимается любой абсолютный путь (`~`/`~user` раскрываются; относительные/нестроковые отвергаются); `atomic_file.py:283-312` (`_atomic_write`) — `parent.mkdir(...)`, `mkstemp`, `os.replace(temp, path)` без проверки, что `path` — файл кэша; `atomic_file.py:247-259` (`_tighten_directory`) — `os.chmod(directory, 0o700)` следует по симлинку.
- **Evidence (эксперименты):**
  1. Замена существующего файла: файл `0o644` с содержимым `IMPORTANT USER DATA` после `save()` стал `0o600` и содержит `{"version":1,"models":{…}}`; исходные данные потеряны. `cache_path_from_config('~/.bashrc')` → `~/.bashrc`, `cache_path_from_config('/etc/passwd')` → `/etc/passwd`.
  2. Симлинк-цель на записи: `os.replace` заменяет саму ссылку, а не цель. Симлинк-**родитель** + `tighten_directory=True`: запись уходит по ссылке в чужой каталог, а `chmod 0700` меняет режим чужого каталога (0755 → 0700).
  3. FIFO как цель: `save() == True`, специальный файл уничтожен; `/dev/full` → `False`; каталог-цель → `False`; read-only каталог/ENOSPC/сбой `os.replace`/сбой сериализации → `False`, старый файл цел, temp удалён.
  4. Матрица `cache_path_from_config`: абсолютный/`~`/`~user` → `Path`; относительный/пустой/`file://`/не-строка/неизвестный `~user` → `None` (fail-safe); NUL-путь/перевод строки принимаются на этапе валидации и безопасно падают позже.
- **Сценарий:** конфиг Barbaros попадает на машину из dotfiles/бэкапа/другой установки либо правится скомпрометированным same-uid приложением; в нём `model_cache_path=<путь к чужому файлу>`. При первом же `set_models`/`remove` приложение атомарно заменяет указанный файл (или FIFO) содержимым кэша. «Случайная» версия: пользователь по ошибке указал существующий файл.
- **Влияние:** безвозвратная потеря данных в произвольном user-writable файле, порча конфигов других приложений, уничтожение специальных файлов. RCE/утечки секретов нет: содержимое ограничено схемой кэша, файл `0600` (не executable), ключи/`api_base` не пишутся.
- **Рекомендация (KISS):**
  1. Перед первой записью: если `path` существует и (`path.is_symlink()` или не regular file или не парсится `ModelCacheDocument.from_bytes`) — отказаться (`WARNING`, `return False`), не удаляя файл.
  2. `_tighten_directory`: не ходить по симлинкам (`os.chmod(..., follow_symlinks=False)` или не chmod-ить, если `directory.is_symlink()`); убрать `tighten_directory` из публичного API.
  3. В README/докстринге не обещать «указывайте файл кэша» — подкрепить guard'ом из п.1.
  4. В UI давать предупреждение при нестандартном пути (или не выносить это в конфиг вовсе — YAGNI).
- **Тест:** `test_save_refuses_to_overwrite_non_cache_file` (существующий `.bashrc`/FIFO/симлинк → `save() is False`, файл байт-в-байт тот же, temp нет); `test_tighten_directory_does_not_follow_symlink`.
- **Исправление (2026-11-13):**
  1. Write-guard в `ModelCacheStore._may_replace()` перед `os.replace`: `os.lstat` → отсутствует = можно писать; иначе target обязан быть regular file, читается через `read_regular_file_limited` (≤ 4 МиБ) и проверяется `ModelCacheDocument.is_cache_document()` — конверт кэша **любой** версии (`version: int`, `models: dict`). Симлинк/FIFO/устройство/каталог/нечитаемый/oversized/битый/чужой JSON → `WARNING` и `False`, файл не изменяется. После успешной записи identity файла запоминается (device/inode/size/mtime_ns/ctime_ns) и повторный `save` не перечитывает до 4 МиБ, пока файл не изменён; повторные отказы по той же причине логируются один раз (иначе 100-провайдерный reload давал бы секунды чтения поверх BAR-20 и 100 WARNING). Проверка не атомарна с `replace`; same-uid процесс вне модели угроз (BAR-10), guard закрывает случайные/синхронизированные/чужие файлы.
  2. `_tighten_directory()` пропускает каталог, если симлинком является **любой компонент** пути (`_has_symlink_component`, а не только непосредственный родитель), поэтому `chmod` не меняет режим чужого каталога; публичный флаг `tighten_directory` убран из `ModelCacheStore` — ужесточение включается только для дефолтного app-resolved пути; у самого механизма умолчание `tighten_directory=False` (opt-in).
  3. README/RU переписаны: файл заменяется только если отсутствует или уже является кэшем (любой версии), иначе предупреждение; битый кэш теперь нужно убрать/переименовать вручную (осознанная цена: нет самовосстановления).
  4. Отклонён п.4 рекомендации (UI-предупреждение): вне scope этого фикса, штатного UI для пути нет; предупреждение остаётся в логе.
- **Evidence после исправления:** `tests/unit/test_model_cache.py` — матрица «чужой файл (10 форм) → `False`, байты/права не изменены, temp нет», «кэш версий 0/1/2/999, с невалидными записями и ровно на границе 4 МиБ → `save` разрешён», FIFO/каталог/oversized/unreadable/symlink/dangling symlink → `False`, hardlink: другой линк сохраняет старые байты, повторный `save` своего файла не парсит его, внешнее изменение перепроверяется, повторный отказ — один WARNING; `tests/system/test_model_cache_security.py` — реальный `MainWindow` с `model_cache_path` на чужом файле и с чужим файлом в default-пути не меняет их; `tests/unit/test_atomic_file.py` — режим каталога-цели 0755 сохранён и для непосредственного симлинк-родителя, и для промежуточного симлинк-компонента. Полный набор: `481 passed, 3 deselected`; `ruff check` чист.
- **Остаточный риск:** identity-эвристика по конверту: чужой JSON с `{"version": <int>, "models": {...}}` будет принят за кэш. Это осознанный компромисс (issue #6: «неважно какой версии»); вероятность случайного совпадения у конфигов других приложений низкая, а цена обратной ошибки (отказ перезаписывать реальный кэш другой версии) — сломанный кэш. «Любая версия» ограничена конвертом и лимитом чтения: файл > 4 МиБ не проверяется и отвергается. TOCTOU-гонка с same-uid процессом не закрывается и вне модели угроз.

### BAR-20. DoS/подвисание: полный разбор кэша на каждого провайдера на старте

- **OWASP:** `Denial_of_Service_Cheat_Sheet.md` → «Input validation»; `Input_Validation_Cheat_Sheet.md` → «Parse Safely, Then Validate». Top-10: A04 (CWE-400, CWE-770).
- **Severity:** Low. Статус: open.
- **Место:** `main_window.py:61-66` — цикл `for provider in past_providers: add(p, cache_policy=RESTORE)`; число провайдеров из конфига ничем не ограничено. `model_manager.py:162-181` — `add(RESTORE)` вызывает `self._cache.load()` **на каждый вызов**; `model_manager.py:483-496` — `_persist` (сериализация + `os.replace` + `fsync`) под `RLock` из GUI-потока.
- **Evidence (замеры):** один разбор 4 МиБ (1000 провайдеров, 77 000 записей) — 69 мс без tracemalloc (366 мс с ним), пик Python-памяти 32.6 МиБ (амплификация файла ~8–10×); 100 × `load()` 4 МиБ = **7.48 с**. Реальный `MainWindow.__init__` (offscreen, fake keyring), кэш 2.7 МиБ: 1 провайдер — 17.9 мс, 3 — 145 мс, 20 — 1353 мс, 100 — **7221 мс**. `save` 4 МиБ ≈ 77–83 мс на tmpfs.
- **Дополнительно:** `docs/model-cache-storage.md` в абзацах о записи «в потоке воркера» противоречит коду после `e47ba99`: и чтение, и запись идут в GUI-потоке.
- **Рекомендация (KISS):** грузить кэш **один раз** (`cached = store.load()` в `MainWindow` или `ModelManager.add_all(providers, cache_policy=RESTORE)`); ограничить число провайдеров из конфига (например, ≤50) и логировать отказ; исправить устаревшие абзацы документа; NFR-тест «100 провайдеров + 2 МиБ кэш → бюджет старта».

### BAR-21. Кэш в общем каталоге читается без проверки владельца/прав (defense-in-depth)

- **OWASP:** `Input_Validation_Cheat_Sheet.md` → «Parse Safely, Then Validate»; `Attack_Surface_Analysis_Cheat_Sheet.md`. Top-10: A08, A02:2025 (CWE-345, CWE-732).
- **Severity:** Low (вне формальной модели «другой uid»; defense-in-depth). Статус: open.
- **Место:** `atomic_file.py:118-155` — у файла проверяются только `S_ISREG` и размер; `st_uid`/`st_gid`/биты записи (`0o022`) не проверяются. При этом `model_cache.py:299-321` и `docs/model-cache-storage.md` допускают путь «в существующем shared-каталоге»; `main_window.py:47-53` отключает только chmod каталога.
- **Evidence:** в shared-каталоге `0777` запись создаётся `0600` (чужие учётки файл не прочитают/не изменят **после** первого сохранения). Но **до** первого сохранения файл может создать/подменить другой пользователь; приложение прочитает его без проверки владельца. Подмена кэша → подмена списка моделей в селекторе (строки `id`), далее BAR-13.
- **Рекомендация (KISS):** в `_read_capped` после `fstat`: если `info.st_uid != os.geteuid()` или `info.st_mode & 0o022` — `WARNING` и `return None`. Тест: «файл кэша с чужим uid/режимом 0666 игнорируется».

### BAR-22. Исключение в GUI-слоте после установки «загрузочного» состояния заклинивает вкладку

- **OWASP:** `Error_Handling_Cheat_Sheet.md` §Objective; `Denial_of_Service_Cheat_Sheet.md` §Application attacks → «Handle exceptions», «Threading»; `AI_Agent_Security_Cheat_Sheet.md` §8. Top-10: A10:2025, в 2021 — A04 Insecure Design.
- **Severity:** Medium. Статус: open (изменения `workers.py` касаются только списка моделей и этот путь не закрывают).
- **Место:** `features/text.py:61-76` — `translate()` сначала скрывает/disable Translate, показывает прогресс и Stop и только затем вызывает `_threaded_translate`; `:86-90` — `selected_item = self.parent.model.selected_item` / `model_manager[selected_item.provider]` (`AttributeError` при `None`, `KeyError` при удалённом провайдере); `workers.py:73,98,145` — создание клиента в GUI-потоке; `model_manager.py:66` — `AnyLLM.create` → `MissingApiKeyError` для openai/anthropic без ключа; `features/ocr.py:155-160,180-181` — та же схема.
- **Evidence (воспроизведено, offscreen, fake keyring):** нет выбранной модели → `AttributeError: 'NoneType' object has no attribute 'provider'`; после исключения: Translate `hidden=True, enabled=False`, прогресс виден, Stop виден; клик Stop → `AttributeError: 'TextFeature' object has no attribute 'worker'`; `handle_clear_button()` состояние не сбрасывает. Провайдер openai без ключа → `MissingApiKeyError`, состояние идентичное.
- **Сценарий:** свежая установка (дефолтный ollama, список моделей ещё не загружен): пользователь вставляет текст и жмёт «Translate» → вкладка навсегда в состоянии «переводит», Stop не работает; восстановление только перезапуском. Тот же путь — в OCR-вкладке и при «Reload models» без ключа.
- **Рекомендация (KISS):** (1) валидировать предпосылки (`selected_item`, наличие провайдера, `provider.client()`) **до** смены UI — в `try` с показом ошибки и возвратом без disable/hide; (2) обернуть операцию в `try/finally`, где `finally` восстанавливает кнопки/прогресс, либо перенести создание клиента в рабочий поток; (3) в `handle_stop_button` — `getattr(self, "worker", None)`; (4) `MissingApiKeyError`/`KeyringError` показывать как «задайте ключ провайдера», а не traceback.
- **Тест:** «translate без выбранной модели → кнопка снова доступна, прогресс скрыт, Stop не падает»; «openai без ключа → видимое сообщение, вкладка работоспособна»; «reload models без ключа → сообщение, нет traceback».

### BAR-23. `terminate()` + `wait()` без таймаута и отсутствие app-level таймаута запроса

- **OWASP:** `Denial_of_Service_Cheat_Sheet.md` §Application attacks → «Handle exceptions», «Threading»; `Error_Handling_Cheat_Sheet.md` §Objective (fail closed / degrade gracefully); `Logging_Cheat_Sheet.md` («Which events to log», «Data to exclude», «Log injection»); `Secure_AI_Model_Ops_Cheat_Sheet.md` §4 Inference API Security (по аналогии — приложение является клиентом inference-API, а не сервером); `Secure_Code_Review_Cheat_Sheet.md` (гонки и время жизни потоков). Top-10: A10:2025 (2021: A04).
- **Severity:** Low. Статус: **fixed (2026-11-13)**.
- **Суть:** `stop_fetching_models` завершал `QThread` через `terminate()` и ждал `wait()` **без таймаута**, а сам запрос `list_models` не имел app-level ограничения времени (`any_llm` оставляет httpx-дефолты: connect 5 с, read 600 с). Остановка загрузки (Reload, удаление провайдера, выход) выполнялась в GUI-потоке, поэтому зависший поток/endpoint вешал интерфейс и не давал закрыть приложение.
- **Место (после исправления):** `model_manager.py:214-232` (`shutdown`), `:233-239` (`_stop_workers` — общий дедлайн), `:240-279` (`stop_fetching_models`), `:280-288` (`_retire_fetch_worker`), `:335-350` (`_remove_worker` — идентичность потока), `:357-400` (`_apply_worker_result`/`_apply_worker_error` — защита от результата и ошибки устаревшего воркера); `workers.py:25` (`LIST_MODELS_TIMEOUT_S = 20`), `:129-250` (`ListModelWorker`: asyncio-задача, `cancel()`, сигнал `stopped`).
- **Evidence (до исправления, воспроизведено):** поток в Python-цикле: `terminate()` возвращается мгновенно, затем `wait(2000)` не вернулся за >20 с; Qt-документация предупреждает, что `QThread::terminate()` может не завершить поток. Контроль: поток в C-`sleep(60)` завершается terminate за 0.001 с. Сеть: у `AnyLLM` дефолт `Timeout(connect=5, read=600, write=600, pool=600)` — endpoint может держать чтение до 10 минут.
- **Исправление:**
  1. **Кооперативная отмена вместо `terminate()`.** `ListModelWorker.run()` создаёт собственный asyncio-loop в своём QThread и запускает запрос как задачу. `cancel()` потокобезопасен и идемпотентен (флаг под локом + `loop.call_soon_threadsafe(task.cancel)`), работает до старта `run()` (запрос вообще не выполняется), во время запроса и после завершения (no-op). Отмена закрывает in-flight HTTP-запрос; для провайдеров, которые мостят синхронный SDK через `asyncio.to_thread` (например bedrock), отменяется ожидающая корутина, поток воркера завершается, но сам SDK-вызов может дорабатывать в фоне.
  2. **Общий таймаут запроса.** `LIST_MODELS_TIMEOUT_S = 20.0` ограничивает весь запрос `await client.alist_models()` через `asyncio.wait_for` (провайдеро-независимо: per-request `timeout` поддерживают не все провайдеры any_llm). По таймауту эмитится ровно один `error` с текстом `list_models timeout after 20s`, `finished` не эмитится.
  3. **Ограниченная остановка и защита от устаревшего результата.** `stop_fetching_models` вызывает `worker.cancel()`, затем `thread.wait(wait_ms)` (`STOP_WAIT_MS = 1000`), `terminate()` не вызывается; не уложившийся в бюджет поток логируется `WARNING` и не блокирует GUI. Ни результат, ни ошибка остановленной загрузки не применяются: диспетчер создаётся на каждую загрузку, держит ссылку на свой воркер и `_apply_worker_result`/`_apply_worker_error` сверяют его идентичность с текущей записью `_fetching_models_workers` (нет записи или другой воркер → DEBUG и drop). Это закрывает гонку Reload/remove: `finished`, поставленный в очередь до `cancel()`, иначе применил бы stale-модели; сверка по `sender()`/disconnect ненадёжна, потому что к моменту доставки Qt может уже удалить C++-объект воркера. Поток, не уложившийся в бюджет, остаётся в `_retiring_workers` до уничтожения: уничтожение работающего `QThread` аварийно завершает процесс.
  4. **Ограниченный `shutdown()`.** Отменяет все воркеры под **одним** общим дедлайном `SHUTDOWN_BUDGET_MS = 1500` (ниже NFR «< 2 с»), идемпотентен; batch-reload всех провайдеров использует тот же общий дедлайн вместо N×`STOP_WAIT_MS`. Воркеры, уже оставленные за прошлым бюджетом (`_retiring_workers`), повторно не ожидаются, но попадают в `WARNING` при `shutdown()` — застрявший провайдер виден в логе при выходе.
  5. **Корректное завершение потока.** `connect_terminate` подключает `thread.quit` с `DirectConnection`: пока GUI-поток заблокирован в `wait()`, его очередь событий не обрабатывается, и queued-подключение не остановило бы поток. Терминальный сигнал `stopped()` эмитится из `finally` на всех путях (успех/ошибка/таймаут/отмена; в том числе если закрытие приватного loop бросит исключение), поэтому поток завершается всегда, а отмена не выглядит как ошибка (не показывает модальный диалог при Reload/выходе).
  6. **Логирование.** Затронутые сообщения переведены с `print()` на `logging`; имена провайдеров — через `_short_repr` (BAR-17, без CR/LF), тела исключений и ключи в новые логи не попадают. Отмена — `DEBUG`, не уложившийся в бюджет поток — `WARNING`.
- **Тесты:** `tests/unit/test_list_model_worker.py` — контракт воркера (успех → один `finished` + один `stopped`, без `error`; ошибка клиента → один `error` + `stopped`, без `finished`; зависший запрос → один `error` со словом timeout и значением бюджета в пределах таймаута; отмена в полёте через реальный `QThread` → поток завершился < 1 с, ноль `finished`/`error`, один `stopped`, отмена дошла до клиента; отмена до `run()` не выполняет запрос; повторная отмена после завершения — no-op; `stopped()` эмитится, даже если `loop.close()` бросает исключение). `tests/components/test_model_manager_fetch_lifecycle.py` — `stop_fetching_models` вызывает `cancel` и `wait(>0)`, никогда `terminate`; возврат в пределах бюджета и WARNING, когда поток игнорирует отмену (`FakeThread.wait() == False`); `shutdown` идемпотентен и очищает все воркеры; `remove()`/reload с активной загрузкой завершаются в бюджете; результат **и ошибка** остановленной загрузки не применяются, а ошибка текущей загрузки по-прежнему доставляется; батч-остановка N воркеров ограничена одним общим дедлайном. `tests/system/test_model_fetch_lifecycle.py` — реальный локальный HTTP-сервер, который принимает запрос и не отвечает, и реальный `any_llm`-клиент: stop hung-загрузки < 2 с и поток `isFinished`; `shutdown()` трёх hung-провайдеров < 2 с, без `error`-сигналов, GUI продолжает обрабатывать события, повторный `shutdown()` — no-op; зависший endpoint без остановки ограничен таймаутом и даёт ровно один `error`; отвечающий endpoint по-прежнему доставляет модели до менеджера.
- **Остаточный риск:**
  - Провайдеры с синхронным SDK в отдельном потоке (bedrock и подобные) отменяются со стороны воркера, но сам SDK-вызов может продолжать работать в фоновом non-daemon потоке пула; на выходе из интерпретатора Python может дождаться этого потока, т.е. процесс способен задержаться с завершением уже после закрытия окна. На уровне приложения не исправляется (поведение any_llm/провайдера); GUI и выход из приложения при этом не блокируются.
  - Явные connect/read-таймауты клиента не выставляются (это провайдеро-специфично); ограничен **общий** бюджет запроса 20 с. Огромный, но успевший прийти ответ по-прежнему разбирается в GUI-потоке — это BAR-24; лимит размера ответа в BAR-23 сознательно не входит.
  - Провайдер, который ловит `CancelledError` и продолжает работу (или блокирует loop синхронным вызовом), не прервётся: GUI вернётся из `stop_fetching_models` за бюджет, поток останется в фоне (удерживается в `_retiring_workers`) и будет залогирован WARNING. Если такой поток всё ещё жив к завершению интерпретатора, Qt аварийно завершает процесс (`QThread: Destroyed while thread is still running`, exit 134) — при кооперативной отмене это патологический случай; `os._exit` как последнее средство сознательно не используется.
  - Выход: `aboutToQuit.connect(cleanup)` по-прежнему подключён только внутри `App.save_language` (**BAR-26**, отдельный issue #12), поэтому при обычном выходе `shutdown()` может не вызваться; когда он вызывается, он ограничен бюджетом. BAR-26 этим PR не исправляется.

### BAR-24. Неограниченный ответ `list_models` в GUI-потоке

- **OWASP:** `LLM_Prompt_Injection_Prevention_Cheat_Sheet.md` §Output Monitoring and Validation, §Input Validation and Sanitization; `AI_Agent_Security_Cheat_Sheet.md` §5; `Denial_of_Service_Cheat_Sheet.md` §Input validation. Top-10: A06:2025 (2021: A04).
- **Severity:** Low. Статус: open, **частично улучшено.** В `provider_models.model_entries()` ответ нормализуется к allowlist (`id/created/object/owned_by`), непригодные записи отбрасываются; `_parse_fetched_models` валидирует strict и не роняет слот. Лимитов на количество/размер по-прежнему нет.
- **Место:** `workers.py:201-217` — `alist_models()` + `json.dumps` всего списка без лимита; `model_manager.py:401-420` — `json.loads` + валидация **всех** моделей в GUI-потоке; `model_manager.py:483-496` — `_persist` тоже в GUI-потоке; `widgets/filterable_combobox.py:263-273` — `QTreeWidgetItem` на каждую модель; лимит есть только у диска-кэша (`model_cache.py:307` `MAX_FILE_BYTES = 4 MiB`, `:157` `MAX_MODELS_PER_PROVIDER = 10_000`).
- **Evidence (замеры):** 20 000 моделей = 1.5 МБ, `json.loads`+`Model.model_validate` 0.066 с + `QTreeWidgetItem` 0.096 с; 100 000 моделей = 7.7 МБ, 0.330 + 0.309 = **0.64 с** только GUI-часть (1 млн ≈ 6.4 с и сотни МБ объектов). Размер ответа ограничен только памятью.
- **Рекомендация:** лимит на количество/длину элементов сразу после `list_models()` (те же константы, что в кэше: ≤10 000 моделей, `id` ≤1024), отбрасывать/усекать лишнее с сообщением; парсинг/валидацию и построение дерева — батчами или с проверкой размера до `json.loads`.

### BAR-25. OCR `fail-open`: изображение уходит провайдеру после ошибки «не поддерживает изображения»

- **OWASP:** `LLM_Prompt_Injection_Prevention_Cheat_Sheet.md` §Multimodal Injection, §Data Exfiltration; `AI_Agent_Security_Cheat_Sheet.md` §8; `Error_Handling_Cheat_Sheet.md` §Objective (fail-closed). Top-10: A10:2025 (2021: A04).
- **Severity:** Low. Статус: **fixed (2026-11-13)**.
- **Место (после исправления):** `workers.py:100-126` (`OCRWorker.run_task`); до исправления — проверка `SUPPORTS_COMPLETION_IMAGE` стояла вне `try` и без `return`; после `error.emit(...)` изображение всё равно кодировалось и уходило в `acompletion`. Отсутствие атрибута давало `AttributeError`, вылетающий из `run_task`/`run()`: `error` не эмитился, причина видна только в traceback; `finished` из `finally` в `AbstractAsyncWorker.run()` всё равно приходил, поэтому вкладка сбрасывалась **молча** (это не зависание, но и не диагностируемая ошибка).
- **Evidence (воспроизведено на `main` до фикса, stub-клиент с `SUPPORTS_COMPLETION_IMAGE=False`):** один `error` и один `done`, `acompletion` вызван один раз с image data URL; stub без атрибута → `AttributeError` из `run()`, ни одного `error`/`done` (при этом `finished` приходит из `finally`); stub без `PROVIDER_NAME` → `AttributeError` на формировании сообщения об ошибке.
- **Исправление:** в `workers.py` проверка перенесена в `try` и стала guard clause: `getattr(client, "SUPPORTS_COMPLETION_IMAGE", False)`; при `False`/отсутствии атрибута эмитится ровно один `error` (имя провайдера из `client.PROVIDER_NAME`, при отсутствии — `unknown`) и выполняется `return` **до** `base64.b64encode`/`acompletion`; `done` не эмитится. Если `acompletion` всё же бросит, прежний `except` эмитит один `error`.
- **Тесты:** `tests/unit/test_workers.py` — все пять сценариев (неподдерживаемый клиент, отсутствующий флаг, отсутствующий `PROVIDER_NAME`, поддерживаемый клиент — изображение уходит один раз, ошибка `acompletion`); `tests/system/test_ocr_worker_flow.py` — неподдерживаемый клиент, клиент без флага, успешный путь и ошибка `acompletion` через реальный `QThread`: изображение не уходит, ровно один `error`, `done` нет, `finished` приходит (вкладка сбрасывается, не зависает). Полный набор: `490 passed, 3 deselected`.
- **Остаточный риск:** проверка отражает объявленную клиентом поддержку; провайдер с `SUPPORTS_COMPLETION_IMAGE=True`, который фактически не принимает изображения, по-прежнему получит запрос — это поведение провайдера, а не fail-open приложения. Отправка изображения/буфера провайдеру без in-app уведомления — отдельная находка BAR-18; отсутствие лимита на размер изображения — BAR-14.

### BAR-26. `aboutToQuit.connect(cleanup)` внутри `save_language` — shutdown обычно не выполняется (Info)

- **Статус:** open, Info (без изменений).
- **OWASP:** `Error_Handling_Cheat_Sheet.md` §Objective. Top-10: A10:2025, A09:2025.
- **Место:** `main.py:68-73` (`save_language`) — единственная точка подключения `aboutToQuit`; `main.py:97-101` (`cleanup` → `ModelManager.shutdown`); `main.py:177-188` (`main()`).
- **Evidence (статика):** если пользователь не менял язык, `save_language()` не вызывается → `cleanup` не подключён; при выходе `ModelManager.shutdown()` не вызывается, QThread-воркеры/сеть остаются живыми до завершения интерпретатора (`QThread: Destroyed while thread is still running`); при каждом изменении языка подключение дублируется.
- **Рекомендация:** подключать `aboutToQuit` один раз в `App.__init__`; идемпотентный `cleanup`; тест «выход без смены языка → shutdown вызван».

### BAR-27. Гигиена документации и расхождение README с поведением (Info)

- **Статус:** open, Info (без изменений; в этой версии отчёта абсолютные пути уже убраны).
- **OWASP:** `User_Privacy_Protection_Cheat_Sheet.md` §Honesty & Transparency. Top-10: A09:2025 (информационная гигиена).
- **Место:** `README.md:33` («Privacy-First»), `README.md:273` («Secure API calls»), при `common.py:108-127` разрешён `http://` (BAR-03) и уведомления о передаче нет (BAR-18).
- **Evidence:** заголовок предыдущей версии отчёта содержал абсолютные пути и имя пользователя; в этой версии они убраны. README утверждает «secure API calls», хотя выбранный пользователем `api_base` может быть `http://`. `docs/settings-migration.md` больше не содержит абсолютных путей.
- **Рекомендация:** не публиковать абсолютные пути и имена пользователя в docs; в README заменить «Secure API calls» на «HTTPS по умолчанию; HTTP допустим только по явной настройке» и добавить строку, что изображение/буфер отправляются выбранному провайдеру.

### BAR-28. Flatpak на PySide6 6.11.3: pickle-RCE через обход санации (исправлено)

- **OWASP:** `Deserialization_Cheat_Sheet.md` → «Python / Clear-box Review»; `Software_Supply_Chain_Security_Cheat_Sheet.md` → «Monitor Deployed Software for Vulnerabilities», «Lockfile/Version Pinning»; `Vulnerable_Dependency_Management_Cheat_Sheet.md`. Top-10: A08:2021/A08:2025 (CWE-502), A06:2021, A03:2025.
- **Severity:** **High** (для релизного Flatpak-артефакта). Статус: **fixed**; issue [#15](https://github.com/FRiMN/barbaros/issues/15). Native/pip-установка с PySide6 6.12 не затронута.
- **Место:** `flatpak/barbaros.yaml:3` (`runtime-version: "6.11"`), `:6` (`base-version: 6.11`), `:57-60` (PySide6 не устанавливается из pip — «it is provided by BaseApp»); `pyproject.toml:27` (`pyside6-essentials~=6.12.0`) на Flatpak не влияет; `settings_sanitize.py:48` (`MAX_SETTINGS_BYTES = 1024*1024`), `:82-137` (fail-open санация); `main.py:33-46`.
- **Evidence (2026-11-13, реальный runtime):**
  - Установленный `io.qt.PySide.BaseApp` 6.11.3 содержит `pyside6-6.11.3.dist-info` и `PySide6.__version__ == "6.11.3"` (Python 3.13). В PySide6 6.12.0 отказ от pickle появился, в 6.11.x его нет.
  - Двухпроцессный тест под BaseApp 6.11.3: writer пишет `Evil.__reduce__` через `QSettings.setValue`, reader в новом процессе делает `QSettings.value("main_window/model")` → payload выполнился (создан файл-маркер). В `.venv` (PySide6 6.12.0) на том же конфиге — `RuntimeError: Failed to deserialize Python object from QDataStream…`, маркер не создан.
  - Обход санации: файл конфига увеличен до **1 048 817 байт** (pickle-значение сохранено). `sanitize_pickled_settings()` вернул `None` с WARNING «file too large» (лимит 1 МиБ) и не тронул файл; чтение под BaseApp 6.11.3 выполнило payload. Симлинк на конфиг и read-only каталог тоже дают `None`, но механизм разный: при симлинке `read_regular_file_limited` отказывается от чтения (O_NOFOLLOW), а при read-only каталоге файл читается, но `_write_backup`/атомарная запись не могут его заменить (`docs/settings-migration.md` §3 и §4). В обоих случаях под 6.11.3 `read_setting` не спасает — unpickle происходит до проверки.
  - При конфиге ≤ 1 МиБ, без симлинка и при записываемом каталоге санация удаляет pickled-строки, и Flatpak-путь защищён — уязвим именно обходной сценарий.
- **Сценарий:** атакующий с записью в `$HOME` (dotfiles-синхронизация, бэкап, скомпрометированное same-uid приложение — всё в модели угроз) кладёт в `~/.var/app/io.github.frimn.barbaros/config/io.github.frimn/barbaros.conf` (или в конфиг native-установки) pickle-payload и добивает файл до > 1 МиБ (либо делает конфиг симлинком). При следующем запуске Flatpak-сборки выполняется произвольный код с правами пользователя. Payload персистентен.
- **Влияние:** RCE в релизном Flatpak-артефакте; обходит именно тот фикс, который закрыл BAR-01 в native-сборке. Это тот же класс/CWE, что BAR-01, но отдельный путь эксплуатации, поэтому отдельный ID и статус.
- **Рекомендация (P0):**
  1. Обновить Flatpak на PySide6 ≥ 6.12 (`base-version: 6.12`, когда BaseApp 6.12 доступен) или ставить `pyside6-essentials` из pip с пином в Flatpak-модуле; проверить `PySide6.__version__` внутри собранного bundle.
  2. Сделать санацию **fail-closed** для случая PySide6 < 6.12: если файл не удалось очистить (размер, симлинк, права, ошибка записи), не подпускать `QSettings` к этому файлу — переместить/переименовать его и стартовать с чистыми настройками (потеря настроек лучше RCE), либо полностью заменить `QSettings` JSON-стором.
  3. Убрать обход по размеру: потоковый скан INI без чтения всего файла в память (или санация+отказ при превышении лимита, а не «оставить как есть»); обрабатывать симлинк через санацию цели.
  4. Добавить регрессионный тест на **реальном Flatpak runtime**: конфиг > 1 МиБ/симлинк с pickle → payload не выполняется.
- **Тест:** «BaseApp 6.11 + oversize/symlink config → sanitize returns None, QSettings не читает файл (fail-closed); marker отсутствует»; «собранный Flatpak-report содержит PySide6 ≥ 6.12».
- **Исправление (2026-11-13):**
  1. **Flatpak на PySide6 6.12.** `io.qt.PySide.BaseApp` 6.12 на Flathub отсутствует (ветки только до `branch/6.11`), поэтому манифест остаётся на BaseApp 6.11, но barbaros-модуль ставит `pyside6-essentials==6.12.0` + `shiboken6==6.12.0` из PyPI поверх base app. Отдельный build-guard `flatpak/bar28_guard.py` валит сборку, если импортируемый PySide6 < 6.12 **или** если `QSettings` не отказался от pickle; версия проверяется и в собранном bundle.
  2. **Fail-closed для PySide6 < 6.12: файл настроек не читается вообще.** Первая версия фикса (санация → карантин только неочищенного файла) была обойдена: Qt снимает `\xHH`-escapes и кавычки INI **до** того, как решает, что значение — `@Variant(...)`, поэтому `\x40Variant(...` или escape байта маркера не видны построчному сканеру, а на 6.11 выполняется unpickle (подтверждено на реальном BaseApp 6.11.3). Итоговое решение: `prepare_settings_file()` на PySide6 < 6.12 **никогда** не отдаёт `QSettings` файл из пути, доступного атакующему — существующий файл уносится как `*.unsafe-<UTC>-<random>` (0600; симлинк переименовывается сам, цель не трогается), а приложение использует `MemoryBackedSettings` (настройки сессии в памяти, ничего не читается и не пишется). Одноразовый *файл* сознательно не используется: same-uid процесс может подменить любой файл, доступный приложению на чтение, поэтому отсутствие файла — единственная граница без гонок. Скан сырых байт остаётся только миграцией на ≥ 6.12, где Qt сам отказывается десериализовать.
  3. **Обход по размеру/симлинку/escape больше не даёт RCE:** на старом runtime все они попадают в ветку «файл не читается», потоковый скан не понадобился.
  4. **Найдены дополнительные обходы сканера (для миграции на ≥ 6.12):** QSettings квотирует значение, если escaped-payload содержит запятую (`0x2c` — обычный байт pickle): `model="@Variant(...`. Старый скан искал `@Variant(` в начале значения и пропускал такую строку. `_is_pickled_variant()` теперь снимает необязательную ведущую кавычку. Но границей безопасности скан не является: escape-форма (см. п. 2) обходит и его — поэтому на < 6.12 решение принимается без скана.
  5. **Тесты:** `tests/system/test_flatpak_pyside.py` (opt-in, `-m slow`) на **реальном** BaseApp 6.11.3: два негативных контроля (обычная и escaped-форма действительно выполняют payload при прямом чтении), а путь приложения уносит small/big/escaped-конфиги и не выполняет код. `tests/unit/test_settings_sanitize.py` — fail-closed по версии, карантин любого существующего файла, `MemoryBackedSettings` (значения, группы, `QByteArray`, `sync`), escaped/квотированная форма (скан говорит «чисто», но решение не меняется); `tests/system/test_legacy_settings.py` — реальный `App` в subprocess с симуляцией PySide6 < 6.12 (включая escape-форму и настройки в памяти); `tests/unit/test_flatpak_manifest.py` — статическая проверка пина PySide6 ≥ 6.12 и вызова build-guard.
- **Остаточный риск:** на PySide6 < 6.12 `QSettings` не открывает ни одного файла (сессия in-memory), поэтому ни скан, ни гонка подмены файла не дают выполнения кода; цена — сброс настроек на таком runtime. Для релизной сборки и native-установки (≥ 6.12) этот путь не задействован. Полное закрытие класса — JSON-стор вместо `QSettings` (отдельная задача, `docs/settings-migration.md` §6).

---

## 5. Что уже сделано хорошо

1. **API-ключи — в OS keyring**, не в конфиге/исходниках/логах; сервис неймспейснут (`barbaros:providers_api_keys`), имя провайдера — username; hardcoded-секретов в репозитории нет (`git grep` чист).
2. **`ProviderMeta` не сериализует ключ:** `api_key_manager` создаётся в `__post_init__` и не является dataclass-полем; `schema().dump()` даёт только `name/provider_type/api_base`; `from_dict` игнорирует лишние поля.
3. **UI маскирует секреты:** `EchoMode.Password`, в таблице/карточках — только `truncate_key` (≤4 последних символа); копирование из password-поля блокируется Qt.
4. **Валидатор URL отклоняет не-http(s) схемы и userinfo** (`javascript:`, `file:`, `user:pass@host` — False).
5. **Вставка в `CustomTextEdit` — обычно plain text** (`insertPlainText`): HTML/MIME из буфера не парсится. При HTML-only буфере Qt-фолбэк `insertFromMimeData` вставляет rich text — это класс BAR-13 (JS не исполняется), а не отдельная уязвимость.
6. **Rich-text ссылки в `LinkLabel`/`QTextEdit` не кликабельны**; Qt rich text не исполняет JS и не загружает remote-картинки; `QImageReader.allocationLimit()=256MB` защищает от грубых decompression-bomb.
7. **IPC-поверхность минимальна:** только сессионный bus, один `void`-слот без аргументов/возврата; данные/ключи через D-Bus не ходят; `deleteLater` и прочие слоты `QObject` не экспортируются.
8. **Flatpak без `--filesystem=home`** и без `--device=all`; cleanup убирает тесты/`__pycache__`/webengine; `--talk-name=org.freedesktop.secrets` нужен для keyring.
9. **`uv.lock` с точными версиями и sha256; с этого аудита `pyproject.toml` пинит зависимости до minor-линии** — хорошая база для исправления BAR-08 и защита от «неожиданного» мажорного обновления (как PySide6 6.12).
10. **Нет телеметрии:** сеть только через `any_llm` к настроенному провайдеру; README раскрывает отправку облачным провайдерам.
11. **Новый кэш моделей — plain JSON, не pickle:** `json.loads` без `object_hook`, allowlist полей `id/created/object/owned_by`, лимит 4 МиБ до разбора; `ModelCacheDocument` не даёт лишним полям/секретам/`api_base` попасть в файл.
12. **Файловая механика кэша безопасна по механике:** `O_NOFOLLOW` + `S_ISREG` (симлинк/FIFO/device/каталог не читаются, FIFO не блокирует), лимит `limit+1`, `0600`/`0700` независимо от umask, атомарный `os.replace`, старый файл цел при любой обработанной ошибке, temp удаляется.
13. **Fail-safe границы:** `load`/`save` не бросают исключений (кроме `BaseException`), битый/огромный/невалидный кэш не ломает старт, кэш не удаляется.
14. **Логирование нового кода — `logging` с `%r` и усечением:** путь/имя провайдера не дают log injection, содержимое файла и ключи не логируются.
15. **Новый код не тянет новых зависимостей** (stdlib: `json`, `os`, `tempfile`, `threading`, `stat`, `logging`); `atomic_file` не импортирует Qt/keyring/any_llm.
16. **Тесты нового PR проверяют безопасность:** symlink/FIFO/oversized/allowlist/права/fail-safe/секреты/log-injection.
17. **BAR-01-фикс для native-установки корректно закрывает вектор:** санация до `QSettings`, JSON-формат выбора, `read_setting` как страховка, `pyproject.toml` держит PySide6 ≥ 6.12; подтверждено тестами и экспериментом (PySide6 6.12.0 не выполняет payload).
18. **Санация INI безопасна по механике:** читает regular file без симлинка, потолок 1 МиБ, бэкап `0600` с уникальным именем, атомарная запись, никогда не бросает (fail-safe для старта), идемпотентна (повторный запуск файл не трогает).
19. **Нормализация списков моделей** вынесена на границу провайдера (`provider_models.py`) и согласована с allowlist кэша; strict-валидация не даёт мусору из ответа провайдера перезаписывать кэш.
20. **`valueFromJson` терпим к повреждённому JSON** (включая `RecursionError`), старт не зависит от целостности всех настроек.

## 6. Проверено и не является уязвимостью

- **Path traversal через настройку `language`** (`i18n.load_translator`): обязательный префикс `barbaros_` делает первым компонентом пути литеральное имя (`barbaros_..`); `lang="../../../etc/passwd"` → `None`. Не эксплуатируется.
- **RCE/десериализация через D-Bus:** метод без аргументов и возврата; `deleteLater` не экспортируется; данных нет.
- **Подмена D-Bus-сервиса:** сквоттер получает только `void`-вызов; максимум — DoS/имитация успеха, не утечка.
- **SIGUSR1:** фиксированный номер сигнала, нет payload; RCE/повреждения памяти нет.
- **Командные/SQL/NoSQL/OS-инъекции:** в `src/barbaros` нет `subprocess`, `os.system`, `eval`/`exec`, unsafe YAML/pickle-импортов; `tasks.py`-команды — build-time, не runtime.
- **SSRF:** URL провайдера выбирает пользователь, серверной стороны нет; link-local адреса в валидаторе — слабость (BAR-03), но без подмены конфига самостоятельной эксплуатации нет.
- **Qt rich text XSS:** JavaScript/обработчики событий не исполняются; remote `http(s)`-картинки не загружаются; клики не открывают ссылки (проблема только у `QMessageBox`, BAR-06).
- **Секреты в конфиге/логах/репозитории:** не обнаружены (ключи — в keyring; `print`/`logging` без ключей; `git grep` секрет-паттернов чист).
- **Plaintext-fallback keyring:** отсутствует; без backend — fail-closed (`NoKeyringError`), а не запись в файл.
- **`--share=ipc`:** стандартное разрешение для X11/MIT-SHM, находкой не является.
- **Расхождение `--own-name` ↔ `SERVICE_NAME`:** не ломает IPC (app-id namespace разрешён по умолчанию), это лишнее/неверное разрешение (BAR-05).
- **`assert` в IPC:** не является границей безопасности; удаление под `-O` не даёт новых прав (гигиена — BAR-12).
- **`--popup`/`--opened`:** аргументы только сравниваются `in sys.argv`, в команды/пути не подставляются — инъекции нет.
- **Новый кэш:** не вызывает pickle, не читает symlink/FIFO/device/каталог, не выходит за `limit+1`/4 МиБ, не пишет секреты/`api_base`, не подменяет `api_base`/имя/тип провайдера, не удаляет битый файл и не перезаписывает существующий не-кэш-файл (BAR-19); безопасен при ENOSPC/read-only/сбое `replace`/сериализации; гонки load/save не дают частичного файла.
- **`cache_path_from_config`:** относительные/пустые/нестроковые/`file://`/`$HOME`-значения отвергаются, `~unknownuser`/NUL-путь не роняют приложение; запись в cwd не происходит.
- **Импортная гигиена:** `atomic_file` не импортирует Qt/keyring/any_llm/barbaros; новых рантайм-зависимостей нет.
- **Санация конфига, остаточные наблюдения (не отдельные находки):** бэкап содержит исходный pickle, но приложением не читается; эвристика вырезает любое значение с маркером (потенциально — пользовательскую строку с этим текстом), но писать в конфиг может только сам пользователь/тот же uid; конкурентный запуск второго экземпляра во время read→replace может потерять его параллельную запись настроек (описано в `docs/settings-migration.md` §6). Всё это — ограничения дизайна санации, а не самостоятельные уязвимости; RCE-остаток вынесен в BAR-28.
- **PySide6 6.12 и pickle:** проверено, что `QSettings.value()` на INI с `PySide::PyObjectWrapper` бросает `RuntimeError` и не выполняет payload; `read_setting` переживает это и восстанавливает соседние ключи.

## 7. Соответствие OWASP Top 10

### 7.1 OWASP Top 10:2021

| Категория | Применимость | Находки |
|---|---|---|
| A01 Broken Access Control | Да (локальный IPC) | BAR-04, BAR-12 |
| A02 Cryptographic Failures | Да (транспорт, секреты) | BAR-02, BAR-03 |
| A03 Injection | Да (HTML/rich text; prompt injection — без исполнения) | BAR-06, BAR-13 |
| A04 Insecure Design | Да | BAR-02, BAR-04, BAR-07, BAR-09, BAR-11, BAR-14, BAR-15, BAR-18, BAR-19, BAR-20, BAR-22, BAR-23, BAR-24, BAR-25 |
| A05 Security Misconfiguration | Да | BAR-05, BAR-09, BAR-10 |
| A06 Vulnerable and Outdated Components | Да | BAR-08, BAR-16, BAR-28 |
| A07 Identification and Authentication Failures | Нет (нет аккаунтов/сессий; аутентификация ОС/keyring) | — |
| A08 Software and Data Integrity Failures | Да | BAR-01, BAR-08, BAR-16, BAR-19, BAR-21, BAR-28 |
| A09 Security Logging and Monitoring Failures | Частично | BAR-12, BAR-15, BAR-17, BAR-26, BAR-27 |
| A10 Server-Side Request Forgery (SSRF) | Нет (клиентское приложение; URL задаёт пользователь) | — |

### 7.2 OWASP Top 10:2025 (актуальная редакция)

| Категория | Применимость | Находки |
|---|---|---|
| A01 Broken Access Control (вкл. SSRF) | Да (локальный IPC; SSRF — нет) | BAR-04, BAR-12 |
| A02 Security Misconfiguration | Да | BAR-05, BAR-09, BAR-10, BAR-21 |
| A03 Software Supply Chain Failures | Да | BAR-08, BAR-16, BAR-28 |
| A04 Cryptographic Failures | Да (транспорт, секреты) | BAR-02, BAR-03 |
| A05 Injection | Да (HTML/rich text) | BAR-06, BAR-13 |
| A06 Insecure Design | Да | BAR-02, BAR-04, BAR-07, BAR-14, BAR-15, BAR-18, BAR-19, BAR-20, BAR-22, BAR-23, BAR-24, BAR-25 |
| A07 Authentication Failures | Нет (нет аккаунтов/сессий) | — |
| A08 Software or Data Integrity Failures | Да | BAR-01, BAR-08, BAR-16, BAR-19, BAR-21, BAR-28 |
| A09 Security Logging & Alerting Failures | Частично | BAR-12, BAR-15, BAR-17, BAR-26, BAR-27 |
| A10 Mishandling of Exceptional Conditions | Да (fail-open, bare except, падение старта, маскировка ошибок) | BAR-09, BAR-11, BAR-12, BAR-15, BAR-22, BAR-23, BAR-25, BAR-26 |

## 8. Поправки к предыдущим версиям отчёта

1. **Версия отчёта из `77462de` потерялась при мерже BAR-01.** `58c92d0`/`ea8822c` разрешили конфликт в пользу ветки, базой которой был аудит `71197f8`, поэтому в `main` осталась старая версия (27 находок → 18). В этой версии `BAR-19..BAR-27` восстановлены и перепроверены; добавлена `BAR-28`.
2. **BAR-01: статус «исправлено» был неполным.** Исправление `3e30fa3` верно для native/pip-установки с PySide6 ≥ 6.12, но Flatpak собирается на BaseApp 6.11.3 (PySide6 6.11.3) и не ставит PySide6 из `pyproject.toml`. Санация обходится конфигом > 1 МиБ/симлинком/read-only. Остаток вынесен в BAR-28 (High); в §3 статус BAR-01 изменён на «fixed (native)».
3. **BAR-04, способ вызова.** Утверждение первого аудита «`QDBusInterface(SERVICE_NAME, "/", "", bus)` успешно вызывает метод» неверно для PySide6 6.11/6.12: такой интерфейс невалиден; Qt экспортирует интерфейс, производный от Python-класса (`local.barbaros.ipc.IPCService`). Отсутствие авторизации подтверждено.
4. **BAR-13, атрибуция некликабельности.** В `widgets/link_label.py` нет `mousePressEvent`; некликабельность обеспечивает присваивание `display_label.mousePressEvent` в `filterable_combobox.py:37,342`.
5. **BAR-09, `api_base=123`.** `ProviderMeta.from_dict` через `dataclasses_json` приводит значение к строке; краш воспроизводится только при прямом `ProviderMeta(..., api_base=123)`. Оценка не меняется: JSON неверного типа по-прежнему роняет старт.
6. **BAR-12, bare `except`.** Один из двух заменён на `contextlib.suppress(BaseException)` (`ipc.py:79`); bare `except:` остался в `_handle_signal_from_socket` (`ipc.py:89`).
7. **BAR-01, первый триггер.** При штатном старте первый unpickle давал чтение `target_language_list` (`main_window.py:190-193`), а не `model`.
8. **BAR-17/18, строки.** `README.md:70` → `README.md:33`; `main_window.py:95` → `:53,211,222`; `ipc.py:142,146,149` → `:137,141,144`; `model_manager.py:121,129,173` → `:187,196,204,251`. Точные строки сдвинулись после рефакторингов — в тексте даны текущие.
9. **Внутренняя документация.** `docs/model-cache-storage.md` цитирует устаревшие строки прошлого аудита; абзацы о записи «в потоке воркера» устарели (BAR-20). После миграции BAR-01 путь санации описан в `docs/settings-migration.md`; в этой версии его §6 дополнен описанием Flatpak-остатка (BAR-28).
10. **Неточность в разделе «Что уже сделано хорошо» #5.** Вставка обычного текста — plain text, но при HTML-only буфере Qt-фолбэк вставляет rich text; JS не исполняется, в LLM уходит `toPlainText()`.
11. **Абсолютные пути в публикуемом отчёте.** Прошлая версия содержала локальные абсолютные пути и имя пользователя (BAR-27); в этой версии они удалены, ссылки даны относительно корня проекта.
12. **Версии PySide6.** В прошлой версии смешаны 6.11.1 (эксперименты) и текущий пиннинг. Уточнение: `.venv` на HEAD — PySide6 **6.12.0**; Flatpak BaseApp 6.11.3 — PySide6 **6.11.3**; поведение `QSettings` проверено на обеих версиях.

## 9. План исправлений

**P0 — до следующего релиза:**
1. ~~**BAR-28:**~~ **выполнено (2026-11-13):** Flatpak ставит `pyside6-essentials==6.12.0`/`shiboken6==6.12.0` поверх BaseApp 6.11 с build-guard; на PySide6 < 6.12 файл настроек не читается вообще (карантин + настройки в памяти), поэтому размер/симлинк/escape не дают RCE; добавлены opt-in тест на реальном Flatpak runtime и статический тест манифеста. Остаток — потеря настроек на PySide6 < 6.12 (страховочная ветка, в релизе не задействована) и возможный переход на JSON-стор.
2. **BAR-02:** вызывать `api_key_manager.delete()` при удалении провайдера + явная очистка ключа в диалоге; обрабатывать `KeyringError`; тест с fake backend.
3. **BAR-06:** `QMessageBox` для ошибок — plain text; `url_to_html_links` переписать как `escape → linkify` или удалить.
4. **BAR-04/BAR-15:** IPC/`--popup` только фокусирует окно; перевод из clipboard — только по явному действию пользователя; D-Bus-метод возвращает явный статус; rate limit/проверка вызывающего; тест IPC.
5. **BAR-03:** HTTPS обязателен, кроме loopback; применить и при загрузке конфига.
6. ~~**BAR-19:**~~ **выполнено (2026-11-13):** write-guard «заменять только отсутствующий файл или кэш любой версии» перед записью (с identity-memo, чтобы не перечитывать свой файл на каждый `save`); `chmod` не идёт по симлинк-компонентам; публичный `tighten_directory` убран; README/RU ужесточены. Тесты: unit-матрица guard, system-тесты через реальный `MainWindow` (override и default-путь), unit на симлинк-компоненты (§4 BAR-19, §10).

**P1 — в ближайший цикл:**
7. **BAR-05:** убрать `--socket=session-bus` и неверный `--own-name`; проверить IPC в Flatpak.
8. **BAR-08:** hashed-requirements из `uv.lock` + `--require-hashes`; SBOM в релиз.
9. **BAR-07:** линейный парсер `<think>` + лимит ответа/`max_tokens`.
10. **BAR-09:** валидировать схему конфига (`llm_providers`, `api_base`, `language`, `target_language_list`), лимит числа провайдеров, fail-safe старт.
11. **BAR-12:** убрать сканирование процессов (lock-файл/сокет с `SO_PEERCRED`), явные исключения и логирование.
12. **BAR-20:** один `load()` кэша на старте; NFR-тест на 100 провайдеров; поправить `docs/model-cache-storage.md`.
13. **BAR-22:** валидировать предпосылки до смены UI + `try/finally` rollback кнопок; создание клиента — в рабочем потоке; `getattr` в Stop; понятные сообщения о ключе.
14. ~~**BAR-23:**~~ **выполнено (2026-11-13) для остановки и вызванного `shutdown()`:** `terminate()` убран, отмена кооперативная (asyncio-задача), `wait(ms)` с бюджетом, общий таймаут запроса 20 с, общий дедлайн `shutdown()` 1.5 с. Лимит размера ответа `list_models` осознанно оставлен в BAR-24 (на этом уровне он не уменьшает объём уже разобранного ответа); подключение `shutdown()` к обычному выходу остаётся за BAR-26. Тесты — §4 BAR-23, §10.
15. **BAR-24:** лимит количества/длины моделей сразу после `list_models()` (те же константы, что в кэше); парсинг/построение дерева — не в одном GUI-шаге.
16. ~~**BAR-25:**~~ **выполнено (2026-11-13):** проверка поддержки изображений перенесена в `try` и стала guard clause (fail-closed при отсутствующем флаге), после `error.emit(...)` — `return`; изображение не кодируется и не отправляется. Тесты: unit + system на реальном `QThread` (§4 BAR-25, §10).

**P2 — гигиена и defense-in-depth:**
17. **BAR-10:** `chmod 0600` на QSettings после каждой записи.
18. **BAR-11:** предупреждение при недоступном keyring, без plaintext-fallback.
19. **BAR-13/BAR-14:** plain-text для внешних имён и ответа LLM; лимиты текста/изображения/ответа; валидация `ChatCompletion`.
20. **BAR-16:** включить CI, пинить actions/build-tools, подписывать bundle, Dependabot/pip-audit, `SECURITY.md`.
21. **BAR-17/BAR-18:** `logging` без чувствительных данных; in-app уведомление о передаче данных провайдеру.
22. **BAR-21:** проверка `st_uid`/битов записи кэша (если shared-каталог остаётся поддерживаемым сценарием).
23. **BAR-26:** `aboutToQuit.connect(cleanup)` один раз в `App.__init__`; идемпотентный `cleanup`.
24. **BAR-27:** привести README к фактическому поведению (HTTPS по умолчанию, HTTP только по явной настройке, отправка изображения/буфера провайдеру).

**Организационно (AGENTS.md #27):** для PR ввести обязательный OWASP-проход по diff с меткой `security/owasp-passed` и комментарием-следом; метку ставить только на финальный diff и снимать при новых security-коммитах. Сейчас CI/автоматической проверки нет (BAR-16). Остаток BAR-28 был заведён отдельным issue [#15](https://github.com/FRiMN/barbaros/issues/15) с меткой `security/owasp-finding` и закрыт исправлением (fail-closed + PySide6 6.12 в Flatpak); issue остаётся ссылкой-следом.

## 10. Security-тесты, которые стоит добавить

1. `QSettings`-round-trip выбора модели не содержит pickle (`PyObjectWrapper`); санация/удаление легаси-конфига выполняется без вызова `QSettings.value/remove/setValue`; старт с подменённым INI не выполняет код. *(частично есть: `tests/unit/test_settings_sanitize.py`, `tests/unit/test_model_selection.py`, `tests/system/test_legacy_settings.py`)*
2. Удаление провайдера и очистка ключа удаляют секрет из keyring (fake/in-memory backend); `NoKeyringError` не роняет старт.
3. `is_valid_url`/`api_base_problem`: `http` вне loopback отклоняется, `http://localhost` разрешён, `https` разрешён; конфиг с `http://evil` не загружается.
4. Битый/подменённый конфиг: приложение стартует с дефолтами, валидные провайдеры загружены; число провайдеров ограничено; JSON неверного типа не роняет старт.
5. IPC: `popup_and_translate` не инициирует отправку без действия пользователя; метод возвращает статус; ошибка обработчика видна вызывающему.
6. Rich text: `model.id`/`provider.name` рендерятся как plain text; ошибка провайдера с HTML не создаёт ссылок/картинок.
7. `pop_think`: линейное время на большом ответе (нефункциональный тест), большой ответ усекается с сообщением.
8. `ChatCompletion(choices=[])` / `content=None`: пользователь видит ошибку, приложение не падает.
9. Лимиты на размер текста/изображения; `max_tokens` передаётся.
10. В логах/сериализованных провайдерах нет API-ключей.
11. **BAR-19:** `save()` отказывается заменять существующий не-кэш-файл (`.bashrc`, чужой JSON, FIFO, симлинк, каталог, пустой/битый/oversized/unreadable) и не меняет его; файл-кэш любой версии (0/1/2/999, граница 4 МиБ) заменяется; `chmod` не идёт по симлинк-компонентам. **Реализовано:** `tests/unit/test_model_cache.py` (матрица guard, `is_cache_document`, memo/повторное чтение, hardlink, dangling symlink), `tests/system/test_model_cache_security.py` (чужой `model_cache_path` и чужой файл в default-пути), `tests/unit/test_atomic_file.py` (симлинк-родитель и промежуточный симлинк-компонент, opt-in `tighten_directory`).
12. **BAR-20:** NFR «100 провайдеров + 2 МиБ кэша → старт в бюджете»; кэш читается один раз.
13. **BAR-21:** файл кэша с чужим uid/режимом `0666` игнорируется с WARNING.
14. **BAR-22:** «translate без выбранной модели → кнопка снова доступна, прогресс скрыт, Stop не падает»; «openai без ключа → видимое сообщение, вкладка работоспособна»; «reload models без ключа → сообщение, нет traceback».
15. **BAR-23:** NFR «stop/shutdown при зависшем fake-провайдере возвращается < 2 с, приложение закрывается»; unit «wait вызывается с таймаутом». **Реализовано:** `tests/unit/test_list_model_worker.py` (контракт воркера: успех/ошибка/таймаут/отмена, отмена до старта, `stopped()` при падении `loop.close()`), `tests/components/test_model_manager_fetch_lifecycle.py` (`wait` с ненулевым бюджетом и без `terminate`, WARNING при игнорируемой отмене, идемпотентный `shutdown`, stop/reload/remove, отбрасывание результата **и ошибки** остановленной загрузки при доставке ошибки текущей, общий дедлайн батч-остановки), `tests/system/test_model_fetch_lifecycle.py` (реальный зависший HTTP-endpoint: stop < 2 с, `shutdown` трёх провайдеров < 2 с, отмена без `error`, таймаут даёт один `error`, happy path).
16. **BAR-24:** «endpoint вернул 100 001 модель → загружено ≤10 000, UI отвечает, в логе предупреждение»; NFR времени обработки 10 000 моделей.
17. **BAR-25:** OCR с неподдерживающим изображения клиентом → `acompletion` не вызван, ровно один `error`. **Реализовано:** `tests/unit/test_workers.py` (unsupported/нет атрибута/нет `PROVIDER_NAME`/supported/ошибка `acompletion`) и `tests/system/test_ocr_worker_flow.py` (реальный `QThread`-путь).
18. **BAR-26:** «выход без смены языка → shutdown вызван»; **BAR-27:** в публикуемых docs/README нет абсолютных путей и заявлений, расходящихся с поведением.
19. **BAR-28:** `tests/system/test_flatpak_pyside.py` (opt-in `-m slow`, реальный BaseApp 6.11.3): два негативных контроля (обычная и escaped-форма выполняют payload при прямом чтении); путь приложения — любой существующий конфиг (мелкий, oversize, escaped, симлинк) уносится, `memory_backed=True`, `QSettings` не открывает ни одного файла, код не выполняется. Плюс проверка `PySide6.__version__` внутри собранного bundle ≥ 6.12 (build-guard `flatpak/bar28_guard.py`).
20. **Пиннинг:** `pyproject.toml` содержит `pyside6-essentials~=6.12.0`; Flatpak-модуль в `flatpak/barbaros.yaml` ставит точный пин `pyside6-essentials==6.12.0`/`shiboken6==6.12.0`, а `flatpak/bar28_guard.py` на сборке проверяет версию, соответствие PySide6 ↔ Qt и отказ от pickle. Статический тест `tests/unit/test_flatpak_manifest.py` проверяет пин ≥ 6.12, вызов и поставку guard в манифесте и что guard проходит.

## 11. Воспроизводимость и ограничения

**Ключевые эксперименты (HEAD `ea8822c`, изолированные XDG/HOME в temp, offscreen Qt, fake keyring):**
- **Pickle-RCE (BAR-01/BAR-28):**
  - PySide6 6.12.0 (`.venv`): INI с `@Variant(...PySide::PyObjectWrapper...)` → `QSettings.value()` бросает `RuntimeError: Failed to deserialize Python object from QDataStream…`, payload не выполняется.
  - BaseApp `io.qt.PySide.BaseApp` 6.11.3 (`flatpak run --command=python3`, PySide6 6.11.3, Python 3.13): writer пишет `Evil.__reduce__` через `QSettings.setValue`, reader в отдельном процессе читает `main_window/model` → payload выполняется (файл-маркер создан).
  - Обход санации (до исправления): конфиг увеличен до 1 048 817 байт; `sanitize_pickled_settings()` вернул `None` (WARNING «file too large», лимит 1 МиБ) и файл не тронул; чтение под BaseApp 6.11.3 выполнило payload. Симлинк/read-only дают тот же `None` по коду санации. Дополнительно найдено, что квотированная форма `model="@Variant(...` (QSettings квотирует значения с запятой) обходила построчный скан и давала `removed == 0`.
  - **Дополнительно (найдено ревью, до финального фикса):** escape-форма `model=\x40Variant(...` и `PySide::PyObject\x57rapper` невидима построчному сканеру, но Qt снимает escapes до разбора варианта — на реальном BaseApp 6.11.3 такая форма выполняла payload даже в первой версии fail-closed. Поэтому итоговый фикс не полагается на скан: на < 6.12 файл просто не читается.
  - **После исправления (реальный BaseApp 6.11.3):** `tests/system/test_flatpak_pyside.py` — оба негативных контроля (обычная и escaped-форма) выполнили payload при прямом чтении, но `prepare_settings_file()` унёс small/big/escaped-конфиги и `QSettings` payload не выполнил; в собранном Flatpak bundle импортируется PySide6 6.12.0 и fresh-process чтение даёт `RuntimeError` без выполнения (см. build-guard).
- **D-Bus (BAR-04/12/15):** `dbus-run-session`, `IPCService(as_server=True, app=Stub)`; `gdbus introspect` → интерфейс `local.barbaros.ipc.IPCService`, метод `popup_and_translate()`; сторонний клиент → `ReplyMessage`, обработчик выполнен; исключение в слоте → клиенту `ReplyMessage` без error; второй сервер → `Exception('')` при `registerService`.
- **Qt rich text (BAR-06/13):** `QT_QPA_PLATFORM=offscreen`; инспекция `QMessageBox.findChildren(QLabel)` (`textFormat`, `openExternalLinks`), `<img src="file://…">` грузится в `QLabel`/`QMessageBox`/`QTextEdit`; remote-картинки не грузятся; ссылки не кликабельны.
- **Keyring (BAR-02/11):** fake/in-memory backend и `fail.Keyring`; отсутствие вызовов `delete()`; `NoKeyringError` на старте; plaintext-fallback отсутствует.
- **`pop_think` (BAR-07):** замеры `re.search` на `<think>`-повторениях без закрывающего тега (5–160 КБ) — квадратичный рост.
- **Конфиг (BAR-09):** повреждённый JSON теперь не роняет старт (`valueFromJson` → default); JSON верной формы неверного типа (число/объект) роняет; `api_base="http://evil"` из конфига принимается.
- **Кэш (BAR-19/20/21), до исправления:** матрица `cache_path_from_config`; замена существующего файла/FIFO/symlink-цели; `chmod` сквозь symlink-родителя; отказ при read-only/ENOSPC/сбое replace с сохранением старого файла; symlink/FIFO/device/каталог не читаются, ровно `limit+1`; права `0600`/`0700` при umask 000/022/077; 100×`load()` 4 МиБ = 7.48 с; реальный `MainWindow` 3/20/100 провайдеров = 145/1353/7221 мс.
- **Кэш (BAR-19), после исправления:** write-guard — чужой файл (10 форм: `.bashrc`, чужой JSON, пустой, whitespace, non-UTF8, обрезанный, неверный `version`/`models`, top-level list) → `save() == False`, байты/права не изменены, temp нет; кэш версий 0/1/2/999 и ровно на границе 4 МиБ → `save()` разрешён и перезаписывается версией 1; FIFO/каталог/symlink/dangling symlink/oversized (4 МиБ + 1)/unreadable (0o000) → `False`; hardlink: другой линк сохраняет старые байты; повторный `save` своего неизменного файла не парсит его (identity-memo), внешнее изменение перепроверяется; реальный `MainWindow` с `model_cache_path` на чужом файле и с чужим файлом в default-пути не меняет их; симлинк-родитель и промежуточный симлинк-компонент: режим целевого каталога 0755 сохранён, файл создан `0600`. `481 passed, 3 deselected`, `ruff check` чист.
- **GUI fail-open (BAR-22):** `TextFeature` на fake-parent (offscreen): нет выбранной модели → `AttributeError`, Translate скрыт/disabled, прогресс крутится, Stop падает; для openai без ключа — `MissingApiKeyError` (из `any_llm` через `AnyLLM.create`), состояние то же; Clear не сбрасывает.
- **Потоки/сеть (BAR-23), до исправления:** `QThread.terminate()` на Python-цикле → `wait(2000)` не вернулся >20 с; на C-`sleep(60)` — 0.001 с; у `AnyLLM` дефолтные таймауты `Timeout(connect=5, read=600, write=600, pool=600)`.
- **Потоки/сеть (BAR-23), после исправления:** зависший реальный HTTP-endpoint (принял соединение, не отвечает) — `stop_fetching_models` возвращается за **~1 мс** (0.5-1.4 мс в независимых замерах), поток `isFinished`, ни одного `error`; `shutdown()` трёх таких провайдеров — **~1 мс**, повторный — no-op; отмена до старта `run()` не выполняет запрос; при `LIST_MODELS_TIMEOUT_S=0.3` таймаут срабатывает за **308 мс** и даёт ровно один `error` (`list_models timeout after 0.3s`); отмена для провайдера с синхронным SDK в фоновом потоке (`asyncio.to_thread`) прерывает ожидание и завершает поток воркера; для забытого (`FakeThread.wait() == False`) потока — WARNING без блокировки. Полный набор — `513 passed, 3 deselected`; `uv run ruff check src tests` — чисто. Пред-фикс контроль (новые тест-файлы против неизменённого `main`: unit 8 failed, component 1 collection error из-за отсутствующих констант, system 3 failed / 1 passed — итого 11 failed + 1 collection error / 1 passed из 23, причём на выходе печатается `QThread: Destroyed while thread is still running`) — то есть старый код не проходит новые тесты.
- **Размер `list_models` (BAR-24):** 20 000 моделей = 1.5 МБ, parse+validate+`QTreeWidgetItem` ≈ 0.16 с; 100 000 = 7.7 МБ / 0.64 с GUI; 1 млн — линейно ≈ 6.4 с.
- **OCR fail-open (BAR-25):** до исправления stub-клиент с `SUPPORTS_COMPLETION_IMAGE=False` → `error` и `done` одновременно, `acompletion` вызван один раз (изображение ушло); stub без атрибута → `AttributeError` без `error`/`done` (`finished` из `finally`, т.е. молчаливый сброс, не зависание). После исправления: `acompletion` не вызван, ровно один `error`, `done` нет — и в unit-, и в system-тесте реального `QThread`-пути; полный набор `490 passed, 3 deselected`.
- **Exit/docs (BAR-26/27):** статическая проверка единственной точки `aboutToQuit.connect`; `grep` абсолютных путей в `docs/` и сверка README с `common.py:108-127`/BAR-18.

**Ограничения:** не выполнялись полная Flatpak-сборка/запуск собственного bundle, реальные операции с системным Secret Service, проверка на реальном X11/Wayland; не проводился SAST зависимостей (CVE) и фаззинг. Вывод по Flatpak-BaseApp сделан на установленном runtime 6.11.3 и его PySide6 6.11.3; вывод по общему каталогу (BAR-21) — на POSIX-семантике и коде (живой тест с другой учётной записью не проводился). Выводы по `QThread.terminate()` — на PySide6 6.12.0/Qt 6.12. Исходный код в ходе аудита не изменялся; полный набор тестов на HEAD — `405 passed, 2 deselected`. После исправления BAR-19 (ветка фикса) — `481 passed, 3 deselected`; после исправления BAR-25 — `490 passed, 3 deselected` (`uv run pytest`), `uv run ruff check src tests` — чисто.
