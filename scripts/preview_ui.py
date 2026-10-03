"""Render each MMS page with synthetic data and without Bluetooth.

    python -X utf8 scripts/preview_ui.py --output artifacts/ui-before
"""
import argparse
import datetime as dt
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from PyQt6.QtGui import QFontDatabase
from PyQt6.QtWidgets import QApplication

from core import storage
from core.kinematics import Check, Metric
from core.report import ReportContext, participant_summary
from ui.main_window import MainWindow


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("artifacts/ui-preview"))
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=820)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    # The offscreen platform does not always enumerate Windows system fonts.
    for font in ("arial.ttf", "arialbd.ttf", "segoeui.ttf", "segoeuib.ttf", "seguisb.ttf", "segoeuil.ttf"):
        font_path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / font
        if font_path.is_file():
            QFontDatabase.addApplicationFont(str(font_path))
    app.setStyle("Fusion")
    with tempfile.TemporaryDirectory(dir=args.output, prefix="synthetic-") as tmp:
        storage.BASE_DATA_DIR = tmp
        storage.DATA_DIR = tmp
        storage.REPORTS_DIR = os.path.join(tmp, "reportes")
        storage.RESULTS_LOG = os.path.join(tmp, "resultados_ciclovia_v2.csv")
        storage.TIMED_RESULTS_LOG = os.path.join(tmp, "resultados_pruebas_funcionales.csv")
        storage.REFERENCE_ORIENTATION_FILE = os.path.join(tmp, "orientacion_referencia.json")
        with patch.object(MainWindow, "_start_sensor"):
            window = MainWindow(simulate=True)
        window.resize(args.width, args.height)
        window.show()
        window.event_page.set_sensor_status("transmitiendo")
        window.home_page.set_sensor_status("transmitiendo")
        t = np.linspace(0, 4, 300)
        y = 1.2 * np.sin(t * 5) * np.exp(-((t - 2.2) ** 2) / 1.2)
        window.event_page.curve.setData(t, y)
        window.event_page._t_buf.extend(t)
        window.event_page._a_buf.extend(y)

        def capture(name, page):
            window.stack.setCurrentWidget(page)
            app.processEvents()
            if not window.grab().save(str(args.output / f"{name}.png")):
                raise RuntimeError(f"Cannot save screenshot {name}")

        capture("01-evento", window.event_page)
        window.goto_home(False)
        capture("02-pruebas", window.home_page)
        window.start_setup("jump")
        window.setup_page.mass_input.setValue(70)
        window.setup_page.age_input.setValue(32)
        capture("03-preparacion", window.setup_page)
        window.capture_page.load_mode("jump")
        window.capture_page._stop()
        window.capture_page._set_state("Movimiento detectado · termina en reposo", "#087F8C")
        window.capture_page.curve.setData(t, y * 3)
        window.capture_page.gauge.set_value(2.4)
        capture("04-captura", window.capture_page)
        metrics = [Metric("altura_salto_cm", "Altura del salto", 30.2, "cm", 1, primary=True),
                   Metric("potencia_pico_w", "Potencia estimada", 2590, "W", 0),
                   Metric("potencia_relativa_w_kg", "Potencia relativa", 37.0, "W/kg", 1)]
        ctx = ReportContext("jump", "Salto vertical", "Cadera", "DEMO", "01", 0.50,
                            metrics, [Check("Continuidad", "ok", "Registro sintético para verificar la interfaz.")],
                            method="Altura estimada a partir del tiempo de vuelo.", mass_kg=70, age_years=32,
                            participant_text=participant_summary("jump", "ok", metrics, 32),
                            timestamp=dt.datetime(2026, 10, 3, 10, 30))
        if hasattr(ctx, "data_source"):
            ctx.data_source = "simulated"
        window.result_page.show_report("jump", ctx, "")
        capture("05-resultados", window.result_page)
        window.close()
        app.processEvents()
    print(f"UI_PREVIEW_OK {args.output.resolve()}")


if __name__ == "__main__":
    main()
