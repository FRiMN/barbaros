import signal
import socket
import typing

from PySide6.QtCore import QObject, Slot, Signal, QSocketNotifier, QTimer
from PySide6.QtDBus import QDBusConnection, QDBusInterface, QDBusReply


SERVICE_NAME = "io.github.frimn.barbaros"


class IPCAdapterInterface(object):
    """Interface for IPC adapter classes. Unified for different IPC mechanisms.

    Argument `ipc_calls`: a instance of service class of IPC calls to be handled by the adapter.
    """
    def __init__(self, ipc_calls, as_server: bool = True, as_client: bool = False):
        self.ipc_calls = ipc_calls
        self.as_server = as_server
        self.as_client = as_client
        assert not(not self.as_server and not self.as_client), "Adapter must be either server or/and client."

    def is_available(self) -> bool: raise NotImplementedError

    def send(self, method_name: str) -> bool:
        """Send a method call to the service via IPC."""
        assert self.as_client, "This method is only available for client adapters."
        assert self.is_available(), "IPC is not available."
        return True


class SignalHandling(QObject):
    """Setup proper Unix signal handling that works with Qt event loop.

    If the main window has not been opened before, Qt does not catch system signals.
    This is likely due to the Qt event loop. System signals are queued in this case.

    We use a socket and timer to be able to receive system signals even in this situation.
    """
    signal_received = Signal(int)  # Custom signal for Qt event loop

    def __init__(self, handler: typing.Callable[[int], None], *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.signals_for_handle: list[signal.Signals] = [signal.SIGUSR1]

        # Setup proper signal handling
        self._setup_signal_handling()
        # Connect custom signal to handler
        self.signal_received.connect(handler)

    def _setup_signal_handling(self):
        # Create socket pair for signal communication
        self.signal_sock, self.signal_write_sock = socket.socketpair()

        # Setup QSocketNotifier to monitor the socket
        self.signal_notifier = QSocketNotifier(
            self.signal_sock.fileno(),
            QSocketNotifier.Type.Read
        )
        self.signal_notifier.activated.connect(self._handle_signal_from_socket)

        # Register signal handlers
        for s in self.signals_for_handle:
            signal.signal(s, self._signal_handler)

        # Timer to keep event loop responsive
        self.timer = QTimer()
        self.timer.start(100)
        self.timer.timeout.connect(lambda: None)

    def _signal_handler(self, signum, frame):
        """Signal handler that writes to socket"""
        try:
            self.signal_write_sock.send(bytes([signum]))
        except:
            pass  # Ignore errors during signal handling

    def _handle_signal_from_socket(self):
        """Read signal from socket and emit Qt signal"""
        try:
            data = self.signal_sock.recv(1)
            if data:
                signum = data[0]
                self.signal_received.emit(signum)
        except:
            pass  # Ignore errors


class SignalAdapter(IPCAdapterInterface):
    """IPC adapter that handles Unix signals"""
    __name__ = "Signal IPC"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if self.as_server:
            self.signal_server = SignalHandling(self.handle_signal_in_qt)

    def handle_signal_in_qt(self, signum: int):
        """Handle signal in Qt event loop context"""
        if signum == signal.SIGUSR1:
            self.ipc_calls.popup_and_translate()

    def is_available(self) -> bool:
        try:
            # Try to use a common signal
            signal.SIGINT
            return True
        except AttributeError:
            # Unix signals not available (likely Windows)
            return False

    def send(self, method_name: str) -> bool:
        super().send(method_name)

        if method_name == "popup_and_translate":
            sig = signal.SIGUSR1
        else:
            raise ValueError(f"Unknown method name: {method_name}")

        return self._send_signal_to_process(sig)

    def _send_signal_to_process(self, sig: signal.Signals) -> bool:
        import psutil
        import os

        app_name = "Barbaros"
        current_pid = os.getpid()

        for proc in psutil.process_iter(['pid', 'name']):
            if proc.info['pid'] == current_pid:
                continue  # Skip current process

            if app_name.lower() == proc.info['name'].lower():
                try:
                    os.kill(proc.pid, sig)  # Send SIGUSR1 to open main window and start process of translation.
                    print(f"Send SIGUSR1 to PID {proc.pid}")
                    return True
                except (ProcessLookupError, PermissionError) as e:
                    # Handle exceptions that might occur if the process is already terminated or access is denied.
                    print(f"Error sending signal: {e}")
                    pass

        print("No running instance found")
        return False


class DBusAdapter(IPCAdapterInterface):
    """Adapter for DBus IPC.

    Docs: <https://www.freedesktop.org/wiki/Software/dbus/>.
    It is known that the Windows port runs on Windows Vista, 8, 10 and server variants.
    """
    __name__ = "DBus IPC"
    object_path = '/'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.session_bus = bus = QDBusConnection.sessionBus()
        self.iface = None
        if bus.isConnected():
            if self.as_server:
                if not bus.registerService(SERVICE_NAME):
                    raise Exception(bus.lastError().message())

                bus.registerObject(self.object_path, self.ipc_calls, QDBusConnection.RegisterOption.ExportAllSlots)
            elif self.as_client:
                self.iface = QDBusInterface(SERVICE_NAME, self.object_path, '', bus)
                if not self.iface.isValid():
                    raise Exception(bus.lastError().message())

    def is_available(self) -> bool:
        return self.session_bus.isConnected()

    def send(self, method_name: str) -> bool:
        super().send(method_name)
        self.iface: QDBusInterface

        message = self.iface.call(method_name)
        reply = QDBusReply(message)
        if not reply.isValid():
            raise Exception(reply.error().message())

        value = reply.value()
        return bool(value)


class IPCService(QObject):
    adapter: IPCAdapterInterface

    def __init__(self, as_server: bool = True, as_client: bool = False, app = None):
        from .main import App

        super().__init__()

        if as_server:
            self.app: App = app

        self.adapter = DBusAdapter(self, as_server, as_client)
        if not self.adapter.is_available():
            # Fallback to Unix signals.
            self.adapter = SignalAdapter(self, as_server, as_client)
        print(f"IPC using: {self.adapter.__name__}")

    @Slot()
    def popup_and_translate(self):
        self.app.process_translation_request()

    def send_popup_and_translate(self):
        return self.adapter.send("popup_and_translate")
