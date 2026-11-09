# Barbaros — аудит безопасности по OWASP Cheat Sheet Series

- **Проект:** `/home/nik/code/my/barbaros`, HEAD `71197f8` (2026-11-03).
- **Предмет:** десктопное PySide6-приложение Barbaros: перевод текста и OCR через `any-llm-sdk`-провайдеров, системный трей, D-Bus/SIGUSR1 IPC, keyring для API-ключей, Flatpak-поставка.
- **Источник требований:** локальная копия OWASP Cheat Sheet Series — `/home/nik/code/CheatSheetSeries/cheatsheets` (ссылки ниже — на имена файлов и разделы).
- **Методика:** статический аудит потоков данных (`source → sink`), проверка чек-листов OWASP, эксперименты в `.venv` (PySide6 6.11.1, Python 3.11): offscreen-Qt, `dbus-run-session`, временный `XDG_CONFIG_HOME`, локальный fake OpenAI-совместимый endpoint, fake keyring-бэкенд. Исходный код не изменялся.
- **Модель угроз:** локальный процесс того же пользователя (в т.ч. скомпрометированное приложение/скрипт), Flatpak-приложение в рамках выданных ему разрешений, поддельный/скомпрометированный LLM-endpoint, подмена/синхронизация файла конфигурации, случайная утечка (бэкапы, скриншоты, логи). Вне модели: root, физический доступ, удалённый сетевой атакующий, полностью доверенный same-uid.
- **Границы:** не проводились динамический фаззинг, SAST-сканирование зависимостей (CVE), реальная сборка Flatpak и реальные операции с системным Secret Service; выводы по Flatpak/Secret Service основаны на манифесте, коде и документации.

## 1. Резюме

Найдено **18 проблем**: 1 High (условно), 7 Medium, 8 Low, 2 Info. Критических проблем, требующих немедленного отзыва ключей или релиза «вчера», не обнаружено; при этом одна находка (pickle-RCE) по формальным критериям OWASP относится к классу RCE и должна быть исправлена в первую очередь.

**Топ-3:**
1. **BAR-01 (High, A08):** выбор модели сохраняется в `QSettings` как Python-объект и сериализуется через **pickle**; подмена строки в INI-конфиге приводит к выполнению кода при следующем старте приложения. Подтверждено экспериментально.
2. **BAR-02 (Medium, A02/A04):** API-ключи не отзываются — `KeySecurityManager.delete()` не вызывается нигде; удаление провайдера оставляет ключ в keyring, а добавление нового провайдера с тем же именем может отправить старый ключ на новый `api_base`.
3. **BAR-04 (Medium, A01/A04):** D-Bus-метод `popup_and_translate` не проверяет вызывающего; любой процесс того же uid может заставить приложение прочитать буфер обмена и отправить текст выбранному (в т.ч. облачному) провайдеру. На HEAD путь сломан регрессией (BAR-15), т.е. риск латентный — но исправление регрессии «включит» его.

## 2. Сводная таблица

| ID | Severity | OWASP (cheat sheet / Top-10) | Находка | Ключевые места |
|---|---|---|---|---|
| BAR-01 | **High*** | Deserialization / A08:2021 | pickle-десериализация `ModelSelection` из `QSettings` → RCE при чтении подменённого конфига | `main_window.py:105-106,200-206`, `ocr.py:94-102` |
| BAR-02 | Medium | Secrets Management §2.7 / A02, A04 | Нет отзыва и очистки API-ключей; stale-ключ может уйти новому endpoint | `security.py:19-24`, `provider_dialog.py:47,111-113,229-232`, `model_manager.py:47` |
| BAR-03 | Medium | Transport Layer Security / A02 | `http://` разрешён для любого хоста → ключ и текст в cleartext | `common.py:66-77`, `provider_dialog.py:95-98`, `tests/test_common.py:6-16` |
| BAR-04 | Medium | Authorization / A01, A04 | D-Bus `popup_and_translate` без аутентификации вызывающего | `ipc.py:169-172,211-213`, `main.py:50-59` |
| BAR-05 | Medium | Attack Surface / A05 | Flatpak: полный `--socket=session-bus` + неверный `--own-name` | `flatpak/barbaros.yaml:21,23` |
| BAR-06 | Medium | XSS/Injection / A03 | HTML-инъекция из ошибки провайдера в `QMessageBox` (`AutoText`, `openExternalLinks=True`) | `main_window.py:76-87`, `common.py:89-93`, `text.py:131`, `ocr.py:213` |
| BAR-07 | Medium | Input Validation (Regex) / A04 | Квадратичный regex `pop_think` в GUI-потоке + нет лимита ответа → зависание UI | `features/text.py:104-110,119-126` |
| BAR-08 | Medium | Supply Chain / A06, A08 | Flatpak-зависимости не запинены и без хэшей; `uv.lock` в сборке не участвует | `flatpak/requirements-flatpak.txt:1-5`, `flatpak/barbaros.yaml:58` |
| BAR-09 | Low | Input Validation / A04, A05 | Конфиг — недоверенный вход: `api_base` не валидируется, битый JSON/тип роняет старт | `main_window.py:44-49,89-99`, `model_manager.py:23-29` |
| BAR-10 | Low | Key Management / A05 | Права QSettings-файла определяются umask (0664/0644); нет `0600` | `main.py:26-27` |
| BAR-11 | Low | Secrets Management §2.9 / A04 | `NoKeyringError` не обрабатывается: без Secret Service падение на старте | `security.py:11-24`, `providers_card.py:30,132` |
| BAR-12 | Low | Authorization/Logging / A04, A09 | Хрупкий SIGUSR1-fallback: `name=None` → краш, сигнал чужому процессу, `assert`/bare `except`/`print` | `ipc.py:127-150,24-31,77-90` |
| BAR-13 | Low | Output encoding / A03 | Rich text из внешних имён и ответа LLM (`QLabel`, `LinkLabel`, `QTextEdit.setText`) | `filterable_combobox.py:70,358`, `providers_card.py:66,106`, `text.py:125`, `ocr.py:198,203` |
| BAR-14 | Low | Input Validation / A04 | Нет лимитов на текст/изображение/ответ; невалидированный `ChatCompletion` (`choices=[]`, `content=None`) | `features/text.py:119-126`, `workers.py:69,102`, `image_manager.py:80-92` |
| BAR-15 | Low | Secure Code Review / A04, A09 | Регрессия `process_translation_request`: popup-перевод сломан, ошибка маскируется как успех | `main.py:50-59`, `main_window.py` (нет `orig_text`) |
| BAR-16 | Low | Supply Chain / A06, A08 | CI отключён, нет Dependabot/pip-audit/`SECURITY.md`, bundle не подписан | `.github/workflows/flatpak.yml.off`, `tasks.py:39-71` |
| BAR-17 | Info | Logging / A09 | Логирование через `print()`: нет структуры/экранирования; секреты не логируются | `workers.py:123,138,141`, `model_manager.py:121,129,173` |
| BAR-18 | Info | User Privacy / A04 | Скриншот (по умолчанию весь экран) и clipboard уходят провайдеру без in-app уведомления | `image_manager.py:162-173`, `main.py:50-59` |

