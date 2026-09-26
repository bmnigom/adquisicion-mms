"""Widgets custom (QPainter) para el stand: indicador de alineacion del sensor
y medidor circular de potencia en vivo."""
from PyQt6.QtCore import Qt, QRectF, QPointF
from PyQt6.QtGui import QPainter, QColor, QPen, QFont
from PyQt6.QtWidgets import QWidget, QFrame, QVBoxLayout, QLabel

from ui.theme import ACCENT, GOOD, WARN, BAD, TEXT_MUTED, BG_PANEL, TEXT


class OrientationBadge(QWidget):
    """Nivel de burbuja + desvio angular respecto a la orientacion de referencia."""

    ALIGN_OK_DEG = 15.0
    ALIGN_WARN_DEG = 35.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(170, 170)
        self._angle_diff = None
        self._roll = 0.0
        self._pitch = 0.0

    def set_values(self, angle_diff, roll: float, pitch: float):
        self._angle_diff = angle_diff
        self._roll = roll
        self._pitch = pitch
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        size = min(w, h) - 24
        cx, cy = w / 2, h / 2 - 6
        radius = size / 2

        p.setPen(QPen(QColor(TEXT_MUTED), 2))
        p.setBrush(QColor(BG_PANEL))
        p.drawEllipse(QPointF(cx, cy), radius, radius)

        if self._angle_diff is None:
            p.setPen(QColor(TEXT_MUTED))
            p.setFont(QFont("Segoe UI", 11))
            p.drawText(QRectF(0, cy - 10, w, 20), Qt.AlignmentFlag.AlignCenter, "Sin calibrar")
            p.end()
            return

        if self._angle_diff <= self.ALIGN_OK_DEG:
            color = QColor(GOOD)
        elif self._angle_diff <= self.ALIGN_WARN_DEG:
            color = QColor(WARN)
        else:
            color = QColor(BAD)

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(color.red(), color.green(), color.blue(), 45))
        p.drawEllipse(QPointF(cx, cy), radius * 0.4, radius * 0.4)

        max_deg = 45.0
        dx = max(-1.0, min(1.0, self._roll / max_deg)) * radius * 0.8
        dy = max(-1.0, min(1.0, -self._pitch / max_deg)) * radius * 0.8
        p.setBrush(color)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx + dx, cy + dy), 11, 11)

        p.setPen(QColor(TEXT))
        p.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        p.drawText(QRectF(0, h - 28, w, 22), Qt.AlignmentFlag.AlignCenter, f"{self._angle_diff:.0f}° de desvío")
        p.end()


class PowerGauge(QWidget):
    """Medidor circular tipo arcade para la intensidad del movimiento en vivo."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(240, 220)
        self._value = 0.0
        self._max_value = 500.0
        self._color = ACCENT
        self._unit = "g"

    def set_unit(self, unit: str):
        self._unit = unit
        self.update()

    def set_range(self, max_value: float):
        self._max_value = max(1.0, max_value)
        self.update()

    def set_value(self, value: float, color: str | None = None):
        self._value = max(0.0, value)
        if color:
            self._color = color
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        size = min(w, h - 20) - 20
        rect = QRectF(w / 2 - size / 2, 10, size, size)

        start_angle = 225 * 16
        span_full = -270 * 16

        pen_bg = QPen(QColor(BG_PANEL))
        pen_bg.setWidth(18)
        pen_bg.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen_bg)
        p.drawArc(rect, start_angle, span_full)

        fraction = min(1.0, self._value / self._max_value)
        pen_fg = QPen(QColor(self._color))
        pen_fg.setWidth(18)
        pen_fg.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen_fg)
        p.drawArc(rect, start_angle, int(span_full * fraction))

        p.setPen(QColor(TEXT))
        p.setFont(QFont("Segoe UI", 36, QFont.Weight.Bold))
        p.drawText(rect.adjusted(0, 16, 0, 16), Qt.AlignmentFlag.AlignCenter, f"{self._value:.1f}" if self._max_value < 20 else f"{self._value:.0f}")
        p.setFont(QFont("Segoe UI", 13))
        p.setPen(QColor(TEXT_MUTED))
        p.drawText(rect.adjusted(0, 68, 0, 68), Qt.AlignmentFlag.AlignCenter, self._unit)
        p.end()


class MetricCard(QFrame):
    """Tarjeta simple con un valor grande y una etiqueta, para la pantalla de resultado."""

    def __init__(self, icon: str, label: str, parent=None):
        super().__init__(parent)
        self.setObjectName("metricCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(8)

        self.icon_label = QLabel(icon)
        self.icon_label.setStyleSheet(f"font-size: 12px; font-weight: 700; color: {ACCENT}; background: transparent;")

        self.value_label = QLabel("--")
        self.value_label.setObjectName("metricValue")
        self.value_label.setStyleSheet("background: transparent;")

        self.name_label = QLabel(label)
        self.name_label.setWordWrap(True)
        self.name_label.setStyleSheet(f"font-size: 13px; color: {TEXT_MUTED}; background: transparent;")

        layout.addWidget(self.icon_label)
        layout.addWidget(self.value_label)
        layout.addWidget(self.name_label)

    def set_value(self, text: str):
        self.value_label.setText(text)

    def set_label(self, text: str):
        self.name_label.setText(text)
