"""Dialogo para elegir el sensor MetaWear de este equipo (buscar o escribir la MAC)."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout,
)

from core import config
from core.sensor_stream import SensorScanner, SimulatedSensorScanner
from ui.theme import BAD, STYLESHEET, TEXT_MUTED


class SensorDialog(QDialog):
    def __init__(self, current_mac: str, simulate: bool, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configurar sensor")
        self.setStyleSheet(STYLESHEET)
        self.setMinimumWidth(520)
        self.selected_mac: str | None = None
        self._scanner_cls = SimulatedSensorScanner if simulate else SensorScanner
        self._scanner = None

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        intro = QLabel(
            "Encienda el sensor y pulse «Buscar sensores». El sensor en uso se desconectará "
            "durante la búsqueda. También puede escribir la dirección MAC impresa en el sensor."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.scan_btn = QPushButton("Buscar sensores")
        self.scan_btn.clicked.connect(self._scan)
        layout.addWidget(self.scan_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        self.devices = QListWidget()
        self.devices.itemClicked.connect(lambda item: self.mac_input.setText(item.data(Qt.ItemDataRole.UserRole)))
        layout.addWidget(self.devices)
        self.hint = QLabel()
        self.hint.setStyleSheet(f"color: {TEXT_MUTED};")
        layout.addWidget(self.hint)

        layout.addWidget(QLabel("Dirección MAC del sensor"))
        self.mac_input = QLineEdit(current_mac)
        self.mac_input.setPlaceholderText("E7:D7:CE:C3:E0:25")
        layout.addWidget(self.mac_input)
        self.error_label = QLabel()
        self.error_label.setStyleSheet(f"color: {BAD};")
        layout.addWidget(self.error_label)

        buttons = QHBoxLayout()
        cancel = QPushButton("Cancelar")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Guardar y conectar")
        save.setObjectName("primaryButton")
        save.clicked.connect(self._save)
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        layout.addLayout(buttons)

    def _scan(self):
        parent = self.parent()
        if parent is not None:
            parent.stop_sensor()
        self.devices.clear()
        self.scan_btn.setEnabled(False)
        self.hint.setText("Buscando durante 6 segundos…")
        self._scanner = self._scanner_cls()
        self._scanner.found.connect(self._on_found)
        self._scanner.error.connect(lambda e: self.hint.setText(f"No se pudo buscar: {e}. ¿Está activado el Bluetooth?"))
        self._scanner.finished.connect(self._on_scan_finished)
        self._scanner.start()

    def _on_found(self, mac: str, name: str, rssi: int):
        item = QListWidgetItem(f"{name}   ·   {mac}   ·   señal {rssi} dBm")
        item.setData(Qt.ItemDataRole.UserRole, mac)
        self.devices.addItem(item)
        if self.devices.count() == 1:
            self.mac_input.setText(mac)

    def _on_scan_finished(self):
        self.scan_btn.setEnabled(True)
        if self.devices.count() == 0 and not self.hint.text().startswith("No se pudo"):
            self.hint.setText("No se encontraron sensores. Compruebe que esté encendido y cargado.")
        elif self.devices.count():
            self.hint.setText("Seleccione un sensor de la lista (el más cercano tiene la señal más alta).")

    def _save(self):
        mac = config.normalize_mac(self.mac_input.text())
        if mac is None:
            self.error_label.setText("Formato no válido. Ejemplo: E7:D7:CE:C3:E0:25")
            return
        self.selected_mac = mac
        self.accept()

    def done(self, result):
        if self._scanner is not None and self._scanner.isRunning():
            self._scanner.wait(8000)
        super().done(result)