\* BAR-01 — High по OWASP/CWE-502 (RCE), но для эксплуатации нужна запись в конфиг пользователя; при модели угроз «same-uid полностью доверенный» — Medium. Обоснование в разделе 3.

---

## 3. Детали находок

### BAR-01. pickle-десериализация `ModelSelection` из `QSettings` → RCE

- **OWASP:** `Deserialization_Cheat_Sheet.md` → «Python / Clear-box Review»: *«Unpickling can execute arbitrary code; never unpickle untrusted data»*; «Using Alternative Data Formats»; `Secure_Code_Review_Cheat_Sheet.md` → «Deserialization Vulnerabilities». Top-10: A08:2021 Software and Data Integrity Failures (CWE-502).
- **Место:**
  - запись: `src/barbaros/main_window.py:105-106` (`save_choosed_model` → `self.settings.setValue("model", selection)`); `src/barbaros/features/ocr.py:101-102` (`save_choosed_ocr_model`);
  - чтение: `src/barbaros/main_window.py:200-206` (`self.settings.value("model")`); `src/barbaros/features/ocr.py:94-99`;
  - тип: `src/barbaros/widgets/filterable_combobox.py:164-168` — `@dataclass class ModelSelection`.
- **Evidence (экспериментально):**
  - `QSettings` в PySide6 сериализует Python-объект через `PySide::PyObjectWrapper` с pickle protocol 4. Строка в INI выглядит как `model=@Variant(...PySide::PyObjectWrapper..., \x80\x04...)`; на машине аудита такие значения уже присутствуют в реальных конфигах native- и Flatpak-установки.
  - В отдельном процессе создан конфиг с `model`, содержащим pickle-payload (`os.system("touch …/PWNED")`), после чего **свежий** процесс, выполнивший только `settings.value("model")`, создал файл-маркер. Код выполнился до какой-либо проверки `isinstance` — проверка в `restore_model` стоит *после* десериализации и бесполезна.
  - **Уточнение (проверено на PySide6 6.11.1):** unpickle срабатывает не только при чтении самого pickled-ключа, но и при чтении **любого ключа из той же группы** (`main_window`/`ocr_feature`), а также при `remove()`, `setValue()`, `allKeys()`, `contains()`, `childKeys()` — эти операции загружают/перезаписывают группу или файл. Безопасны только `fileName()`, `sync()`, `status()` без предварительного чтения; `value(..., type=str)` **не** защищает. Практически это значит, что штатный старт приложения, читающий `main_window/llm_providers` из той же группы, что и `model`, уже запускает unpickle — отдельное чтение `model` не требуется.
- **Сценарий:** злоумышленник получает запись в `~/.config/io.github.frimn/barbaros.conf` (Flatpak: `~/.var/app/io.github.frimn.barbaros/config/...`) — например, вредоносное приложение с доступом к `$HOME`, синхронизация dotfiles/бэкап, восстановление чужого конфига, group-writable файл на shared-машине. При следующем запуске Barbaros (в т.ч. автозапуск из трея) выполняется произвольный код с правами пользователя. Payload персистентный — срабатывает при каждом чтении настройки.
- **Влияние:** локальное выполнение кода, персистентность, обход любых проверок формата; в Flatpak-сценарии — выход за пределы ожидаемого уровня доверия между приложениями.
- **Почему High\*:** по OWASP/CWE это RCE-класс. Практическая эксплуатация требует записи в конфиг; если считать «процесс того же uid» полностью доверенным, это Medium, потому что такой процесс и так может выполнить код. Но «запись файла → выполнение кода» — нежелательная цепочка (бэкапы/синхронизация/другие sandbox-приложения), поэтому в отчёте она помечена High с оговоркой.
- **Рекомендация (KISS):**
  1. Хранить выбор как данные: `settings.setValueAsJson("model_selection", {"provider": …, "model": …})` или два строковых ключа (`model_provider`, `model_name`). Чтение — через `valueFromJson`.
  2. **Не пытаться «прочитать/удалить» легаси-ключ через `QSettings`:** в PySide6 6.11.1 `remove()`, `setValue()`, `allKeys()`, `contains()` и чтение любого ключа из группы с pickled-значением уже вызывают unpickle. Миграция должна начинаться **до** первого обращения к `QSettings`: прочитать сырой INI-файл как текст (путь из `QStandardPaths`), при наличии `PyObjectWrapper`/`@Variant` — сохранить бэкап и удалить/санитизировать файл без разбора `QSettings`, затем стартовать с дефолтами. Бесшовный вариант — вообще заменить `QSettings` на собственный JSON-стор (см. ниже), а старый файл переименовать.
  3. Правило: в `QSettings.setValue` — только `str`/`int`/`bool`/`QByteArray` (геометрия `saveGeometry()` — корректный Qt-тип). Добавить проверку в ревью/линт.
  4. Тест: сохранение и чтение выбора без `pickle` (в файле конфига нет `PyObjectWrapper`); тест, что `restore_model` не падает на легаси-ключе.

### BAR-02. Неполный жизненный цикл API-ключей

- **OWASP:** `Secrets_Management_Cheat_Sheet.md` §2.7.3 «Revocation», §2.7.2 «Rotation», §2.6 «Auditing»; `Key_Management_Cheat_Sheet.md` → «Zeroization and Destruction». Top-10: A02, A04.
- **Место:** `src/barbaros/security.py:19-24` (`delete()` реализован), `src/barbaros/widgets/provider_dialog.py:47` (предзаполнение ключа), `:111-113` (запись только непустого), `:229-232` (удаление провайдера), `src/barbaros/model_manager.py:47` (чтение ключа для клиента), `model_manager.py:86-89` (`remove()`).
- **Evidence:** `KeySecurityManager.delete()` **не вызывается нигде** (`grep` по `delete_password|api_key_manager.delete` даёт только определение). Эксперимент с in-memory keyring: после `ModelManager.remove("audit-provider")` ключ остаётся доступным. Очистка поля ключа в диалоге редактирования + сохранение оставляет старый ключ в keyring (`get()` возвращает старое значение).
- **Сценарий:**
  1. Пользователь удаляет облачного провайдера, считая, что ключ отозван, — секрет остаётся в keyring пользователя (вне приложения).
  2. Пользователь переиспользует имя провайдера для нового аккаунта/локального шлюза, не вводя ключ: `ProviderClient.client()` возьмёт старый ключ и отправит его на новый `api_base` — облачный ключ уйдёт стороне, которой пользователь его не давал.
  3. Сменить endpoint, оставив провайдера, нельзя без перезаписи ключа: «пусто» трактуется как «оставить старый».
