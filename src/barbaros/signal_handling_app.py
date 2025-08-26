import signal
import socket

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Signal, Slot, QSocketNotifier, QTimer


class SignalHandlingApp(QApplication):
    """Subclass of QApplication that handles Unix signals in a Qt event loop."""

    signal_received = Signal(int)  # Custom signal for Qt event loop
    signals_for_handle: list[signal.Signals] = []

    def __init__(self, args):
        super().__init__(args)
        # Setup proper signal handling
        self._setup_signal_handling()
        # Connect custom signal to handler
        self.signal_received.connect(self.handle_signal_in_qt)

    def _setup_signal_handling(self):
        """Setup proper Unix signal handling that works with Qt event loop"""
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

    @Slot(int)
    def handle_signal_in_qt(self, signum: int):
        """Handle signal in Qt event loop context. Need to implement in user code."""
        pass
