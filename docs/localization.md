# Localization (i18n) Developer Documentation

Barbaros uses Qt's translation system (`.ts` / `.qm` files) for UI localization. The source language is English.

## Architecture

- **Source language**: English (`en`) — no `.qm` file needed
- **Translation source**: `src/barbaros/i18n/*.ts` (XML, Qt Linguist format)
- **Compiled translations**: `src/barbaros/i18n/*.qm` (binary, loaded at runtime)
- **Runtime loader**: `src/barbaros/i18n/__init__.py`

## Adding a New Language

1. **Create a new `.ts` file**  
   Copy `src/barbaros/i18n/barbaros_ru.ts` to `src/barbaros/i18n/barbaros_<lang>.ts` (e.g., `barbaros_de.ts` for German). Update the `language` attribute in the `<TS>` root element:
   ```xml
   <TS version="2.1" language="de_DE">
   ```

2. **Translate strings**  
   Open the `.ts` file in **Qt Linguist** (`pyside6-linguist`) or edit the XML directly. Each `<message>` has:
   - `<source>` — English text (do not modify)
   - `<translation>` — translated text (edit this)

3. **Compile to `.qm`**  
   Run the build script (compiles all `.ts` files):
   ```bash
   uv run invoke compile_translations
   ```
   Or manually:
   ```bash
   pyside6-lrelease src/barbaros/i18n/barbaros_de.ts -qm src/barbaros/i18n/barbaros_de.qm
   ```

4. **Verify**  
   Run the app and switch to the new language in **Settings → Language**. Restart required.

## Marking Strings for Translation

### In `QObject` subclasses (widgets, windows, etc.)
Use `self.tr("Text")` or `self.tr("Context", "Text")`:
```python
class MyWidget(QWidget):
    def __init__(self):
        super().__init__()
        label = QLabel(self.tr("Hello"))  # context = "MyWidget"
```

### In non-QObject code (utils, workers, etc.)
Use the `_()` helper from `barbaros.i18n`:
```python
from barbaros.i18n import _

def some_function():
    return _("MyContext", "Translatable text")
```
The context should be a unique identifier (typically the class/module name).

### In `.ui` files (if any)
Qt Designer marks translatable strings automatically. Run `pyside6-lupdate` to extract them.

## Updating Translations After Code Changes

1. **Extract new strings** (run from project root):
   ```bash
   pyside6-lupdate src/barbaros -ts src/barbaros/i18n/barbaros_ru.ts
   ```
   Repeat for each language-specific `.ts` file.

2. **Translate new entries** in Qt Linguist.

3. **Recompile** (step 3 above).


## Adding Translatable Strings Checklist

- [ ] Wrap user-visible strings with `self.tr()` or `_()`
- [ ] Run `pyside6-lupdate` to update `.ts` files
- [ ] Translate new entries in Qt Linguist
- [ ] Run `./build.sh` (or `pyside6-lrelease`) to compile
- [ ] Test language switch in Settings → restart app

## Common Patterns

### Disambiguation (same English text, different meanings)
```python
# Context distinguishes "Open" (verb) vs "Open" (adjective)
self.tr("FileMenu|Open")      # → "Открыть" (verb)
self.tr("FileMenu|Open")      # → "Открыт" (adjective)
# Or use different contexts:
self.tr("FileMenu", "Open")
self.tr("StatusLabel", "Open")
```

### Placeholders
```python
# In source
self.tr("Eval: %1s; %2 tkn/s")
# In .ts translation
Оценка: %1 с; %2 ток/с
# Placeholders (%1, %2) must be preserved exactly
```

### Plural forms (if needed)
Qt supports plural forms in `.ts` via `<numerusform>`. Use `tr()` with `n` argument:
```python
self.tr("%n file(s) found", "", n)  # n = count
```