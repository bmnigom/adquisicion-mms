"""Small visual components shared by MMS pages."""
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ui.theme import ACCENT, BG, BG_PANEL, BORDER, TEXT_MUTED


class BrandMark(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(40, 40)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(ACCENT))
        painter.drawRoundedRect(QRectF(0, 0, 40, 40), 11, 11)
        path = QPainterPath(QPointF(7, 23))
        for x, y in ((13, 23), (17, 12), (23, 29), (27, 19), (33, 19)):
            path.lineTo(x, y)
        pen = QPen(QColor(BG), 2.3)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawPath(path)


class WorkflowSteps(QWidget):
    def __init__(self, active: int, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        for index, title in enumerate(("Preparar", "Registrar", "Resultados")):
            if index:
                arrow = QLabel("›")
                arrow.setStyleSheet(f"color: {TEXT_MUTED};")
                layout.addWidget(arrow)
            label = QLabel(f"{index + 1:02d}  {title}")
            label.setObjectName("stepActive" if index == active else "stepInactive")
            layout.addWidget(label)
        layout.addStretch()


def style_plot(plot, *, compact=False):
    """A restrained plot: readable axes, quiet grid, no surrounding frame."""
    plot.setBackground(BG_PANEL)
    plot.showGrid(x=not compact, y=True, alpha=0.10)
    plot.setMouseEnabled(x=False, y=False)
    plot.setMenuEnabled(False)
    plot.hideButtons()
    for name in ("bottom", "left"):
        axis = plot.getAxis(name)
        axis.setPen(QColor(BORDER))
        axis.setTextPen(QColor(TEXT_MUTED))
    if compact:
        plot.hideAxis("bottom")
        plot.hideAxis("left")


def label(text="", name=None, *, wrap=False):
    widget = QLabel(text)
    if name:
        widget.setObjectName(name)
    widget.setWordWrap(wrap)
    return widget


def page_layout(page):
    layout = QVBoxLayout(page)
    layout.setContentsMargins(32, 22, 32, 22)
    layout.setSpacing(12)
    return layout


def panel(*, horizontal=False, margins=20):
    frame = QFrame()
    frame.setObjectName("panel")
    layout = QHBoxLayout(frame) if horizontal else QVBoxLayout(frame)
    layout.setContentsMargins(margins, margins, margins, margins)
    layout.setSpacing(10)
    return frame, layout
