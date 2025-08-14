# Barbaros

AI Translation app

## Installation

### Python Dependencies

Install the required Python packages:

```bash
pip install -r requirements.txt
```

Or install directly with pip:

```bash
pip install ollama PyGObject python-xlib
```

### System Dependencies

Some features require system-level libraries to be installed:

#### AppIndicator3 (System Tray Support)

For systems with system tray support, you can install AppIndicator3 for better integration:

**Ubuntu/Debian**:
```bash
sudo apt install libappindicator3-1 gir1.2-appindicator3-0.1 gir1.2-keybinder-3.0 libkeybinder-3.0-0 python3-gi python3-gi-cairo gir1.2-gtk-3.0
```

**Fedora**:
```bash
sudo dnf install libappindicator-gtk3 libappindicator-devel
```

**Arch Linux**:
```bash
sudo pacman -S libappindicator-gtk3
```

The application will work without these packages installed, but will run in fallback mode with the main window visible by default instead of minimized to the system tray.

#### X11 Development Libraries

For keyboard shortcut functionality:

**Ubuntu/Debian**:
```bash
sudo apt install libx11-dev libxtst-dev
```

**Fedora**:
```bash
sudo dnf install libX11-devel libXtst-devel
```

**Arch Linux**:
```bash
sudo pacman -S libx11 libxtst
```

## Usage

Run the application:

```bash
python -m barbaros
```

Or if installed as a package:

```bash
barbaros
```

Use `Ctrl+Alt+A` to activate the translation window.

## Features

- System tray integration (when AppIndicator3 is available)
- Global keyboard shortcut (Ctrl+Alt+A)
- AI-powered translation using Ollama
