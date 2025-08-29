# Barbaros

AI Translation App

Barbaros is a desktop application for quick translations using AI. It runs in the system tray and can be quickly invoked to translate text from your clipboard.

## Features

- **System Tray Integration:** Runs unobtrusively in the system tray.
- **Clipboard Translation:** Automatically picks up text from the clipboard for translation.
- **AI-Powered:** Uses AI models for translation.
- **Fast Popup:** Can be quickly opened with a command or a hotkey.

## Installation & Usage

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/FRiMN/barbaros.git
    cd barbaros
    ```

2.  **Install dependencies using uv:**
    ```bash
    uv sync
    ```

3.  **Run the application:**
    ```bash
    uv run barbaros
    ```
    The application will start in the system tray.

4.  **Translate text:**
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
