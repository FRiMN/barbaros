# Barbaros — аудит безопасности по OWASP Cheat Sheet Series

- **Проект:** репозиторий `barbaros` (корень проекта), HEAD `1e3d17f` (2026-11-09); абсолютные пути с машины аудита в публикуемый документ не включаются (BAR-27).
- **Предыдущая версия отчёта:** аудит HEAD `71197f8` (2026-11-03), `docs/security/owasp-audit.md` в коммите `6dc2a4c`. Находки `BAR-01..BAR-18` сохранены с прежними ID и перепроверены на текущем HEAD; новые находки — `BAR-19+`.
- **Предмет:** десктопное PySide6-приложение Barbaros: перевод текста и OCR через `any-llm-sdk`-провайдеров, системный трей, D-Bus/SIGUSR1 IPC, keyring для API-ключей, Flatpak-поставка. С прошлого аудита добавлен JSON-кэш списков моделей (`model_cache.py`, `atomic_file.py`) и переработан `model_manager.py`.
- **Источник требований:** локальная копия OWASP Cheat Sheet Series (137 читшитов; ссылки ниже — на имена файлов и разделы; путь на машине аудита не публикуется). Маппинг дан на **OWASP Top 10:2021** (для преемственности с прошлой версией) и **OWASP Top 10:2025** (актуальная редакция; https://top10.owasp.org/2025/0x00_2025-Introduction/).
- **Методика:** статический аудит потоков данных (`source → sink`), сверка с чек-листами OWASP, эксперименты в `.venv` (PySide6 6.11.1, any-llm-sdk 1.15.0, Python 3.11): offscreen-Qt, `dbus-run-session`, временные `XDG_CONFIG_HOME`/`XDG_DATA_HOME`/`XDG_RUNTIME_DIR`, локальный fake OpenAI-совместимый endpoint, fake/in-memory keyring. Работа велась тремя независимыми проходами: (1) ре-проверка всех находок `BAR-01..BAR-18` с воспроизведением экспериментов; (2) аудит нового attack surface кэша моделей; (3) систематическая сверка с OWASP Cheat Sheet Series. Исходный код не изменялся.
- **Тесты:** полный набор на HEAD — `345 passed, 2 deselected` (`pytest`, slow-NFR исключены `addopts`); целевые security-тесты кэша — `155 passed`.
- **Модель угроз:** локальный процесс того же пользователя (в т.ч. скомпрометированное приложение/скрипт), Flatpak-приложение в рамках выданных ему разрешений, поддельный/скомпрометированный LLM-endpoint, подмена/синхронизация файла конфигурации, случайная утечка (бэкапы, скриншоты, логи). Вне модели: root, физический доступ, удалённый сетевой атакующий, «полностью доверенный» same-uid. Права файлов `0600`/`0700` рассматриваются как defense-in-depth, а не как граница против same-uid (это же явно признаёт `atomic_file.py:40-44`).
- **Границы:** не проводились динамический фаззинг, SAST-сканирование зависимостей (CVE), реальная сборка/запуск Flatpak, реальные операции с системным Secret Service, проверка на реальном X11/Wayland. Выводы по Flatpak/Secret Service основаны на манифесте, коде и документации; выводы по keyring — на fake-бэкендах.

## 0. Что изменилось с предыдущей версии

С прошлого аудита — **47 коммитов**, из них основной security-релевантный PR «json models cache» (`b1eca29..1116155`) и серия рефакторингов. В `src/` на HEAD: `17 файлов, +1198/−205` строк; добавлены `src/barbaros/model_cache.py` (440 строк) и `src/barbaros/atomic_file.py` (312 строк), изменены `model_manager.py`, `main_window.py`, `ipc.py`, `security.py`, `flatpak/barbaros.yaml` (только перевод комментариев). Кэш списков моделей вынесен из `QSettings` в отдельный JSON-файл с правами `0600`.

**Итог ре-проверки:** все **18 прежних находок остаются открытыми**; ни одна не исправлена и ни одна не смягчена по существу. Частичные улучшения: новый код кэша использует `logging` с repr-экранированием (BAR-17 — только новые модули); один из двух bare `except` в `ipc.py` заменён на `contextlib.suppress` (BAR-12); `model_cache_path` валидируется формально, но добавляет новый sink записи (см. BAR-19). Новый JSON-кэш **сознательно не закрывает BAR-01** — это прямо зафиксировано в `docs/model-cache-storage.md:16` и в комментарии `main_window.py:104-113`.

**Добавлено 9 новых находок:** 2 Medium (BAR-19 — запись по пути из конфига; BAR-22 — заклиненная вкладка при исключении в GUI-слоте), 5 Low (BAR-20, BAR-21, BAR-23, BAR-24, BAR-25) и 2 Info (BAR-26, BAR-27).

**Поправки к предыдущей версии отчёта** (подробно в §8): способ вызова D-Bus-метода (BAR-04), атрибуция некликабельности ссылок (BAR-13), поведение `api_base=123` (BAR-09), статус bare `except` (BAR-12), первый ключ, вызывающий unpickle (BAR-01), строки `README.md` (BAR-18), неточность про plain-text вставку из буфера (BAR-13), абсолютные пути в публикуемом документе (BAR-27).

## 1. Резюме

На HEAD найдено **27 проблем**: **1 High, 9 Medium, 13 Low, 4 Info** (18 прежних — все открыты; 9 новых). Критических проблем, требующих немедленного отзыва ключей или внеочередного релиза, нет. High — pickle-RCE (BAR-01): на HEAD полный путь воспроизведён, включая подделку INI-файла **без Python-писателя** у атакующего; достаточно записи в файл конфигурации (бэкап, dotfiles-синхронизация, другое приложение с доступом к `$HOME`).

**Топ-3:**
1. **BAR-01 (High, A08):** выбор модели сохраняется в `QSettings` как Python-объект и сериализуется через **pickle**; подмена строки в INI-конфиге приводит к выполнению кода при следующем старте. На HEAD подтверждено: unpickle запускает чтение **любого** ключа группы `main_window` (`value/contains/allKeys/childKeys/remove`); первый триггер при штатном старте — `target_language_list` (`main_window.py:188`). Реальный `App()` выполнил payload до падения на трее.
2. **BAR-19 (Medium, A04/A08, новая):** `model_cache_path` из конфига не проверяется на «это наш файл кэша». `os.replace` заменяет **любой** user-writable файл (`.bashrc`, конфиг другого приложения, FIFO) содержимым кэша; старые данные теряются без предупреждения. Прямой эскалации относительно BAR-01 нет (кто пишет конфиг, обычно может писать и файлы), но это отдельный деструктивный sink, который переживёт исправление BAR-01.
3. **BAR-02 (Medium, A02/A04):** API-ключи не отзываются — `KeySecurityManager.delete()` не вызывается нигде; удаление провайдера оставляет ключ в keyring, а добавление нового провайдера с тем же именем может отправить старый ключ на новый `api_base`. Практически важная связка: **BAR-04 (Medium, латентная)** — D-Bus-метод `popup_and_translate` не проверяет вызывающего; сейчас путь падает на BAR-15 до отправки, но исправление регрессии «включит» риск без изменения дизайна.

**Отдельно по доступности:** **BAR-22 (Medium, A10:2025)** — на чистой установке (модель ещё не выбрана, список моделей пуст) нажатие «Translate» навсегда заклинивает вкладку: кнопка скрыта/disabled, прогресс крутится, Stop падает с `AttributeError`; лечится только перезапуском. Тот же fail-open — в OCR-вкладке и при отсутствующем API-ключе (`MissingApiKeyError`). Это не RCE/утечка, но нарушает AGENTS.md #14 и воспроизводится без атакующего.

## 2. Сводная таблица

| ID | Severity | Статус | OWASP (cheat sheet / Top-10) | Находка | Ключевые места (HEAD) |
|---|---|---|---|---|---|
| BAR-01 | **High** | open | Deserialization / A08:2021, A08:2025 | pickle-десериализация `ModelSelection` из `QSettings` → RCE при чтении подменённого конфига | `main_window.py:119-120,210-216,188`; `features/ocr.py:94-102` |
| BAR-02 | Medium | open | Secrets Management §2.7 / A02, A04 | Нет отзыва и очистки API-ключей; stale-ключ может уйти новому endpoint | `security.py:21-25`; `provider_dialog.py:42-49,111-113,218-232`; `model_manager.py:53` |
| BAR-03 | Medium | open | Transport Layer Security / A02 | `http://` разрешён для любого хоста → ключ и текст в cleartext | `common.py:62-77`; `provider_dialog.py:95-98`; `tests/test_common.py:6-16` |
| BAR-04 | Medium\* | open | Authorization / A01, A04, A06 | D-Bus `popup_and_translate` без аутентификации вызывающего; практический риск латентный из-за BAR-15 | `ipc.py:13,160-171,206-208`; `main.py:50-59` |
| BAR-05 | Medium | open | Attack Surface / A05, A02 | Flatpak: полный `--socket=session-bus` + неверный `--own-name` | `flatpak/barbaros.yaml:21,23` |
| BAR-06 | Medium | open | XSS/Injection / A03 | HTML-инъекция из ошибки провайдера в `QMessageBox` (`AutoText`, `openExternalLinks=True`) | `main_window.py:91-102`; `common.py:89-93`; `features/text.py:131`; `features/ocr.py:211-215` |
| BAR-07 | Medium | open | Input Validation (Regex) / A04 | Квадратичный regex `pop_think` в GUI-потоке + нет лимита ответа → зависание UI | `features/text.py:104-110,119-126`; `workers.py:69,102` |
| BAR-08 | Medium | open | Supply Chain / A06, A08, A03:2025 | Flatpak-зависимости не запинены и без хэшей; `uv.lock` в сборке не участвует | `flatpak/requirements-flatpak.txt:1-5`; `flatpak/barbaros.yaml:58` |
| BAR-09 | Low | open | Input Validation / A04, A05, A10 | Конфиг — недоверенный вход: `api_base` не валидируется, битый JSON/тип роняет старт | `common.py:20-24`; `main_window.py:56-64,186-191`; `model_manager.py:27-35` |
| BAR-10 | Low | open | Key Management / A05 | Права QSettings-файла определяются umask (0664/0644); нет `0600` | `main.py:26-27` |
| BAR-11 | Low | open | Secrets Management §2.9 / A04, A10 | `NoKeyringError` не обрабатывается: без Secret Service падение на старте | `security.py:7-25`; `providers_card.py:30,132` |
| BAR-12 | Low | open (changed) | Authorization/Logging / A04, A09, A10 | Хрупкий SIGUSR1-fallback: `name=None` → краш, сигнал чужому процессу, `assert`/bare `except`/`print` | `ipc.py:25,31-32,76-90,122-145,160-171` |
| BAR-13 | Low | open | Output encoding / A03 | Rich text из внешних имён и ответа LLM (`QLabel`, `LinkLabel`, `QTextEdit.setText`); новый источник — `model.id` из кэша | `filterable_combobox.py:70,358,72,361`; `providers_card.py:66,106`; `features/text.py:125`; `features/ocr.py:198,203` |
| BAR-14 | Low | open | Input Validation / A04 | Нет лимитов на текст/изображение/ответ; невалидированный `ChatCompletion` (`choices=[]`, `content=None`) | `features/text.py:61-76,119-126`; `features/ocr.py:127-139,195-203`; `workers.py:69,90-96,102` |
| BAR-15 | Low | open | Secure Code Review / A04, A09, A10 | Регрессия `process_translation_request`: popup-перевод сломан, ошибка маскируется как успех | `main.py:50-59`; `features/text.py:41,45` |
| BAR-16 | Low | open | Supply Chain / A06, A08, A03:2025 | CI отключён, нет Dependabot/pip-audit/`SECURITY.md`, bundle не подписан | `.github/workflows/flatpak.yml.off`; `tasks.py:41,46,63,71` |
| BAR-17 | Info | open (частично улучшено) | Logging / A09 | Логирование через `print()`: нет структуры/экранирования; секреты не логируются; новый `print` пути кэша | 22 `print` в старых модулях; `main_window.py:53` |
| BAR-18 | Info | open | User Privacy / A04 | Скриншот (по умолчанию весь экран) и clipboard уходят провайдеру без in-app уведомления | `image_manager.py:63-70,162-173`; `main.py:50-59`; `README.md:33` |
| **BAR-19** | **Medium\*\*** | **новая** | Secure Code Review (file path sink) / A04, A08 | `model_cache_path` — произвольный sink записи: замена/уничтожение любого user-writable файла; `chmod` каталога сквозь симлинк | `main_window.py:44-52`; `model_cache.py:51-100`; `atomic_file.py:247-259,283-312` |
| **BAR-20** | Low | **новая** | Denial of Service / A04 | Кэш читается/парсится заново на каждого `RESTORE`-провайдера в GUI-потоке: 100 провайдеров + 4 МиБ ≈ 7.2 с старта | `main_window.py:62-64`; `model_manager.py:132-150,299-312`; `model_cache.py:325-335` |
| **BAR-21** | Low | **новая** | Input Validation / A08, A02 | Кэш в общем каталоге читается без проверки владельца/прав (defense-in-depth, вне формальной модели) | `atomic_file.py:118-155`; `model_cache.py:299-305` |
| **BAR-22** | **Medium** | **новая** | Error Handling/DoS / A10:2025 (A04:2021) | Исключение в GUI-слоте после установки «загрузочного» состояния → вкладка заклинена навсегда; Stop падает | `features/text.py:69-76,86-88`; `features/ocr.py:120-125`; `workers.py:59,84,119`; `model_manager.py:43-53,225` |
| **BAR-23** | Low | **новая** | DoS/Threading / A10:2025 (A04:2021) | `QThread.terminate()` + `wait()` без таймаута, нет сетевых таймаутов → зависание GUI при остановке/выходе | `model_manager.py:185-201`; `workers.py:121-142` |
| **BAR-24** | Low | **новая** | LLM output validation/DoS / A06:2025 (A04:2021) | Неограниченный ответ `list_models` от endpoint: 100 000 моделей = 7.7 МБ / 0.64 с в GUI-потоке | `workers.py:125-136`; `model_manager.py:255-258`; `filterable_combobox.py:233-253` |
| **BAR-25** | Low | **новая** | LLM multimodal/Privacy / A10:2025 (A04:2021) | OCR fail-open: после «провайдер не поддерживает изображения» изображение всё равно уходит провайдеру | `workers.py:86-106` (особенно `:87-89`) |
| **BAR-26** | Info | **новая** | Error Handling/Logging / A10, A09:2025 | `aboutToQuit.connect(cleanup)` внутри `save_language` → при обычном выходе shutdown не вызывается | `main.py:43-48,72-76,152-159` |
| **BAR-27** | Info | **новая** | Privacy/Honesty / A09:2025 | Гигиена документации: абсолютные локальные пути; README обещает «Secure API calls», хотя `http://` разрешён, а уведомлений о передаче нет | `docs/`, `README.md:33,273` |

\* BAR-04 — Medium как дефект дизайна; в текущем состоянии (BAR-15 открыт) практическая severity — Low: D-Bus-вызов приводит только к показу окна и `AttributeError` до отправки. После исправления BAR-15 без изменения дизайна риск станет реальным (clipboard → облачный провайдер).
\*\* BAR-19 — Medium, потому что impact — тихая деструктивная запись (integrity/availability), отдельный класс от RCE. Прямой эскалации относительно BAR-01 нет; Medium отражает, что sink переживёт исправление BAR-01 и что «данные конфига едут между машинами» (dotfiles/sync/бэкап).

---

## 3. Детали: повторная проверка BAR-01..BAR-18

### BAR-01. pickle-десериализация `ModelSelection` из `QSettings` → RCE

- **OWASP:** `Deserialization_Cheat_Sheet.md` → «Python / Clear-box Review»: *«Unpickling can execute arbitrary code; never unpickle untrusted data»*; «Using Alternative Data Formats»; `Secure_Code_Review_Cheat_Sheet.md` → «Deserialization Vulnerabilities». Top-10: A08:2021 / A08:2025 Software or Data Integrity Failures (CWE-502).
- **Статус:** **open, High** (без прежней оговорки High\*/Medium: модель угроз включает подмену файла конфигурации, а подделка INI возможна чистым текстом).
- **Место:**
  - запись: `main_window.py:119-120` (`save_choosed_model` → `settings.setValue("model", selection)`); `features/ocr.py:101-102`;
  - чтение: `main_window.py:210-216`; `features/ocr.py:94-99`;
  - тип: `widgets/filterable_combobox.py:164-168` — `@dataclass class ModelSelection`;
  - первый unpickle при штатном старте: `main_window.py:186-191` (`restore_target_languages` → `settings.value("target_language_list")` на `:188`).
- **Evidence (эксперименты на HEAD):**
  - `QSettings` в PySide6 6.11.1 сериализует Python-объект через `PySide::PyObjectWrapper` с pickle protocol 4: `model=@Variant(\0\0\0\x7f\0\0\0\x18PySide::PyObjectWrapper\0\0\0\0l\x80\x04...)`, где pickle-байты лежат открыто.
  - Вручную (только текстовый редактор, без Python-писателя) собрана INI-строка с pickle-payload `os.system("touch …/PWNED")`. **Свежий процесс**, прочитавший только соседний ключ `main_window/language`, создал файл-маркер — код выполнен. Матрица триггеров: `value`, `contains`, `allKeys`, `childKeys`, `remove` → выполнение; `fileName`, `status`, `sync`, ключ другой группы → нет.
  - Реальный `App(["x"])` с такой конфиг-строкой выполнил payload **до** падения на `TrayIcon` (`System tray is not available`). Отдельное чтение `model` не требуется: группа `main_window` читается на каждом старте.
  - `_drop_legacy_model_cache` (`main_window.py:104-113`) удаляет только plain-JSON ключ `llm_by_providers`; pickle-ключи `main_window/model` и `ocr_feature/model` не трогаются — это зафиксировано в комментарии и в `docs/model-cache-storage.md:16`.
- **Сценарий:** запись в `~/.config/io.github.frimn/barbaros.conf` (Flatpak: `~/.var/app/io.github.frimn.barbaros/config/...`) — вредоносное приложение с доступом к `$HOME`, синхронизация dotfiles/бэкап, восстановление чужого конфига, group-writable файл. При следующем запуске Barbaros (в т.ч. автозапуск из трея) выполняется произвольный код с правами пользователя; payload персистентный.
- **Рекомендация (KISS):**
  1. Хранить выбор как данные: `settings.setValueAsJson("model_selection", {"provider": …, "model": …})` или два строковых ключа; чтение — `valueFromJson`.
  2. **Не пытаться «прочитать/удалить» легаси-ключ через `QSettings`:** unpickle вызывают `remove()`, `setValue()`, `allKeys()`, `contains()` и чтение любого ключа группы. Миграция должна начинаться **до** первого обращения к `QSettings`: в `App.__init__` это `main.py:31` (`language`, root-группа) и `main_window.py:44-46` (`model_cache_path`); санитизация сырого INI-файла (путь из `QStandardPaths`) — до этих вызовов. При наличии `PyObjectWrapper`/`@Variant` — сохранить бэкап и удалить/санитизировать файл без разбора `QSettings`, затем стартовать с дефолтами. Бесшовный вариант — заменить `QSettings` на собственный JSON-стор (механика уже есть в `atomic_file.py`), а старый файл переименовать.
  3. Правило: в `QSettings.setValue` — только `str`/`int`/`bool`/`QByteArray` (геометрия `saveGeometry()` — корректный Qt-тип). Добавить проверку в ревью/линт.
  4. Тест: сохранение и чтение выбора без `pickle` (в конфиге нет `PyObjectWrapper`); тест, что `restore_model` не падает на легаси-ключе; тест, что старт не вызывает unpickle на подменённом INI.

### BAR-02. Неполный жизненный цикл API-ключей

- **OWASP:** `Secrets_Management_Cheat_Sheet.md` §2.7.3 «Revocation», §2.7.2 «Rotation», §2.6 «Auditing»; `Key_Management_Cheat_Sheet.md` → «Zeroization and Destruction». Top-10: A02, A04.
- **Статус:** open, Medium.
- **Место:** `security.py:21-25` (`delete()` реализован), `provider_dialog.py:42-49` (предзаполнение ключа), `:111-113` (запись только непустого), `:218-232` (удаление провайдера, `model_manager.remove` на `:230`), `model_manager.py:53` (чтение ключа для клиента), `model_manager.py:152-157` (`remove()`).
- **Evidence (HEAD):** `KeySecurityManager.delete()` **не вызывается нигде** (`grep` по `api_key_manager.delete` даёт только определение). Fake in-memory keyring: после `ModelManager.remove("audit-provider")` ключ остаётся доступным. Очистка поля ключа в диалоге редактирования + сохранение оставляет старый ключ (`get()` возвращает старое значение). `delete()` по-прежнему ловит только `PasswordDeleteError`, не `KeyringError`.
- **Сценарий:** (1) пользователь удаляет облачного провайдера, считая, что ключ отозван, — секрет остаётся в keyring; (2) пользователь переиспользует имя провайдера для нового аккаунта/локального шлюза, не вводя ключ: `ProviderClient.client()` возьмёт старый ключ и отправит его на новый `api_base`; (3) сменить endpoint, оставив провайдера, нельзя без перезаписи ключа: «пусто» трактуется как «оставить старый».
- **Рекомендация:** вызывать `api_key_manager.delete()` при удалении провайдера (после подтверждения), но **не** при `ModelManager.update()` (иначе редактирование сотрёт ключ). Добавить явную кнопку «Удалить сохранённый ключ» с подтверждением. В `delete()` ловить `keyring.errors.KeyringError`, а не только `PasswordDeleteError`. Тест с fake backend: «удалил провайдера / очистил ключ → в хранилище пусто».

### BAR-03. `http://` допускается для любого хоста → cleartext

- **OWASP:** `Secrets_Management_Cheat_Sheet.md` §2.8 «TLS Everywhere»; `Transport_Layer_Security_Cheat_Sheet.md` → «Use TLS For All Pages». Top-10: A02.
- **Статус:** open, Medium.
- **Место:** `common.py:62-77` (шаблон `^https?://` на `:66-77`), `widgets/provider_dialog.py:95-98` (единственная проверка URL), `tests/test_common.py:6-16` (тесты закрепляют `http://google.com`, `http://192.168.0.1:1234` как валидные), `model_manager.py:53` (URL уходит в `AnyLLM.create`).
- **Evidence:** `is_valid_url('http://evil.example.com') == True`, `is_valid_url('http://169.254.169.254/…') == True`, `http://192.168.0.1:1234/v1` → True. `ftp://`, `javascript:`, `user:pass@host` → False; `http://[::1]:8080` → False (IPv6-loopback не поддержан — не проблема). При custom OpenAI-совместимом endpoint `api_base` становится `base_url` httpx; в открытом виде уходят `Authorization: Bearer <ключ>` и весь переводимый текст. Для `api_base=None` any-llm использует HTTPS по умолчанию.
- **Рекомендация:** один helper (например, `api_base_problem(url)`) с `urllib.parse`: разрешать `https` для любых хостов; `http` — только `localhost`/`127.0.0.0/8`/`::1`; при не-loopback `http` — отказ. Применять и в диалоге, и при загрузке из конфига (BAR-09). Обновить `tests/test_common.py`.

### BAR-04. D-Bus `popup_and_translate` без проверки вызывающего

- **OWASP:** `Authorization_Cheat_Sheet.md` → «Deny by Default», «Validate Permissions on Every Request», «Enforce Least Privileges»; `Attack_Surface_Analysis_Cheat_Sheet.md`; `User_Privacy_Protection_Cheat_Sheet.md` → «Honesty & Transparency». Top-10: A01, A04, A06.
- **Статус:** open, Medium (практическая — Low, пока BAR-15 открыт).
- **Место:** `ipc.py:13` (`SERVICE_NAME`), `:160-171` (`registerService`, `registerObject(..., ExportAllSlots)` на пути `/`), `:206-208` (`@Slot()` → `app.process_translation_request()`), `main.py:50-59` (чтение clipboard + программный клик «Translate»).
- **Evidence:** под `dbus-run-session` сторонний процесс вызывает экспортированный слот; сервер-заглушка реально выполнил обработчик, клиент получил `ReplyMessage` без ошибки. Никакой проверки PID/uid/имени вызывающего, токена, подтверждения или rate limit нет. **Поправка к прошлому отчёту:** `QDBusInterface(SERVICE_NAME, "/", "", bus)` на PySide6 6.11.1 невалиден; Qt экспортирует интерфейс, производный от Python-класса (для приложения — `local.barbaros.ipc.IPCService`), вызов делается с этим именем или через `gdbus`.
- **Сценарий:** любая программа того же пользователя (вне sandbox или Flatpak с разрешением `talk-name`) вызывает метод; запущенный экземпляр читает буфер обмена и отправляет текст облачному провайдеру без явного действия пользователя; повторные вызовы — платные API-запросы и перекрытие окна. Прямого канала «прочитать буфер атакующим» нет (`void`), но при подмене `api_base` данные можно направить на свой endpoint.
- **Оговорка:** на HEAD `process_translation_request` падает с `AttributeError` до отправки (BAR-15) — сейчас риск латентный. Если обработчик бросает исключение, клиент всё равно получает валидный ответ — сбой неотличим от успеха.
- **Рекомендация:** разделить «показать окно» и «перевести из буфера»: IPC/`--popup` должны только фокусировать окно; перевод из clipboard — только по явному действию пользователя в UI. Если автоперевод нужен — подтверждение в UI с указанием провайдера, rate limit/дедупликация, проверка вызывающего (`QDBusContext`/`GetConnectionUnixProcessID` + сверка `/proc/<pid>/exe`), узкий D-Bus-интерфейс вместо `ExportAllSlots` на `/`.

### BAR-05. Flatpak: полный `--socket=session-bus` и неверный `--own-name`

- **OWASP:** `Authorization_Cheat_Sheet.md` → «Enforce Least Privileges», «Deny by Default»; `Attack_Surface_Analysis_Cheat_Sheet.md`. Top-10: A05, A02:2025.
- **Статус:** open, Medium.
- **Место:** `flatpak/barbaros.yaml:21` (`--socket=session-bus`), `:23` (`--own-name=org.frimn.barbaros`); `ipc.py:13`.
- **Evidence:** манифест на HEAD изменён только переводом комментариев; оба разрешения на месте. `--socket=session-bus` отключает фильтрацию xdg-dbus-proxy и даёт приложению нефильтрованный доступ ко всей сессии (Flatpak docs называют это security risk). Строка `--own-name=org.frimn.barbaros` не совпадает с app-id/`SERVICE_NAME` `io.github.frimn.barbaros`; имя app-id разрешено по умолчанию, это разрешение лишнее. `--talk-name=org.freedesktop.secrets` нужен для keyring и сам по себе не даёт чужих секретов.
- **Рекомендация:** убрать `--socket=session-bus`; оставить `--talk-name=org.freedesktop.secrets`; убрать `--own-name=org.frimn.barbaros`. Проверить IPC после изменения (`flatpak run --log-session-bus …`).

### BAR-06. HTML-инъекция из ошибки провайдера в `QMessageBox`

- **OWASP:** `Cross_Site_Scripting_Prevention_Cheat_Sheet.md` → «Output Encoding for HTML Contexts», «HTML Sanitization», «Safe Sinks»; `Injection_Prevention_Cheat_Sheet.md` → «Rule #3»; `LLM_Prompt_Injection_Prevention_Cheat_Sheet.md` → «HTML and Markdown Injection». Top-10: A03, A05:2025.
- **Статус:** open, Medium.
- **Место:** `main_window.py:91-102` (`msg = url_to_html_links(msg)` → `QMessageBox.critical`), `common.py:89-93` (`url_to_html_links` **без** `html.escape`); источники ошибок: `model_manager.py:252-253`, `workers.py:72-73,105-106`; независимые sink'и: `features/text.py:131`, `features/ocr.py:211-215`.
- **Evidence:** `url_to_html_links('<b>quota</b> <a href="file:///etc/passwd">x</a> https://…')` сохраняет живые теги и линкификацию. `QMessageBox` использует `Qt.TextFormat.AutoText` и `openExternalLinks=True`; `<img src="file://…">` загружается, клик по `<a href="file://…">` приводит к `QDesktopServices`/`xdg-open`. Доставка недоверенного текста подтверждена локальным fake-endpoint: `any_llm` кладёт тело HTTP-ошибки в `str(exception)`, оно уходит в `error.emit(...)` и в `QMessageBox.critical` без экранирования.
- **Влияние:** UI-spoofing в системном модальном окне (поддельный текст «ключ истёк, войдите заново»), фишинговая ссылка, открытие локальных `file://`-путей. JavaScript/команд не исполняется (Qt rich text без скриптов).
- **Рекомендация:** для ошибок — plain text: `box.setTextFormat(Qt.TextFormat.PlainText)` (или `setTextInteractionFlags` без ссылок), не использовать `url_to_html_links` для недоверенных сообщений. Если ссылки нужны — сначала `html.escape(text, quote=True)`, затем линкификация по экранированному тексту с экранированием URL в `href`; ограничить длину сообщения.

### BAR-07. Квадратичный `pop_think` regex в GUI-потоке

- **OWASP:** `Input_Validation_Cheat_Sheet.md` → «Regular Expressions (Regex)»; `LLM_Prompt_Injection_Prevention_Cheat_Sheet.md` → «Output Monitoring and Validation». Top-10: A04, A06:2025.
- **Статус:** open, Medium.
- **Место:** `features/text.py:104-110` (`re.search(r"<think>.*?<\/think>", text, MULTILINE|DOTALL)`), вызов в GUI-слоте `:119-126` (строка 123); нет `max_tokens`/лимита ответа (`workers.py:69,102`).
- **Evidence (замеры на HEAD):** худший случай — строка из повторяющихся `<think>` без закрывающего тега; рост ~×4 на удвоение длины: 5 КБ — 13.2 мс, 10 КБ — 54.8 мс, 20 КБ — 211.7 мс, 40 КБ — 784.7 мс, 80 КБ — 3165 мс, 160 КБ — **17.7 с** (квадратично). Regex выполняется в главном потоке; 1 МБ ≈ минуты зависания UI. Дополнительно `text = text[len(think_text):]` режет не по позиции блока, а по его длине (логическая ошибка при `<think>` не в начале).
- **Рекомендация:** заменить regex на линейный `str.find("<think>")`/`find("</think>")`; жёстко ограничить длину ответа до обработки (1–2 МБ) и reasoning; передавать `max_tokens` в `acompletion`; добавить не функциональный тест на время обработки большого ответа.

### BAR-08. Непинованные зависимости Flatpak / невоспроизводимая сборка

- **OWASP:** `Software_Supply_Chain_Security_Cheat_Sheet.md` → «Lockfile/Version Pinning»; `Vulnerable_Dependency_Management_Cheat_Sheet.md`; `Dependency_Graph_SBOM_Cheat_Sheet.md`. Top-10: A06:2021, A08:2021 / A03:2025.
- **Статус:** open, Medium.
- **Место:** `flatpak/requirements-flatpak.txt:1-5` (`psutil`, `any-llm-sdk[all]`, `keyring>=25.7.0`, `psygnal>=0.15.1`, `dataclasses-json>=0.6.7` — без версий/хэшей у двух из пяти), `flatpak/barbaros.yaml:58` (`pip3 install -r requirements-flatpak.txt`), `pyproject.toml` (зависимости не запинены); `uv.lock` в сборке Flatpak не используется.
- **Evidence:** `--require-hashes` нет; сборка резолвит последние версии PyPI на момент сборки. `uv.lock` на HEAD: 150 пакетов, 1963 `sha256`-хэша, но фиксирует только dev-окружение. `any-llm-sdk[all]` тянет SDK всех провайдеров — широкая транзитивная поверхность.
- **Рекомендация:** генерировать hashed-requirements из `uv.lock` (`uv export --format requirements-txt --hashes` / `uv pip compile --generate-hashes`) и ставить `pip3 install --require-hashes -r …`; собирать wheel в CI из зафиксированного lock; добавить SBOM (`uv export`/Syft).

### BAR-09. Конфиг как недоверенный вход: нет валидации и fail-safe старта

- **OWASP:** `Input_Validation_Cheat_Sheet.md` → «Parse Safely, Then Validate»; `Secure_Code_Review_Cheat_Sheet.md` → «Configuration & Deployment»; `Error_Handling_Cheat_Sheet.md`. Top-10: A04, A05, A10:2025.
- **Статус:** open, Low.
- **Место:** `common.py:20-24` (`valueFromJson` → `json.loads` без обработки ошибок); `main_window.py:56-64` (`llm_providers`), `:44-52` (новый `model_cache_path`), `:186-191` (`target_language_list`); `model_manager.py:27-35` (`ProviderMeta.from_dict`).
- **Evidence (изолированный XDG):** обрезанный JSON в `main_window/llm_providers` → `JSONDecodeError` при старте; неизвестный `provider_type` → `ValueError` при старте; `api_base="http://evil.example.com"` из конфига принимается (валидатор URL — только в диалоге, `provider_dialog.py:96`). **Поправка:** `api_base=123` теперь не роняет карточку — `dataclasses_json` приводит значение к строке `"123"`; старый отчёт обещал падение `len(int)`; краш воспроизводится только при прямом `ProviderMeta(api_base=123)` в обход `from_dict`. Новый ключ `model_cache_path` валидируется формально (`model_cache.py:52-100`: только непустой абсолютный путь), но это узкое улучшение (и BAR-19).
- **Влияние:** подмена конфига перенаправляет ключ/текст на чужой `api_base`; повреждённый конфиг (после некорректного завершения/заполнения диска) вызывает цикл падений при автозапуске — противоречит AGENTS.md #14.
- **Рекомендация:** обернуть загрузку в `try/except (json.JSONDecodeError, ValueError, TypeError)`: логировать, удалять проблемный ключ, стартовать с `default_providers`; валидировать `api_base` (`str | None` + helper из BAR-03), `name`, `language`, `target_language_list`; проверять `QSettings.status()`; ограничить число провайдеров. Тест: битый конфиг → приложение стартует, валидные провайдеры загружены.

### BAR-10. Права файла настроек по umask

- **OWASP:** `Key_Management_Cheat_Sheet.md` → «Storage»; `Logging_Cheat_Sheet.md` → «Data to exclude». Top-10: A05, A02:2025.
- **Статус:** open, Low.
- **Место:** `main.py:26-27`; в `src/` нет `chmod`/`umask` для QSettings.
- **Evidence:** режим `QSettings`-файла = `0666 & ~umask`: umask 022 → `0644`, umask 002 → `0664`, umask 077 → `0600`; повторная запись не ужесточает. Новый файл кэша моделей — исключение (`0600`/`0700`, `atomic_file.py:242,250,293`), но это другой файл.
- **Влияние:** на машинах с проходимым `$HOME` и permissive-umask/общей группой другой пользователь прочитает метаданные провайдеров и внутренние адреса; запись в конфиг в связке с BAR-01/BAR-09 даёт больше. Defense-in-depth.
- **Рекомендация:** после создания `QSettings` выставлять `os.chmod(settings.fileName(), 0o600)` и при необходимости `0700` на каталог (в `try/except OSError`, no-op на Windows); сохранить инвариант «секреты никогда не пишутся в QSettings» и закрыть его тестом.

### BAR-11. `NoKeyringError` не обрабатывается

- **OWASP:** `Secrets_Management_Cheat_Sheet.md` §2.9; `Key_Management_Cheat_Sheet.md` → «Storage» (fallback в plaintext отсутствует — это хорошо). Top-10: A04, A10:2025.
- **Статус:** open, Low.
- **Место:** `security.py:7-25` (`get` на `:19`, `delete` на `:25`); `providers_card.py:30,132` (чтение keyring при конструировании карточки); `provider_dialog.py:47,180`.
- **Evidence:** при `keyring.set_keyring(fail.Keyring())` вызовы бросают `NoKeyringError`; реальный `App(...)` падает при старте — traceback через `security.py:19` из построения `ProvidersCard` (дефолтный `ollama`). В Flatpak доступ к `org.freedesktop.secrets` объявлен, поэтому проблема маловероятна.
- **Рекомендация:** обернуть вызовы в `try/except keyring.errors.KeyringError`, возвращать типизированный результат/`None`; при старте проверять `keyring.get_keyring()` и показывать неблокирующее предупреждение; не читать keyring в конструкторе `ProvidersCard`; в `delete()` ловить `KeyringError`. **Не** добавлять plaintext-fallback.

### BAR-12. Хрупкий SIGUSR1-fallback и обработка ошибок IPC

- **OWASP:** `Authorization_Cheat_Sheet.md` → «Deny by Default», «Exit Safely when Authorization Checks Fail»; `Logging_Cheat_Sheet.md`; `Error_Handling_Cheat_Sheet.md`. Top-10: A01, A09, A10:2025.
- **Статус:** open (changed), Low.
- **Место:** `ipc.py:25,31-32` (`assert` как проверка), `:76-80` (бывший bare `except` → `contextlib.suppress(BaseException)`), `:89` (**остался bare `except:`**), `:122-145` (перебор `psutil.process_iter`, `None.lower()` на `:134`, `os.kill` по имени на `:136`, `print` на `:137,141,144`), `:160-171` (занятое имя → необработанный `Exception` на `:165`), `:204` (`print`).
- **Evidence:** `proc.info['name']` может быть `None` → `AttributeError` в `barbaros --popup`. Сравнение только по имени и первый матч: процесс, назвавшийся `Barbaros`, может получить SIGUSR1 вместо приложения (default action SIGUSR1 = terminate). Занятие `SERVICE_NAME` другим процессом → `registerService` = False → `raise Exception('')` → падение при старте, fallback не срабатывает. `assert` исчезают под `python -O`.
- **Рекомендация:** убрать сканирование процессов; для single-instance использовать lock-файл в `$XDG_RUNTIME_DIR/app/<app-id>/` (`O_CREAT|O_EXCL`, 0600) и/или `AF_UNIX`-сокет с `SO_PEERCRED`; при fallback — `name = proc.info.get("name") or ""`, проверка uid/exe/cmdline; не падать на конфликте имени, а логировать и работать без D-Bus; `assert` → явные проверки; `except:` → конкретные исключения + `logging`; `print` → `logging`.

### BAR-13. Rich text из внешних имён и ответа LLM

- **OWASP:** `Cross_Site_Scripting_Prevention_Cheat_Sheet.md` → «Output Encoding», «Safe Sinks»; `Input_Validation_Cheat_Sheet.md` → «Validating Rich User Content»; `LLM_Prompt_Injection_Prevention_Cheat_Sheet.md` → «HTML and Markdown Injection». Top-10: A03, A05:2025.
- **Статус:** open, Low.
- **Место:** `filterable_combobox.py:70` (`display_label.setText(elided_text)`), `:358` (выбранная модель), tooltip `:72,361`; `providers_card.py:66,106,126,130,134` (`QLabel(text)`/`QLabel(name)`); `features/text.py:125` и `features/ocr.py:198,203` (`QTextEdit.setText(ответ LLM)`); промпт `resources/translation_agent_prompt.md` просит сохранять HTML. Новый источник: `model.id` из JSON-кэша (недоверенный файл, `MAX_MODEL_ID_LEN=1024`).
- **Evidence:** `QLabel`/`LinkLabel` по умолчанию `AutoText`; `QLabel('<img src="file://…"><h1>PWN</h1>…')` реально рендерится, локальный PNG грузится, `sizeHint` меняется (184×289 против 72×17). `QTextEdit.setText` тоже парсит HTML (`toHtml()` содержит `img`/`h1`). Ссылки **не кликабельны**, но **поправка:** это не из-за `LinkLabel` (в `link_label.py` нет `mousePressEvent`), а из-за переназначения `display_label.mousePressEvent = self.show_filterable_popup` (`filterable_combobox.py:50`); у read-only `QTextEdit` нет `LinksAccessibleByMouse`. Remote-картинки Qt не грузит.
- **Рекомендация:** для всех меток с внешними именами (`model.id`, `provider.name`, `api_base`, `provider_type`) — `setTextFormat(Qt.TextFormat.PlainText)`; tooltip тоже plain text; ответ LLM выводить через `setPlainText()` либо рендерить allowlist после `html.escape` (переносы, bold/italic; без `img/a/style`); согласовать с промптом отказ от «сохранять HTML».

### BAR-14. Нет лимитов и валидации ответа модели

- **OWASP:** `LLM_Prompt_Injection_Prevention_Cheat_Sheet.md` → «Input Validation and Sanitization», «Output Monitoring and Validation»; `File_Upload_Cheat_Sheet.md` → «Upload and Download Limits», «File Content Validation». Top-10: A04, A06:2025.
- **Статус:** open, Low.
- **Место:** `features/text.py:61-76,119-126`; `features/ocr.py:127-139,195-203`; `workers.py:69,102` (`acompletion` без `max_tokens`), `:90-96` (base64 без лимита); `image_manager.py:80-92,107-132` (PNG без ограничений).
- **Evidence:** `max_tokens` не передаётся. `QImageReader.allocationLimit()` = 256 МБ — только грубая защита Qt; PNG 8192×8192 весом 64 КиБ декодируется в 64 МиБ, после чего кодируется в base64 и уходит в запрос; downscale нет. `ChatCompletion(choices=[])` → `IndexError`; `content=None` → `TypeError` в `pop_think` — слот падает до `setText`, пользователь видит пустой результат без ошибки. Лимиты нового кэша к ответу LLM/изображению отношения не имеют.
- **Рекомендация:** лимиты на текст (например, 100–200 тыс. символов), изображение (≤20 Мп и ≤10 МБ после декодирования, downscale перед base64), `max_tokens`, таймауты; при превышении — понятная ошибка, а не отправка. Валидировать `resp.choices`, `content or ""`, `finish_reason`; тесты на пустой/None-ответ.

### BAR-15. Регрессия `process_translation_request`

- **OWASP:** `Secure_Code_Review_Cheat_Sheet.md`; `Authorization_Cheat_Sheet.md` → «Exit Safely when Authorization Checks Fail»; `Error_Handling_Cheat_Sheet.md`; `Logging_Cheat_Sheet.md`. Top-10: A04, A09, A10:2025.
- **Статус:** open, Low.
- **Место:** `main.py:50-59`; у `MainWindow` атрибутов `orig_text`/`translate_button` нет (они у `TextFeature`: `features/text.py:41,45`). В v2025.9.2 `MainWindow` их имел — регрессия появилась при рефакторинге.
- **Evidence:** живой запуск: `app.process_translation_request()` → `AttributeError: 'MainWindow' object has no attribute 'orig_text'`. D-Bus-вызов слота, который бросает исключение, возвращает клиенту **валидный ответ** (`void`), сервер печатает traceback и продолжает работу: сбой неотличим от успеха. В дереве нет тестов IPC (`tests/components/test_ipc.py` отсутствует, остался только `__pycache__`).
- **Влияние:** заявленный popup-перевод не работает; ошибка маскируется (вызывающий считает вызов успешным). Security-последствие: пока путь сломан, BAR-04 не эксплуатируется; при исправлении — включится, если не поменять дизайн.
- **Рекомендация:** вынести операцию в публичный метод `App`/`MainWindow` (например, `App.translate_from_text(text)`); D-Bus-метод должен возвращать явный статус/ошибку, а не `void`; добавить тест `process_translation_request` с подменённым clipboard и мок-провайдером.

### BAR-16. CI/supply-chain: отключённый workflow, отсутствие мониторинга, неподписанный bundle

- **OWASP:** `Software_Supply_Chain_Security_Cheat_Sheet.md` → «Harden Build Tools», «Enforce Code Signing», «Leverage Security Automation»; `CI_CD_Security_Cheat_Sheet.md`; `Vulnerable_Dependency_Management_Cheat_Sheet.md`. Top-10: A06:2021, A08:2021 / A03:2025.
- **Статус:** open, Low.
- **Место:** `.github/workflows/flatpak.yml.off`; `tasks.py:41` (pytest), `:46` (ruff), `:63` (ccache), `:71` (bundle без `--gpg-sign`); отсутствуют `SECURITY.md`, `.github/dependabot.yml`, pip-audit/renovate.
- **Evidence:** workflow отключён суффиксом `.off`, ссылается на несуществующий `flatpak/io.github.frimn.barbaros.yml`; actions — mutable major-теги (`actions/checkout@v4`, `actions/setup-python@v5`, `svenstaro/upload-release-action@v2`); `pip install build` без версии; `overwrite: true` для release-ассетов. Автоматической сборки/проверки нет.
- **Рекомендация:** включить workflow и исправить путь манифеста; пинить actions по полному SHA; пинить build-tools; подписывать bundle (`--gpg-sign`) и публиковать SHA256/SLSA-provenance; не перезаписывать release-ассеты; для релизных сборок — чистый эфемерный раннер без `--ccache`; Dependabot/Renovate + `pip-audit`/`uv audit` в `tasks.py` и CI; `SECURITY.md`.

### BAR-17. Логирование через `print()` (Info)

- **OWASP:** `Logging_Cheat_Sheet.md` → «Log Injection», «Data to exclude», «Event attributes». Top-10: A09.
- **Статус:** open (частично улучшено в новом коде), Info.
- **Место:** 22 `print()` в старых модулях: `ipc.py:137,141,144,204`; `main.py:27,74`; `main_window.py:53,207,216`; `model_manager.py:180,189,197,244`; `workers.py:123,138,141`; `features/ocr.py:99`; `features/settings.py:108`; `filterable_combobox.py:60,381,386,393`. Новые `model_cache.py`/`atomic_file.py` и часть `model_manager.py` используют `logging` с `%r`+truncate.
- **Evidence:** служебные сообщения без уровней/времени; имя провайдера из пользовательского ввода/конфига может содержать CR/LF (log injection). Содержимое буфера, OCR-текст, ответы LLM и ключи **не** печатаются — утечки нет. Новый код добавил `print` пути кэша (`main_window.py:53`): путь (имя пользователя, приватные каталоги) уходит в journald/терминал; `!r` экранирует CR/LF, поэтому log injection там закрыт. В Flatpak stdout уходит в journald.
- **Рекомендация:** `logging` вместо `print`, структурированные записи, `%r`/truncate для внешних строк, уровни, исключение недоверенных значений из шаблонов; путь кэша — `DEBUG`, не INFO; не логировать содержимое перевода/OCR/clipboard.

### BAR-18. Приватность: скриншот/clipboard уходят провайдеру без in-app уведомления (Info)

- **OWASP:** `User_Privacy_Protection_Cheat_Sheet.md` → «Honesty & Transparency»; `LLM_Prompt_Injection_Prevention_Cheat_Sheet.md` → «Multimodal Injection», «Data Exfiltration». Top-10: A04.
- **Статус:** open, Info.
- **Место:** `image_manager.py:63-70` (кроп по умолчанию = весь снимок), `:162-173` (`_take_screenshot` — весь экран), `:175-181`; `workers.py:90-96` (PNG → base64 → провайдер); `main.py:50-59` (clipboard → перевод); `README.md:33` (честное раскрытие, но не в UI).
- **Evidence:** по коду скриншот по умолчанию — весь экран, уведомлений/подтверждения перед отправкой нет; автоперевод из clipboard по IPC/`--popup` вызывается без явного действия пользователя в UI. Вредоносной телеметрии не найдено: сеть только через `any_llm` к настроенному провайдеру.
- **Рекомендация:** уведомление при первом запуске и при отправке («текст/изображение уходит в <provider> (<api_base>)»), предупреждение о полноэкранном захвате, локальный провайдер по умолчанию, возможность отключить автоперевод из clipboard, показ того, что именно отправляется (превью кропа уже есть).

---

## 4. Новые находки (BAR-19..BAR-27)

### BAR-19. `model_cache_path` — произвольный sink записи: замена/уничтожение чужого файла

- **OWASP:** `Secure_Code_Review_Cheat_Sheet.md` → «Injection Vulnerabilities» (unsafe file path construction), «Data Flow Analysis» (sink: file write); `Input_Validation_Cheat_Sheet.md` → «Parse Safely, Then Validate»; `Attack_Surface_Analysis_Cheat_Sheet.md`. Top-10: A04, A08 (CWE-73, CWE-15).
- **Severity:** Medium\* (см. сноску в §2).
- **Место:** `main_window.py:44-52` — путь из `QSettings` передаётся в `ModelCacheStore(path=...)`; `model_cache.py:51-100` (`cache_path_from_config`) — принимается любой абсолютный путь (`~`/`~user` раскрываются; относительные/нестроковые отвергаются); `atomic_file.py:283-312` (`_atomic_write`) — `parent.mkdir(...)`, `mkstemp`, `os.replace(temp, path)` без проверки, что `path` — файл кэша; `atomic_file.py:247-259` (`_tighten_directory`) — `os.chmod(directory, 0o700)` следует по симлинку (в проде только для default-пути, но `ModelCacheStore(path=..., tighten_directory=True)` — публичный API-футган).
- **Evidence (эксперименты):**
  1. Замена существующего файла: файл `0o644` с содержимым `IMPORTANT USER DATA` после `save()` стал `0o600` и содержит `{"version":1,"models":{…}}`; исходные данные потеряны. `cache_path_from_config('~/.bashrc')` → `~/.bashrc` (раскрыт в домашний каталог пользователя), `cache_path_from_config('/etc/passwd')` → `/etc/passwd`.
  2. Симлинк-цель на записи: `os.replace` заменяет саму ссылку, а не цель (хорошо). Симлинк-**родитель** + `tighten_directory=True`: запись уходит по ссылке в чужой каталог, а `chmod 0700` меняет режим чужого каталога (0755 → 0700).
  3. FIFO как цель: `save() == True`, специальный файл уничтожен (стал обычным JSON); `/dev/full` → `False`; каталог-цель → `False`; read-only каталог/ENOSPC/сбой `os.replace`/сбой сериализации → `False`, старый файл цел, temp удалён.
  4. Матрица `cache_path_from_config`: абсолютный/`~`/`~user` → `Path`; относительный/пустой/`file://`/не-строка/неизвестный `~user` → `None` (fail-safe); NUL-путь/перевод строки принимаются на этапе валидации и безопасно падают позже.
- **Сценарий:** конфиг Barbaros попадает на машину из dotfiles/бэкапа/другой установки либо правится скомпрометированным same-uid приложением; в нём `model_cache_path=<путь к чужому файлу>`. При первом же `set_models`/`remove` приложение атомарно заменяет указанный файл (или FIFO) содержимым кэша. «Случайная» версия: пользователь по ошибке указал существующий файл (README предупреждает, но предупреждение только в README, не в коде/UI).
- **Влияние:** безвозвратная потеря данных в произвольном user-writable файле, порча конфигов других приложений, уничтожение специальных файлов. RCE/утечки секретов нет: содержимое ограничено схемой кэша, файл `0600` (не executable), ключи/`api_base` не пишутся.
- **Рекомендация (KISS):**
  1. Перед первой записью: если `path` существует и (`path.is_symlink()` или не regular file или не парсится `ModelCacheDocument.from_bytes`) — отказаться (`WARNING`, `return False`), не удаляя файл. Это одна проверка поверх `read_regular_file_limited`; кэш регенерируем, чужой файл остаётся цел.
  2. `_tighten_directory`: не ходить по симлинкам (`os.chmod(..., follow_symlinks=False)` или не chmod-ить, если `directory.is_symlink()`); убрать `tighten_directory` из публичного API — store сам знает, резолвил ли он default-путь.
  3. В README/докстринге не обещать «указывайте файл кэша» — подкрепить guard'ом из п.1; явно написать, что `model_cache_path` — «путь, который приложение перезапишет».
  4. В UI давать предупреждение при нестандартном пути (или не выносить это в конфиг вовсе — YAGNI).
- **Тест:** `test_save_refuses_to_overwrite_non_cache_file` (существующий `.bashrc`/FIFO/симлинк → `save() is False`, файл байт-в-байт тот же, temp нет); `test_tighten_directory_does_not_follow_symlink`.

### BAR-20. DoS/подвисание: полный разбор кэша на каждого провайдера на старте

- **OWASP:** `Denial_of_Service_Cheat_Sheet.md` → «Input validation» («Prevent input based resource allocation», «Prevent input based function and threading interaction»); `Input_Validation_Cheat_Sheet.md` → «Parse Safely, Then Validate». Top-10: A04 (CWE-400, CWE-770).
- **Severity:** Low.
- **Место:** `main_window.py:62-64` — цикл `for provider in past_providers: add(p, cache_policy=RESTORE)`; число провайдеров из конфига ничем не ограничено (BAR-09). `model_manager.py:132-150` — `add(RESTORE)` вызывает `self._cache.load()` **на каждый вызов**, т.е. файл читается и парсится N раз; `model_manager.py:260-276,299-312` — `save()` (сериализация + `os.replace` + `fsync`) под `RLock` из GUI-потока.
- **Evidence (замеры):** один разбор 4 МиБ (1000 провайдеров, 77 000 записей) — 69 мс без tracemalloc (366 мс с ним), пик Python-памяти 32.6 МиБ (амплификация файла ~8–10×); 100 × `load()` 4 МиБ = **7.48 с**. Реальный `MainWindow.__init__` (offscreen, fake keyring), кэш 2.7 МиБ: 1 провайдер — 17.9 мс (пустой кэш), 3 провайдера — 145 мс, 20 — 1353 мс, 100 — **7221 мс**. `save` 4 МиБ ≈ 77–83 мс на tmpfs (на NFS/sshfs дороже).
- **Дополнительно:** `docs/model-cache-storage.md:37` («пишется из потока воркера») и `:47` («фактически она идёт в потоке воркера») внутренне противоречат `:154-155,167` того же документа и коду (`_FetchResultsDispatcher`, queued-соединение): после `e47ba99` и запись, и чтение идут в GUI-потоке. Обоснование «синхронная запись допустима, потому что в воркере» — устарело.
- **Сценарий:** конфиг с большим `llm_providers` (sync/бэкап/скомпрометированный same-uid — BAR-09) и валидным 4 МиБ кэшем (например, от поддельного endpoint) → старт блокируется на секунды-десятки секунд (GUI не отвечает, автозапуск из трея), либо UI замирает на reload/удаление провайдера на медленной ФС. Отдельного RCE нет.
- **Рекомендация (KISS):** грузить кэш **один раз** (`cached = store.load()` в `MainWindow` или `ModelManager.add_all(providers, cache_policy=RESTORE)`); ограничить число провайдеров из конфига (например, ≤50) и логировать отказ; исправить устаревшие абзацы документа; NFR-тест «100 провайдеров + 2 МиБ кэш → бюджет старта» (текущий `test_startup_with_25k_cached_models_is_not_much_slower` проверяет только 3 провайдера и умножение не видит).

### BAR-21. Кэш в общем каталоге читается без проверки владельца/прав (defense-in-depth)

- **OWASP:** `Input_Validation_Cheat_Sheet.md` → «Parse Safely, Then Validate»; `Attack_Surface_Analysis_Cheat_Sheet.md`. Top-10: A08, A02:2025 (CWE-345, CWE-732).
- **Severity:** Low (вне формальной модели «другой uid»; defense-in-depth).
- **Место:** `atomic_file.py:118-155` — у файла проверяются только `S_ISREG` и размер; `st_uid`/`st_gid`/биты записи (`0o022`) не проверяются. При этом `model_cache.py:299-305` и `docs/model-cache-storage.md` прямо допускают путь «в существующем shared-каталоге»; `main_window.py:51` отключает только chmod каталога.
- **Evidence:** в shared-каталоге `0777` запись создаётся `0600` (чужие учётки файл не прочитают/не изменят **после** первого сохранения). Но **до** первого сохранения файл в общем каталоге может создать/подменить другой пользователь или другое Flatpak-приложение с доступом к каталогу; приложение прочитает его без проверки владельца. Подмена кэша → подмена списка моделей в селекторе (строки `id`), далее BAR-13 (rich text), плюс ввод в заблуждение.
- **Рекомендация (KISS, одна проверка):** в `_read_capped` после `fstat`: если `info.st_uid != os.geteuid()` или `info.st_mode & 0o022` — `WARNING` и `return None`. Тест: «файл кэша с чужим uid/режимом 0666 игнорируется» (uid-ветку — через `mock.patch` на `os.geteuid`).

### BAR-22. Исключение в GUI-слоте после установки «загрузочного» состояния заклинивает вкладку

- **OWASP:** `Error_Handling_Cheat_Sheet.md` §Objective (ошибка не должна оставлять систему в неопределённом состоянии; fail-safe обработчик); `Denial_of_Service_Cheat_Sheet.md` §Application attacks → «Handle exceptions», «Threading»; `AI_Agent_Security_Cheat_Sheet.md` §8 (graceful failure). Top-10: A10:2025, в 2021 — A04 Insecure Design.
- **Severity:** Medium.
- **Место:** `features/text.py:69-76` — `translate()` сначала скрывает/disable Translate, показывает прогресс и Stop и только затем вызывает `_threaded_translate`; `:86-88` — `selected_item = self.parent.model.selected_item` / `model_manager[selected_item.provider]` (`AttributeError` при `None`, `KeyError` при удалённом провайдере); `workers.py:59,84,119` — создание клиента (`provider.client()` → `AnyLLM.create`) в GUI-потоке; `model_manager.py:43-53` — `MissingApiKeyError` для openai/anthropic без ключа; `features/ocr.py:120-125,141-147,166-172` — та же схема; `widgets/providers_card.py:74-75` → reload моделей без ключа.
- **Evidence (воспроизведено, offscreen, fake keyring):** нет выбранной модели → `AttributeError: 'NoneType' object has no attribute 'provider'`; после исключения: Translate `hidden=True, enabled=False`, прогресс виден, Stop виден; клик Stop → `AttributeError: 'TextFeature' object has no attribute 'worker'`; `handle_clear_button()` состояние не сбрасывает. Провайдер openai без ключа → `MissingApiKeyError`, состояние идентичное.
- **Сценарий:** свежая установка (дефолтный ollama, список моделей ещё не загружен): пользователь вставляет текст и жмёт «Translate» → вкладка навсегда в состоянии «переводит», Stop не работает; восстановление только перезапуском. Тот же путь — при удалённом провайдере/битом конфиге, в OCR-вкладке и при «Reload models» без ключа.
- **Влияние:** отказ в обслуживании функции (availability), противоречит AGENTS.md #14/#28; не конфиденциальность. Атакующий с правом записи конфига может воспроизводить гарантированно (провайдер без ключа), но путь достижим и без атакующего.
- **Рекомендация (KISS):** (1) валидировать предпосылки (`selected_item`, наличие провайдера, `provider.client()`) **до** смены UI — в `try` с показом ошибки и возвратом без disable/hide; (2) обернуть операцию в `try/finally`, где `finally` восстанавливает кнопки/прогресс (rollback UI), либо перенести создание клиента в `run_task` рабочего потока; (3) в `handle_stop_button` — `getattr(self, "worker", None)`; (4) `MissingApiKeyError`/`KeyringError` показывать как «задайте ключ провайдера», а не traceback.
- **Тест:** «translate без выбранной модели → кнопка снова доступна, прогресс скрыт, Stop не падает»; «fake keyring без ключа + openai → видимое сообщение, вкладка работоспособна»; «reload models без ключа → сообщение, нет traceback».

### BAR-23. `terminate()` + `wait()` без таймаута и отсутствие сетевых таймаутов

- **OWASP:** `Denial_of_Service_Cheat_Sheet.md` §Application attacks → «Handle exceptions», «Threading»; `Secure_AI_Model_Ops_Cheat_Sheet.md` §4 Inference API Security (limits/kill switches). Top-10: A10:2025 (2021: A04).
- **Severity:** Low.
- **Место:** `model_manager.py:185-201` — `stop_fetching_models`: `thread.terminate()` (`:198`) + `thread.wait()` **без аргумента** (`:199`); вызывается из `remove()` (`:152-157`), `shutdown()` (`:178-183`, по `aboutToQuit`), `_start_fetching_models` (`:218`). `workers.py:121-142` — синхронный `client.list_models()` без таймаута.
- **Evidence (воспроизведено):** поток в Python-цикле (типично для маршалинга `workers.py:128-136`): `terminate()` возвращается мгновенно, затем `wait(2000)` не вернулся за >20 с (процесс снят по timeout); Qt-документация `QThread::terminate()` предупреждает, что поток может не завершиться. Контроль: поток в C-`sleep(60)` завершается terminate за 0.001 с. Таймауты сети приложение не задаёт: у `AnyLLM` дефолт `Timeout(connect=5, read=600, write=600, pool=600)` — endpoint может держать чтение до 10 минут.
- **Сценарий:** скомпрометированный/поддельный endpoint отдаёт «медленный»/огромный список моделей; пользователь жмёт Reload/удаляет провайдера/закрывает приложение → GUI уходит в `wait()` и зависает (в вырожденном случае — неограниченно); при выходе приложение не закрывается.
- **Влияние:** доступность (зависание GUI, невозможность выйти), потенциально порча состояния интерпретатора из-за `terminate()` (Qt: «dangerous and its use is discouraged»).
- **Рекомендация:** не использовать `terminate()`: кооперативная отмена (`QThread.requestInterruption()` + флаг в цикле; для HTTP — asyncio-задача/таймаут), `wait(ms)` с таймаутом и логированием; явные connect/read/total таймауты и лимит размера ответа `list_models`; `shutdown()` не должен блокировать GUI дольше N мс.
- **Тест:** NFR «stop/shutdown при зависшем fake-провайдере возвращается < 2 с, приложение закрывается»; unit «wait вызывается с таймаутом».

### BAR-24. Неограниченный ответ `list_models` в GUI-потоке

- **OWASP:** `LLM_Prompt_Injection_Prevention_Cheat_Sheet.md` §Output Monitoring and Validation, §Input Validation and Sanitization; `AI_Agent_Security_Cheat_Sheet.md` §5 Output Validation & Guardrails; `Denial_of_Service_Cheat_Sheet.md` §Input validation. Top-10: A06:2025 (2021: A04).
- **Severity:** Low.
- **Место:** `workers.py:125-136` — `list_models()` + маршалинг всего списка без лимита; `model_manager.py:255-258` — `json.loads` + `Model.model_validate` для **всех** моделей в GUI-потоке (queued-слот `_FetchResultsDispatcher`, `model_manager.py:89-91`); `model_manager.py:260-276` — `_persist` (sanitize/encode) тоже в GUI-потоке; `widgets/filterable_combobox.py:233-253` — `QTreeWidgetItem` на каждую модель; лимит есть только у диска-кэша (`model_cache.py:307` `MAX_FILE_BYTES = 4 MiB`, `:157` `MAX_MODELS_PER_PROVIDER = 10_000`).
- **Evidence (замеры):** 20 000 моделей = 1.5 МБ, `json.loads`+`Model.model_validate` 0.066 с + `QTreeWidgetItem` 0.096 с; 100 000 моделей = 7.7 МБ, 0.330 + 0.309 = **0.64 с** только GUI-часть (1 млн ≈ 6.4 с и сотни МБ объектов, плюс столько же в worker-потоке). Размер ответа ограничен только памятью; `Model` создаётся **не** strict, лишние поля сохраняются.
- **Влияние:** DoS интерфейса/память в рамках модели угроз (endpoint недоверенный); в связке с BAR-23 усугубляется остановкой.
- **Рекомендация:** лимит на количество/длину элементов сразу после `list_models()` (те же константы, что в кэше: ≤10 000 моделей, `id` ≤1024), отбрасывать/усекать лишнее с сообщением; парсинг/валидацию и построение дерева — батчами или с проверкой размера до `json.loads`; явные лимиты completion — BAR-14.
- **Тест:** «endpoint вернул 100 001 модель → загружено ≤10 000, UI отвечает, в логе предупреждение»; NFR времени обработки 10 000 моделей.

### BAR-25. OCR `fail-open`: изображение уходит провайдеру после ошибки «не поддерживает изображения»

- **OWASP:** `LLM_Prompt_Injection_Prevention_Cheat_Sheet.md` §Multimodal Injection, §Data Exfiltration; `AI_Agent_Security_Cheat_Sheet.md` §8 Data Protection & Privacy; `Error_Handling_Cheat_Sheet.md` §Objective (fail-closed). Top-10: A10:2025 (2021: A04).
- **Severity:** Low.
- **Место:** `workers.py:86-106`:
  ```python
  if not self.client.SUPPORTS_COMPLETION_IMAGE:
      self.error.emit(f"Provider '{self.model.provider}' ... not supports images")
  # нет return
  try:
      ... base64_img ... acompletion(...)   # изображение всё равно отправляется
      self.done.emit(resp)
  ```
- **Evidence (воспроизведено, stub-клиент с `SUPPORTS_COMPLETION_IMAGE=False`):** один вызов `error` и один `done`; `acompletion called: 1 -> image sent despite unsupported: True`. `SUPPORTS_COMPLETION_IMAGE` читается вне `try` — отсутствие атрибута даст `AttributeError` в `run_task` без сигналов (тихий сбой/зависание прогресса).
- **Сценарий:** пользователь выбирает OCR-модель провайдера, который не поддерживает изображения (или неверно сконфигурированный endpoint): приложение сообщает об ошибке, но изображение всё равно уходит по сети.
- **Влияние:** передача данных вопреки заявленному поведению (privacy), непредсказуемые сигналы/UI; не RCE.
- **Рекомендация:** после `error.emit(...)` — сразу `return` (guard clause); проверку поддержки и наличие атрибута — внутри `try`; отправлять изображение только после успешной проверки; тест: неподдерживающий клиент → `acompletion` не вызван, ровно один `error`.

### BAR-26. `aboutToQuit.connect(cleanup)` внутри `save_language` — shutdown обычно не выполняется (Info)

- **OWASP:** `Error_Handling_Cheat_Sheet.md` §Objective. Top-10: A10:2025, A09:2025.
- **Место:** `main.py:43-48` (`save_language`) — единственная точка подключения `aboutToQuit`; `main.py:72-76` (`cleanup` → `ModelManager.shutdown`); `main.py:152-159` (`main()`).
- **Evidence (статика):** если пользователь не менял язык, `save_language()` не вызывается → `cleanup` не подключён; при выходе `ModelManager.shutdown()` не вызывается, QThread-воркеры/сеть остаются живыми до завершения интерпретатора (Qt: `QThread: Destroyed while thread is still running`); при каждом изменении языка подключение дублируется.
- **Влияние:** шум/потенциальный аварийный выход при завершении, незавершённые запросы; reliability/A10-гигиена, не уязвимость.
- **Рекомендация:** подключать `aboutToQuit` один раз в `App.__init__`; идемпотентный `cleanup`; тест «выход без смены языка → shutdown вызван».

### BAR-27. Гигиена документации и расхождение README с поведением (Info)

- **OWASP:** `User_Privacy_Protection_Cheat_Sheet.md` §Honesty & Transparency. Top-10: A09:2025 (информационная гигиена).
- **Место:** заголовок предыдущей версии этого отчёта (абсолютные пути и имя пользователя в публикуемом документе); `README.md:33` («Privacy-First»), `README.md:273` («Secure API calls»), при `common.py:62-77` разрешён `http://` (BAR-03) и уведомления о передаче нет (BAR-18).
- **Evidence:** `grep` по `docs/` публиковал локальные абсолютные пути; README утверждает «secure API calls», хотя выбранный пользователем `api_base` может быть `http://` (ключ и текст в cleartext), а скриншот/clipboard уходят без in-app уведомления.
- **Влияние:** info-leak окружения разработчика в публичном репозитории; вводящие в заблуждение заявления о приватности (юридический/репутационный риск). В модель угроз как уязвимость не входит — Info; усиливает BAR-03/BAR-18.
- **Рекомендация:** не публиковать абсолютные пути и имена пользователя в docs; в README заменить «Secure API calls» на «HTTPS по умолчанию; HTTP допустим только по явной настройке» и добавить строку, что изображение/буфер отправляются выбранному провайдеру. В этой версии отчёта абсолютные пути из заголовка уже убраны.

---

## 5. Что уже сделано хорошо

1. **API-ключи — в OS keyring**, не в конфиге/исходниках/логах; сервис неймспейснут (`barbaros:providers_api_keys`), имя провайдера — username; hardcoded-секретов в репозитории нет (`git grep` чист).
2. **`ProviderMeta` не сериализует ключ:** `api_key_manager` создаётся в `__post_init__` и не является dataclass-полем; `schema().dump()` даёт только `name/provider_type/api_base`; `from_dict` игнорирует лишние поля.
3. **UI маскирует секреты:** `EchoMode.Password`, в таблице/карточках — только `truncate_key` (≤4 последних символа); копирование из password-поля блокируется Qt (проверено).
4. **Валидатор URL отклоняет не-http(s) схемы и userinfo** (`javascript:`, `file:`, `user:pass@host` — False).
5. **Вставка в `CustomTextEdit` — обычно plain text** (`insertPlainText`): HTML/MIME из буфера не парсится. **Уточнение по итогам ре-проверки:** при HTML-only буфере (`hasText()==False`) Qt-фолбэк `insertFromMimeData` вставляет rich text — это тот же класс sink'а, что BAR-13 (JS не исполняется), а не отдельная уязвимость; рекомендация `setPlainText`/plain-text актуальна.
6. **Rich-text ссылки в `LinkLabel`/`QTextEdit` не кликабельны**; Qt rich text не исполняет JS и не загружает remote-картинки; `QImageReader.allocationLimit()=256MB` защищает от грубых decompression-bomb, `isNull()` корректно обрабатывается.
7. **IPC-поверхность минимальна:** только сессионный bus, один `void`-слот без аргументов/возврата; данные/ключи через D-Bus не ходят; `deleteLater` и прочие слоты `QObject` не экспортируются.
8. **Flatpak без `--filesystem=home`** и без `--device=all`; cleanup убирает тесты/`__pycache__`/webengine; `--talk-name=org.freedesktop.secrets` нужен для keyring.
9. **`uv.lock` с точными версиями и sha256** — хорошая база для исправления BAR-08.
10. **Нет телеметрии:** сеть только через `any_llm` к настроенному провайдеру; README раскрывает отправку облачным провайдерам.
11. **Новый кэш моделей — plain JSON, не pickle:** `json.loads` без `object_hook`, allowlist полей `id/created/object/owned_by`, лимит 4 МиБ до разбора, `ModelCacheDocument` не даёт лишним полям/секретам/`api_base` попасть в файл (подтверждено тестами и e2e).
12. **Файловая механика кэша безопасна по механике:** `O_NOFOLLOW` + `S_ISREG` (симлинк/FIFO/device/каталог не читаются, FIFO не блокирует), лимит `limit+1`, `0600`/`0700` независимо от umask, атомарный `os.replace`, старый файл цел при любой обработанной ошибке, temp удаляется.
13. **Fail-safe границы:** `load`/`save` не бросают исключений (кроме `BaseException`), битый/огромный/невалидный кэш не ломает старт, кэш не удаляется (остаётся для диагностики), конкурентные load/save не дают частичного файла.
14. **Логирование нового кода — `logging` с `%r` и усечением:** путь/имя провайдера не дают log injection, содержимое файла и ключи не логируются.
15. **Новый код не тянет новых зависимостей** (stdlib: `json`, `os`, `tempfile`, `threading`, `stat`, `logging`); `atomic_file` не импортирует Qt/keyring/any_llm (проверено AST-тестом).
16. **Тесты нового PR действительно проверяют безопасность:** symlink/FIFO/oversized/allowlist/права/fail-safe/секреты/log-injection; тесты честно фиксируют «BAR-01 не исправлен».

## 6. Проверено и не является уязвимостью

- **Path traversal через настройку `language`** (`i18n.load_translator`): обязательный префикс `barbaros_` делает первым компонентом пути литеральное имя (`barbaros_..`), таких каталогов нет; `lang="../../../etc/passwd"` → `None`. Не эксплуатируется (остаточное замечание: `language` не сверяется с `available_languages()`).
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
- **Новый кэш:** не вызывает pickle, не читает symlink/FIFO/device/каталог, не выходит за `limit+1`/4 МиБ, не пишет секреты/`api_base`, не создаёт провайдеров/клиентов/сетевых вызовов, не подменяет `api_base`/имя/тип провайдера, не удаляет битый файл, безопасен при ENOSPC/read-only/сбое `replace`/сериализации; гонки load/save не дают частичного файла; `tempfile`/`mkdir` не дают записи за пределы разрешённого механизмом (кроме BAR-19 path-override).
- **`cache_path_from_config`:** относительные/пустые/нестроковые/`file://`/`$HOME`-значения отвергаются, `~unknownuser`/NUL-путь не роняют приложение; запись в cwd не происходит.
- **Импортная гигиена:** `atomic_file` не импортирует Qt/keyring/any_llm/barbaros; новых рантайм-зависимостей нет.

## 7. Соответствие OWASP Top 10

### 7.1 OWASP Top 10:2021

| Категория | Применимость | Находки |
|---|---|---|
| A01 Broken Access Control | Да (локальный IPC) | BAR-04, BAR-12 |
| A02 Cryptographic Failures | Да (транспорт, секреты) | BAR-02, BAR-03 |
| A03 Injection | Да (HTML/rich text; prompt injection — без исполнения) | BAR-06, BAR-13 |
| A04 Insecure Design | Да | BAR-02, BAR-04, BAR-07, BAR-09, BAR-14, BAR-15, BAR-18, BAR-19, BAR-20, BAR-22, BAR-23, BAR-24, BAR-25 |
| A05 Security Misconfiguration | Да | BAR-05, BAR-09, BAR-10 |
| A06 Vulnerable and Outdated Components | Да | BAR-08, BAR-16 |
| A07 Identification and Authentication Failures | Нет (нет аккаунтов/сессий; аутентификация ОС/keyring) | — |
| A08 Software and Data Integrity Failures | Да | BAR-01, BAR-08, BAR-16, BAR-19, BAR-21 |
| A09 Security Logging and Monitoring Failures | Частично | BAR-12, BAR-15, BAR-17, BAR-26, BAR-27 |
| A10 Server-Side Request Forgery (SSRF) | Нет (клиентское приложение; URL задаёт пользователь) | — |

### 7.2 OWASP Top 10:2025 (актуальная редакция)

| Категория | Применимость | Находки |
|---|---|---|
| A01 Broken Access Control (вкл. SSRF) | Да (локальный IPC; SSRF — нет) | BAR-04, BAR-12 |
| A02 Security Misconfiguration | Да | BAR-05, BAR-09, BAR-10, BAR-21 |
| A03 Software Supply Chain Failures | Да | BAR-08, BAR-16 |
| A04 Cryptographic Failures | Да (транспорт, секреты) | BAR-02, BAR-03 |
| A05 Injection | Да (HTML/rich text) | BAR-06, BAR-13 |
| A06 Insecure Design | Да | BAR-02, BAR-04, BAR-07, BAR-14, BAR-15, BAR-18, BAR-19, BAR-20, BAR-22, BAR-23, BAR-24, BAR-25 |
| A07 Authentication Failures | Нет (нет аккаунтов/сессий) | — |
| A08 Software or Data Integrity Failures | Да | BAR-01, BAR-08, BAR-16, BAR-19, BAR-21 |
| A09 Security Logging & Alerting Failures | Частично | BAR-12, BAR-15, BAR-17, BAR-26, BAR-27 |
| A10 Mishandling of Exceptional Conditions | Да (fail-open, bare except, падение старта, маскировка ошибок) | BAR-09, BAR-11, BAR-12, BAR-15, BAR-22, BAR-23, BAR-25, BAR-26 |

## 8. Поправки к предыдущей версии отчёта

1. **BAR-04, способ вызова.** Утверждение прошлой версии «клиент с пустым именем интерфейса (`QDBusInterface(SERVICE_NAME, "/", "", bus)`) успешно вызывает метод» на HEAD/PySide6 6.11.1 неверно: такой `QDBusInterface` **невалиден**. Qt экспортирует интерфейс, производный от Python-класса (для приложения — `local.barbaros.ipc.IPCService`); вызов делается с этим именем или через `gdbus`. Факт отсутствия авторизации подтверждён.
2. **BAR-13, атрибуция некликабельности.** В `widgets/link_label.py` нет `mousePressEvent`; некликабельность обеспечивает присваивание `display_label.mousePressEvent` в `filterable_combobox.py:50`. Вывод верен, атрибуция исправлена.
3. **BAR-09, `api_base=123`.** `ProviderMeta.from_dict` через `dataclasses_json` приводит значение к строке (`123` → `"123"`), поэтому из конфига приложение стартует; `TypeError: object of type 'int' has no len()` воспроизводится только при прямом `ProviderMeta(..., api_base=123)`. Оценка находки не меняется: битый JSON/неизвестный `provider_type` по-прежнему роняют старт.
4. **BAR-12, bare `except`.** Один из двух заменён на `contextlib.suppress(BaseException)` (`ipc.py:76-80`); bare `except:` остался в `_handle_signal_from_socket` (`ipc.py:89`).
5. **BAR-01, первый триггер.** При штатном старте первый unpickle даёт чтение `target_language_list` (`main_window.py:188`), а не `model`/`llm_providers`; на вывод не влияет. Строки записи/чтения сдвинулись: `:119-120` и `:210-216`.
6. **BAR-17/18, строки.** `README.md:70` → `README.md:33`; `main_window.py:95` → `:53,207,216`; `ipc.py:142,146,149` → `:137,141,144`; `model_manager.py:121,129,173` → `:180,189,197,244`.
7. **Внутренняя документация.** `docs/model-cache-storage.md:16` цитирует устаревшие строки прошлого аудита (`main_window.py:105-106,200-206`); на HEAD это `:119-120,210-216`. Абзацы `docs/model-cache-storage.md:37,47` о записи «в потоке воркера» устарели (BAR-20).
8. **Неточность в разделе «Что уже сделано хорошо» #5.** Прошлая версия утверждала, что вставка в `CustomTextEdit` — всегда plain text. На HEAD обычный текст вставляется plain-text, но при HTML-only буфере Qt-фолбэк `insertFromMimeData` вставляет rich text (`<b>`/`<img src=file://…>` остаются в документе); JS не исполняется, в LLM уходит `toPlainText()`, поэтому это класс BAR-13, а не отдельная уязвимость.
9. **Абсолютные пути в публикуемом отчёте.** Прошлая версия содержала локальные абсолютные пути и имя пользователя (BAR-27); в этой версии они удалены, ссылки даны относительно корня проекта.

## 9. План исправлений

**P0 — до следующего релиза:**
1. **BAR-01:** убрать pickle из `QSettings` (JSON/два строковых ключа); миграция — санитизация сырого INI до первого обращения к `QSettings` либо полный переход на JSON-стор; тест на отсутствие `PyObjectWrapper` в конфиге и на невозможность unpickle при старте.
2. **BAR-02:** вызывать `api_key_manager.delete()` при удалении провайдера + явная очистка ключа в диалоге; обрабатывать `KeyringError`; тест с fake backend.
3. **BAR-06:** `QMessageBox` для ошибок — plain text; `url_to_html_links` переписать как `escape → linkify` или удалить.
4. **BAR-04/BAR-15:** IPC/`--popup` только фокусирует окно; перевод из clipboard — только по явному действию пользователя; D-Bus-метод возвращает явный статус; rate limit/проверка вызывающего; тест IPC.
5. **BAR-03:** HTTPS обязателен, кроме loopback; применить и при загрузке конфига.
6. **BAR-19:** guard «не заменять не-кэш-файл» перед первой записью; не chmod-ить через симлинк; ужесточить формулировки README.

**P1 — в ближайший цикл:**
7. **BAR-05:** убрать `--socket=session-bus` и неверный `--own-name`; проверить IPC в Flatpak.
8. **BAR-08:** hashed-requirements из `uv.lock` + `--require-hashes`; SBOM в релиз.
9. **BAR-07:** линейный парсер `<think>` + лимит ответа/`max_tokens`.
10. **BAR-09:** fail-safe загрузка конфига, валидация `api_base`/провайдеров, лимит числа провайдеров.
11. **BAR-12:** убрать сканирование процессов (lock-файл/сокет с `SO_PEERCRED`), явные исключения и логирование.
12. **BAR-20:** один `load()` кэша на старте; NFR-тест на 100 провайдеров; поправить `docs/model-cache-storage.md`.
13. **BAR-22:** валидировать предпосылки до смены UI + `try/finally` rollback кнопок; создание клиента — в рабочем потоке; `getattr` в Stop; понятные сообщения о ключе.
14. **BAR-23:** убрать `QThread.terminate()`, кооперативная отмена + `wait(ms)` с таймаутом, явные сетевые таймауты и лимит размера ответа.
15. **BAR-24:** лимит количества/длины моделей сразу после `list_models()` (те же константы, что в кэше); парсинг/построение дерева — не в одном GUI-шаге.
16. **BAR-25:** `return` после `error.emit`; проверка поддержки изображений внутри `try`; fail-closed.

**P2 — гигиена и defense-in-depth:**
17. **BAR-10:** `chmod 0600` на QSettings.
18. **BAR-11:** предупреждение при недоступном keyring, без plaintext-fallback.
19. **BAR-13/BAR-14:** plain-text для внешних имён и ответа LLM; лимиты текста/изображения/ответа; валидация `ChatCompletion`.
20. **BAR-16:** включить CI, пинить actions/build-tools, подписывать bundle, Dependabot/pip-audit, `SECURITY.md`.
21. **BAR-17/BAR-18:** `logging` без чувствительных данных; in-app уведомление о передаче данных провайдеру.
22. **BAR-21:** проверка `st_uid`/битов записи кэша (если shared-каталог остаётся поддерживаемым сценарием).
23. **BAR-26:** `aboutToQuit.connect(cleanup)` один раз в `App.__init__`; идемпотентный `cleanup`.
24. **BAR-27:** убрать абсолютные пути/имя пользователя из публикуемых docs; привести README к фактическому поведению (HTTPS по умолчанию, HTTP только по явной настройке, отправка изображения/буфера провайдеру).

**Организационно (AGENTS.md #27):** для PR ввести обязательный OWASP-проход по diff с меткой `security/owasp-passed` и комментарием-следом (какие читшиты проверялись, что найдено, вердикт); метку ставить только на финальный diff и снимать при новых security-коммитах. Сейчас CI/автоматической проверки нет (BAR-16).

## 10. Security-тесты, которые стоит добавить

1. `QSettings`-round-trip выбора модели не содержит pickle (`PyObjectWrapper`); санитизация/удаление легаси-конфига выполняется без вызова `QSettings.value/remove/setValue`; старт с подменённым INI не выполняет код.
2. Удаление провайдера и очистка ключа удаляют секрет из keyring (fake/in-memory backend); `NoKeyringError` не роняет старт.
3. `is_valid_url`/`api_base_problem`: `http` вне loopback отклоняется, `http://localhost` разрешён, `https` разрешён; конфиг с `http://evil` не загружается.
4. Битый/подменённый конфиг: приложение стартует с дефолтами, валидные провайдеры загружены; число провайдеров ограничено.
5. IPC: `popup_and_translate` не инициирует отправку без действия пользователя; метод возвращает статус; ошибка обработчика видна вызывающему.
6. Rich text: `model.id`/`provider.name` рендерятся как plain text; ошибка провайдера с HTML не создаёт ссылок/картинок.
7. `pop_think`: линейное время на большом ответе (нефункциональный тест), большой ответ усекается с сообщением.
8. `ChatCompletion(choices=[])` / `content=None`: пользователь видит ошибку, приложение не падает.
9. Лимиты на размер текста/изображения; `max_tokens` передаётся.
10. В логах/сериализованных провайдерах нет API-ключей.
11. **BAR-19:** `save()` отказывается заменять существующий не-кэш-файл (`.bashrc`, FIFO, симлинк) и не меняет его; `chmod` не идёт по симлинку.
12. **BAR-20:** NFR «100 провайдеров + 2 МиБ кэша → старт в бюджете»; кэш читается один раз.
13. **BAR-21:** файл кэша с чужим uid/режимом `0666` игнорируется с WARNING.
14. **BAR-22:** «translate без выбранной модели → кнопка снова доступна, прогресс скрыт, Stop не падает»; «openai без ключа → видимое сообщение, вкладка работоспособна»; «reload models без ключа → сообщение, нет traceback».
15. **BAR-23:** NFR «stop/shutdown при зависшем fake-провайдере возвращается < 2 с, приложение закрывается»; unit «wait вызывается с таймаутом».
16. **BAR-24:** «endpoint вернул 100 001 модель → загружено ≤10 000, UI отвечает, в логе предупреждение»; NFR времени обработки 10 000 моделей.
17. **BAR-25:** OCR с неподдерживающим изображения клиентом → `acompletion` не вызван, ровно один `error`.
18. **BAR-26:** «выход без смены языка → shutdown вызван»; **BAR-27:** в публикуемых docs/README нет абсолютных путей и заявлений, расходящихся с поведением.

## 11. Воспроизводимость и ограничения

**Ключевые эксперименты (все — на HEAD `1e3d17f`, изолированные XDG/HOME в temp, offscreen Qt, fake keyring):**
- **Pickle-RCE (BAR-01):** writer пишет `ModelSelection`/`Evil.__reduce__` через `QSettings`; затем вручную склеенная INI-строка с `@Variant(...PySide::PyObjectWrapper)` + pickle + payload `os.system("touch …")`; свежий процесс читает соседний ключ группы `main_window` → маркер создан. Матрица операций: `value/contains/allKeys/childKeys/remove` → выполнение; `fileName/status/sync`/другая группа → нет. Реальный `App(["x"])` → маркер до падения на `TrayIcon`.
- **D-Bus (BAR-04/12/15):** `dbus-run-session`, `IPCService(as_server=True, app=Stub)`; `gdbus introspect` → интерфейс `local.barbaros.ipc.IPCService`, метод `popup_and_translate()`; сторонний клиент → `ReplyMessage`, обработчик выполнен; исключение в слоте → клиенту `ReplyMessage` без error; второй сервер → `Exception('')` при `registerService`.
- **Qt rich text (BAR-06/13):** `QT_QPA_PLATFORM=offscreen`; инспекция `QMessageBox.findChildren(QLabel)` (`textFormat`, `openExternalLinks`), клик `QTest.mouseClick` → `QDesktopServices`; `<img src="file://…">` грузится в `QLabel`/`QMessageBox`/`QTextEdit`; remote-картинки не грузятся; ссылки в `LinkLabel`/`QTextEdit` не кликабельны.
- **Keyring (BAR-02/11):** fake/in-memory backend и `fail.Keyring`; отсутствие вызовов `delete()`; `NoKeyringError` на старте; plaintext-fallback отсутствует.
- **`pop_think` (BAR-07):** замеры `re.search` на `<think>`-повторениях без закрывающего тега (5–160 КБ) — квадратичный рост.
- **Конфиг (BAR-09):** битый JSON/неизвестный `provider_type` → падение старта; `api_base` int коэрцится в строку; `http://evil` из конфига принимается.
- **Кэш (BAR-19/20/21):** матрица `cache_path_from_config`; замена существующего файла/FIFO/symlink-цели; `chmod` сквозь symlink-родителя; отказ при read-only/ENOSPC/сбое replace с сохранением старого файла; symlink/FIFO/device/каталог не читаются, ровно `limit+1`; права `0600`/`0700` при umask 000/022/077; 100×`load()` 4 МиБ = 7.48 с; реальный `MainWindow` 3/20/100 провайдеров = 145/1353/7221 мс; 155 целевых тестов кэша passed.
- **GUI fail-open (BAR-22):** `TextFeature` на fake-parent (offscreen): нет выбранной модели → `AttributeError`, Translate скрыт/disabled, прогресс крутится, Stop падает; для openai без ключа — `MissingApiKeyError`, состояние то же; Clear не сбрасывает.
- **Потоки/сеть (BAR-23):** `QThread.terminate()` на Python-цикле → `wait(2000)` не вернулся >20 с; на C-`sleep(60)` — 0.001 с; у `AnyLLM` дефолтные таймауты `Timeout(connect=5, read=600, write=600, pool=600)`.
- **Размер `list_models` (BAR-24):** 20 000 моделей = 1.5 МБ, parse+validate+`QTreeWidgetItem` ≈ 0.16 с; 100 000 = 7.7 МБ / 0.64 с GUI; 1 млн — линейно ≈ 6.4 с.
- **OCR fail-open (BAR-25):** stub-клиент с `SUPPORTS_COMPLETION_IMAGE=False` → `error` и `done` одновременно, `acompletion` вызван один раз (изображение отправлено).
- **Exit/docs (BAR-26/27):** статическая проверка единственной точки `aboutToQuit.connect`; `grep` абсолютных путей в `docs/` и сверка README с `common.py:62-77`/BAR-18.

**Ограничения:** не выполнялись полная Flatpak-сборка/запуск, реальные операции с системным Secret Service, проверка на реальном X11/Wayland; не проводился SAST зависимостей (CVE) и фаззинг. Выводы по Flatpak основаны на манифесте и документации; выводы по keyring — на fake-бэкендах; выводы по общему каталогу (BAR-21) — на POSIX-семантике и коде (живой тест с другой учётной записью не проводился). Выводы по `QThread.terminate()`/`QTranslator` — на PySide6 6.11.1/Qt 6.11. Исходный код в ходе аудита не изменялся; полный набор тестов на HEAD — `345 passed`.
