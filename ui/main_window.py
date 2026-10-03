"""Ventana principal para experiencias de evento y evaluación funcional."""
import os
import sys
import time
import datetime as dt
from collections import deque

import pyqtgraph as pg
from PyQt6.QtCore import QRegularExpression, Qt, QTimer, QUrl
from PyQt6.QtGui import QDesktopServices, QRegularExpressionValidator
from PyQt6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QPushButton, QScrollArea, QStackedWidget, QTextBrowser, QVBoxLayout,
    QWidget, QSpinBox, QFileDialog, QMenu,
)

from core import config
from core import quality as signal_quality
from core import storage
from core import __version__
from core.capture_requirements import CaptureRequirements
from core.connection import ConnectionController
from core.clinical_references import sts_comparison, timed_comparison
from core.kinematics import ALGORITHM_VERSION, Check, Metric, RepDetector, RepResult
from core.orientation import tilt_angle_diff_deg
from core.pipeline import SignalProcessor
from core.report import (ReportContext, effective_checks, interpretation_for,
                         measurement_verdict, participant_summary, render_html, verdict)
from core.sample_clock import reconstruct
from core.sensor_stream import ACC_RANGE_G, SensorStream, SimulatedSensorStream
from core.timed_capture import TimedCapture, TimedResult
from ui.theme import ACCENT, BAD, BG, BG_PANEL, BORDER, GOOD, MODES, STYLESHEET, TEXT, TEXT_MUTED, WARN
from ui.sensor_dialog import SensorDialog
from ui.widgets import MetricCard, OrientationBadge, PowerGauge
from ui.components import BrandMark

from ui.constants import *
from ui.pages import CapturePage, EventPage, HomePage, ResultPage, SetupPage


