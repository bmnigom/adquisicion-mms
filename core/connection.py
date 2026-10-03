"""Coordinate Bluetooth operations without waiting on the graphical thread.

Only one stream or scanner may own the adapter. A requested replacement starts
after the previous worker emits ``finished``, including a blocked SDK connect.
Factories make the lifecycle testable without Bluetooth or a visible window.
"""
from collections.abc import Callable

from PyQt6.QtCore import QObject, pyqtSignal

from core.sensor_stream import (
    SensorScanner, SensorStream, SimulatedSensorScanner, SimulatedSensorStream,
)


# Keep workers and their owner alive even if a standalone dialog closes first.
_ACTIVE_CONTROLLERS: set = set()


class ConnectionController(QObject):
    sample_ready = pyqtSignal(dict)
    status_changed = pyqtSignal(str)
    error = pyqtSignal(str)
    scan_found = pyqtSignal(str, str, int)
    scan_error = pyqtSignal(str)
    scan_started = pyqtSignal()
    scan_finished = pyqtSignal()
    stopped = pyqtSignal()

    def __init__(
        self, simulate: bool = False, parent=None, *,
        stream_factory: Callable | None = None,
        scanner_factory: Callable | None = None,
    ):
        super().__init__(parent)
        self._stream_factory = stream_factory or (
            (lambda mac: SimulatedSensorStream()) if simulate else SensorStream
        )
        self._scanner_factory = scanner_factory or (
            SimulatedSensorScanner if simulate else SensorScanner
        )
        self._stream = None
        self._scanner = None
        self._pending: tuple[str, str | None] | None = None
        self._stopping = False
        self._closing = False
        self._stream_failed = False
        self._status = "desconectado"
        self._profile = None

    @property
    def stream(self):
        """Current stream, retained until its finished signal is received."""
        return self._stream

    @property
    def busy(self) -> bool:
        return self._stream is not None or self._scanner is not None or self._pending is not None

    @property
    def status(self) -> str:
        return self._status

    def has_running_threads(self) -> bool:
        return any(worker is not None and worker.isRunning()
                   for worker in (self._stream, self._scanner))

    def _set_status(self, status: str):
        self._status = status
        self.status_changed.emit(status)

    def start(self, mac: str):
        if self._closing:
            return
        self._pending = ("start", mac)
        self._stop_workers()
        self._drive()

    def scan(self):
        if self._closing:
            return
        self._pending = ("scan", None)
        self._stop_workers()
        self._drive()

    def cancel_scan(self):
        """Cancel an active scan or a scan waiting for a connection to finish."""
        if self._pending is not None and self._pending[0] == "scan":
            self._pending = None
        if self._scanner is not None:
            self._scanner.request_stop()

    def stop(self):
        self._pending = None
        self._stop_workers()
        self._drive()

    def shutdown(self):
        """Prevent any queued replacement from starting during application exit."""
        self._closing = True
        self.stop()

    def set_profile(self, task: str):
        self._profile = task
        if self._stream is not None:
            self._stream.set_profile(task)

    def _stop_workers(self):
        stream, scanner = self._stream, self._scanner
        self._stopping = stream is not None or scanner is not None
        if self._stopping:
            self._set_status("desconectado")
        if stream is not None:
            stream.request_stop()
        if scanner is not None:
            scanner.request_stop()

    def _drive(self):
        if self._stream is not None or self._scanner is not None:
            return
        self._stopping = False
        operation, self._pending = self._pending, None
        if operation is None or self._closing:
            _ACTIVE_CONTROLLERS.discard(self)
            self.stopped.emit()
            return
        _ACTIVE_CONTROLLERS.add(self)
        kind, mac = operation
        try:
            if kind == "start":
                stream = self._stream_factory(mac)
                self._stream = stream
                self._stream_failed = False
                stream.sample_ready.connect(lambda sample, s=stream: self._sample(s, sample))
                stream.status_changed.connect(lambda status, s=stream: self._stream_status(s, status))
                stream.error.connect(lambda message, s=stream: self._stream_error(s, message))
                stream.finished.connect(lambda s=stream: self._stream_finished(s))
                if self._profile is not None:
                    stream.set_profile(self._profile)
                self._set_status("conectando")
                stream.start()
            else:
                scanner = self._scanner_factory()
                self._scanner = scanner
                scanner.found.connect(lambda mac, name, rssi, s=scanner: self._found(s, mac, name, rssi))
                scanner.error.connect(lambda message, s=scanner: self._scan_error(s, message))
                scanner.finished.connect(lambda s=scanner: self._scan_finished(s))
                self.scan_started.emit()
                scanner.start()
        except Exception as exc:
            # Factory/start failures have no live thread to release later.
            if kind == "start":
                self._stream = None
                self._set_status("error")
                self.error.emit(str(exc))
            else:
                self._scanner = None
                self.scan_error.emit(str(exc))
                self.scan_finished.emit()
            self._drive()

    def _sample(self, stream, sample):
        if stream is self._stream and not self._stopping and not self._closing:
            self.sample_ready.emit(sample)

    def _stream_status(self, stream, status):
        if stream is self._stream and not self._stopping and not self._closing:
            self._set_status(status)

    def _stream_error(self, stream, message):
        if stream is self._stream and not self._stopping and not self._closing:
            self._stream_failed = True
            self._set_status("error")
            self.error.emit(message)

    def _stream_finished(self, stream):
        if stream is not self._stream:
            return
        self._stream = None
        if not self._stream_failed and self._status != "desconectado":
            self._set_status("desconectado")
        self._drive()

    def _found(self, scanner, mac, name, rssi):
        if scanner is self._scanner and not self._stopping and not self._closing:
            self.scan_found.emit(mac, name, rssi)

    def _scan_error(self, scanner, message):
        if scanner is self._scanner and not self._stopping and not self._closing:
            self.scan_error.emit(message)

    def _scan_finished(self, scanner):
        if scanner is not self._scanner:
            return
        self._scanner = None
        self.scan_finished.emit()
        self._drive()