- **Рекомендация:** вызывать `api_key_manager.delete()` при удалении провайдера (после подтверждения), но **не** при `ModelManager.update()` (иначе редактирование сотрёт ключ). Добавить явную кнопку «Удалить сохранённый ключ» с подтверждением. В `delete()` ловить `keyring.errors.KeyringError`, а не только `PasswordDeleteError`. Тест с fake backend: «удалил провайдера / очистил ключ → в хранилище пусто».

### BAR-03. `http://` допускается для любого хоста → cleartext

- **OWASP:** `Secrets_Management_Cheat_Sheet.md` §2.8 «TLS Everywhere»: *«Never transmit secrets via plaintext»*; `Transport_Layer_Security_Cheat_Sheet.md` → «Use TLS For All Pages»: *«API-only endpoints should disable HTTP altogether…»*. Top-10: A02.
- **Место:** `src/barbaros/common.py:66-77` (`^https?://`), `src/barbaros/widgets/provider_dialog.py:95-98` (единственная проверка URL), `tests/test_common.py:6-16` (тесты закрепляют `http://google.com`, `http://192.168.0.1:1234` как валидные), `src/barbaros/model_manager.py:47` (URL уходит в `AnyLLM.create`).
- **Evidence:** `is_valid_url('http://evil.example.com') == True`, `is_valid_url('http://169.254.169.254/…') == True`. При custom OpenAI-совместимом endpoint `api_base` становится `base_url` httpx; в открытом виде уходят `Authorization: Bearer <ключ>` и весь переводимый текст. Для `api_base=None` any-llm использует HTTPS по умолчанию — проблема только при явном `http`-эндпоинте.
- **Рекомендация:** один helper (например, `api_base_problem(url)`) с `urllib.parse`: разрешать `https` для любых хостов; `http` — только `localhost`/`127.0.0.0/8`/`::1`; при не-loopback `http` — отказ (проще и предсказуемее, чем предупреждение). Применять его и в диалоге, и при загрузке из конфига (BAR-09). Обновить `tests/test_common.py`.

### BAR-04. D-Bus `popup_and_translate` без проверки вызывающего

- **OWASP:** `Authorization_Cheat_Sheet.md` → «Deny by Default», «Validate Permissions on Every Request», «Enforce Least Privileges»; `Attack_Surface_Analysis_Cheat_Sheet.md` → «Identifying and Mapping the Attack Surface»; `User_Privacy_Protection_Cheat_Sheet.md` → «Honesty & Transparency». Top-10: A01, A04.
- **Место:** `src/barbaros/ipc.py:12` (`SERVICE_NAME`), `:169-172` (`registerService` + `registerObject(..., ExportAllSlots)` на пути `/`), `:211-213` (`@Slot()` → `app.process_translation_request()`), `src/barbaros/main.py:50-59` (чтение clipboard + программный клик «Translate»).
- **Evidence:** экспериментально под `dbus-run-session` с минимальным аналогом адаптера: клиент с **пустым** именем интерфейса (`QDBusInterface(SERVICE_NAME, "/", "", bus)`) успешно вызывает метод; `gdbus introspect` показывает `popup_and_translate()`; никакой проверки PID/uid/имени вызывающего, токена, подтверждения или rate limit нет. Метод без аргументов и возврата — данных через D-Bus не передаётся, но действие чувствительное.
- **Сценарий:** любая программа того же пользователя (вне sandbox или Flatpak с разрешением на `talk-name=io.github.frimn.barbaros`) вызывает метод; либо просто запускает `barbaros --popup`. Запущенный экземпляр читает буфер обмена и отправляет текст облачному провайдеру без явного действия пользователя; повторные вызовы — платные API-запросы и перекрытие окна. Прямого канала «прочитать буфер атакующим» нет (метод `void`), но при подмене `api_base` (запись конфига) данные можно направить на свой endpoint.
- **Оговорка:** на HEAD `process_translation_request` падает с `AttributeError` до отправки (BAR-15), поэтому сейчас риск латентный; в v2025.9.2 цепочка работала. Исправление регрессии без изменения дизайна включит риск.
- **Рекомендация:** разделить «показать окно» и «перевести из буфера»: IPC/`--popup` должны только фокусировать окно; перевод из clipboard — только по явному действию пользователя в UI. Если автоперевод нужен — подтверждение в UI с указанием провайдера, rate limit/дедупликация, проверка вызывающего (`QDBusContext`/`GetConnectionUnixProcessID` + сверка `/proc/<pid>/exe`), узкий D-Bus-интерфейс вместо `ExportAllSlots` на `/`.

### BAR-05. Flatpak: полный `--socket=session-bus` и неверный `--own-name`

- **OWASP:** `Authorization_Cheat_Sheet.md` → «Enforce Least Privileges», «Deny by Default»; `Attack_Surface_Analysis_Cheat_Sheet.md` → сокращение поверхности. Top-10: A05.
- **Место:** `flatpak/barbaros.yaml:16-23`, `src/barbaros/ipc.py:12`.
- **Evidence:** `--socket=session-bus` отключает фильтрацию xdg-dbus-proxy и даёт приложению нефильтрованный доступ ко всей сессии (Flatpak docs называют это security risk, которое следует избегать). Строка `--own-name=org.frimn.barbaros` не совпадает с app-id/`SERVICE_NAME` `io.github.frimn.barbaros`; имя app-id разрешено по умолчанию, это разрешение лишнее и вводит в заблуждение. `--talk-name=org.freedesktop.secrets` нужен для keyring и сам по себе не даёт чужих секретов.
- **Влияние:** расширение blast radius при компрометации приложения (доступ к D-Bus-интерфейсам других приложений, имперсонация свободных имён); нарушение least privilege; потенциальные вопросы при ревью для Flathub. Прямой уязвимости без code execution нет.
- **Рекомендация:** убрать `--socket=session-bus`; оставить `--talk-name=org.freedesktop.secrets`; убрать `--own-name=org.frimn.barbaros` (при необходимости исправить на `io.github.frimn.barbaros`, но app-id namespace и так разрешён). Проверить IPC после изменения (`flatpak run --log-session-bus …`). `--share=ipc` и `--device=dri` — стандартные для X11/GL, не находка; `--filesystem=home` закомментирован — хорошо.

