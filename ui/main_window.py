"""Ventana principal para experiencias de evento y evaluación funcional."""
import os
import time
from collections import deque

import pyqtgraph as pg
from PyQt6.QtCore import Qt, QTimer, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QPushButton, QScrollArea, QStackedWidget, QTextBrowser, QVBoxLayout, QWidget,
    QSpinBox,
)

from core import config
from core import quality as signal_quality
from core import storage
from core.clinical_references import sts_comparison, timed_comparison
from core.kinematics import ALGORITHM_VERSION, Check, Metric, RepDetector, RepResult
from core.orientation import tilt_angle_diff_deg
from core.pipeline import SignalProcessor
from core.report import ReportContext, interpretation_for, render_html, verdict
from core.sample_clock import reconstruct
from core.sensor_stream import ACC_RANGE_G, SensorStream, SimulatedSensorStream
from core.timed_capture import TimedCapture, TimedResult
from ui.theme import ACCENT, BAD, BG_PANEL, BORDER, GOOD, MODES, STYLESHEET, TEXT_MUTED, WARN
from ui.sensor_dialog import SensorDialog
from ui.widgets import MetricCard, OrientationBadge, PowerGauge

PLOT_WINDOW_S = 4.0
SAMPLE_RATE_HZ = 100.0
NO_REP_TIMEOUT_MS = 20_000
PLOT_REFRESH_MS = 33
LINK_WINDOW_S = 2.0


