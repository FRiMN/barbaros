# Инструкции по сборке Flatpak-пакета (для разработчиков)

Эти инструкции предназначены для разработчиков, желающих собрать Flatpak-пакет для приложения.

## Предварительные требования

*   Установленный `flatpak`, `flatpak-builder` и `uv`.
*   Настроенный репозиторий Flathub (для установки зависимостей).

## Шаги сборки

### 1.  Сборка приложения

```sh
uv build
```

Эта команда выполняет сборку вашего приложения.

### 2.  Сборка Flatpak-пакета

```sh
flatpak-builder --force-clean --repo=repo --install-deps-from=flathub build flatpak/barbaros.yaml
```

*   `--force-clean`:  Удаляет все предыдущие сборки, гарантируя чистое состояние. Это важно при внесении изменений в манифест или исходный код.
*   `--repo=repo`: Указывает локальный репозиторий (директорию) (`repo`), где будет размещен собранный Flatpak.  Этот репозиторий будет использоваться для установки и тестирования пакета.
*   `--install-deps-from=flathub`: Указывает, что зависимости, перечисленные в манифесте (`flatpak/barbaros.yaml`), должны быть установлены из Flathub.
*   `build flatpak/barbaros.yaml`: Запускает процесс сборки, используя файл манифеста `flatpak/barbaros.yaml`.

### 3.  Добавление локального репозитория

Это нужно только один раз.

```sh
flatpak --user remote-add --no-gpg-verify local-repo repo
```

*   `--user`: Добавляет репозиторий для текущего пользователя.
*   `remote-add`:  Добавляет новый удаленный репозиторий Flatpak.
*   `--no-gpg-verify`: Отключает проверку GPG для локального репозитория. **Предупреждение:** Используйте только для локальных репозиториев. Никогда не отключайте проверку GPG для общедоступных репозиториев.
*   `local-repo`:  Имя, которое вы даете локальному репозиторию. Вы можете выбрать любое имя.
*   `repo`:  Путь к локальному репозиторию, который вы указали в команде `flatpak-builder`.

### 4.  Локальная установка Flatpak-пакета

```sh
flatpak --user install --or-update local-repo com.github.frimn.barbaros
```

*   `--user`: Устанавливает пакет для текущего пользователя.
*   `install`:  Устанавливает приложение Flatpak.
*   `--or-update`: Обновляет приложение, если оно уже установлено. Это удобно при повторной сборке и установке пакета.
*   `local-repo`: Имя локального репозитория, который вы добавили на предыдущем шаге.
*   `com.github.frimn.barbaros`:  Идентификатор приложения Flatpak, указанный в файле манифеста (`flatpak/barbaros.yaml`).

### 5.  Создайте одиночный установочный файл (bundle)

```sh
flatpak build-bundle repo barbaros.flatpak com.github.frimn.barbaros
```

Этот файл `.flatpak` можно распространять и устанавливать напрямую:

```sh
flatpak install barbaros.flatpak
```

### 6.  Создание flatpakref файла

Содержимое файла:

```ini
[Flatpak Ref]
Title=Barbaros
Name=com.github.frimn.barbaros
Branch=stable
Url=https://github.com/frimn/barbaros/releases/download/v2025.8.4.dev5/barbaros-v2025.8.4.dev5.flatpak
IsRuntime=false
Sdk=org.kde.Sdk
```