### BAR-06. HTML-инъекция из ошибки провайдера в `QMessageBox`

- **OWASP:** `Cross_Site_Scripting_Prevention_Cheat_Sheet.md` → «Output Encoding for HTML Contexts», «HTML Sanitization», «Safe Sinks»; `Injection_Prevention_Cheat_Sheet.md` → «Rule #3 (contextually escape)»; `LLM_Prompt_Injection_Prevention_Cheat_Sheet.md` → «HTML and Markdown Injection». Top-10: A03.
- **Место:** `src/barbaros/main_window.py:76-87` (`msg = url_to_html_links(msg)` → `QMessageBox.critical`), `src/barbaros/common.py:89-93` (`url_to_html_links` **без** `html.escape`), источники ошибок: `model_manager.py:181-182`, `workers.py:72-73,106`, `features/text.py:131`, `features/ocr.py:213`.
- **Evidence:** `QMessageBox` использует `Qt.TextFormat.AutoText` и рендерит HTML; метка текста имеет `openExternalLinks=True` (замер на PySide6 6.11.1). `<img src="file://…">` загружается, клик по `<a href="file://…">` приводит к `QDesktopServices`/`xdg-open`. Доставка недоверенного текста подтверждена локальным fake-endpoint: `any_llm` кладёт тело HTTP-ошибки в `str(exception)`, оно уходит в `error.emit(...)` и в `QMessageBox.critical` без экранирования. `url_to_html_links` ломает атрибут на кавычке и пропускает произвольные теги (нет escape/sanitize).
- **Влияние:** UI-spoofing в системном модальном окне (поддельный текст «ключ истёк, войдите заново»), фишинговая ссылка, открытие локальных `file://`-путей, отображение локальных картинок. JavaScript/команд не исполняется (Qt rich text без скриптов), но это тот же класс «untrusted data → HTML sink».
- **Рекомендация:** для ошибок — plain text: `box.setTextFormat(Qt.TextFormat.PlainText)` (или `setTextInteractionFlags` без ссылок), не использовать `url_to_html_links` для недоверенных сообщений. Если ссылки нужны — сначала `html.escape(text, quote=True)`, затем линкификация по экранированному тексту с экранированием URL в `href`; ограничить длину сообщения.

### BAR-07. Квадратичный `pop_think` regex в GUI-потоке

- **OWASP:** `Input_Validation_Cheat_Sheet.md` → «Regular Expressions (Regex)» (bound input length, avoid excessive backtracking); `LLM_Prompt_Injection_Prevention_Cheat_Sheet.md` → «Output Monitoring and Validation». Top-10: A04.
- **Место:** `src/barbaros/features/text.py:104-110` (`re.search(r"<think>.*?<\/think>", text, MULTILINE|DOTALL)`), вызов в GUI-слоте `:119-126`; нет `max_tokens`/лимита ответа (`workers.py:69,102`).
- **Evidence (замеры):** худший случай — строка из повторяющихся `<think>` без закрывающего тега; рост ~×4 на удвоение длины: 5 КБ — 16 мс, 10 КБ — 68 мс, 20 КБ — 292 мс, 40 КБ — 1.5 с, 80 КБ — 5.8 с, 160 КБ — 20.7 с (квадратично). Regex выполняется в главном потоке; 1 МБ ≈ 13 минут зависания UI. Дополнительно `text = text[len(think_text):]` режет не по позиции блока, а по его длине (логическая ошибка при `<think>` не в начале).
- **Влияние:** локальный DoS интерфейса: вредоносный/скомпрометированный провайдер, «болтливая» reasoning-модель или prompt injection могут вернуть большой ответ с `<think>`-маркерами. RCE нет.
- **Рекомендация:** заменить regex на линейный `str.find("<think>")`/`find("</think>")`; жёстко ограничить длину ответа до обработки (1–2 МБ) и reasoning; передавать `max_tokens` в `acompletion`; добавить не функциональный тест на время обработки большого ответа.

### BAR-08. Непинованные зависимости Flatpak / невоспроизводимая сборка

- **OWASP:** `Software_Supply_Chain_Security_Cheat_Sheet.md` → «Lockfile/Version Pinning», «Understand and Monitor Software Dependencies»; `Vulnerable_Dependency_Management_Cheat_Sheet.md` → «Tools». Top-10: A06, A08.
- **Место:** `flatpak/requirements-flatpak.txt:1-5`, `flatpak/barbaros.yaml:58` (`pip3 install -r requirements-flatpak.txt`), `pyproject.toml:22-30`; `uv.lock` в сборке Flatpak не используется.
- **Evidence:** в requirements нет версий и `--require-hashes`; сборка резолвит последние версии PyPI на момент сборки. `uv.lock` (≈150 пакетов, ≈1963 sha256-хэша) фиксирует только dev-окружение. `any-llm-sdk[all]` тянет SDK всех провайдеров — широкая транзитивная поверхность.
- **Влияние:** подмена/новая вредоносная версия зависимости попадает в релизный артефакт; сборка невоспроизводима; невозможно проверить соответствие артефакта проверенному lock-файлу.
- **Рекомендация:** генерировать hashed-requirements из `uv.lock` (`uv export --format requirements-txt --hashes` / `uv pip compile --generate-hashes`) и ставить `pip3 install --require-hashes -r …`; собирать wheel в CI из зафиксированного lock; добавить SBOM (`uv export`/Syft).

### BAR-09. Конфиг как недоверенный вход: нет валидации и fail-safe старта

- **OWASP:** `Input_Validation_Cheat_Sheet.md` → «Parse Safely, Then Validate»; `Secure_Code_Review_Cheat_Sheet.md` → «Configuration & Deployment». Top-10: A04, A05.
- **Место:** `src/barbaros/common.py:20-24` (`valueFromJson` → `json.loads` без обработки ошибок), `src/barbaros/main_window.py:44-49` (`ProviderMeta.from_dict` в цикле), `:89-99` (кэш моделей), `src/barbaros/model_manager.py:23-29`; `restore_target_languages` (`main_window.py:176-181`).
- **Evidence:** `ProviderMeta.from_dict({"name":"x","provider_type":"ollama","api_base":"http://evil.example.com"})` принимается без проверки; `api_base=123` тоже принимается (позже `len(int)` падает при построении карточки); неизвестный `provider_type` → `ValueError`; обрезанный JSON → `JSONDecodeError`. Всё это — в `MainWindow.__init__`, т.е. приложение не стартует.
- **Влияние:** подмена конфига перенаправляет ключ/текст на чужой `api_base`; повреждённый конфиг (после некорректного завершения/заполнения диска) вызывает цикл падений при автозапуске — противоречит AGENTS.md п.14 («приложение должно падать и подниматься»).
- **Рекомендация:** обернуть загрузку в `try/except (json.JSONDecodeError, ValueError, TypeError)`: логировать, удалять проблемный ключ, стартовать с `default_providers`; валидировать `api_base` (`str | None` + BAR-03 helper), `name`, `language`, `target_language_list`; проверять `QSettings.status()`. Тест: битый конфиг → приложение стартует, валидные провайдеры загружены.

