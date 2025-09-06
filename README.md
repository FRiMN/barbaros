# Barbaros

[Русская документация](docs/README_RU.md)

**AI-Powered Translation Desktop Application**

Barbaros is a lightweight desktop application that provides instant AI translations through your system tray. Simply copy text to your clipboard and get quick translations with a hotkey.

![Screenshot 1](docs/img/window-1.png)
![Screenshot 2](docs/img/window_translation_process.png)
![Screenshot 3](docs/img/window-2.png)

## Features

- **🚀 System Tray Integration**: Runs quietly in the background without cluttering your desktop
- **📋 Clipboard Translation**: Automatically translates text from your clipboard
- **🤖 AI-Powered**: Leverages advanced AI models through Ollama for accurate translations
- **🔒 Privacy-First**: All translations are processed locally - your data never leaves your machine
- **🏠 Offline Capable**: Works completely offline once models are downloaded
- **⚡ Quick Access**: Instant popup with customizable hotkeys
- **🔄 Multiple Communication Methods**: Uses DBus and Unix signals for reliable operation

## Prerequisites

### Ollama Installation

Barbaros requires [Ollama](https://ollama.ai/) to be installed and running on your system.

**Linux Installation:**
```bash
curl -fsSL https://ollama.com/install.sh | sh
```

**Pull a Translation Model:**
After installing Ollama, download a model for translations:
```bash
ollama pull llama3.1
```

Browse available models in the [official Ollama catalog](https://ollama.com/search).

## Installation

### Option 1: Flatpak Package (Recommended)

**Download and Install:**
1. Get the latest `.flatpak` file from [GitHub Releases](https://github.com/FRiMN/barbaros/releases)
2. Install the package:
   ```bash
   cd ~/Downloads
   flatpak install Barbaros-v1.2.3.flatpak
   ```

**Launch:**
- **Terminal**: `flatpak run io.github.frimn.barbaros`
- **GUI**: Find "Barbaros" in your application menu

**Quick Translation:**
```bash
flatpak run io.github.frimn.barbaros --popup
```
*Tip: Bind this command to a keyboard shortcut for instant access*

> **Note**: Manual Flatpak installation doesn't support automatic updates. Check GitHub releases for new versions.

### Option 2: Development Installation

**Clone and Setup:**
```bash
git clone https://github.com/FRiMN/barbaros.git
cd barbaros
uv sync
```

**Run Application:**
```bash
# Start system tray application
uv run barbaros

# Quick translation popup
uv run barbaros --popup
```

## Usage

1. **Start the Application**: Launch Barbaros to run it in your system tray
2. **Copy Text**: Copy any text you want to translate to your clipboard
3. **Translate**:
   - Use the `--popup` command, or
   - Click the system tray icon
4. **Get Results**: The translation window will appear with your translated text

## How It Works

Barbaros uses a dual-communication system for reliable popup functionality:

- **Primary**: DBus messaging for seamless desktop integration
- **Fallback**: Unix signals (`SIGUSR1`) for reliable operation

When you use the `--popup` argument, the command communicates with the running application instance, which then:
1. Brings the main window to the foreground
2. Retrieves text from your clipboard
3. Processes the translation through Ollama
4. Displays the results

## Dependencies

**Runtime Requirements:**
- [Ollama](https://ollama.ai/) - AI model backend
- [PySide6](https://www.qt.io/qt-for-python) - GUI framework
- [psutil](https://github.com/giampaolo/psutil) - Process utilities

**Development Tools:**
- [uv](https://docs.astral.sh/uv/) - Python package management
- [Flatpak](https://flatpak.org/) - Application distribution

## Development

### Building Flatpak Package

For detailed information about building the Flatpak package, see [build_flatpak.md](docs/build_flatpak.md).

**Quick Build:**
```bash
./build.sh
```

## Translation Quality Disclaimer

**Important Notice**: The quality of translations depends entirely on the AI model you choose and its capabilities. Barbaros is a tool that facilitates the translation process, but it does not guarantee the accuracy, completeness, or appropriateness of translations.

- Translation accuracy varies between different language pairs
- Complex technical, legal, or medical texts may require professional human translation
- Always review and verify translations for important documents
- The application is not responsible for any consequences resulting from translation errors

For critical translations, we recommend consulting professional translation services.

## Contributing

Contributions are welcome! Please feel free to submit issues and pull requests.

## License

This project is open source. Please check the repository for license details.
