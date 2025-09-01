# Barbaros

AI Translation App

Barbaros is a desktop application for quick translations using AI. It runs in the system tray and can be quickly invoked to translate text from your clipboard.

## Features

- **System Tray Integration:** Runs unobtrusively in the system tray.
- **Clipboard Translation:** Automatically picks up text from the clipboard for translation.
- **AI-Powered:** Uses AI models for translation.
- **Fast Popup:** Can be quickly opened with a command or a hotkey.

## For developers

Information about how build flatpak-package can be found in the [build_flatpak.md](build_flatpak.md) file.

Automated build script: [build.sh](build.sh).

## Installation & Usage

### Ollama

This application requires [ollama](https://ollama.ai/) to be installed and running. To install ollama, follow the instructions for your operating system on the [ollama website](https://ollama.ai/).

On Linux, you can install it with the following command:
```bash
curl -fsSL https://ollama.com/install.sh | sh
```

After installation, you need to pull the model that you want to use. For example, to use the `llama3.1` model, run:
```bash
ollama pull llama3.1
```

You can find available models in [official catalog](https://ollama.com/search).

### Barbaros

**Installation through flatpak**

Install Barbaros using flatpakref:
```bash
flatpak install https://github.com/FRiMN/barbaros/releases/download/v0.1.0/barbaros.flatpakref
```

**Note:** Change version number to the latest release. You can check the latest release on the [GitHub releases page](https://github.com/FRiMN/barbaros/releases).

Or download the latest flatpak file from the [GitHub releases page](https://github.com/FRiMN/barbaros/releases) and install it using flatpak:
```bash
flatpak install <path_to_flatpak_file>
```

**Installation through repository clone**

1.  Clone the repository:
    ```bash
    git clone https://github.com/FRiMN/barbaros.git
    cd barbaros
    ```

2.  Install dependencies using uv:
    ```bash
    uv sync
    ```

3.  Run the application:
    ```bash
    uv run barbaros
    ```
    The application will start in the system tray.

4.  Translate text:
    Copy any text to your clipboard and then run:
    ```bash
    uv run barbaros --popup
    ```
    This will open the main window and start the translation. It is recommended to bind this command to a keyboard shortcut for quick access.

## How it Works

The application listens for a `SIGUSR1` signal. When the `--popup` argument is used, the script sends this signal to the running application instance. The application then opens its main window, takes the text from the clipboard, and performs the translation.

## Dependencies

- [ollama](https://ollama.ai/)
- [PySide6](https://www.qt.io/qt-for-python)
- [psutil](https://github.com/giampaolo/psutil)
- For developing and distribution:
  - [uv](https://docs.astral.sh/uv/)
  - [Flatpak](https://flatpak.org/)