### BAR-10. Права файла настроек по umask

- **OWASP:** `Key_Management_Cheat_Sheet.md` → «Storage»; `Logging_Cheat_Sheet.md` → «Data to exclude» (внутренние адреса/имена). Top-10: A05.
- **Место:** `src/barbaros/main.py:26-27`; в `src/` нет `chmod`/`umask`.
- **Evidence:** режим `QSettings`-файла = `0666 & ~umask`: наблюдалось `0644` при umask 022 и `0664` при umask 002; повторная запись не ужесточает. На машине аудита файл `0664`, каталог `0775`, но `$HOME` — `0700`, что блокирует доступ. Секретов в конфиге нет (ключи — в keyring), но есть полные `api_base`, имена и кэш моделей.
- **Влияние:** на машинах с проходимым `$HOME` и permissive-umask/общей группой другой пользователь прочитает метаданные провайдеров и внутренние адреса; запись в конфиг в связке с BAR-09/BAR-01 даёт больше. Defense-in-depth.
- **Рекомендация:** после создания `QSettings` выставлять `os.chmod(settings.fileName(), 0o600)` и при необходимости `0700` на каталог (в `try/except OSError`, no-op на Windows); сохранить инвариант «секреты никогда не пишутся в QSettings» и закрыть его тестом.

### BAR-11. `NoKeyringError` не обрабатывается

- **OWASP:** `Secrets_Management_Cheat_Sheet.md` §2.9 «Downtime, Break-glass, Backup and Restore»; `Key_Management_Cheat_Sheet.md` → «Storage» (fallback в plaintext отсутствует — это хорошо). Top-10: A04.
- **Место:** `src/barbaros/security.py:11-24`, `src/barbaros/widgets/providers_card.py:30,132` (чтение keyring при конструировании карточки), `provider_dialog.py:113,180`.
- **Evidence:** без рабочего Secret Service `keyring.get_keyring()` возвращает `fail.Keyring`, вызовы бросают `NoKeyringError`. С fake `fail.Keyring` конструирование `ProvidersCard` упало — приложение не стартует даже без настроенных провайдеров (из-за дефолтного `ollama`). В Flatpak доступ к `org.freedesktop.secrets` объявлен, поэтому проблема маловероятна.
- **Влияние:** на минимальных окружениях (WM без gnome-keyring/KWallet, сломанный Secret Service) — падение при старте или молчаливое несохранение ключа. Утечки нет: fallback в plaintext не происходит.
- **Рекомендация:** обернуть вызовы в `try/except keyring.errors.KeyringError`, возвращать типизированный результат/`None`; при старте проверить `keyring.get_keyring()` и показать неблокирующее предупреждение; не читать keyring в конструкторе `ProvidersCard`; в `delete()` ловить `KeyringError`. **Не** добавлять plaintext-fallback.

### BAR-12. Хрупкий SIGUSR1-fallback и обработка ошибок IPC

- **OWASP:** `Authorization_Cheat_Sheet.md` → «Deny by Default», «Exit Safely when Authorization Checks Fail»; `Attack_Surface_Analysis_Cheat_Sheet.md`; `Logging_Cheat_Sheet.md` → «Event collection». Top-10: A04, A09.
- **Место:** `src/barbaros/ipc.py:127-150` (перебор `psutil.process_iter`, `os.kill` по имени), `:48,67-68,100-106` (обработчик любого SIGUSR1), `:24-31` (`assert` как проверка), `:77-90` (bare `except:`), `:142,146,149` и `main.py:27` (`print`); `ipc.py:169-170` (занятое имя → необработанный `Exception`, fallback только при отсутствии bus).
- **Evidence:** `proc.info['name']` может быть `None` (psutil `ad_value=None` при `AccessDenied`/`ZombieProcess`) → `None.lower()` → `AttributeError` в `barbaros --popup`. Сравнение только по имени и первый матч (сортировка по PID): процесс, назвавшийся `barbaros`, может получить SIGUSR1 вместо приложения — default action SIGUSR1 = terminate. Занятие имени `io.github.frimn.barbaros` другим процессом → `registerService` = False → падение при старте (DoS), fallback не срабатывает. `assert` исчезают под `python -O`.
- **Влияние:** доступность popup/приложения, потенциальное завершение чужого процесса с именем `barbaros`, отсутствие диагностируемых логов. RCE нет: сигнал фиксирован, данных нет.
- **Рекомендация:** убрать сканирование процессов; для single-instance использовать lock-файл в `$XDG_RUNTIME_DIR/app/<app-id>/` (`O_CREAT|O_EXCL`, 0600) и/или `AF_UNIX`-сокет с `SO_PEERCRED`; при fallback — `name = proc.info.get("name") or ""`, проверка uid/exe/cmdline; не падать на конфликте имени, а логировать и работать без D-Bus; `assert` → явные проверки; `except:` → конкретные исключения + `logging`; `print` → `logging`.

### BAR-13. Rich text из внешних имён и ответа LLM

- **OWASP:** `Cross_Site_Scripting_Prevention_Cheat_Sheet.md` → «Output Encoding», «Safe Sinks»; `Input_Validation_Cheat_Sheet.md` → «Validating Rich User Content»; `LLM_Prompt_Injection_Prevention_Cheat_Sheet.md` → «HTML and Markdown Injection». Top-10: A03.
- **Место:** `filterable_combobox.py:70` (`display_label.setText(elided_text)`), `:358` (выбранная модель), `providers_card.py:66,106` (`QLabel(text)`/`QLabel(name)`), `text.py:125` и `ocr.py:198,203` (`QTextEdit.setText(ответ LLM)`); промпт `resources/translation_agent_prompt.md:36` прямо просит сохранять HTML.
- **Evidence:** `QLabel`/`LinkLabel` по умолчанию `AutoText`; id модели с разметкой (`<img src="file://…">`, 80pt-текст) рендерится как rich text, локальные PNG загружаются. `QTextEdit.setText` тоже парсит HTML. Ссылки при этом **не кликабельны** (`LinkLabel` переопределяет `mousePressEvent`, у read-only `QTextEdit` нет `LinksAccessibleByMouse`), remote-картинки Qt не грузит — поэтому Low, а не Medium.
- **Влияние:** визуальный спуфинг/искажение UI, отображение локальных изображений, раздувание виджетов; возможен поддельный «перевод» при HTML в ответе модели. Кода/ссылок нет.
- **Рекомендация:** для всех меток с внешними именами (`model.id`, `provider.name`, `api_base`, `provider_type`) — `setTextFormat(Qt.TextFormat.PlainText)`; tooltip тоже plain text; ответ LLM выводить через `setPlainText()` либо рендерить allowlist после `html.escape` (переносы, bold/italic; без `img/a/style`); согласовать с промптом отказ от «сохранять HTML».