class MainWindow(QMainWindow):
    def __init__(self, simulate: bool = False):
        super().__init__()
        self.setWindowTitle("Laboratorio de Biomecánica en Movimiento")
        self.setStyleSheet(STYLESHEET)
        self.resize(1120, 760)
        self.setMinimumSize(940, 650)

        self.simulate = simulate
        self.config = config.load()
        self.sensor = None
        self.sensor_status = "conectando"
        self.current_mode = None
        self.current_condition = ""
        self.current_age_years: int | None = None
        self.current_mass_kg: float | None = None
        self.detector: RepDetector | None = None
        self.raw_buffer: list[dict] = []
        self.current_sub = storage.next_participant_number()

        self.processor = SignalProcessor(SAMPLE_RATE_HZ, ACC_RANGE_G)
        self.reference_q = storage.load_reference_orientation()
        self.live_orientation = {"roll": 0.0, "pitch": 0.0, "angle_diff": None}
        # (hora de llegada, muestras perdidas antes) para el indicador de enlace en vivo
        self._link: deque = deque()

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)
        signature = QLabel("Desarrollada por bmnigom")
        signature.setObjectName("signature")
        self.statusBar().setSizeGripEnabled(False)
        self.statusBar().addPermanentWidget(signature)

        self.event_page = EventPage(self)
        self.home_page = HomePage(self)
        self.setup_page = SetupPage(self)
        self.capture_page = CapturePage(self)
        self.result_page = ResultPage(self)

        for page in (self.event_page, self.home_page, self.setup_page, self.capture_page, self.result_page):
            self.stack.addWidget(page)

        self._start_sensor()
        self.goto_event()

    # -- Sensor lifecycle -----------------------------------------------
    def _start_sensor(self):
        cls = SimulatedSensorStream if self.simulate else SensorStream
        self.processor = SignalProcessor(SAMPLE_RATE_HZ, ACC_RANGE_G)
        self._link.clear()
        self.sensor = cls() if self.simulate else cls(self.config["mac_address"])
        self.sensor.status_changed.connect(self.home_page.set_sensor_status)
        self.sensor.status_changed.connect(self.event_page.set_sensor_status)
        self.sensor.error.connect(self._on_sensor_error)
        self.sensor.sample_ready.connect(self._on_sample)
        self.sensor.start()

    def _on_sensor_error(self, message: str):
        if "Failed to discover gatt services" in message:
            message = (
                "No se pudieron leer los servicios Bluetooth del sensor (GATT). "
                "Comprueba que esté encendido y que ninguna otra aplicación lo esté usando"
            )
        self.home_page.set_sensor_status("error")
        self.home_page.set_error_message(message)
        self.event_page.set_sensor_status("error")
        self.event_page.set_error_message(message)
        if self.stack.currentWidget() is self.capture_page:
            self.capture_page.abort(f"Se perdió la conexión con el sensor durante la prueba: {message}.")

    def stop_sensor(self):
        if self.sensor is not None and self.sensor.isRunning():
            # Sus avisos de "desconectado" ya no corresponden al sensor que se usará.
            self.sensor.blockSignals(True)
            self.sensor.request_stop()
            self.sensor.wait(5000)

    def configure_sensor(self):
        """Elegir otro sensor (buscar por Bluetooth o escribir la MAC)."""
        if self.stack.currentWidget() is self.capture_page:
            return
        dialog = SensorDialog(self.config["mac_address"], self.simulate, self)
        accepted = dialog.exec()
        if accepted and dialog.selected_mac:
            self.config["mac_address"] = dialog.selected_mac
            config.save(self.config)
        if accepted or not self.sensor.isRunning():
            self.stop_sensor()
            self.event_page.set_sensor_status("conectando")
            self.home_page.set_sensor_status("conectando")
            self._start_sensor()

    def retry_sensor(self):
        if self.sensor.isRunning():
            return
        self.event_page.set_sensor_status("conectando")
        self.home_page.set_sensor_status("conectando")
        self._start_sensor()

    def link_received_pct(self) -> float | None:
        """Porcentaje de muestras recibidas en los ultimos segundos."""
        if len(self._link) < 10:
            return None
        received = len(self._link)
        lost = sum(lost for _, lost in self._link)
        return 100.0 * received / (received + lost)

    def _on_sample(self, sample: dict):
        s = self.processor.process(sample)
        now = time.perf_counter()
        self._link.append((now, s.lost_before))
        while self._link and now - self._link[0][0] > LINK_WINDOW_S:
            self._link.popleft()

        angle_diff = None
        if self.reference_q is not None:
            angle_diff = tilt_angle_diff_deg(self.reference_q, self.processor.ahrs.q)
        self.live_orientation = {"roll": s.roll, "pitch": s.pitch, "angle_diff": angle_diff}

        row = {
            **sample,
            "a_vertical_m_s2": round(s.a_vertical, 4),
            "roll_deg": round(s.roll, 2), "pitch_deg": round(s.pitch, 2),
            "saturado": int(s.saturated),
        }
        current = self.stack.currentWidget()
        if current is self.event_page:
            self.event_page.feed_sample(s)
        elif current is self.setup_page:
            self.setup_page.update_orientation(self.live_orientation)
        elif current is self.capture_page:
            self.capture_page.feed_sample(row, s)

    def calibrate_reference(self):
        self.reference_q = self.processor.ahrs.q.copy()
        storage.save_reference_orientation(list(self.reference_q))

    def closeEvent(self, event):
        self.stop_sensor()
        event.accept()

    # -- Navegacion -------------------------------------------------------
    def goto_event(self, new_participant: bool = True):
        if new_participant:
            self.current_sub = storage.next_participant_number()
            self.current_age_years = None
            self.setup_page.age_input.setValue(0)
        self.stack.setCurrentWidget(self.event_page)

    def start_event(self):
        self.current_mode = "event"
        self.start_capture(None, self.current_sub)

    def goto_home(self, new_participant: bool = True):
        if new_participant:
            self.current_sub = storage.next_participant_number()
            self.current_age_years = None
            self.setup_page.age_input.setValue(0)
        self.home_page.refresh()
        self.stack.setCurrentWidget(self.home_page)

    def start_setup(self, mode_key: str):
        self.current_mode = mode_key
        self.setup_page.load_mode(mode_key)
        self.stack.setCurrentWidget(self.setup_page)

    def start_capture(
        self, mass_kg: float | None, sub_id: str, condition: str = "", age_years: int | None = None
    ):
        self.current_sub = sub_id
        self.current_condition = condition
        self.current_age_years = age_years
        self.current_mass_kg = mass_kg
        meta = MODES[self.current_mode]
        self.detector = (
            RepDetector(self.current_mode, mass_kg or 70.0, SAMPLE_RATE_HZ)
            if meta["capture_type"] == "power" else None
        )
        self.sensor.set_profile(self.current_mode)
        self.raw_buffer = []
        self.capture_page.load_mode(self.current_mode)
        self.stack.setCurrentWidget(self.capture_page)

    def finish_capture(self, result, abort_reason: str | None = None):
        mode = self.current_mode
        meta = MODES[mode]
        task = meta["task_code"]
        is_timed = isinstance(result, TimedResult)
        run = storage.next_run_number(self.current_sub, task)
        self._finalize_times()
        raw_path = storage.save_raw_session(self.current_sub, task, run, self.raw_buffer) if self.raw_buffer else ""
        quality = signal_quality.assess(self.raw_buffer, SAMPLE_RATE_HZ)

        checks: list[Check] = []
        if abort_reason:
            checks.append(Check("Conexión con el sensor", "fail", abort_reason))
        checks.append(signal_quality.transmission_check(quality, strict=False))
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
                else:
                    checks.append(Check("Finalización", "ok", "Detenido por el operador."))
            else:
                checks.append(Check("Datos del sensor", "fail", "No se recibieron datos durante la prueba."))
            if quality.saturated:
                checks.append(Check("Saturación del acelerómetro", "warn",
                                    f"{quality.saturated} muestras en el límite del sensor."))
            duration = result.duration_s
            if result.sample_count and not abort_reason:
                before = storage.previous_value(self.current_sub, task, timed=True,
                                                condition=self.current_condition)
                if before is not None:
                    previous = ("Tiempo", before, result.duration_s, "s")
                storage.append_timed_result(self.current_sub, task, run, result, self.current_condition,
                                            self.current_age_years, quality)
                if mode != "event":
                    comparison_html = _comparison_html(
                        timed_comparison(mode, result.duration_s, self.current_age_years))
            method = ("Cronómetro accionado por el operador (reloj monotónico del computador). "
                      "La señal IMU se guarda como registro complementario.")
        else:
            rep: RepResult = result
            # El CSV (columna "valido") y el reporte usan las mismas verificaciones.
            rep.checks = checks + rep.checks
            checks = rep.checks
            metrics = rep.metrics
            duration = rep.duration_s
            method = rep.method
            primary = rep.primary
            if primary is not None:
                before = storage.previous_value(self.current_sub, task, timed=False, metric_key=primary.key)
                if before is not None and rep.valid:
                    previous = (primary.label, before, primary.value, primary.unit)
            storage.append_result(self.current_sub, task, run, rep, quality, self.current_mass_kg,
                                  self.current_age_years, ALGORITHM_VERSION)
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
        )
        report_path = storage.save_report(self.current_sub, task, run, render_html(ctx, standalone=True))
        self.result_page.show_report(mode, ctx, report_path)
        self.stack.setCurrentWidget(self.result_page)

    def _finalize_times(self):
        """Reemplaza los tiempos provisionales por los reconstruidos (con perdidas detectadas)."""
        if len(self.raw_buffer) < 2:
            return
        times, lost = reconstruct([r["host_time"] for r in self.raw_buffer], SAMPLE_RATE_HZ)
        for row, t, k in zip(self.raw_buffer, times, lost):
            row["time"] = round(float(t), 4)
            row["lost_before"] = int(k)


