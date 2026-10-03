"""Pages of the MMS acquisition workflow."""
from __future__ import annotations

import os
import sys
import time
from collections import deque

import pyqtgraph as pg
from PyQt6.QtCore import QRegularExpression, Qt, QTimer, QUrl
from PyQt6.QtGui import QDesktopServices, QRegularExpressionValidator
from PyQt6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QScrollArea, QTextBrowser, QVBoxLayout, QWidget, QSpinBox,
)
from core import storage, quality as signal_quality
from core.kinematics import RepResult
from core.report import ReportContext, measurement_verdict, render_html, verdict
from core.timed_capture import TimedCapture
from ui.constants import *
from ui.theme import ACCENT, BAD, BG, BG_PANEL, BORDER, GOOD, MODES, MODE_SUMMARIES, TEXT, TEXT_MUTED, WARN
from ui.widgets import MetricCard, OrientationBadge, PowerGauge
from ui.components import WorkflowSteps, label, page_layout, panel, style_plot

SIMULATION_HINT = (
    "abre «Adquisición MMS (simulación, sin sensor)» desde el menú Inicio"
    if getattr(sys, "frozen", False) else "usa Simular_MMS.cmd"
)


class EventPage(QWidget):
    def __init__(self, main_window: MainWindow):
        super().__init__()
        self.main_window = main_window
        layout = page_layout(self)
        hero = QFrame()
        hero.setObjectName("hero")
        hero_row = QHBoxLayout(hero)
        hero_row.setContentsMargins(28, 22, 32, 22)
        hero_row.setSpacing(24)
        hero_text = QVBoxLayout()
        hero_text.setSpacing(8)
        hero_text.addWidget(label("EXPERIENCIA INTERACTIVA", "eyebrow"))
        hero_text.addWidget(label("Descubre tu movimiento", "eventTitle", wrap=True))
        hero_text.addWidget(label("Tu movimiento, convertido en una señal.\nColoca el sensor en la muñeca y explora.", "eventLead", wrap=True))
        hero_row.addLayout(hero_text, stretch=3)
        duration = QVBoxLayout()
        duration.setSpacing(0)
        duration.addWidget(label("20", "eventNumber"), alignment=Qt.AlignmentFlag.AlignCenter)
        seconds = label("SEGUNDOS DE MOVIMIENTO", "eyebrow", wrap=True)
        seconds.setAlignment(Qt.AlignmentFlag.AlignCenter)
        duration.addWidget(seconds)
        hero_row.addLayout(duration, stretch=1)
        layout.addWidget(hero)

        steps = QHBoxLayout()
        for number, title, text in (("01", "Coloca", "Sensor firme en la muñeca"),
                                    ("02", "Mueve", "Explora el movimiento del brazo"),
                                    ("03", "Descubre", "Observa tu señal y tu registro")):
            step = QVBoxLayout()
            step.setSpacing(3)
            step.addWidget(label(f"{number}  {title}", "sectionTitle"))
            step.addWidget(label(text, "formHint", wrap=True))
            steps.addLayout(step, stretch=1)
        layout.addLayout(steps)

        sensor_panel, sensor_row = panel(horizontal=True, margins=14)
        self.status_label = label("Conectando al sensor…", wrap=True)
        self.link_label = label("", "formHint")
        status_col = QVBoxLayout()
        status_col.setSpacing(3)
        status_col.addWidget(self.status_label)
        status_col.addWidget(self.link_label)
        sensor_row.addLayout(status_col, stretch=1)
        self.retry_btn = QPushButton("Reintentar")
        self.retry_btn.clicked.connect(self.main_window.retry_sensor)
        self.retry_btn.hide()
        sensor_row.addWidget(self.retry_btn)
        self.sensor_btn = QPushButton("Configurar sensor")
        self.sensor_btn.clicked.connect(self.main_window.configure_sensor)
        sensor_row.addWidget(self.sensor_btn)
        layout.addWidget(sensor_panel)

        signal_panel, signal_layout = panel(margins=16)
        signal_header = QHBoxLayout()
        signal_header.addWidget(label("SEÑAL EN VIVO", "eyebrow"))
        signal_header.addStretch()
        signal_header.addWidget(label("Aceleración vertical · m/s²", "formHint"))
        signal_layout.addLayout(signal_header)
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setMinimumHeight(90)
        style_plot(self.plot_widget, compact=True)
        self.curve = self.plot_widget.plot(pen=pg.mkPen(color=ACCENT, width=2.5))
        self._t_buf = deque(maxlen=300)
        self._a_buf = deque(maxlen=300)
        signal_layout.addWidget(self.plot_widget, stretch=1)
        layout.addWidget(signal_panel, stretch=1)

        actions = QHBoxLayout()
        self.start_btn = QPushButton("Iniciar experiencia  →")
        self.start_btn.setObjectName("eventButton")
        self.start_btn.clicked.connect(self.main_window.start_event)
        actions.addWidget(self.start_btn)
        actions.addStretch()
        more = QPushButton("Explorar las 7 evaluaciones  →")
        more.clicked.connect(lambda: self.main_window.goto_home(False))
        actions.addWidget(more)
        layout.addLayout(actions)
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
            "desconectado": f"Sensor desconectado. Comprueba el Bluetooth o {SIMULATION_HINT}.",
            "error": f"Error del sensor. Comprueba el Bluetooth o {SIMULATION_HINT}.",
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
        self.status_label.setText(f"Sensor: {message}. Para probar la interfaz sin sensor, {SIMULATION_HINT}.")

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
        layout = page_layout(self)
        layout.addWidget(label("EVALUACIÓN FUNCIONAL", "eyebrow"))
        layout.addWidget(label("Elige una evaluación", "title"))
        layout.addWidget(label("Siete protocolos para registrar y comprender el movimiento.", "subtitle"))
        sensor_panel, sensor_row = panel(horizontal=True, margins=14)
        sensor_row.addWidget(label("SENSOR", "eyebrow"))
        self.status_label = label("Conectando…", wrap=True)
        sensor_row.addWidget(self.status_label, stretch=1)
        self.retry_btn = QPushButton("Reintentar")
        self.retry_btn.clicked.connect(self.main_window.retry_sensor)
        self.retry_btn.hide()
        sensor_row.addWidget(self.retry_btn)
        sensor_btn = QPushButton("Configurar sensor")
        sensor_btn.clicked.connect(self.main_window.configure_sensor)
        sensor_row.addWidget(sensor_btn)
        layout.addWidget(sensor_panel)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        cards_container = QWidget()
        cards_grid = QGridLayout(cards_container)
        cards_grid.setContentsMargins(0, 0, 10, 0)
        cards_grid.setSpacing(14)
        for column in range(3):
            cards_grid.setColumnStretch(column, 1)
        for index, (key, meta) in enumerate((item for item in MODES.items() if item[0] != "event")):
            card = QFrame()
            card.setObjectName("modeCard")
            card.setMinimumHeight(218)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(18, 16, 18, 16)
            card_layout.setSpacing(7)
            top = QHBoxLayout()
            number = label(meta["number"])
            number.setStyleSheet(f"color: {ACCENT}; font-size: 23px; font-weight: 600;")
            top.addWidget(number)
            top.addStretch()
            top.addWidget(label("IMU" if meta["capture_type"] == "power" else "CRONÓMETRO", "eyebrow"))
            card_layout.addLayout(top)
            name = label(meta["label"], wrap=True)
            name.setStyleSheet(f"font-size: 17px; font-weight: 600; color: {TEXT};")
            card_layout.addWidget(name)
            card_layout.addWidget(label(MODE_SUMMARIES[key], "muted", wrap=True))
            card_layout.addStretch()
            position = "Cadera · sobre el sacro" if key in ("jump", "sts") else meta["sensor_pos"]
            card_layout.addWidget(label(f"Sensor: {position.lower()}", "formHint", wrap=True))
            btn = QPushButton("Preparar evaluación  →")
            btn.setObjectName("modeButton")
            btn.clicked.connect(lambda _, k=key: self.main_window.start_setup(k))
            card_layout.addWidget(btn)
            cards_grid.addWidget(card, index // 3, index % 3)
        cards_grid.setRowStretch(3, 1)
        scroll.setWidget(cards_container)
        layout.addWidget(scroll, stretch=1)
        layout.addWidget(label("Selecciona un protocolo para ver las instrucciones y preparar al participante.", "formHint", wrap=True))

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
        layout = page_layout(self)
        layout.addWidget(WorkflowSteps(0))
        self.title_label = label("", "title", wrap=True)
        self.instructions_label = label("", "subtitle", wrap=True)
        layout.addWidget(self.title_label)
        layout.addWidget(self.instructions_label)
        content_row = QHBoxLayout()
        content_row.setSpacing(16)
        form_panel, form_layout = panel()
        form_layout.addWidget(label("Datos del participante", "sectionTitle"))
        form = QGridLayout()
        form.setHorizontalSpacing(20)
        form.setVerticalSpacing(7)
        form.addWidget(label("N° de participante"), 0, 0)
        self.sub_input = QLineEdit()
        self.sub_input.setValidator(QRegularExpressionValidator(QRegularExpression(r"[A-Za-z0-9]{0,12}")))
        self.sub_input.setPlaceholderText("Ej. 01 o AB12")
        self.sub_input.setAccessibleName("Identificador del participante")
        form.addWidget(self.sub_input, 1, 0)
        form.addWidget(label("Edad · opcional"), 0, 1)
        self.age_input = QSpinBox()
        self.age_input.setRange(0, 110)
        self.age_input.setSpecialValueText("No indicada")
        self.age_input.setAccessibleName("Edad del participante en años")
        form.addWidget(self.age_input, 1, 1)
        self.mass_label = label("Peso corporal · kg")
        form.addWidget(self.mass_label, 2, 0)
        self.mass_input = QDoubleSpinBox()
        self.mass_input.setRange(0, 200)
        self.mass_input.setDecimals(1)
        self.mass_input.setSpecialValueText("Indique el peso")
        self.mass_input.setAccessibleName("Peso corporal en kilogramos")
        form.addWidget(self.mass_input, 3, 0)
        self.condition_label = label("Pierna de apoyo")
        form.addWidget(self.condition_label, 2, 1)
        self.condition_input = QComboBox()
        self.condition_input.addItem("Izquierda", "left")
        self.condition_input.addItem("Derecha", "right")
        self.condition_input.setAccessibleName("Pierna de apoyo")
        form.addWidget(self.condition_input, 3, 1)
        form.setColumnStretch(0, 1)
        form.setColumnStretch(1, 1)
        form_layout.addLayout(form)
        form_layout.addWidget(label("Los datos se conservan al cambiar de prueba.\nNuevo participante borra edad y peso.", "formHint", wrap=True))
        form_layout.addStretch()
        content_row.addWidget(form_panel, stretch=2)

        orientation_panel, orientation_col = panel(margins=16)
        orientation_panel.setMaximumWidth(310)
        orientation_col.addWidget(label("COLOCACIÓN DEL SENSOR", "eyebrow"))
        self.orientation_badge = OrientationBadge()
        self.orientation_badge.setFixedHeight(145)
        orientation_col.addWidget(self.orientation_badge)
        self.calibrate_btn = QPushButton("Calibrar referencia")
        self.calibrate_btn.clicked.connect(self._on_calibrate)
        orientation_col.addWidget(self.calibrate_btn)
        content_row.addWidget(orientation_panel, stretch=1)
        layout.addLayout(content_row, stretch=1)
        self.readiness_label = label("Esperando señal reciente…", "formHint", wrap=True)
        layout.addWidget(self.readiness_label)
        self.form_error = label("", wrap=True)
        self.form_error.setStyleSheet(f"color: {BAD}; font-weight: 600;")
        self.form_error.hide()
        layout.addWidget(self.form_error)
        buttons = QHBoxLayout()
        back = QPushButton("← Evaluaciones")
        back.clicked.connect(lambda: self.main_window.goto_home(False))
        buttons.addWidget(back)
        buttons.addStretch()
        self.start_btn = QPushButton("Comenzar  →")
        self.start_btn.setObjectName("primaryButton")
        self.start_btn.clicked.connect(self._on_start)
        buttons.addWidget(self.start_btn)
        layout.addLayout(buttons)

    def reset_participant(self):
        self.age_input.setValue(0)
        self.mass_input.setValue(0.0)

    def load_mode(self, mode_key: str):
        self.mode_key = mode_key
        self.form_error.setText("")
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
        self.update_orientation(self.main_window.live_orientation)

    def update_orientation(self, state: dict):
        self.orientation_badge.set_values(state["angle_diff"], state["roll"], state["pitch"])

    def set_signal_readiness(self, allowed: bool, message: str):
        self.start_btn.setEnabled(allowed)
        self.readiness_label.setText("● Señal reciente · listo para registrar" if allowed else message)
        self.readiness_label.setStyleSheet(f"color: {GOOD if allowed else WARN}; font-size: 12px;")
        self.form_error.setVisible(bool(self.form_error.text()))

    def _on_calibrate(self):
        self.main_window.calibrate_reference()

    def _on_start(self):
        needs_mass = bool(MODES[self.mode_key].get("needs_mass"))
        mass = self.mass_input.value() if needs_mass else None
        if needs_mass and mass < MIN_MASS_KG:
            self.form_error.setText(f"Indique el peso corporal de esta persona (mínimo {MIN_MASS_KG:.0f} kg): "
                                    "la potencia se calcula con él.")
            self.mass_input.setFocus()
            return
        entered_sub = self.sub_input.text().strip()
        sub_id = storage.normalize_sub(entered_sub) if entered_sub else self.main_window.current_sub
        if sub_id is None:
            self.form_error.setText("El N° de participante solo puede tener letras y números (máximo 12).")
            self.sub_input.setFocus()
            return
        self.form_error.setText("")
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
        layout = page_layout(self)
        layout.addWidget(WorkflowSteps(1))
        self.title_label = label("", "title", wrap=True)
        self.state_label = label("Permanezca quieto un momento…", wrap=True)
        self.state_label.setStyleSheet(f"color: {WARN}; font-size: 18px; font-weight: 600;")
        self.link_label = label("", "formHint", wrap=True)
        layout.addWidget(self.title_label)
        info_panel, info_row = panel(horizontal=True, margins=14)
        info = QVBoxLayout()
        info.setSpacing(5)
        info.addWidget(label("EN REGISTRO", "eyebrow"))
        info.addWidget(self.state_label)
        info.addWidget(self.link_label)
        info_row.addLayout(info, stretch=1)
        self.gauge = PowerGauge()
        self.gauge.setFixedSize(170, 145)
        info_row.addWidget(self.gauge)
        self.timer_display = label("00:00.0")
        self.timer_display.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.timer_display.setStyleSheet(f"color: {ACCENT}; font-size: 48px; font-weight: 300;")
        info_row.addWidget(self.timer_display)
        layout.addWidget(info_panel)
        plot_panel, plot_layout = panel(margins=16)
        plot_layout.addWidget(label("MOVIMIENTO EN TIEMPO REAL", "eyebrow"))
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setMinimumHeight(130)
        style_plot(self.plot_widget)
        self.plot_widget.setLabel("bottom", "Tiempo", units="s")
        self.plot_widget.setLabel("left", "Aceleración vertical", units="m/s²")
        self.curve = self.plot_widget.plot(pen=pg.mkPen(color=ACCENT, width=2.5))
        plot_layout.addWidget(self.plot_widget, stretch=1)
        layout.addWidget(plot_panel, stretch=1)
        actions = QHBoxLayout()
        cancel = QPushButton("Cancelar intento")
        cancel.clicked.connect(self._cancel)
        actions.addWidget(cancel)
        actions.addStretch()
        self.finish_btn = QPushButton("Finalizar registro  →")
        self.finish_btn.setObjectName("primaryButton")
        self.finish_btn.clicked.connect(lambda: self._finish_timed())
        actions.addWidget(self.finish_btn)
        layout.addLayout(actions)
        length = int(PLOT_WINDOW_S * SAMPLE_RATE_HZ)
        self._t_buf = deque(maxlen=length)
        self._a_buf = deque(maxlen=length)
        self._timeout_timer = QTimer(self)
        self._timeout_timer.setSingleShot(True)
        self._timeout_timer.timeout.connect(self._on_timeout)
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(100)
        self._elapsed_timer.timeout.connect(self._update_elapsed)
        self._refresh = QTimer(self)
        self._refresh.setInterval(PLOT_REFRESH_MS)
        self._refresh.timeout.connect(self._redraw)
        self._timed_capture = None
        self._first_sample_time = None
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
            if live.phase == "armed":
                # El plazo para moverse cuenta desde «¡Ahora!», no desde que se abrió la pantalla.
                self._timeout_timer.start(NO_REP_TIMEOUT_MS)
            elif live.phase == "moving":
                # Un movimiento en curso no se corta: el detector lo cierra por reposo final
                # o, a los MAX_REP_S segundos, lo marca para repetir.
                self._timeout_timer.stop()

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
        session = self.main_window.session_context
        if session is not None:
            try:
                from core import storage
                storage.discard_session(session)
            except Exception as exc:
                self.main_window.statusBar().showMessage(f"No se pudo descartar la sesión: {exc}", 8000)
            self.main_window.session_context = None
        self.main_window.raw_buffer = []
        if self.mode_key == "event":
            self.main_window.goto_event(False)
        else:
            self.main_window.goto_home(False)
        self.main_window._refresh_requirements()


class ResultPage(QWidget):
    """Resultado para el participante (tarjetas) y reporte para el personal."""

    def __init__(self, main_window: MainWindow):
        super().__init__()
        self.main_window = main_window
        self.report_path = ""
        layout = page_layout(self)
        layout.addWidget(WorkflowSteps(2))
        self.title_label = label("", "title", wrap=True)
        self.verdict_label = label("", wrap=True)
        self.participant_label = label("", wrap=True)
        self.participant_label.setStyleSheet(f"color: {TEXT}; font-size: 15px;")
        layout.addWidget(self.title_label)
        layout.addWidget(self.verdict_label)
        layout.addWidget(self.participant_label)
        cards = QHBoxLayout()
        cards.setSpacing(12)
        self.cards = [MetricCard(f"0{i + 1}", "") for i in range(4)]
        for card in self.cards:
            cards.addWidget(card)
        layout.addLayout(cards)
        report_header = QHBoxLayout()
        report_header.addWidget(label("DETALLE DE LA MEDICIÓN", "eyebrow"))
        report_header.addStretch()
        self.session_label = label("", "formHint")
        report_header.addWidget(self.session_label)
        layout.addLayout(report_header)
        self.report_view = QTextBrowser()
        self.report_view.setOpenExternalLinks(True)
        self.report_view.setMinimumHeight(90)
        layout.addWidget(self.report_view, stretch=1)
        self.save_label = label("", wrap=True)
        self.save_label.setStyleSheet(f"color: {WARN}; font-weight: 600;")
        layout.addWidget(self.save_label)
        buttons = QHBoxLayout()
        retry = QPushButton("Repetir")
        retry.clicked.connect(self._retry)
        buttons.addWidget(retry)
        self.open_btn = QPushButton("Abrir reporte")
        self.open_btn.clicked.connect(self._open_report)
        buttons.addWidget(self.open_btn)
        buttons.addStretch()
        self.other_btn = QPushButton("Otra prueba")
        self.other_btn.clicked.connect(lambda: self.main_window.goto_home(False))
        buttons.addWidget(self.other_btn)
        self.new_btn = QPushButton("Nuevo participante  →")
        self.new_btn.setObjectName("primaryButton")
        self.new_btn.clicked.connect(self._new_participant)
        buttons.addWidget(self.new_btn)
        layout.addLayout(buttons)

    def show_report(self, mode_key: str, ctx: ReportContext, report_path: str):
        meta = MODES[mode_key]
        self.report_path = report_path
        self.session_label.setText(f"Participante {ctx.sub} · intento {ctx.run}")
        self.title_label.setText(meta["unit_label"])
        self.other_btn.setVisible(mode_key != "event")
        self.new_btn.setText("Siguiente participante" if mode_key == "event" else "Nuevo participante")

        state, title, action = measurement_verdict(ctx)
        color = {"ok": GOOD, "warn": WARN, "fail": BAD}[state]
        self.verdict_label.setText(title if state != "fail" else f"{title}: {action}")
        self.verdict_label.setStyleSheet(f"color: {color}; font-size: 18px; font-weight: 700;")
        self.participant_label.setText(ctx.participant_text)
        self.participant_label.setVisible(bool(ctx.participant_text))
        self.save_label.setText("\n".join(ctx.save_warnings))
        self.save_label.setVisible(bool(ctx.save_warnings))
        self.open_btn.setEnabled(bool(report_path))

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