### BAR-14. Нет лимитов и валидации ответа модели

- **OWASP:** `LLM_Prompt_Injection_Prevention_Cheat_Sheet.md` → «Input Validation and Sanitization» («limit input length»), «Output Monitoring and Validation»; `File_Upload_Cheat_Sheet.md` → «Upload and Download Limits», «File Content Validation». Top-10: A04.
- **Место:** `features/text.py:61-76`, `features/ocr.py:127-139` (весь текст без лимита), `workers.py:69,102` (`acompletion` без `max_tokens`), `image_manager.py:80-92,107-132` (PNG без ограничений), `workers.py:90-96` (base64); `text.py:119-126`, `ocr.py:195-203` (`resp.choices[0]` / `content` без валидации).
- **Evidence:** `max_tokens` не передаётся; Qt ограничивает декодирование 256 МБ (`QImageReader.allocationLimit()`), но PNG 8192×8192 весом 64 КиБ декодируется в 64 МиБ, после чего кодируется в base64 и уходит в запрос; `ChatCompletion(choices=[])` → `IndexError`, `content=None` → `AttributeError`, слот падает до `setText` — пользователь видит пустой результат без ошибки.
- **Влияние:** пики памяти/сеть/стоимость у платного провайдера, длинная блокировка UI, тихие сбои при нестандартном ответе. Не RCE.
- **Рекомендация:** лимиты на текст (например, 100–200 тыс. символов), изображение (≤20 Мп и ≤10 МБ после декодирования, downscale перед base64), `max_tokens`, таймауты; при превышении — понятная ошибка, а не отправка. Валидировать `resp.choices`, `content or ""`, `finish_reason`; тесты на пустой/None-ответ.

### BAR-15. Регрессия `process_translation_request`

- **OWASP:** `Secure_Code_Review_Cheat_Sheet.md`; `Authorization_Cheat_Sheet.md` → «Exit Safely when Authorization Checks Fail»; `Logging_Cheat_Sheet.md` → «Event collection». Top-10: A04, A09.
- **Место:** `src/barbaros/main.py:50-59`; `src/barbaros/main_window.py` — атрибутов `orig_text`/`translate_button` нет (они у `TextFeature`: `features/text.py:41,45`). В v2025.9.2 `MainWindow` их имел (`git show v2025.9.2:src/barbaros/main_window.py`), регрессия появилась при рефакторинге.
- **Evidence:** D-Bus-вызов слота, который бросает исключение, возвращает клиенту **валидный ответ** (`void`), сервер печатает traceback и продолжает работу: сбой обработчика неотличим от успеха. В дереве нет тестов IPC (`tests/components/test_ipc.py` отсутствует, остался только `__pycache__`).
- **Влияние:** заявленный popup-перевод не работает; ошибка маскируется (вызывающий считает вызов успешным). Security-последствие: пока путь сломан, BAR-04 не эксплуатируется; при исправлении — включится, если не поменять дизайн.
- **Рекомендация:** вынести операцию в публичный метод `App`/`MainWindow` (например, `App.translate_from_text(text)`), не лазить в виджеты через `MainWindow`; D-Bus-метод должен возвращать явный статус/ошибку, а не `void`; добавить тест `process_translation_request` с подменённым clipboard и мок-провайдером.

### BAR-16. CI/supply-chain: отключённый workflow, отсутствие мониторинга, неподписанный bundle

- **OWASP:** `Software_Supply_Chain_Security_Cheat_Sheet.md` → «Harden Build Tools», «Enforce Code Signing», «Leverage Security Automation», «Monitor Deployed Software for Vulnerabilities»; `Vulnerable_Dependency_Management_Cheat_Sheet.md` → «Responsible disclosure», «Tools». Top-10: A06, A08.
- **Место:** `.github/` (только `workflows/flatpak.yml.off`), `tasks.py:39-46` (только pytest/ruff), `tasks.py:63,71` (ccache, bundle без `--gpg-sign`); отсутствуют `SECURITY.md`, `.github/dependabot.yml`, конфигурация pip-audit/renovate.
- **Evidence:** workflow отключён суффиксом `.off`, ссылается на несуществующий `flatpak/io.github.frimn.barbaros.yml`; actions — mutable major-теги (`actions/checkout@v4`, `actions/setup-python@v5`, `svenstaro/upload-release-action@v2`); `pip install build` без версии; `flatpak build-bundle` без подписи; `overwrite: true` для release-ассетов. Автоматической сборки/проверки нет.
- **Влияние:** нет обнаружения CVE в зависимостях и канала ответственного раскрытия; пользователь не может проверить целостность `.flatpak`; компрометация CI/подмена релиза.
- **Рекомендация:** включить workflow и исправить путь манифеста; пинить actions по полному SHA; пинить build-tools; подписывать bundle (`--gpg-sign`) и публиковать SHA256/SLSA-provenance; не перезаписывать release-ассеты; для релизных сборок — чистый эфемерный раннер без `--ccache`; Dependabot/Renovate + `pip-audit`/`uv audit` в `tasks.py` и CI; `SECURITY.md`.

### BAR-17. Логирование через `print()` (Info)

- **OWASP:** `Logging_Cheat_Sheet.md` → «Log Injection», «Data to exclude», «Event attributes». Top-10: A09.
- **Место:** `workers.py:123,138,141`; `model_manager.py:121,129,173`; `main_window.py:95`; `features/settings.py:108`; `main.py:27`; `ipc.py:142,146,149`.
- **Evidence:** `print()` без структуры и экранирования; имя провайдера из пользовательского ввода/конфига может содержать CR/LF (log injection), служебные сообщения без уровней/времени. Содержимое буфера, OCR-текст, ответы LLM и ключи **не** печатаются — утечки нет. В Flatpak stdout уходит в journald.
- **Влияние:** низкая наблюдаемость инцидентов, возможность подделки локальных логов; не самостоятельная уязвимость.
- **Рекомендация:** `logging` вместо `print`, структурированные записи, `%r`/truncate для внешних строк, уровни, исключение недоверенных значений из шаблонов; не логировать содержимое перевода/OCR/clipboard.

