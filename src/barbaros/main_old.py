import signal
import sys

import pystray
from PIL import Image

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Keybinder', '3.0')

from gi.repository import Gtk
from gi.repository import Keybinder


class TrayApp:
    def __init__(self):
        # Create tray icon
        image = Image.open("/usr/share/icons/desktop-base/128x128/emblems/emblem-debian-symbolic.png").convert("RGBA")
        self.icon = pystray.Icon("translation-app", image, "Translation App")

        # Create menu
        self.icon.menu = pystray.Menu(
            pystray.MenuItem("Exit", lambda _: self.exit())
        )

        # Register hotkey
        import threading
        self.key_thread = threading.Thread(target=self.register_hotkey, daemon=True)
        self.key_thread.start()

    def exit(self):
        self.icon.stop()
        Gtk.main_quit()

    def register_hotkey(self):
        print("started thread keys")
        from Xlib import display, XK, X
        from Xlib.protocol import event

        d = display.Display()
        root = d.screen().root
        root.change_attributes(event_mask=X.KeyPressMask | X.KeyReleaseMask)

        keycode = d.keysym_to_keycode(XK.string_to_keysym('A'))
        modifiers = X.ControlMask | X.Mod1Mask  # Ctrl + Alt

        # Try to grab the key combination
        try:
            root.grab_key(
                keycode, 
                modifiers, 
                owner_events=1, 
                pointer_mode=X.GrabModeAsync, 
                keyboard_mode=X.GrabModeAsync
            )
            print(f"Successfully grabbed key: Ctrl+Alt+A (keycode: {keycode})")
        except Exception as e:
            print(f"Failed to grab key: {e}")

        print("Starting event loop...")
        while True:
            print("Waiting for event...")
            _event = d.next_event()
            print(f"Received event: type={_event.type}, detail={_event.detail}, state={_event.state}")
            
            # Check if this is a key press event for our hotkey
            is_key_press = _event.type == X.KeyPress
            is_key_release = _event.type == X.KeyRelease
            is_key = _event.detail == keycode
            is_modifiers = (_event.state & modifiers) == modifiers
            
            print(f"Event details: key_press={is_key_press}; key_release={is_key_release}; is_key={is_key}; is_modifiers={is_modifiers}")
            
            if is_key_press and is_key and is_modifiers:
                print("Hotkey pressed, activating window")
            elif is_key_release and is_key and is_modifiers:
                print("Hotkey released")


def main():
    try:
        # Allow app to be terminated with Ctrl+C
        signal.signal(signal.SIGINT, signal.SIG_DFL)

        app = TrayApp()
        app.icon.run()

    except Exception as e:
        print(f"An error occurred: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
