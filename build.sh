#!/bin/bash
#
# Скрипт для сборки приложения и создания Flatpak-пакета.
# В результате будут созданы файлы для дистрибуции:
# - Flatpak
#   - dist/barbaros.flatpak
#   - dist/barbaros.flatpakref
# - Python package
#   - dist/barbaros-*.whl
#   - dist/barbaros-*.tar.gz


# Проверка наличия необходимых команд
required_commands=("flatpak" "flatpak-builder" "uv" "git")
missing_commands=()

for cmd in "${required_commands[@]}"; do
  if ! command -v "$cmd" &> /dev/null; then
    missing_commands+=("$cmd")
  fi
done

if [ ${#missing_commands[@]} -ne 0 ]; then
  echo "Ошибка: Не найдены следующие необходимые команды:"
  for cmd in "${missing_commands[@]}"; do
    echo "  - $cmd"
  done
  echo "Пожалуйста, установите недостающие программы и попробуйте снова."
  exit 1
fi

# Функция для измерения времени выполнения
start_time=$(date +%s)
last_step_time=$start_time

function log_step_time() {
    current_time=$(date +%s)
    step_duration=$((current_time - last_step_time))
    total_duration=$((current_time - start_time))
    echo "Время выполнения шага: ${step_duration}с | Общее время: ${total_duration}с"
    last_step_time=$current_time
}

# Шаги сборки:

echo "1/5. Проверка и подготовка dist директории."
if [ ! -d "./dist" ]; then
  mkdir -p ./dist
  echo "Создана директория dist."
else
  rm -rf ./dist/*
  echo "Очищена директория dist."
fi
log_step_time

echo -e "\n\n2/5. Сборка приложения..."
if uv build; then
  echo "Сборка приложения выполнена успешно."
else
  echo "Ошибка: Сборка приложения не удалась. Выход."
  exit 1
fi
log_step_time

echo -e "\n\n3/5. Сборка Flatpak-пакета в репозитории..."
if flatpak-builder --force-clean --repo=repo --install-deps-from=flathub build flatpak/barbaros.yaml; then
  echo "Сборка Flatpak-пакета в репозитории выполнена успешно."
else
  echo "Ошибка: Сборка Flatpak-пакета в репозитории не удалась. Выход."
  exit 1
fi
log_step_time

echo -e "\n\n4/5. Создание одиночного установочного файла (bundle)..."
if flatpak build-bundle repo dist/barbaros.flatpak com.github.frimn.barbaros; then
  echo "Создание одиночного установочного файла (bundle) выполнено успешно."
else
  echo "Ошибка: Создание одиночного установочного файла (bundle) не удалось. Выход."
  exit 1
fi
log_step_time

echo -e "\n\n5/5. Создание flatpakref файла..."
git_tag=$(git describe --tags --abbrev=0)
version=$(echo $git_tag | sed 's/^v//')
flatpak_url="https://github.com/frimn/barbaros/releases/download/${git_tag}/barbaros.flatpak"

if cat > dist/barbaros.flatpakref <<EOF
[Flatpak Ref]
Title=Barbaros
Name=com.github.frimn.barbaros
Branch=stable
Url=${flatpak_url}
IsRuntime=false
Sdk=org.kde.Sdk
EOF
then
    echo "Создание flatpakref файла выполнено успешно."
else
    echo "Ошибка: Создание flatpakref файла не удалось. Выход."
    exit 1
fi
log_step_time

total_time=$(($(date +%s) - start_time))
echo -e "\nСборка завершена за ${total_time} секунд."