### BAR-18. Приватность: скриншот/clipboard уходят провайдеру без in-app уведомления (Info)

- **OWASP:** `User_Privacy_Protection_Cheat_Sheet.md` → «Honesty & Transparency»; `LLM_Prompt_Injection_Prevention_Cheat_Sheet.md` → «Multimodal Injection», «Data Exfiltration». Top-10: A04.
- **Место:** `image_manager.py:162-173` (`_take_screenshot` — весь экран; кроп по умолчанию = весь снимок), `:80-92` + `workers.py:90-96` (PNG → base64 → провайдер), `main.py:50-59` (clipboard → перевод).
- **Evidence:** по коду скриншот по умолчанию — весь экран, уведомления/подтверждения перед отправкой нет; README честно описывает отправку облачным провайдерам (`README.md:70`), но в UI этого нет. Вредоносной телеметрии не найдено: сеть только через `any_llm` к настроенному провайдеру.
- **Влияние:** непреднамеренная передача персональных данных/секретов третьей стороне (скриншот с открытым менеджером паролей, скопированный секрет); юридические/приватностные последствия.
- **Рекомендация:** уведомление при первом запуске и при отправке («текст/изображение уходит в <provider> (<api_base>)»), предупреждение о полноэкранном захвате, локальный провайдер по умолчанию, возможность отключить автоперевод из clipboard, показ того, что именно отправляется (превью кропа уже есть).

---

## 4. Что уже сделано хорошо

1. **API-ключи — в OS keyring**, не в конфиге/исходниках/логах; сервис неймспейснут (`barbaros:providers_api_keys`), имя провайдера — username; hardcoded-секретов в репозитории нет (`git grep` чист).
2. **`ProviderMeta` не сериализует ключ:** `api_key_manager` создаётся в `__post_init__` и не является dataclass-полем; `schema().dump()` даёт только `name/provider_type/api_base`; `from_dict` игнорирует лишние поля.
3. **UI маскирует секреты:** `EchoMode.Password`, в таблице/карточках — только `truncate_key` (≤4 последних символа); копирование из password-поля блокируется Qt (проверено).
4. **Валидатор URL отклоняет не-http(s) схемы и userinfo** (`javascript:`, `file:`, `user:pass@host` — False).
5. **Вставка в `CustomTextEdit` — plain text** (`insertPlainText`): HTML/MIME из буфера не парсится.
6. **Rich-text ссылки в `LinkLabel`/`QTextEdit` не кликабельны**; Qt rich text не исполняет JS и не загружает remote-картинки (проверено); `QImageReader.allocationLimit()=256MB` защищает от грубых decompression-bomb, `isNull()` корректно обрабатывается.
7. **IPC-поверхность минимальна:** только сессионный bus, один `void`-слот без аргументов/возврата; данные/ключи через D-Bus не ходят; `deleteLater` и прочие слоты `QObject` не экспортируются.
8. **Flatpak без `--filesystem=home`** и без `--device=all`; cleanup убирает тесты/`__pycache__`/webengine; `--talk-name=org.freedesktop.secrets` нужен для keyring.
9. **`uv.lock` с точными версиями и sha256** — хорошая база для исправления BAR-08.
10. **Нет телеметрии:** сеть только через `any_llm` к настроенному провайдеру; README раскрывает отправку облачным провайдерам (часть `User_Privacy_Protection` → «Honesty & Transparency»).

## 5. Проверено и не является уязвимостью

- **Path traversal через настройку `language`** (`i18n.load_translator`): обязательный префикс `barbaros_` делает первым компонентом пути литеральное имя (`barbaros_..`), таких каталогов нет; `lang="../../../etc/passwd"` → `None`, абсолютный `lang` даёт относительный путь. Не эксплуатируется (остаточное замечание: `language` не сверяется с `available_languages()`).
- **RCE/десериализация через D-Bus:** метод без аргументов и возврата; `deleteLater` не экспортируется (проверено); данных нет.
- **Подмена D-Bus-сервиса:** сквоттер получает только `void`-вызов; максимум — DoS/имитация успеха, не утечка.
- **Flatpak-приложение без `--talk-name=io.github.frimn.barbaros`** не может вызвать Barbaros; `--socket=session-bus` у *вызывающего* — отдельное разрешение.
- **SIGUSR1:** фиксированный номер сигнала, нет payload; RCE/повреждения памяти нет; максимум — вызов IPC-пути или завершение процесса с именем `barbaros`.
- **Командные/SQL/NoSQL/OS-инъекции:** в `src/barbaros` нет `subprocess`, `os.system`, `eval`/`exec`, unsafe YAML/pickle-импортов; `tasks.py`-команды — build-time, не runtime.
- **SSRF:** URL провайдера выбирает пользователь, серверной стороны нет; link-local адреса в валидаторе — слабость (BAR-03), но без подмены конфига самостоятельной эксплуатации нет.
- **Qt rich text XSS:** JavaScript/обработчики событий не исполняются; remote `http(s)`-картинки не загружаются; клики в `LinkLabel`/`QTextEdit` не открывают ссылки (проблема только у `QMessageBox`, BAR-06).
- **Секреты в конфиге/логах/репозитории:** не обнаружены (ключи — в keyring; `print` без ключей; `git grep` секрет-паттернов чист).
- **Plaintext-fallback keyring:** отсутствует; без backend — fail-closed (`NoKeyringError`), а не запись в файл.
- **`--share=ipc`:** стандартное разрешение для X11/MIT-SHM, находкой не является.
- **Расхождение `--own-name` ↔ `SERVICE_NAME`:** не ломает IPC (app-id namespace разрешён по умолчанию), это лишнее/неверное разрешение (BAR-05).
- **`assert` в IPC:** не является границей безопасности; удаление под `-O` не даёт новых прав (гигиена — BAR-12).
- **`--popup`/`--opened`:** аргументы только сравниваются `in sys.argv`, в команды/пути не подставляются — инъекции нет.

## 6. Соответствие OWASP Top 10 (2021)

