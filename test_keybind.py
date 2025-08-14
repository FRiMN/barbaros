from Xlib.display import Display
from Xlib import X, XK
from Xlib.protocol import event as protocol_event

class KeyBinder(object):
    """ This class allows you to bind keys to functions in your Python program. 
    It uses the Xlib library to interact with the X Window System.
    
    Docs: <https://tronche.com/gui/x/xlib/input/XGrabKey.html>. 

    If some other client has issued a XGrabKey() with the same key combination on the same window, a BadAccess error results.
    When using AnyModifier or AnyKey, the request fails completely, and a BadAccess error results (no grabs are established) if there is a conflicting grab for any combination. 
    """

    def __init__(self):
        self.cancel = False
        # Specifies the connection to the X server. 
        self.xdisp = Display()
        # Specifies the grab window. 
        self.xroot = self.xdisp.screen().root
        self.keycode = self.xdisp.keysym_to_keycode(XK.string_to_keysym('A'))
        # Specifies the set of keymasks or AnyModifier. The mask is the bitwise inclusive OR of the valid keymask bits. 
        self.modifiers = X.ControlMask | X.ShiftMask

    def handle_event(self, event: protocol_event.KeyButtonPointer):
        if event.type != X.KeyPress:
            return

        if event.detail != self.keycode:
            return

        if self.modifiers & event.state != self.modifiers:
            return

        print(">>> event captured")
        self.cancel = True

    def start(self):
        """ Start the keybind listener. It is blocking. """

        self.xroot.change_attributes(event_mask=X.KeyPressMask)
        self.xroot.grab_key(
            self.keycode, 
            # Bug in xlib??? We need to use X.AnyModifier instead of self.modifiers.
            X.AnyModifier, 
            # Specifies a Boolean value that indicates whether the keyboard events are to be reported as usual. 
            owner_events=True, 
            pointer_mode=X.GrabModeAsync, 
            keyboard_mode=X.GrabModeAsync
        )

        while not self.cancel:
            # print(f">>> waiting for events for key: {self.keycode}; mod: {self.modifiers}")
            # Wait next event. This is blocking.
            event = self.xroot.display.next_event()
            self.handle_event(event)

if __name__ == '__main__':
    keybinder = KeyBinder()
    keybinder.start()