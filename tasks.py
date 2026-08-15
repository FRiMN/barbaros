import functools
import time
from pathlib import Path

from invoke import task


def timing(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        result = func(*args, **kwargs)
        end = time.perf_counter()
        delta = end-start
        minutes = delta / 60
        print(f"⏱️  Задача '{func.__name__}' выполнена за {minutes:.2f} минут")
        return result
    return wrapper


@task
def update_translations(c):
    """Обновление переводов (lupdate)"""
    print("Обновление файлов переводов (.ts)...")
    for ts in sorted(Path("src/barbaros/i18n").glob("*.ts")):
        c.run(f"./.venv/bin/pyside6-lupdate -extensions py -no-obsolete src/barbaros -ts {ts}")
    print("Переводы обновлены.")

@task(pre=[update_translations])
def compile_translations(c):
    """Компиляция переводов"""
    print("Компиляция файлов переводов (.ts -> .qm)...")
    for ts in c.run("ls src/barbaros/i18n/*.ts", hide=True).stdout.split():
        qm = ts.replace('.ts', '.qm')
        c.run(f"./.venv/bin/pyside6-lrelease {ts} -qm {qm}")
    print("Файлы переводов скомпилированы.")

@task(pre=[compile_translations])
def build_python(c):
    """Подготовка dist и сборка Python-пакета"""
    print("Подготовка dist...")
    c.run("mkdir -p dist")
    c.run("rm -rf dist/*")

    print("Сборка приложения...")
    c.run("uv build")

@task()
@timing
def build_flatpak(c):
    """Сборка Flatpak-репозитория"""
    print("Сборка Flatpak-пакета...")
    c.run("flatpak-builder --ccache --force-clean --repo=repo --install-deps-from=flathub build flatpak/barbaros.yaml")

@task()
@timing
def bundle(c):
    """Создание bundle"""
    version = c.run("ls dist/barbaros-*.whl | head -1 | sed 's/.*barbaros-\\([^-]*\\).*/\\1/'", hide=True).stdout.strip()
    print(f"Создание bundle для версии {version}...")
    c.run(f"flatpak build-bundle -vv repo dist/barbaros-{version}.flatpak io.github.frimn.barbaros")

@task(pre=[build_python, build_flatpak, bundle])
def build(c):
    """Полная сборка"""
    print("Сборка завершена.")

@task
def clean(c):
    """Очистка артефактов"""
    c.run("rm -rf dist/ build/ .flatpak-builder/", echo=True)
    print("Очищено.")