def _comparison_html(comparison) -> str:
    source = (f' <a href="{comparison.source_url}">Fuente: {comparison.source_name}</a>'
              if comparison.source_url else "")
    return (f'<table width="100%" cellpadding="10" style="background-color:#EEF4F7;"><tr><td>'
            f'<b>{comparison.title}</b><br>{comparison.explanation}{source}</td></tr></table>')


class EventPage(QWidget):
    def __init__(self, main_window: MainWindow):
        super().__init__()
        self.main_window = main_window
        layout = QVBoxLayout(self)
        layout.setContentsMargins(74, 30, 74, 24)
        layout.setSpacing(9)

        eyebrow = QLabel("MMS  /  EXPERIENCIA INTERACTIVA")
        eyebrow.setObjectName("eyebrow")
        title = QLabel("Descubre tu movimiento")
        title.setObjectName("eventTitle")
        lead = QLabel("Una experiencia de 20 segundos con un sensor de movimiento.")
        lead.setObjectName("eventLead")
        lead.setWordWrap(True)
        layout.addWidget(eyebrow)
        layout.addSpacing(8)
        layout.addWidget(title)
        layout.addWidget(lead)
        layout.addSpacing(12)

        panel = QFrame()
        panel.setObjectName("panel")
        panel_layout = QHBoxLayout(panel)
        panel_layout.setContentsMargins(24, 12, 24, 12)
        number = QLabel("20")
        number.setObjectName("eventNumber")
        unit = QLabel("segundos\npara explorar la señal IMU en vivo")
        unit.setObjectName("eventLead")
        unit.setWordWrap(True)
        panel_layout.addWidget(number)
        panel_layout.addSpacing(18)
        panel_layout.addWidget(unit, stretch=1)
        layout.addWidget(panel)
        layout.addSpacing(8)

        instruction = QLabel("Coloca el sensor en la muñeca y mueve el brazo cómodamente.")
        instruction.setObjectName("eventLead")
        instruction.setWordWrap(True)
        layout.addWidget(instruction)
        self.status_label = QLabel("Conectando al sensor…")
        self.status_label.setStyleSheet(f"color: {WARN}; font-size: 15px; font-weight: 600;")
        layout.addWidget(self.status_label)
        self.link_label = QLabel()
        self.link_label.setObjectName("muted")
        layout.addWidget(self.link_label)
        self.retry_btn = QPushButton("Reintentar conexión")
        self.retry_btn.clicked.connect(self.main_window.retry_sensor)
        sensor_row = QHBoxLayout()
        sensor_row.addWidget(self.retry_btn)
        self.sensor_btn = QPushButton("Configurar sensor")
        self.sensor_btn.clicked.connect(self.main_window.configure_sensor)
        sensor_row.addWidget(self.sensor_btn)
        sensor_row.addStretch()
        layout.addLayout(sensor_row)
        self.retry_btn.hide()

        signal_title = QLabel("SEÑAL DEL SENSOR EN VIVO")
        signal_title.setObjectName("eyebrow")
        layout.addSpacing(6)
        layout.addWidget(signal_title)
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground(BG_PANEL)
        self.plot_widget.setMinimumHeight(95)
        self.plot_widget.showGrid(x=True, y=True, alpha=0.15)
        self.plot_widget.hideAxis("bottom")
        self.plot_widget.hideAxis("left")
        self.curve = self.plot_widget.plot(pen=pg.mkPen(color=ACCENT, width=3))
        self._t_buf: deque = deque(maxlen=300)
        self._a_buf: deque = deque(maxlen=300)
        layout.addWidget(self.plot_widget, stretch=1)

        actions = QHBoxLayout()
        self.start_btn = QPushButton("Iniciar experiencia  →")
        self.start_btn.setObjectName("eventButton")
        self.start_btn.clicked.connect(self.main_window.start_event)
        assessments_btn = QPushButton("Ver todas las pruebas")
        assessments_btn.clicked.connect(lambda: self.main_window.goto_home(False))
        actions.addWidget(self.start_btn)
        actions.addStretch()
        actions.addWidget(assessments_btn)
        layout.addLayout(actions)
        credit = QLabel("Desarrollada por bmnigom")
        credit.setObjectName("muted")
        layout.addSpacing(8)
        layout.addWidget(credit)
        self.set_sensor_status("conectando")

        self._refresh = QTimer(self)
        self._refresh.setInterval(PLOT_REFRESH_MS)
        self._refresh.timeout.connect(self._redraw)
        self._refresh.start()

    def set_sensor_status(self, status: str):
        self.main_window.sensor_status = status
        messages = {
            "conectando": "Conectando al sensor…",
            "conectado": "Sensor conectado. Preparando señal…",
            "transmitiendo": "Sensor listo para comenzar",
            "desconectado": "Sensor desconectado. Comprueba Bluetooth o usa Simular_MMS.cmd.",
            "error": "Error del sensor. Comprueba Bluetooth o usa Simular_MMS.cmd.",
        }
        self.status_label.setText(messages.get(status, status))
        self.status_label.setStyleSheet(
            f"color: {GOOD if status == 'transmitiendo' else BAD if status in ('error', 'desconectado') else WARN}; font-size: 15px; font-weight: 600;"
        )
        self.start_btn.setEnabled(status == "transmitiendo")
        self.retry_btn.setVisible(status in ("error", "desconectado"))
        if status != "transmitiendo":
            self.link_label.setText("")

    def set_error_message(self, message: str):
        self.status_label.setText(f"Sensor: {message}. Puedes abrir Simular_MMS.cmd para probar la interfaz.")

    def feed_sample(self, s):
        self._t_buf.append(s.t)
        self._a_buf.append(s.a_vertical)

    def _redraw(self):
        if not self.isVisible():
            return
        self.curve.setData(list(self._t_buf), list(self._a_buf))
        if self.main_window.sensor_status == "transmitiendo":
            self.link_label.setText(_link_text(self.main_window.link_received_pct()))


