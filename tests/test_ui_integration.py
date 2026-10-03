"""Real Qt workflow with a fake transport and isolated synthetic sessions."""
import csv
import json
import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QMessageBox

import main
from core import simulation, storage
from core.connection import ConnectionController
from core.timed_capture import TimedCapture
from tests.test_algoritmos import temporary_data_dir
from tests.test_connection import FakeWorker
from ui.main_window import MainWindow


class UIIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.tmp = self.enterContext(temporary_data_dir())
        self.workers = []
        self.sample_index = 0
        self.timer_clock = 0.0
        def make_stream(mac):
            worker = FakeWorker()
            self.workers.append(worker)
            return worker
        self.enterContext(patch("ui.main_window.ConnectionController", side_effect=lambda **kwargs:
            ConnectionController(stream_factory=make_stream, scanner_factory=FakeWorker)))
        self.enterContext(patch("ui.pages.TimedCapture", side_effect=lambda:
            TimedCapture(clock=lambda: self.timer_clock)))
        self.window = MainWindow(simulate=True)
        # Show only in Qt's offscreen backend; visibility is needed for real UI guards.
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.close()
        for worker in self.workers:
            if worker.isRunning():
                worker.finish()
        self.window.deleteLater()
        self.app.processEvents()

    def feed(self, raw, *, host_end=None):
        host_end = time.perf_counter() if host_end is None else host_end
        first_host = host_end - (len(raw) - 1) / 100.0
        for offset, (ax, ay, az, gx, gy, gz) in enumerate(raw):
            self.sample_index += 1
            self.workers[0].sample_ready.emit({
                "time": self.sample_index / 100.0,
                "device_time": self.sample_index / 100.0, "sequence": self.sample_index,
                "host_time": first_host + offset / 100.0, "lost_before": 0,
                "acc_x": ax, "acc_y": ay, "acc_z": az,
                "gyr_x": gx, "gyr_y": gy, "gyr_z": gz,
                "gyro_emparejado": 1, "gyro_pairing": "native",
            })

    def ready(self):
        self.feed([(0, 0, 1, 0, 0, 0)])
        self.workers[0].status_changed.emit("transmitiendo")

    def rest(self):
        self.feed([(0, 0, 1, 0, 0, 0)] * 101)
        self.workers[0].status_changed.emit("transmitiendo")

    def start_timed(self, mode="walk", seconds=2.0):
        self.ready()
        self.window.start_setup(mode)
        self.window.setup_page._on_start()
        self.assertTrue(self.window.capture_page._active)
        session = self.window.session_context
        self.feed([(0, 0, 1, 0, 0, 0)] * 50)
        self.timer_clock += seconds
        return session

    def manifests(self):
        folder = Path(storage.DATA_DIR) / "sesiones"
        return list(folder.glob("*.json")) if folder.exists() else []

    def saved_manifest(self, session):
        manifest_path = Path(session.data_dir) / "sesiones" / f"{session.session_id}.json"
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(data["session_id"], session.session_id)
        self.assertEqual(data["status"], "guardada")
        self.assertEqual(data["data_source"], "simulacion")
        self.assertEqual(set(data["artifacts"]), {"raw", "results", "report"})
        for artifact in data["artifacts"].values():
            self.assertTrue((Path(session.data_dir) / artifact["path"]).is_file())
        return data

    def result_row(self, session, manifest):
        path = Path(session.data_dir) / manifest["artifacts"]["results"]["path"]
        with path.open(newline="", encoding="utf-8-sig") as handle:
            return next(row for row in csv.DictReader(handle) if row["session_id"] == session.session_id)

    def test_capture_without_signal_does_not_reserve_a_session(self):
        self.window.start_setup("walk")
        with patch.object(storage, "create_session", wraps=storage.create_session) as reserve:
            self.assertFalse(self.window.start_capture(None, "01"))
        reserve.assert_not_called()
        self.assertIsNone(self.window.session_context)
        self.assertFalse(self.window.capture_page._active)
        self.assertIs(self.window.stack.currentWidget(), self.window.setup_page)
        self.assertEqual(self.manifests(), [])
        self.assertFalse(self.window.setup_page.start_btn.isEnabled())
        self.assertFalse(self.window.setup_page.form_error.isHidden())

    def test_calibration_without_samples_does_not_confirm_or_save(self):
        self.window.start_setup("jump")
        with patch("ui.main_window.QMessageBox.question") as question, patch.object(
                storage, "save_reference_orientation", wraps=storage.save_reference_orientation) as save:
            self.assertFalse(self.window.calibrate_reference())
        question.assert_not_called()
        save.assert_not_called()
        self.assertFalse(Path(storage.REFERENCE_ORIENTATION_FILE).exists())
        self.assertFalse(self.window.setup_page.calibrate_btn.isEnabled())

    def test_calibration_rechecks_signal_after_confirmation(self):
        for change in ("disconnect", "movement"):
            with self.subTest(change=change):
                self.window.start_setup("jump")
                self.rest()
                self.assertTrue(self.window.requirements.calibration_check(
                    self.window.sensor_status, self.window.processor.ahrs.initialized).allowed)
                def confirm(*args):
                    if change == "disconnect":
                        self.workers[0].status_changed.emit("desconectado")
                    else:
                        self.feed([(0, 0, 1, 40, 0, 0)])
                    return QMessageBox.StandardButton.Yes
                with patch("ui.main_window.QMessageBox.question", side_effect=confirm) as question, patch.object(
                        storage, "save_reference_orientation", wraps=storage.save_reference_orientation) as save:
                    self.assertFalse(self.window.calibrate_reference())
                question.assert_called_once()
                save.assert_not_called()
        self.assertFalse(Path(storage.REFERENCE_ORIENTATION_FILE).exists())

    def test_timed_and_detected_captures_save_linked_simulated_artifacts(self):
        timed = self.start_timed()
        self.window.capture_page.finish_btn.click()
        self.assertIs(self.window.stack.currentWidget(), self.window.result_page)
        timed_manifest = self.saved_manifest(timed)
        timed_row = self.result_row(timed, timed_manifest)
        self.assertEqual(timed_row["valido"], "si")
        self.assertEqual(timed_row["duration_s"], "2.0")
        self.assertEqual(timed_row["data_source"], "simulacion")
        self.assertTrue(all(button.isEnabled() for button in self.window._nav_buttons))

        self.ready()
        self.window.start_setup("jump")
        self.window.setup_page.mass_input.setValue(70)
        self.window.setup_page._on_start()
        detected = self.window.session_context
        self.assertTrue(self.window.capture_page._active)
        self.feed(simulation.to_sensor_samples(simulation.jump_profile(0.30), seed=2))
        self.assertFalse(self.window.capture_page._active)
        self.assertIs(self.window.stack.currentWidget(), self.window.result_page)
        detected_manifest = self.saved_manifest(detected)
        detected_row = self.result_row(detected, detected_manifest)
        self.assertEqual(detected_row["valido"], "si")
        self.assertEqual(detected_row["data_source"], "simulacion")
        self.assertAlmostEqual(float(detected_row["altura_salto_cm"]), 30, delta=1)
        self.assertNotEqual(timed.session_id, detected.session_id)
        report_path = Path(detected.data_dir) / detected_manifest["artifacts"]["report"]["path"]
        report = report_path.read_text(encoding="utf-8")
        self.assertIn(detected.session_id, report)
        self.assertIn("SIMULACIÓN", report)
        self.assertFalse((Path(self.tmp) / "resultados_ciclovia_v2.csv").exists())

    def test_invalid_timed_capture_is_saved_but_has_no_comparison_or_cards(self):
        baseline = self.start_timed()
        self.window.capture_page.finish_btn.click()
        self.assertEqual(storage.previous_value(baseline.sub, baseline.task, timed=True), 2.0)
        invalid = self.start_timed(seconds=3.0)
        with patch.object(storage, "previous_value", wraps=storage.previous_value) as previous, patch.object(
                self.window.result_page, "show_report", wraps=self.window.result_page.show_report) as report:
            self.workers[0].status_changed.emit("desconectado")
        previous.assert_not_called()
        context = report.call_args.args[1]
        self.assertIsNone(context.previous)
        self.assertEqual(context.comparison_html, "")
        self.assertTrue(all(card.isHidden() for card in self.window.result_page.cards))
        manifest = self.saved_manifest(invalid)
        row = self.result_row(invalid, manifest)
        self.assertEqual(row["valido"], "no")
        self.assertEqual(row["ended_by"], "desconexion")
        self.assertEqual(storage.previous_value(invalid.sub, invalid.task, timed=True), 2.0)

    def test_cancel_restores_navigation_and_protocol_controls_hide_correctly(self):
        self.ready()
        for mode, expects_mass, expects_condition, timed in (
                ("walk", False, False, True), ("single_leg", False, True, True),
                ("jump", True, False, False)):
            with self.subTest(mode=mode):
                self.window.start_setup(mode)
                self.assertEqual(not self.window.setup_page.mass_input.isHidden(), expects_mass)
                self.assertEqual(not self.window.setup_page.condition_input.isHidden(), expects_condition)
                if expects_mass:
                    self.window.setup_page.mass_input.setValue(70)
                self.window.setup_page._on_start()
                self.assertTrue(self.window.capture_page._active)
                self.assertTrue(all(not button.isEnabled() for button in self.window._nav_buttons))
                self.assertEqual(not self.window.capture_page.finish_btn.isHidden(), timed)
                self.assertEqual(not self.window.capture_page.timer_display.isHidden(), timed)
                self.assertEqual(self.window.capture_page.gauge.isHidden(), timed)
                self.window.capture_page._cancel()
                self.assertFalse(self.window.capture_page._active)
                self.assertTrue(all(button.isEnabled() for button in self.window._nav_buttons))
                self.assertIs(self.window.stack.currentWidget(), self.window.home_page)

    def test_active_capture_prevents_duplicate_sessions_and_hidden_page_navigation(self):
        session = self.start_timed()
        with patch.object(storage, "create_session", wraps=storage.create_session) as reserve:
            self.assertFalse(self.window.start_capture(None, session.sub))
            self.window.goto_event(False)
            self.window.goto_home(False)
            self.window.start_setup("jump")
        reserve.assert_not_called()
        self.assertIs(self.window.stack.currentWidget(), self.window.capture_page)
        self.assertIs(self.window.session_context, session)
        self.assertEqual(self.window.current_mode, "walk")

    def test_check_error_handler_exits_without_a_modal_dialog(self):
        with patch.object(sys, "excepthook", sys.excepthook), patch("main.QMessageBox.critical") as modal, patch(
                "main.QApplication.exit") as exit_app, patch("main._write") as write:
            main._install_error_handler(check=True)
            exc = RuntimeError("Synthetic startup failure")
            sys.excepthook(RuntimeError, exc, None)
        modal.assert_not_called()
        exit_app.assert_called_once_with(2)
        self.assertIn("MMS_ERROR: Synthetic startup failure", [call.args[0] for call in write.call_args_list])


if __name__ == "__main__":
    unittest.main()
