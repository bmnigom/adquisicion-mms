"""Bluetooth lifecycle regressions, with no adapter or participant files."""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QEventLoop, QObject, QThread, QTimer, pyqtSignal
from PyQt6.QtWidgets import QApplication

from core.connection import ConnectionController
from core.sensor_stream import SensorScanner, SensorStream, SimulatedSensorScanner, SimulatedSensorStream
from ui.sensor_dialog import SensorDialog


class FakeWorker(QObject):
    sample_ready = pyqtSignal(dict)
    status_changed = pyqtSignal(str)
    error = pyqtSignal(str)
    found = pyqtSignal(str, str, int)
    finished = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.running = False
        self.started = 0
        self.stop_requests = 0
        self.profiles = []

    def start(self):
        self.running = True
        self.started += 1

    def isRunning(self):
        return self.running

    def request_stop(self):
        self.stop_requests += 1

    def wait(self, *args):
        raise AssertionError("The graphical thread must never wait for a worker")

    def set_profile(self, task):
        self.profiles.append(task)

    def finish(self):
        self.running = False
        self.finished.emit()


class ConnectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.streams = []
        self.scanners = []
        self.controller = ConnectionController(
            stream_factory=self.make_stream, scanner_factory=self.make_scanner,
        )

    def make_stream(self, mac):
        worker = FakeWorker()
        worker.mac = mac
        self.streams.append(worker)
        return worker

    def make_scanner(self):
        worker = FakeWorker()
        self.scanners.append(worker)
        return worker

    def tearDown(self):
        self.controller.shutdown()
        for worker in self.streams + self.scanners:
            if worker.running:
                worker.finish()

    def test_scan_waits_for_blocked_connection_without_waiting_on_gui(self):
        self.controller.start("A")
        self.controller.scan()
        self.assertEqual(self.scanners, [])
        self.assertEqual(self.streams[0].stop_requests, 1)
        self.assertTrue(self.controller.has_running_threads())
        self.streams[0].finish()
        self.assertEqual(self.scanners[0].started, 1)

    def test_old_samples_and_errors_are_not_delivered_after_stop(self):
        received, errors = [], []
        self.controller.sample_ready.connect(received.append)
        self.controller.error.connect(errors.append)
        self.controller.start("A")
        old = self.streams[0]
        old.sample_ready.emit({"test": 1})
        self.controller.start("B")
        old.sample_ready.emit({"test": 2})
        old.error.emit("obsolete")
        old.finish()
        old.sample_ready.emit({"test": 3})
        self.streams[1].sample_ready.emit({"test": 4})
        self.assertEqual(received, [{"test": 1}, {"test": 4}])
        self.assertEqual(errors, [])

    def test_latest_requested_operation_wins(self):
        self.controller.start("A")
        self.controller.scan()
        self.controller.start("B")
        self.streams[0].finish()
        self.assertEqual([worker.mac for worker in self.streams], ["A", "B"])
        self.assertEqual(self.scanners, [])

    def test_shutdown_prevents_queued_connection(self):
        self.controller.start("A")
        self.controller.start("B")
        self.controller.shutdown()
        self.assertIs(self.controller.stream, self.streams[0])
        self.streams[0].finish()
        self.controller.start("C")
        self.assertEqual(len(self.streams), 1)
        self.assertFalse(self.controller.busy)

    def test_cancel_pending_scan_releases_without_scanning(self):
        self.controller.start("A")
        self.controller.scan()
        self.controller.cancel_scan()
        self.streams[0].finish()
        self.assertEqual(self.scanners, [])
        self.assertFalse(self.controller.busy)

    def test_reconnect_waits_for_scanner_and_discards_late_results(self):
        found = []
        self.controller.scan_found.connect(lambda *args: found.append(args))
        self.controller.scan()
        self.controller.start("B")
        scanner = self.scanners[0]
        scanner.found.emit("A", "MetaWear", -40)
        self.assertEqual(self.streams, [])
        scanner.finish()
        self.assertEqual(found, [])
        self.assertEqual(self.streams[0].mac, "B")

    def test_failure_status_survives_worker_finished(self):
        self.controller.start("A")
        self.streams[0].error.emit("No adapter")
        self.streams[0].finish()
        self.assertEqual(self.controller.status, "error")

    def test_factory_failure_is_reported_and_releases_owner(self):
        errors = []
        self.controller.error.connect(errors.append)
        self.controller._stream_factory = lambda mac: (_ for _ in ()).throw(RuntimeError("Unavailable"))
        self.controller.start("A")
        self.assertEqual(errors, ["Unavailable"])
        self.assertFalse(self.controller.busy)

    def test_profile_is_applied_to_a_delayed_new_stream(self):
        self.controller.set_profile("sts")
        self.controller.start("A")
        self.assertEqual(self.streams[0].profiles, ["sts"])

    def test_dialog_cancel_does_not_wait_for_active_scanner(self):
        dialog = SensorDialog("E7:D7:CE:C3:E0:25", False, connection=self.controller)
        dialog._scan()
        scanner = self.scanners[0]
        dialog.reject()
        self.assertEqual(scanner.stop_requests, 1)
        scanner.found.emit("E7:D7:CE:C3:E0:25", "MetaWear", -50)
        scanner.finish()
        self.assertEqual(dialog.devices.count(), 0)

    def test_stream_property_exists_before_connection_status(self):
        observed = []
        self.controller.status_changed.connect(lambda status: observed.append(self.controller.stream))
        self.controller.start("A")
        self.assertIs(observed[0], self.streams[0])

    def test_stop_before_run_is_not_lost(self):
        for cls in (SensorStream, SimulatedSensorStream, SensorScanner, SimulatedSensorScanner):
            worker = cls()
            worker.request_stop()
            # A cancelled worker returns before importing/connecting/scanning.
            with patch.object(SensorStream, "_run_real_sensor", side_effect=AssertionError("Hardware accessed")):
                worker.run()

    def test_partial_hardware_start_is_cleaned_up_with_a_fake_sdk(self):
        calls, errors = [], []
        class FakeLibrary:
            def __getattr__(self, name):
                def command(*args):
                    calls.append(name)
                    if name == "mbl_mw_metawearboard_lookup_module":
                        return 0
                    if name == "mbl_mw_acc_start":
                        raise RuntimeError("Partial start failed")
                    if "data_signal" in name:
                        return name
                return command
        device = SimpleNamespace(
            board=object(), connect=lambda: calls.append("connect"),
            disconnect=lambda: calls.append("disconnect"),
        )
        bindings = SimpleNamespace(
            c_float=lambda value: value, FnVoid_VoidP_DataP=lambda fn: fn,
            GyroBoschOdr=SimpleNamespace(_100Hz=100),
            GyroBoschRange=SimpleNamespace(_2000dps=2000), Module=SimpleNamespace(GYRO=1),
        )
        worker = SensorStream()
        worker._stop_event = SimpleNamespace(is_set=lambda: False, wait=lambda seconds: False)
        worker.error.connect(errors.append)
        with patch.dict(sys.modules, {
            "mbientlab.metawear": SimpleNamespace(MetaWear=lambda *args, **kwargs: device,
                                                 libmetawear=FakeLibrary(), parse_value=lambda data: None),
            "mbientlab.metawear.cbindings": bindings,
        }):
            worker.run()
        self.assertEqual(errors, ["Partial start failed"])
        self.assertIn("mbl_mw_gyro_bmi160_stop", calls)
        self.assertIn("mbl_mw_gyro_bmi160_disable_rotation_sampling", calls)
        self.assertEqual(calls.count("mbl_mw_datasignal_unsubscribe"), 2)
        self.assertEqual(calls[-1], "disconnect")

    def test_unnamed_advertisement_is_handled_without_callback_exception(self):
        scanner = SensorScanner()
        errors = []
        scanner.error.connect(errors.append)
        callback = []
        def start():
            callback[0](SimpleNamespace(name=None, mac="aa:bb:cc:dd:ee:ff", rssi=-60,
                                       has_service_uuid=lambda uuid: False))
            scanner.request_stop()
        bluetooth = SimpleNamespace(set_handler=lambda fn: callback.append(fn), start=start, stop=lambda: None)
        with patch.dict(sys.modules, {
            "mbientlab.metawear": SimpleNamespace(MetaWear=SimpleNamespace(GATT_SERVICE="test")),
            "mbientlab.warble": SimpleNamespace(BleScanner=bluetooth),
        }):
            scanner.run()
        self.assertEqual(errors, [])

    def test_simulator_signals_and_shutdown_use_the_graphical_event_loop(self):
        controller = ConnectionController(simulate=True)
        loop = QEventLoop()
        timeout = QTimer()
        timeout.setSingleShot(True)
        timed_out, sample_threads = [], []
        controller.sample_ready.connect(lambda sample: sample_threads.append(QThread.currentThread()))
        controller.status_changed.connect(lambda status: controller.stop() if status == "transmitiendo" else None)
        controller.stopped.connect(loop.quit)
        def expire():
            timed_out.append(True)
            controller.shutdown()
        timeout.timeout.connect(expire)
        timeout.start(3000)
        controller.start("SIMULATED")
        loop.exec()
        timeout.stop()
        controller.shutdown()
        self.assertEqual(timed_out, [])
        self.assertTrue(sample_threads)
        self.assertTrue(all(thread is self.app.thread() for thread in sample_threads))
        self.assertFalse(controller.has_running_threads())


if __name__ == "__main__":
    unittest.main()