def _link_text(pct: float | None) -> str:
    if pct is None:
        return ""
    state = "buena" if pct >= signal_quality.GOOD_RECEIVED_PCT else (
        "irregular" if pct >= signal_quality.MIN_RECEIVED_PCT else "mala: acerque el computador al sensor")
    return f"Señal Bluetooth: {pct:.0f} % de muestras recibidas · {state}"


class HomePage(QWidget):
    def __init__(self, main_window: MainWindow):
        super().__init__()
        self.main_window = main_window

        layout = QVBoxLayout(self)
        layout.setContentsMargins(64, 48, 64, 48)
        layout.setSpacing(12)

        eyebrow = QLabel("LABORATORIO  /  ADQUISICIÓN DE MOVIMIENTO")
        eyebrow.setObjectName("eyebrow")
        title = QLabel("Biomecánica en movimiento")
        title.setObjectName("title")
        subtitle = QLabel("Seleccione una prueba para iniciar una nueva medición.")
        subtitle.setObjectName("subtitle")
        layout.addWidget(eyebrow)
        event_btn = QPushButton("← Volver a experiencia de evento")
        event_btn.clicked.connect(lambda: self.main_window.goto_event(False))
        layout.addWidget(event_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addSpacing(8)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(24)

        status_panel = QFrame()
        status_panel.setObjectName("panel")
        status_layout = QHBoxLayout(status_panel)
        status_layout.setContentsMargins(20, 16, 20, 16)
        status_title = QLabel("ESTADO DEL SENSOR")
        status_title.setObjectName("eyebrow")
        self.status_label = QLabel("Conectando al sensor…")
        self.status_label.setStyleSheet(f"color: {WARN}; font-weight: 600; background: transparent;")
        self.retry_btn = QPushButton("Reintentar conexión")
        self.retry_btn.clicked.connect(self.main_window.retry_sensor)
        self.retry_btn.hide()
        status_layout.addWidget(status_title)
        status_layout.addStretch()
        status_layout.addWidget(self.status_label)
        status_layout.addWidget(self.retry_btn)
        sensor_btn = QPushButton("Configurar sensor")
        sensor_btn.clicked.connect(self.main_window.configure_sensor)
        status_layout.addWidget(sensor_btn)
        layout.addWidget(status_panel)
        layout.addSpacing(26)

        section = QLabel("Pruebas disponibles")
        section.setObjectName("sectionTitle")
        layout.addWidget(section)
        hint = QLabel("Siete protocolos disponibles. Desplácese para verlos todos.")
        hint.setObjectName("muted")
        layout.addWidget(hint)
        layout.addSpacing(8)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        cards_container = QWidget()
        cards_grid = QGridLayout(cards_container)
        cards_grid.setContentsMargins(0, 0, 8, 0)
        cards_grid.setHorizontalSpacing(16)
        cards_grid.setVerticalSpacing(16)
        for index, (key, meta) in enumerate((item for item in MODES.items() if item[0] != "event")):
            card = QFrame()
            card.setObjectName("modeCard")
            card.setMinimumHeight(210)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(20, 20, 20, 20)
            card_layout.setSpacing(12)
            number = QLabel(meta["number"])
            number.setStyleSheet(f"color: {meta['color']}; font-size: 27px; font-weight: 700; background: transparent;")
            name = QLabel(meta["label"])
            name.setStyleSheet("font-size: 18px; font-weight: 650; background: transparent;")
            position = QLabel(f"Sensor: {meta['sensor_pos'].lower()}")
            position.setObjectName("muted")
            position.setWordWrap(True)
            position.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
            description = QLabel(meta["instructions"])
            description.setWordWrap(True)
            description.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent; line-height: 1.3;")
            btn = QPushButton("Seleccionar prueba  →")
            btn.setObjectName("modeButton")
            btn.clicked.connect(lambda _, k=key: self.main_window.start_setup(k))
            card_layout.addWidget(number)
            card_layout.addSpacing(10)
            card_layout.addWidget(name)
            card_layout.addWidget(position)
            card_layout.addSpacing(12)
            card_layout.addWidget(description)
            card_layout.addStretch()
            card_layout.addWidget(btn)
            cards_grid.addWidget(card, index // 3, index % 3)
        scroll.setWidget(cards_container)
        layout.addWidget(scroll, stretch=1)
        layout.addSpacing(12)
        footer = QLabel("MMS  ·  Registro IMU y pruebas funcionales")
        footer.setObjectName("muted")
        layout.addWidget(footer)

    def set_sensor_status(self, status: str):
        colors = {
            "conectando": WARN, "conectado": WARN, "transmitiendo": GOOD,
            "desconectado": BAD, "error": BAD,
        }
        texts = {
            "conectando": "Conectando al sensor...",
            "conectado": "Conectado, preparando transmisión...",
            "transmitiendo": "Sensor conectado y transmitiendo",
            "desconectado": "Sensor desconectado",
            "error": "Error de conexión con el sensor",
        }
        self.status_label.setText(texts.get(status, status))
        self.status_label.setStyleSheet(
            f"color: {colors.get(status, TEXT_MUTED)}; font-weight: 600; background: transparent;"
        )
        self.retry_btn.setVisible(status in ("error", "desconectado"))

    def set_error_message(self, message: str):
        self.status_label.setText(f"Error: {message}")

    def refresh(self):
        pass


class SetupPage(QWidget):
    def __init__(self, main_window: MainWindow):
        super().__init__()
        self.main_window = main_window
        self.mode_key = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(64, 48, 64, 48)
        layout.setSpacing(14)

        eyebrow = QLabel("PREPARACIÓN DE LA PRUEBA")
        eyebrow.setObjectName("eyebrow")
        layout.addWidget(eyebrow)

        self.title_label = QLabel()
        self.title_label.setObjectName("title")

        self.instructions_label = QLabel()
        self.instructions_label.setObjectName("subtitle")
        self.instructions_label.setWordWrap(True)

        content_row = QHBoxLayout()
        content_row.setSpacing(36)

        # -- columna izquierda: peso + participante ------------------------
        form_col = QVBoxLayout()
        self.mass_label = QLabel("Peso corporal (kg)")
        form_col.addWidget(self.mass_label)
        self.mass_input = QDoubleSpinBox()
        self.mass_input.setRange(15.0, 200.0)
        self.mass_input.setValue(70.0)
        self.mass_input.setFixedWidth(190)
        form_col.addWidget(self.mass_input)

        form_col.addSpacing(16)
        form_col.addWidget(QLabel("N° de participante"))
        self.sub_input = QLineEdit()
        self.sub_input.setFixedWidth(190)
        form_col.addWidget(self.sub_input)

        form_col.addSpacing(16)
        form_col.addWidget(QLabel("Edad (años, opcional)"))
        self.age_input = QSpinBox()
        self.age_input.setRange(0, 110)
        self.age_input.setSpecialValueText("No indicada")
        self.age_input.setFixedWidth(190)
        form_col.addWidget(self.age_input)

        form_col.addSpacing(16)
        self.condition_label = QLabel("Pierna de apoyo")
        form_col.addWidget(self.condition_label)
        self.condition_input = QComboBox()
        self.condition_input.addItem("Izquierda", "left")
        self.condition_input.addItem("Derecha", "right")
        self.condition_input.setFixedWidth(190)
        form_col.addWidget(self.condition_input)
        form_col.addStretch()
        content_row.addLayout(form_col)

        # -- columna derecha: badge de orientacion -------------------------
        orientation_col = QVBoxLayout()
        orientation_col.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        orientation_col.addWidget(QLabel("Inclinación del sensor"), alignment=Qt.AlignmentFlag.AlignHCenter)
        self.orientation_badge = OrientationBadge()
        orientation_col.addWidget(self.orientation_badge)
        calibrate_btn = QPushButton("Calibrar referencia")
        calibrate_btn.clicked.connect(self._on_calibrate)
        orientation_col.addWidget(calibrate_btn)
        content_row.addLayout(orientation_col)

        buttons_row = QHBoxLayout()
        back_btn = QPushButton("Volver")
        back_btn.clicked.connect(lambda: self.main_window.goto_home(False))
        self.start_btn = QPushButton("Comenzar")
        self.start_btn.setObjectName("primaryButton")
        self.start_btn.clicked.connect(self._on_start)
        buttons_row.addWidget(back_btn)
        buttons_row.addStretch()
        buttons_row.addWidget(self.start_btn)

        layout.addWidget(self.title_label)
        layout.addWidget(self.instructions_label)
        layout.addSpacing(24)
        layout.addLayout(content_row)
        layout.addStretch()
        layout.addLayout(buttons_row)

    def load_mode(self, mode_key: str):
        self.mode_key = mode_key
        meta = MODES[mode_key]
        self.title_label.setText(meta["label"])
        self.instructions_label.setText(
            f"{meta['instructions']}\n\nUbicación: {meta['sensor_pos']}."
        )
        is_power = meta["capture_type"] == "power"
        needs_mass = bool(meta.get("needs_mass"))
        self.mass_label.setVisible(needs_mass)
        self.mass_input.setVisible(needs_mass)
        self.condition_label.setVisible(mode_key == "single_leg")
        self.condition_input.setVisible(mode_key == "single_leg")
        self.start_btn.setText("Comenzar" if is_power else "Iniciar registro")
        self.sub_input.setText(self.main_window.current_sub)

    def update_orientation(self, state: dict):
        self.orientation_badge.set_values(state["angle_diff"], state["roll"], state["pitch"])

    def _on_calibrate(self):
        self.main_window.calibrate_reference()

    def _on_start(self):
        needs_mass = bool(MODES[self.mode_key].get("needs_mass"))
        mass = self.mass_input.value() if needs_mass else None
        entered_sub = self.sub_input.text().strip()
        sub_id = entered_sub.zfill(2) if entered_sub else self.main_window.current_sub
        condition = self.condition_input.currentData() if self.mode_key == "single_leg" else ""
        age_years = self.age_input.value() or None
        self.main_window.start_capture(mass, sub_id, condition, age_years)


PHASE_TEXT = {
    "wait_rest": ("Quieto un momento… preparando la medición", WARN),
    "armed": ("¡Ahora! Puede realizar el movimiento", GOOD),
    "moving": ("Movimiento detectado… termine quieto", ACCENT),
    "done": ("Calculando…", ACCENT),
}


class CapturePage(QWidget):
    def __init__(self, main_window: MainWindow):
        super().__init__()
        self.main_window = main_window
        self.mode_key = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(64, 40, 64, 40)
        layout.setSpacing(12)

        eyebrow = QLabel("CAPTURA EN CURSO")
        eyebrow.setObjectName("eyebrow")
        layout.addWidget(eyebrow)

        self.title_label = QLabel()
        self.title_label.setObjectName("title")
        self.title_label.setMinimumHeight(44)

        self.state_label = QLabel("Permanezca quieto un momento…")
        self.state_label.setMinimumHeight(30)
        self.state_label.setStyleSheet(f"color: {WARN}; font-size: 20px; font-weight: 700;")
        self.link_label = QLabel()
        self.link_label.setObjectName("muted")

        center_row = QHBoxLayout()
        center_row.addStretch()
        self.gauge = PowerGauge()
        center_row.addWidget(self.gauge)
        self.timer_display = QLabel("00:00.0")
        self.timer_display.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.timer_display.setStyleSheet("font-size: 64px; font-weight: 700;")
        center_row.addWidget(self.timer_display)
        center_row.addStretch()

        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground(BG_PANEL)
        self.plot_widget.showGrid(x=True, y=True, alpha=0.2)
        self.plot_widget.getAxis("bottom").setPen(TEXT_MUTED)
        self.plot_widget.getAxis("left").setPen(TEXT_MUTED)
        self.plot_widget.getAxis("bottom").setTextPen(TEXT_MUTED)
        self.plot_widget.getAxis("left").setTextPen(TEXT_MUTED)
        self.plot_widget.setLabel("bottom", "tiempo (s)")
        self.plot_widget.setLabel("left", "aceleración vertical (m/s²)")
        self.curve = self.plot_widget.plot(pen=pg.mkPen(color=ACCENT, width=2))

        cancel_btn = QPushButton("Cancelar")
        cancel_btn.clicked.connect(self._cancel)
        self.finish_btn = QPushButton("Finalizar registro")
        self.finish_btn.setObjectName("primaryButton")
        self.finish_btn.clicked.connect(lambda: self._finish_timed())
        actions = QHBoxLayout()
        actions.addWidget(cancel_btn)
        actions.addStretch()
        actions.addWidget(self.finish_btn)

        layout.addWidget(self.title_label)
        layout.addWidget(self.state_label)
        layout.addWidget(self.link_label)
        layout.addLayout(center_row)
        layout.addWidget(self.plot_widget, stretch=1)
        layout.addLayout(actions)

        buf_len = int(PLOT_WINDOW_S * SAMPLE_RATE_HZ)
        self._t_buf: deque = deque(maxlen=buf_len)
        self._a_buf: deque = deque(maxlen=buf_len)

        self._timeout_timer = QTimer(self)
        self._timeout_timer.setSingleShot(True)
        self._timeout_timer.timeout.connect(self._on_timeout)
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(100)
        self._elapsed_timer.timeout.connect(self._update_elapsed)
        self._refresh = QTimer(self)
        self._refresh.setInterval(PLOT_REFRESH_MS)
        self._refresh.timeout.connect(self._redraw)
        self._timed_capture: TimedCapture | None = None
        self._first_sample_time: float | None = None
        self._capture_started_at = 0.0
        self._active = False
        self._phase = None
        self._gauge_value = 0.0

    def load_mode(self, mode_key: str):
        self.mode_key = mode_key
        meta = MODES[mode_key]
        self.title_label.setText(meta["label"])
        timed = meta["capture_type"] == "timed"
        self.gauge.setVisible(not timed)
        self.timer_display.setVisible(timed)
        self.finish_btn.setVisible(timed)
        self._phase = None
        if timed:
            self._set_state("Registro en curso · finalizar al completar la prueba", GOOD)
        else:
            self._set_state(*PHASE_TEXT["wait_rest"])
            self.gauge.set_range(meta["gauge_max"])
            self.gauge.set_unit("g de movimiento")
            self.gauge.set_value(0.0, color=meta["color"])
        self._t_buf.clear()
        self._a_buf.clear()
        self.curve.setData([], [])
        self._first_sample_time = None
        self._elapsed_timer.stop()
        self._timeout_timer.stop()
        self._gauge_value = 0.0
        self._active = True
        self._capture_started_at = time.monotonic()
        self._refresh.start()
        if timed:
            self._timed_capture = TimedCapture()
            self._timed_capture.start()
            self.timer_display.setText("00:00.0")
            self._elapsed_timer.start()
        else:
            self._timed_capture = None
            self._timeout_timer.start(NO_REP_TIMEOUT_MS)

    def _set_state(self, text: str, color: str):
        self.state_label.setText(text)
        self.state_label.setStyleSheet(f"color: {color}; font-size: 20px; font-weight: 700;")

    def feed_sample(self, row: dict, s):
        if not self._active:
            return
        if self._first_sample_time is None:
            self._first_sample_time = s.t
        relative_t = max(0.0, s.t - self._first_sample_time)
        self.main_window.raw_buffer.append({**row, "time": round(relative_t, 4)})

        if self._timed_capture is not None:
            self._t_buf.append(relative_t)
            self._a_buf.append(s.a_vertical)
            return

        detector = self.main_window.detector
        if detector is None:
            return
        live, rep_result = detector.update(s)
        self._t_buf.append(relative_t)
        self._a_buf.append(live.a_vertical)
        self._gauge_value = max(self._gauge_value * 0.97, live.intensity_g)
        if live.phase != self._phase:
            self._phase = live.phase
            self._set_state(*PHASE_TEXT[live.phase])

        if rep_result is not None:
            self._stop()
            self.main_window.finish_capture(rep_result)

    def _redraw(self):
        self.curve.setData(list(self._t_buf), list(self._a_buf))
        if self._timed_capture is None:
            self.gauge.set_value(self._gauge_value, color=MODES[self.mode_key]["color"])
        self.link_label.setText(_link_text(self.main_window.link_received_pct()))

    def _stop(self):
        self._active = False
        self._timeout_timer.stop()
        self._elapsed_timer.stop()
        self._refresh.stop()

    def abort(self, reason: str):
        """El sensor se desconecto durante la captura."""
        if not self._active:
            return
        elapsed = time.monotonic() - self._capture_started_at
        self._stop()
        if self._timed_capture is not None:
            result = self._timed_capture.finish(len(self.main_window.raw_buffer), "desconexion")
            self._timed_capture = None
        else:
            result = RepResult(self.main_window.current_mode, elapsed)
        self.main_window.finish_capture(result, abort_reason=reason)

    def _on_timeout(self):
        if not self._active:
            return
        elapsed = time.monotonic() - self._capture_started_at
        self._stop()
        self.main_window.finish_capture(self.main_window.detector.timeout_result(elapsed))

    def _update_elapsed(self):
        if self._timed_capture is None:
            return
        elapsed = self._timed_capture.elapsed()
        minutes, seconds = divmod(elapsed, 60)
        self.timer_display.setText(f"{int(minutes):02d}:{seconds:04.1f}")
        limit = MODES[self.mode_key].get("duration_limit_s")
        if limit is not None and elapsed >= limit:
            self._finish_timed(ended_by="limit")

    def _finish_timed(self, *, ended_by: str = "manual"):
        if self._timed_capture is None:
            return
        self._stop()
        result = self._timed_capture.finish(len(self.main_window.raw_buffer), ended_by)
        self._timed_capture = None
        self.main_window.finish_capture(result)

    def _cancel(self):
        self._stop()
        self._timed_capture = None
        if self.mode_key == "event":
            self.main_window.goto_event(False)
        else:
            self.main_window.goto_home(False)


class ResultPage(QWidget):
    """Resultado para el participante (tarjetas) y reporte para el personal."""

    def __init__(self, main_window: MainWindow):
        super().__init__()
        self.main_window = main_window
        self.report_path = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(56, 28, 56, 24)
        layout.setSpacing(10)

        eyebrow = QLabel("RESULTADO DE LA MEDICIÓN")
        eyebrow.setObjectName("eyebrow")
        layout.addWidget(eyebrow)

        self.title_label = QLabel()
        self.title_label.setObjectName("title")
        self.verdict_label = QLabel()
        self.verdict_label.setWordWrap(True)

        cards_row = QHBoxLayout()
        cards_row.setSpacing(16)
        self.cards = [MetricCard(f"0{i + 1}", "") for i in range(4)]
        for card in self.cards:
            cards_row.addWidget(card)

        report_title = QLabel("REPORTE PARA EL PERSONAL")
        report_title.setObjectName("eyebrow")
        self.report_view = QTextBrowser()
        self.report_view.setOpenExternalLinks(True)
        self.report_view.setStyleSheet(
            f"QTextBrowser {{ background: {BG_PANEL}; border: 1px solid {BORDER}; border-radius: 10px; "
            f"padding: 10px; font-size: 13px; }}"
        )

        buttons_row = QHBoxLayout()
        retry_btn = QPushButton("Reintentar")
        retry_btn.clicked.connect(self._retry)
        self.open_btn = QPushButton("Abrir reporte guardado")
        self.open_btn.clicked.connect(self._open_report)
        self.other_btn = QPushButton("Otra prueba")
        self.other_btn.clicked.connect(lambda: self.main_window.goto_home(False))
        self.new_btn = QPushButton("Nuevo participante")
        self.new_btn.setObjectName("primaryButton")
        self.new_btn.clicked.connect(self._new_participant)
        buttons_row.addWidget(retry_btn)
        buttons_row.addWidget(self.open_btn)
        buttons_row.addStretch()
        buttons_row.addWidget(self.other_btn)
        buttons_row.addWidget(self.new_btn)

        layout.addWidget(self.title_label)
        layout.addWidget(self.verdict_label)
        layout.addLayout(cards_row)
        layout.addSpacing(6)
        layout.addWidget(report_title)
        layout.addWidget(self.report_view, stretch=1)
        layout.addLayout(buttons_row)

    def show_report(self, mode_key: str, ctx: ReportContext, report_path: str):
        meta = MODES[mode_key]
        self.report_path = report_path
        self.title_label.setText(meta["unit_label"])
        self.other_btn.setVisible(mode_key != "event")
        self.new_btn.setText("Siguiente participante" if mode_key == "event" else "Nuevo participante")

        state, title, action = verdict(ctx.checks, bool(ctx.metrics))
        color = {"ok": GOOD, "warn": WARN, "fail": BAD}[state]
        self.verdict_label.setText(title if state != "fail" else f"{title}: {action}")
        self.verdict_label.setStyleSheet(f"color: {color}; font-size: 18px; font-weight: 700;")

        shown = [] if state == "fail" else sorted(ctx.metrics, key=lambda m: not m.primary)[:4]
        for card, metric in zip(self.cards, shown):
            card.set_value(metric.text())
            card.set_label(f"{metric.label} ({metric.unit})")
            card.show()
        for card in self.cards[len(shown):]:
            card.hide()

        self.report_view.setHtml(render_html(ctx))

    def _open_report(self):
        if self.report_path and os.path.exists(self.report_path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.report_path))

    def _retry(self):
        if self.main_window.current_mode == "event":
            self.main_window.start_event()
        else:
            self.main_window.start_setup(self.main_window.current_mode)

    def _new_participant(self):
        if self.main_window.current_mode == "event":
            self.main_window.goto_event(True)
        else:
            self.main_window.goto_home(True)