| Категория | Применимость | Находки |
|---|---|---|
| A01 Broken Access Control | Да (локальный IPC) | BAR-04, BAR-12 |
| A02 Cryptographic Failures | Да (транспорт, секреты) | BAR-02, BAR-03 |
| A03 Injection | Да (HTML/rich text; prompt injection — без исполнения) | BAR-06, BAR-13 |
| A04 Insecure Design | Да | BAR-02, BAR-04, BAR-07, BAR-09, BAR-14, BAR-15, BAR-18 |
| A05 Security Misconfiguration | Да | BAR-05, BAR-09, BAR-10 |
| A06 Vulnerable and Outdated Components | Да | BAR-08, BAR-16 |
| A07 Identification and Authentication Failures | Нет (нет аккаунтов/сессий; аутентификация ОС/keyring) | — |
| A08 Software and Data Integrity Failures | Да | BAR-01, BAR-08, BAR-16 |
| A09 Security Logging and Monitoring Failures | Частично | BAR-12, BAR-15, BAR-17 |
| A10 Server-Side Request Forgery (SSRF) | Нет (клиентское приложение; URL задаёт пользователь) | — |

## 7. План исправлений

**P0 — до следующего релиза:**
1. **BAR-01:** убрать pickle из `QSettings` (JSON/два строковых ключа); миграция — санитизация сырого INI до первого обращения к `QSettings` либо полный переход на JSON-стор; тест на отсутствие `PyObjectWrapper` в конфиге.
2. **BAR-02:** вызывать `api_key_manager.delete()` при удалении провайдера + явная очистка ключа в диалоге; обрабатывать `KeyringError`; тест с fake backend.
3. **BAR-06:** `QMessageBox` для ошибок — plain text; `url_to_html_links` переписать как `escape → linkify` или удалить.
4. **BAR-04/BAR-15:** IPC/`--popup` только фокусирует окно; перевод из clipboard — только по явному действию пользователя; D-Bus-метод возвращает явный статус; rate limit/проверка вызывающего.
5. **BAR-03:** HTTPS обязателен, кроме loopback; применить и при загрузке конфига.

**P1 — в ближайший цикл:**
6. **BAR-05:** убрать `--socket=session-bus` и неверный `--own-name`; проверить IPC в Flatpak.
7. **BAR-08:** hashed-requirements из `uv.lock` + `--require-hashes`; SBOM в релиз.
8. **BAR-07:** линейный парсер `<think>` + лимит ответа/`max_tokens`.
9. **BAR-09:** fail-safe загрузка конфига, валидация `api_base`/провайдеров.
10. **BAR-12:** убрать сканирование процессов (lock-файл/сокет с `SO_PEERCRED`), явные исключения и логирование.

**P2 — гигиена и defense-in-depth:**
11. **BAR-10:** `chmod 0600` на QSettings.
12. **BAR-11:** предупреждение при недоступном keyring, без plaintext-fallback.
13. **BAR-13/BAR-14:** plain-text для внешних имён и ответа LLM; лимиты текста/изображения/ответа; валидация `ChatCompletion`.
14. **BAR-16:** включить CI, пинить actions/build-tools, подписывать bundle, Dependabot/pip-audit, `SECURITY.md`.
15. **BAR-17/BAR-18:** `logging` без чувствительных данных; in-app уведомление о передаче данных провайдеру.

## 8. Security-тесты, которые стоит добавить

1. `QSettings`-round-trip выбора модели не содержит pickle (`PyObjectWrapper`); санитизация/удаление легаси-конфига выполняется без вызова `QSettings.value/remove/setValue`.
2. Удаление провайдера и очистка ключа удаляют секрет из keyring (fake/in-memory backend); `NoKeyringError` не роняет старт.
3. `is_valid_url`/`api_base_problem`: `http` вне loopback отклоняется, `http://localhost` разрешён, `https` разрешён; конфиг с `http://evil` не загружается.
4. Битый/подменённый конфиг: приложение стартует с дефолтами, валидные провайдеры загружены.
5. IPC: `popup_and_translate` не инициирует отправку без действия пользователя; метод возвращает статус; ошибка обработчика видна вызывающему.
6. Rich text: `model.id`/`provider.name` рендерятся как plain text; ошибка провайдера с HTML не создаёт ссылок/картинок.
7. `pop_think`: линейное время на большом ответе (нефункциональный тест), большой ответ усекается с сообщением.
8. `ChatCompletion(choices=[])` / `content=None`: пользователь видит ошибку, приложение не падает.
9. Лимиты на размер текста/изображения; `max_tokens` передаётся.
10. В логах/сериализованных провайдерах нет API-ключей.

## 9. Воспроизводимость и ограничения

**Ключевые эксперименты:**
- **Pickle-RCE:** writer пишет `ModelSelection` через `QSettings`; в INI-строку `model=` вставлен pickle-payload; reader в свежем процессе делает только `settings.value("model")` и создаёт файл-маркер (код выполнен). Дополнительно проверено на PySide6 6.11.1: unpickle вызывают `value("geometry")` (любой ключ той же группы), `remove()`, `setValue()`, `allKeys()`, `contains()`, `childKeys()`; `value(..., type=str)` не помогает; `value` из другой группы, `fileName()`, `sync()`, `status()` — безопасны. В реальных native/Flatpak-конфигах на машине аудита уже есть `@Variant(...PySide::PyObjectWrapper,\x80\x04...)`.
- **D-Bus:** под `dbus-run-session` минимальный `QObject` с `@Slot()` + `registerService`/`registerObject(..., ExportAllSlots)`; вызов `popup_and_translate` с пустым именем интерфейса/через `gdbus` успешен; `deleteLater` не экспортируется; при исключении в слоте клиент получает `valid=True`.
- **Qt rich text:** `QT_QPA_PLATFORM=offscreen`; инспекция `QMessageBox.findChildren(QLabel)` (`textFormat`, `openExternalLinks`, `textInteractionFlags`), клик `QTest.mouseClick` → `QDesktopServices`; `<img src="file://…">` реально грузится в `QLabel`/`QMessageBox`/`QTextEdit`; remote-картинки не грузятся; ссылки в `LinkLabel`/`QTextEdit` не кликабельны.
- **Доставка ошибки:** локальный `ThreadingHTTPServer` как OpenAI-совместимый endpoint возвращает `401` с HTML в теле; `any_llm` кладёт тело в `str(exception)` → `error.emit` → `QMessageBox`.
- **`pop_think`:** замеры `re.search` на `<think>`-повторениях без закрывающего тега (5–160 КБ) — квадратичный рост.
- **Keyring:** fake/in-memory и `fail.Keyring`; отсутствие вызовов `delete()`; очистка поля ключа; `ProviderMeta.from_dict` с произвольным `api_base`; `QSettings`-режимы при umask 022/002.

**Ограничения:** не выполнялись полная Flatpak-сборка/запуск, реальные операции с системным Secret Service (чтобы не создавать записи), проверка на реальном X11/Wayland; не проводился SAST зависимостей (CVE) и фаззинг. Выводы по Flatpak основаны на манифесте и документации; выводы по keyring — на fake-бэкендах. Исходный код в ходе аудита не изменялся.