class MainWindow(QMainWindow):
    def __init__(self, simulate: bool = False):
        super().__init__()
        self.setWindowTitle(f"MMS · Biomecánica en movimiento · {__version__}")
        self.setStyleSheet(STYLESHEET)
        self.resize(1280, 820)
        self.setMinimumSize(940, 650)

        self.simulate = simulate
        storage.configure_storage(simulate)
        self.config = config.load()
        self.connection = ConnectionController(simulate=simulate)
        self.requirements = CaptureRequirements()
        self.sensor_status = "conectando"
        self.current_mode = None
        self.current_condition = ""
        self.current_age_years: int | None = None
        self.current_mass_kg: float | None = None
        self.detector: RepDetector | None = None
        self.raw_buffer: list[dict] = []
        self.session_context: storage.SessionContext | None = None
        self.current_sub = storage.next_participant_number()

        self.processor = SignalProcessor(SAMPLE_RATE_HZ, ACC_RANGE_G)
        self._references: dict = {}  # ubicacion del sensor -> cuaternion de referencia
        self.live_orientation = {"roll": 0.0, "pitch": 0.0, "angle_diff": None}
        # (hora de llegada, muestras perdidas antes) para el indicador de enlace en vivo
        self._link: deque = deque()

        self.stack = QStackedWidget()
        shell = QWidget()
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)
        shell_layout.addWidget(self._build_header())
        shell_layout.addWidget(self.stack, stretch=1)
        self.setCentralWidget(shell)
        signature = QLabel("Desarrollada por bmnigom")
        signature.setObjectName("signature")
        self.statusBar().setSizeGripEnabled(False)
        self.statusBar().addPermanentWidget(signature)
        self.statusBar().showMessage(f"MMS {__version__} · {'Datos simulados' if simulate else 'Adquisición con sensor'}")

        self.event_page = EventPage(self)
        self.home_page = HomePage(self)
        self.setup_page = SetupPage(self)
        self.capture_page = CapturePage(self)
        self.result_page = ResultPage(self)

        for page in (self.event_page, self.home_page, self.setup_page, self.capture_page, self.result_page):
            self.stack.addWidget(page)

        self.connection.status_changed.connect(self._on_sensor_status_changed)
        self.connection.error.connect(self._on_sensor_error)
        self.connection.sample_ready.connect(self._on_sample)
        self._health_timer = QTimer(self)
        self._health_timer.setInterval(200)
        self._health_timer.timeout.connect(self._refresh_requirements)
        self._health_timer.start()

        self._start_sensor()
        self.goto_event()

    def _build_header(self):
        header = QFrame()
        header.setObjectName("appHeader")
        row = QHBoxLayout(header)
        row.setContentsMargins(32, 13, 32, 13)
        row.setSpacing(12)
        row.addWidget(BrandMark())
        brand = QVBoxLayout()
        brand.setSpacing(0)
        title = QLabel("MMS")
        title.setObjectName("brand")
        subtitle = QLabel("BIOMECÁNICA EN MOVIMIENTO")
        subtitle.setObjectName("brandSubtitle")
        brand.addWidget(title)
        brand.addWidget(subtitle)
        row.addLayout(brand)
        row.addStretch()
        self._nav_buttons = []
        for text, callback in (("Experiencia", lambda: self.goto_event(False)),
                               ("Evaluaciones", lambda: self.goto_home(False))):
            button = QPushButton(text)
            button.setObjectName("navButton")
            button.clicked.connect(callback)
            row.addWidget(button)
            self._nav_buttons.append(button)
        data_button = QPushButton("Datos")
        data_button.setObjectName("navButton")
        menu = QMenu(data_button)
        menu.addAction("Abrir carpeta de datos", self.open_data_folder)
        menu.addAction("Crear respaldo…", self.export_backup)
        menu.addAction("Restaurar respaldo en una carpeta nueva…", self.restore_backup)
        data_button.setMenu(menu)
        row.addWidget(data_button)
        self._nav_buttons.append(data_button)
        if self.simulate:
            simulation = QLabel("SIMULACIÓN")
            simulation.setObjectName("simulationTag")
            simulation.setToolTip("Las mediciones y referencias se guardan separadas de los datos reales.")
            row.addWidget(simulation)
        return header

    def open_data_folder(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(storage.DATA_DIR))

    def export_backup(self):
        if self.capture_page._active:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Crear respaldo", "MMS-respaldo.zip", "Respaldo MMS (*.zip)")
        if not path:
            return
        try:
            storage.export_backup(path)
        except storage.SaveError as exc:
            QMessageBox.warning(self, "Respaldo", str(exc))
        else:
            self.statusBar().showMessage(f"Respaldo verificado: {path}", 10000)

    def restore_backup(self):
        if self.capture_page._active:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Restaurar respaldo", "", "Respaldo MMS (*.zip)")
        if not path:
            return
        try:
            folder = storage.restore_backup(path)
        except storage.SaveError as exc:
            QMessageBox.warning(self, "Restaurar respaldo", str(exc))
        else:
            QMessageBox.information(self, "Respaldo restaurado", f"Archivos verificados y restaurados en:\n{folder}")

    # -- Sensor lifecycle -----------------------------------------------
    @property
    def sensor(self):
        return self.connection.stream

    def _start_sensor(self):
        self.processor = SignalProcessor(SAMPLE_RATE_HZ, ACC_RANGE_G)
        self.requirements.reset()
        self._link.clear()
        self.connection.start(self.config["mac_address"])

    def _on_sensor_status_changed(self, status: str):
        self.sensor_status = status
        self.event_page.set_sensor_status(status)
        self.home_page.set_sensor_status(status)
        self._refresh_requirements()
        if status in ("desconectado", "error") and self.capture_page._active:
            self.capture_page.abort("Se interrumpió la transmisión del sensor durante la prueba.")

    def _on_sensor_error(self, message: str):
        if "Failed to discover gatt services" in message:
            message = ("No se pudieron leer los servicios Bluetooth del sensor (GATT). "
                       "Compruebe que esté encendido y libre para conectar")
        self.home_page.set_error_message(message)
        self.event_page.set_error_message(message)
        if self.capture_page._active:
            self.capture_page.abort(f"Se perdió la conexión con el sensor: {message}.")

    def sensor_running(self) -> bool:
        return self.sensor is not None and self.sensor.isRunning()

    def stop_sensor(self, wait_ms: int = 0):
        self.connection.stop()
        self.requirements.reset()

    def sensor_threads_alive(self) -> bool:
        return self.connection.has_running_threads()

    def configure_sensor(self):
        if self.capture_page._active:
            return
        dialog = SensorDialog(self.config["mac_address"], self.simulate, self, connection=self.connection)
        accepted = dialog.exec()
        if accepted and dialog.selected_mac:
            self.config["mac_address"] = dialog.selected_mac
            try:
                config.save(self.config)
            except OSError as exc:
                QMessageBox.warning(self, "Configuración", f"No se pudo guardar: {exc}")
        if accepted or not self.sensor_running():
            self._start_sensor()

    def retry_sensor(self):
        if not self.capture_page._active:
            self._start_sensor()

    def _refresh_requirements(self):
        check = self.requirements.capture_check(self.sensor_status)
        self.event_page.start_btn.setEnabled(check.allowed)
        self.setup_page.set_signal_readiness(check.allowed, check.message)
        calibrated = self.requirements.calibration_check(self.sensor_status, self.processor.ahrs.initialized)
        self.setup_page.calibrate_btn.setEnabled(calibrated.allowed)
        self.setup_page.calibrate_btn.setToolTip(calibrated.message or "Guardar esta inclinación como referencia.")
        for button in self._nav_buttons:
            button.setEnabled(not self.capture_page._active)

    def link_received_pct(self) -> float | None:
        """Porcentaje de muestras recibidas en los ultimos segundos."""
        if len(self._link) < 10:
            return None
        received = len(self._link)
        lost = sum(lost for _, lost in self._link)
        return 100.0 * received / (received + lost)

    def _on_sample(self, sample: dict):
        s = self.processor.process(sample)
        self.requirements.update(s)
        now = time.perf_counter()
        self._link.append((now, s.lost_before))
        while self._link and now - self._link[0][0] > LINK_WINDOW_S:
            self._link.popleft()

        angle_diff = None
        reference = self._reference_q()
        if reference is not None:
            angle_diff = tilt_angle_diff_deg(reference, self.processor.ahrs.q)
        self.live_orientation = {"roll": s.roll, "pitch": s.pitch, "angle_diff": angle_diff}

        row = {
            **sample,
            "a_vertical_m_s2": round(s.a_vertical, 4),
            "roll_deg": round(s.roll, 2), "pitch_deg": round(s.pitch, 2),
            "saturado": int(s.saturated),
            "signal_valid": int(s.signal_valid), "signal_error": s.signal_error,
            "gyro_pairing": s.gyro_pairing, "gyro_saturado": int(s.gyro_saturated),
            "gyro_saturated": int(s.gyro_saturated),
        }
        current = self.stack.currentWidget()
        if current is self.event_page:
            self.event_page.feed_sample(s)
        elif current is self.setup_page:
            self.setup_page.update_orientation(self.live_orientation)
        elif current is self.capture_page:
            self.capture_page.feed_sample(row, s)

    def _sensor_position(self) -> str | None:
        return MODES[self.current_mode]["sensor_pos"] if self.current_mode else None

    def _reference_q(self):
        """Referencia de la ubicacion de la prueba actual (cadera, muneca...)."""
        position = self._sensor_position()
        if position is None:
            return None
        if position not in self._references:
            self._references[position] = storage.load_reference_orientation(position)
        return self._references[position]

    def calibrate_reference(self) -> bool:
        position = self._sensor_position()
        if position is None:
            return False
        check = self.requirements.calibration_check(self.sensor_status, self.processor.ahrs.initialized)
        if not check.allowed:
            self.setup_page.form_error.setText(check.message)
            self.setup_page.form_error.setVisible(True)
            return False
        answer = QMessageBox.question(
            self, "Calibrar referencia",
            f"¿Guardar la inclinación actual como referencia para el sensor en «{position.lower()}»?\n\n"
            "Hágalo con el sensor bien colocado en la postura inicial de la prueba. "
            "Reemplaza la referencia anterior de esa ubicación.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return False
        check = self.requirements.calibration_check(self.sensor_status, self.processor.ahrs.initialized)
        if not check.allowed:
            self.setup_page.form_error.setText(check.message)
            self.setup_page.form_error.setVisible(True)
            return False
        q = self.processor.ahrs.q.copy()
        try:
            storage.save_reference_orientation(position, list(q))
        except (OSError, ValueError, storage.SaveError) as exc:
            QMessageBox.warning(self, "Calibrar referencia", f"No se pudo guardar la referencia: {exc}")
            return False
        self._references[position] = list(q)
        self.setup_page.form_error.setText("")
        self.statusBar().showMessage("Referencia de inclinación guardada", 5000)
        return True

    def closeEvent(self, event):
        if getattr(self.capture_page, "_active", False):
            self.capture_page.abort("La aplicación se cerró durante la captura.")
        self.capture_page._stop()
        self._health_timer.stop()
        self.connection.shutdown()
        event.accept()

    # -- Navegacion -------------------------------------------------------
    def goto_event(self, new_participant: bool = True):
        if getattr(self.capture_page, "_active", False):
            return
        if new_participant:
            self._new_participant()
        self.stack.setCurrentWidget(self.event_page)

    def _new_participant(self):
        """Borra los datos de la persona anterior: su peso no debe usarse con la siguiente."""
        self.current_sub = storage.next_participant_number()
        self.current_age_years = None
        self.current_mass_kg = None
        self.setup_page.reset_participant()

    def start_event(self):
        self.current_mode = "event"
        self.start_capture(None, self.current_sub)

    def goto_home(self, new_participant: bool = True):
        if getattr(self.capture_page, "_active", False):
            return
        if new_participant:
            self._new_participant()
        self.home_page.refresh()
        self.stack.setCurrentWidget(self.home_page)

    def start_setup(self, mode_key: str):
        if getattr(self.capture_page, "_active", False):
            return
        self.current_mode = mode_key
        self.setup_page.load_mode(mode_key)
        self.stack.setCurrentWidget(self.setup_page)

    def start_capture(
        self, mass_kg: float | None, sub_id: str, condition: str = "", age_years: int | None = None
    ):
        if getattr(self.capture_page, "_active", False):
            return False
        check = self.requirements.capture_check(self.sensor_status)
        if not check.allowed:
            self.setup_page.form_error.setText(check.message)
            self.setup_page.form_error.setVisible(True)
            if self.current_mode == "event":
                self.event_page.status_label.setText(check.message)
            return False
        meta = MODES[self.current_mode]
        try:
            self.session_context = storage.create_session(
                sub_id, meta["task_code"], metadata={
                    "algorithm_version": ALGORITHM_VERSION, "protocol": self.current_mode,
                    "sensor_position": meta["sensor_pos"], "sensor_mac": self.config["mac_address"] if not self.simulate else None,
                    "sample_rate_hz": SAMPLE_RATE_HZ, "acc_range_g": ACC_RANGE_G,
                    "mass_kg": mass_kg, "age_years": age_years, "condition": condition,
                    "reference_orientation": self._reference_q(),
                })
        except storage.SaveError as exc:
            self.setup_page.form_error.setText(str(exc))
            self.setup_page.form_error.setVisible(True)
            if self.current_mode == "event":
                self.event_page.status_label.setText(str(exc))
            return False
        self.current_sub = sub_id
        self.current_condition = condition
        self.current_age_years = age_years
        self.current_mass_kg = mass_kg
        self.detector = (
            RepDetector(self.current_mode, mass_kg or 70.0, SAMPLE_RATE_HZ)
            if meta["capture_type"] == "power" else None
        )
        self.connection.set_profile(self.current_mode)
        self.raw_buffer = []
        self.capture_page.load_mode(self.current_mode)
        self.stack.setCurrentWidget(self.capture_page)
        self._refresh_requirements()
        return True

    def finish_capture(self, result, abort_reason: str | None = None):
        mode = self.current_mode
        meta = MODES[mode]
        task = meta["task_code"]
        is_timed = isinstance(result, TimedResult)
        # Un fallo al guardar (disco lleno, archivo bloqueado...) no debe impedir mostrar el
        # resultado: se avisa en el reporte y en pantalla.
        save_warnings: list[str] = []
        session = self.session_context
        if session is None:
            session = storage.create_session(self.current_sub, task,
                                             metadata={"algorithm_version": ALGORITHM_VERSION})
        run = session.run
        timing_error = None
        try:
            self._finalize_times()
        except (TypeError, ValueError, OverflowError) as exc:
            timing_error = Check("Tiempo IMU", "fail",
                                 f"No se pudo reconstruir el tiempo nativo del sensor ({exc}). "
                                 "Los datos IMU no son válidos para análisis; repita la captura.")
        raw_path = ""
        if self.raw_buffer:
            try:
                raw_path = storage.save_raw_session(self.current_sub, task, run, self.raw_buffer, session=session)
            except storage.SaveError as exc:
                save_warnings.append(str(exc))
        quality = signal_quality.assess(self.raw_buffer, SAMPLE_RATE_HZ)

        def save_row(append, *args, **kwargs):
            try:
                warning = append(*args, session=session, **kwargs)
            except storage.SaveError as exc:
                warning = str(exc)
            if warning:
                save_warnings.append(warning)

        checks: list[Check] = []
        if timing_error:
            checks.append(timing_error)
        if abort_reason:
            checks.append(Check("Conexión con el sensor", "fail", abort_reason))
        # Estricto en las pruebas que se calculan con la señal IMU (igual que el reprocesado).
        checks.append(signal_quality.transmission_check(quality, strict=not is_timed, requires_gyro=mode in ("sts", "punch")))
        comparison_html = ""
        previous = None

        if is_timed:
            metrics = []
            if result.sample_count:
                metrics.append(Metric("duration_s", "Tiempo", result.duration_s, "s", 1, primary=True))
                if mode == "walk" and result.duration_s > 0:
                    metrics.append(Metric("velocidad_marcha", "Velocidad media", 5.0 / result.duration_s, "m/s", 2))
                if result.ended_by == "limit":
                    checks.append(Check("Finalización", "ok", "Terminó automáticamente al cumplir el tiempo."))
                elif result.ended_by != "desconexion":
                    checks.append(Check("Finalización", "ok", "Detenido por el operador."))
            else:
                checks.append(Check("Datos del sensor", "fail", "No se recibieron datos durante la prueba."))
            if quality.saturated:
                checks.append(Check("Saturación del acelerómetro", "warn",
                                    f"{quality.saturated} muestras en el límite del sensor."))
            duration = result.duration_s
            validity_context = ReportContext(mode, meta["label"], meta["sensor_pos"],
                                              self.current_sub, run, result.duration_s, metrics, checks)
            checks = effective_checks(validity_context)
            valid_timed = measurement_verdict(validity_context)[0] != "fail"
            if valid_timed:
                before = storage.previous_value(self.current_sub, task, timed=True,
                                                condition=self.current_condition)
                if before is not None:
                    previous = ("Tiempo", before, result.duration_s, "s")
                if mode != "event":
                    comparison_html = _comparison_html(
                        timed_comparison(mode, result.duration_s, self.current_age_years))
            save_row(storage.append_timed_result, self.current_sub, task, run, result,
                     self.current_condition, self.current_age_years, quality,
                     valid=valid_timed, reasons=" | ".join(c.detail for c in checks if c.status == "fail"),
                     algorithm_version=ALGORITHM_VERSION)
            method = ("Cronómetro accionado por el operador (reloj monotónico del computador). "
                      "La señal IMU se guarda como registro complementario.")
        else:
            rep: RepResult = result
            if (mode == "jump" and rep.metric("potencia_pico_w") is not None
                    and self.current_age_years is not None and self.current_age_years < 18):
                checks.append(Check(
                    "Ecuación de potencia", "warn",
                    "La ecuación de Sayers se obtuvo en adultos jóvenes: en menores de 18 años la potencia "
                    "estimada es poco fiable. La altura del salto sí es válida.",
                ))
            # El CSV (columna "valido") y el reporte usan las mismas verificaciones.
            rep.checks = checks + rep.checks
            checks = rep.checks
            metrics = rep.metrics
            duration = rep.duration_s
            method = rep.method
            validity_context = ReportContext(mode, meta["label"], meta["sensor_pos"],
                                              self.current_sub, run, duration, metrics, checks)
            checks = effective_checks(validity_context)
            rep.checks = checks
            primary = rep.primary
            if primary is not None:
                before = storage.previous_value(self.current_sub, task, timed=False, metric_key=primary.key)
                if before is not None and rep.valid:
                    previous = (primary.label, before, primary.value, primary.unit)
            save_row(storage.append_result, self.current_sub, task, run, rep, quality,
                     self.current_mass_kg, self.current_age_years, ALGORITHM_VERSION)
            if mode == "sts":
                comparison_html = _comparison_html(sts_comparison())

        side = {"left": "pierna de apoyo izquierda", "right": "pierna de apoyo derecha"}.get(self.current_condition, "")
        ctx = ReportContext(
            mode_key=mode, test_label=meta["label"], sensor_pos=meta["sensor_pos"],
            sub=self.current_sub, run=run, duration_s=duration if not is_timed else None,
            metrics=metrics, checks=checks, method=method,
            interpretation=interpretation_for(mode), comparison_html=comparison_html,
            previous=previous, mass_kg=self.current_mass_kg if meta.get("needs_mass") else None,
            age_years=self.current_age_years, condition=side,
            raw_file=os.path.basename(raw_path) if raw_path else "",
            participant_text=participant_summary(
                mode, measurement_verdict(ReportContext(mode, meta["label"], meta["sensor_pos"],
                     self.current_sub, run, duration, metrics, checks))[0], metrics, self.current_age_years),
            save_warnings=save_warnings,
            timestamp=session.timestamp, session_id=session.session_id, data_source=session.origin,
        )
        try:
            report_path = storage.save_report(self.current_sub, task, run, render_html(ctx, standalone=True), session=session)
        except storage.SaveError as exc:
            report_path = ""
            ctx.save_warnings.append(str(exc))
        self.result_page.show_report(mode, ctx, report_path)
        self.stack.setCurrentWidget(self.result_page)
        self.session_context = None
        self._refresh_requirements()

    def _finalize_times(self):
        """Reemplaza los tiempos provisionales por los reconstruidos (con perdidas detectadas)."""
        if len(self.raw_buffer) < 2:
            return
        times, lost = reconstruct([r["host_time"] for r in self.raw_buffer], SAMPLE_RATE_HZ,
                                  device_times=[r.get("device_time") for r in self.raw_buffer],
                                  sequences=[r.get("sequence") for r in self.raw_buffer])
        for row, t, k in zip(self.raw_buffer, times, lost):
            row["time"] = round(float(t), 4)
            row["lost_before"] = int(k)


def _comparison_html(comparison) -> str:
    source = (f' <a href="{comparison.source_url}">Fuente: {comparison.source_name}</a>'
              if comparison.source_url else "")
    return (f'<table width="100%" cellpadding="10" style="background-color:{BG_PANEL}; color:{TEXT};"><tr><td>'
            f'<b>{comparison.title}</b><br>{comparison.explanation}{source}</td></tr></table>')
