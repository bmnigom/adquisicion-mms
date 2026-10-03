"""Identidad visual y configuración de las pruebas."""

BG = "#0B1420"
BG_PANEL = "#121F2E"
TEXT = "#E6EDF5"
TEXT_MUTED = "#9CB0C3"
ACCENT = "#43D5CE"
GOOD = "#68D8A0"
WARN = "#F3C778"
BAD = "#FF8990"
BORDER = "#24364A"
NAVY = "#132D40"
SOFT_ACCENT = "#16343E"

MODE_SUMMARIES = {
    "tug": "Levantarse, caminar 3 m y volver a sentarse.",
    "sts": "Potencia y velocidad al levantarse de la silla.",
    "walk": "Tiempo y velocidad media en un recorrido de 5 m.",
    "stand": "Registro de equilibrio durante dos minutos.",
    "single_leg": "Duración del apoyo sobre una pierna.",
    "jump": "Altura de salto a partir del tiempo de vuelo.",
    "punch": "Velocidad del puño y aceleración de la muñeca.",
}

MODES = {
    "event": {
        "label": "Explora tu movimiento",
        "task_code": "event",
        "color": ACCENT,
        "number": "00",
        "sensor_pos": "Muñeca",
        "instructions": "Mueve el brazo con comodidad durante 20 segundos. La pantalla mostrará la señal de movimiento en vivo. Puedes detener el registro antes si lo necesitas.",
        "unit_label": "Tu movimiento en 20 segundos",
        "capture_type": "timed",
        "duration_limit_s": 20,
    },
    "tug": {
        "label": "TUG · Timed Up and Go",
        "task_code": "tug",
        "color": ACCENT,
        "number": "01",
        "sensor_pos": "Tronco o cintura",
        "instructions": "Desde una silla, al dar la orden de inicio levántese, camine a ritmo habitual hasta la marca a 3 metros, gire, regrese y siéntese. Inicie el cronómetro con la orden y deténgalo al sentarse.",
        "unit_label": "Tiempo de TUG",
        "capture_type": "timed",
    },
    "sts": {
        "label": "STS · Sit to Stand",
        "task_code": "sts",
        "color": ACCENT,
        "number": "02",
        "sensor_pos": "Cadera (sobre el sacro, con cinturón)",
        "instructions": "Registro de una repetición. Fije el sensor firme sobre el sacro con un cinturón. Con la persona sentada y quieta al menos un segundo, pida que se levante lo más rápido posible y que quede de pie, quieta, hasta que la pantalla lo indique.",
        "unit_label": "Potencia al levantarse",
        "capture_type": "power",
        "needs_mass": True,
        "gauge_max": 1.5,
    },
    "walk": {
        "label": "Marcha · 5 metros",
        "task_code": "walk",
        "color": "#58708A",
        "number": "03",
        "sensor_pos": "Cintura",
        "instructions": "Delimite un recorrido de 5 metros. Pida caminar a ritmo habitual; inicie el cronómetro al comenzar y deténgalo al cruzar la marca final.",
        "unit_label": "Tiempo de marcha · 5 m",
        "capture_type": "timed",
    },
    "stand": {
        "label": "Bipedestación · 2 minutos",
        "task_code": "stand",
        "color": "#58708A",
        "number": "04",
        "sensor_pos": "Tronco o cintura",
        "instructions": "Inicie la grabación con la persona en bipedestación. La captura finalizará automáticamente a los 2 minutos.",
        "unit_label": "Tiempo de bipedestación",
        "capture_type": "timed",
        "duration_limit_s": 120,
    },
    "single_leg": {
        "label": "Apoyo monopodal",
        "task_code": "single-leg",
        "color": "#806C5B",
        "number": "05",
        "sensor_pos": "Tronco o cintura",
        "instructions": "Inicie la grabación al levantar un pie del suelo y deténgala cuando finalice el apoyo monopodal.",
        "unit_label": "Tiempo de apoyo monopodal",
        "capture_type": "timed",
    },
    "jump": {
        "label": "Salto vertical",
        "task_code": "jump",
        "color": "#58708A",
        "number": "06",
        "sensor_pos": "Cadera (sobre el sacro, con cinturón)",
        "instructions": "Fije el sensor firme sobre el sacro con un cinturón (no en el tobillo). La persona debe quedarse quieta un segundo; cuando la pantalla diga «¡Ahora!», salta lo más alto posible con las manos en la cintura, aterriza con ambas piernas extendidas y queda quieta.",
        "unit_label": "Altura del salto",
        "capture_type": "power",
        "needs_mass": True,
        "gauge_max": 6.0,
    },
    "punch": {
        "label": "Golpe rápido",
        "task_code": "punch",
        "color": "#806C5B",
        "number": "07",
        "sensor_pos": "Muñeca",
        "instructions": "Fije el sensor firme en la muñeca. Con el brazo quieto un segundo, cuando la pantalla diga «¡Ahora!», dé un golpe rápido al aire y regrese el brazo a la posición inicial, quieto.",
        "unit_label": "Velocidad del golpe",
        "capture_type": "power",
        "gauge_max": 12.0,
    },
}

