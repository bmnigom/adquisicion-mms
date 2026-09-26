"""Punto de entrada de la aplicación de registro IMU.

Uso:
    python main.py            # usa el sensor MMS real (Bluetooth)
    python main.py --simulate # genera datos sinteticos, sin hardware (para probar la UI)
    python main.py --check    # comprobacion de arranque con el simulador (MMS_OK / MMS_ERROR)
"""
import datetime as dt
import os
import sys
import traceback

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QMessageBox

from core import __version__, storage


def _log_path() -> str:
    return os.path.join(storage.DATA_DIR, "registro_errores.log")


def _write(text: str) -> None:
    # En el ejecutable sin consola, sys.stdout es None.
    if sys.stdout is not None:
        print(text, flush=True)


def _install_error_handler(app: QApplication) -> None:
    """Un error inesperado queda en data/registro_errores.log y se muestra en pantalla,
    en lugar de cerrar la aplicación sin explicación."""
    def handler(exc_type, exc, tb):
        details = "".join(traceback.format_exception(exc_type, exc, tb))
        try:
            os.makedirs(storage.DATA_DIR, exist_ok=True)
            with open(_log_path(), "a", encoding="utf-8") as f:
                f.write(f"\n=== {dt.datetime.now():%Y-%m-%d %H:%M:%S} · MMS {__version__}\n{details}")
        except OSError:
            pass
        _write(details)
        QMessageBox.critical(
            None, "Error inesperado",
            f"Ocurrió un error inesperado:\n\n{exc}\n\nQuedó registrado en:\n{_log_path()}",
        )
    sys.excepthook = handler


def main():
    check = "--check" in sys.argv
    simulate = check or "--simulate" in sys.argv
    app = QApplication(sys.argv)
    app.setApplicationName("Adquisición MMS")
    app.setApplicationVersion(__version__)
    base = getattr(sys, "_MEIPASS", os.path.join(os.path.dirname(os.path.abspath(__file__)), "packaging"))
    app.setWindowIcon(QIcon(os.path.join(base, "mms.png")))
    _install_error_handler(app)

    from ui.main_window import MainWindow
    if check:
        app.setQuitOnLastWindowClosed(False)
        try:
            # Carga las bibliotecas nativas de Bluetooth: verifica la instalacion sin sensor.
            import mbientlab.metawear  # noqa: F401
            import mbientlab.warble  # noqa: F401
        except Exception as exc:  # noqa: BLE001
            _write(f"MMS_ERROR: biblioteca Bluetooth: {exc}")
            sys.exit(2)
    window = MainWindow(simulate=simulate)
    window.show()
    if check:
        def finish_check():
            ready = window.sensor_status == "transmitiendo"
            _write("MMS_OK" if ready else f"MMS_ERROR: {window.sensor_status}")
            window.close()
            app.exit(0 if ready else 1)
        QTimer.singleShot(1500, finish_check)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
