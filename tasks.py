from invoke import task

@task
def compile_translations(c):
    """Компиляция переводов"""
    print("Компиляция файлов переводов (.ts -> .qm)...")
    if c.run("test -x ./.venv/bin/pyside6-lrelease", warn=True).ok:
        for ts in c.run("ls src/barbaros/i18n/*.ts", hide=True).stdout.split():
            qm = ts.replace('.ts', '.qm')
            c.run(f"./.venv/bin/pyside6-lrelease {ts} -qm {qm}")
        print("Файлы переводов скомпилированы.")
    else:
        print("Пропуск компиляции переводов: .venv/pyside6-lrelease не найден.")

@task(pre=[compile_translations])
def build_python(c):
    """Подготовка dist и сборка Python-пакета"""
    print("Подготовка dist...")
    c.run("mkdir -p dist")
    c.run("rm -rf dist/*")

    print("Сборка приложения...")
    c.run("uv build")

@task(pre=[build_python])
def build_flatpak(c):
    """Сборка Flatpak-репозитория"""
    print("Сборка Flatpak-пакета...")
    c.run("flatpak-builder --ccache --force-clean --repo=repo --install-deps-from=flathub build flatpak/barbaros.yaml")

@task(pre=[build_flatpak])
def bundle(c):
    """Создание bundle"""
    # Получаем версию
    version = c.run("ls dist/barbaros-*.whl | head -1 | sed 's/.*barbaros-\\([^-]*\\).*/\\1/'", hide=True).stdout.strip()
    print(f"Создание bundle для версии {version}...")
    c.run(f"flatpak build-bundle -vv repo dist/barbaros-{version}.flatpak io.github.frimn.barbaros")

@task(pre=[bundle])
def build(c):
    """Полная сборка"""
    print("Сборка завершена.")

@task
def clean(c):
    """Очистка артефактов"""
    c.run("rm -rf dist/ repo/ build/")
    print("Очищено.")