STYLESHEET = f"""
QWidget {{ background-color: {BG}; color: {TEXT}; font-family: 'Segoe UI'; font-size: 14px; }}
QLabel {{ background: transparent; }}
QFrame#appHeader {{ background: {BG_PANEL}; border-bottom: 1px solid {BORDER}; }}
QFrame#appHeader QLabel {{ background: transparent; }}
QLabel#brand {{ font-size: 24px; font-weight: 700; color: {TEXT}; }}
QLabel#brandSubtitle {{ font-size: 11px; color: {TEXT_MUTED}; }}
QLabel#simulationTag {{ color: {WARN}; background: #3C3020; padding: 6px 10px; border-radius: 7px; font-size: 11px; font-weight: 700; }}
QFrame#panel, QFrame#modeCard, QFrame#metricCard {{
    background-color: {BG_PANEL}; border: 1px solid {BORDER}; border-radius: 16px;
}}
QFrame#panel QLabel, QFrame#modeCard QLabel, QFrame#metricCard QLabel {{ background: transparent; border: none; }}
QFrame#modeCard:hover {{ border: 1px solid #98C6CD; }}
QFrame#hero {{ background-color: {NAVY}; border: none; border-radius: 20px; }}
QFrame#hero QLabel {{ background: transparent; color: white; }}
QFrame#hero QLabel#eyebrow {{ color: #91DADB; }}
QFrame#hero QLabel#eventLead {{ color: #D0E1E9; font-size: 16px; }}
QFrame#hero QLabel#eventNumber {{ color: #91DADB; font-size: 84px; font-weight: 300; }}
QLabel#eyebrow {{ color: {ACCENT}; font-size: 11px; font-weight: 700; }}
QLabel#title {{ color: {TEXT}; font-size: 30px; font-weight: 600; }}
QLabel#sectionTitle {{ color: {TEXT}; font-size: 19px; font-weight: 600; }}
QLabel#subtitle, QLabel#muted {{ color: {TEXT_MUTED}; font-size: 14px; }}
QLabel#metricValue {{ color: {TEXT}; font-size: 34px; font-weight: 600; }}
QLabel#stepActive {{ color: {ACCENT}; background: {SOFT_ACCENT}; border-radius: 7px; padding: 7px 12px; font-size: 12px; font-weight: 600; }}
QLabel#stepInactive {{ color: {TEXT_MUTED}; padding: 7px 12px; font-size: 12px; }}
QLabel#formHint {{ color: {TEXT_MUTED}; font-size: 12px; }}
QStatusBar {{ background-color: {BG_PANEL}; min-height: 26px; }}
QStatusBar::item {{ border: none; }}
QLabel#signature {{ color: {TEXT_MUTED}; background: transparent; font-size: 12px; }}
QLabel#eventTitle {{ font-size: 40px; font-weight: 600; }}
QLabel#eventLead {{ color: {TEXT_MUTED}; font-size: 17px; }}
QPushButton#eventButton {{ background-color: {ACCENT}; color: {BG}; border: 1px solid {ACCENT}; border-radius: 10px; padding: 12px 24px; font-size: 17px; font-weight: 600; min-height: 22px; }}
QPushButton#eventButton:hover, QPushButton#primaryButton:hover {{ background-color: #80E5DF; }}
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 9px; margin: 0; }}
QScrollBar::handle:vertical {{ background: #3B5268; border-radius: 4px; min-height: 28px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
QPushButton {{
    background-color: {BG_PANEL}; border: 1px solid {BORDER}; border-radius: 9px;
    padding: 9px 16px; font-size: 14px; font-weight: 600; min-height: 20px;
}}
QPushButton:hover {{ background-color: {SOFT_ACCENT}; border-color: #36848D; }}
QPushButton:pressed {{ background-color: #23505B; }}
QPushButton:focus {{ border: 2px solid {ACCENT}; }}
QPushButton:disabled, QPushButton#primaryButton:disabled, QPushButton#eventButton:disabled {{ background: #213246; color: #8297AA; border-color: #213246; }}
QPushButton#primaryButton {{ background-color: {ACCENT}; color: {BG}; border-color: {ACCENT}; padding: 10px 22px; }}
QPushButton#navButton {{ background: transparent; border: none; padding: 8px 12px; color: {TEXT_MUTED}; font-size: 13px; }}
QPushButton#navButton:hover {{ color: {ACCENT}; background: {SOFT_ACCENT}; }}
QPushButton#modeButton {{
    background-color: {SOFT_ACCENT}; color: {ACCENT}; border: none; border-radius: 8px;
    padding: 9px 14px; text-align: left; font-size: 13px; font-weight: 600;
}}
QPushButton#modeButton:hover {{ background-color: #23505B; }}
QDoubleSpinBox, QSpinBox, QLineEdit, QComboBox {{
    background-color: #0D1A28; border: 1px solid {BORDER}; border-radius: 8px;
    padding: 8px 11px; min-height: 22px; font-size: 15px;
}}
QDoubleSpinBox:focus, QSpinBox:focus, QLineEdit:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
QTextBrowser {{ background: {BG_PANEL}; color: {TEXT}; border: 1px solid {BORDER}; border-radius: 12px; padding: 12px; font-size: 13px; }}
QToolTip {{ background: {NAVY}; color: {TEXT}; border: 1px solid {BORDER}; padding: 7px 10px; }}
"""
