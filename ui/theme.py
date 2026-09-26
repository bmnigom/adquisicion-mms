"""Identidad visual y configuración de las pruebas."""

BG = "#F5F7FA"
BG_PANEL = "#FFFFFF"
TEXT = "#172B3A"
TEXT_MUTED = "#637586"
ACCENT = "#176B84"
GOOD = "#247A64"
WARN = "#A56819"
BAD = "#B44949"
BORDER = "#DCE4EA"

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
QWidget {{ background-color: {BG}; color: {TEXT}; font-family: Arial; font-size: 14px; }}
QFrame#panel, QFrame#modeCard, QFrame#metricCard {{
    background-color: {BG_PANEL}; border: 1px solid {BORDER}; border-radius: 14px;
}}
QFrame#panel QLabel {{ background: transparent; border: none; }}
QLabel#eyebrow {{ color: {ACCENT}; font-size: 11px; font-weight: 700; letter-spacing: 1px; }}
QLabel#title {{ color: {TEXT}; font-size: 31px; font-weight: 700; }}
QLabel#sectionTitle {{ color: {TEXT}; font-size: 20px; font-weight: 650; }}
QLabel#subtitle, QLabel#muted {{ color: {TEXT_MUTED}; font-size: 14px; }}
QLabel#metricValue {{ color: {TEXT}; font-size: 29px; font-weight: 700; }}
QStatusBar {{ background-color: {BG}; border-top: 1px solid {BORDER}; min-height: 28px; }}
QStatusBar::item {{ border: none; }}
QLabel#signature {{ color: {TEXT_MUTED}; background: transparent; font-size: 12px; }}
QLabel#eventTitle {{ color: {TEXT}; font-size: 43px; font-weight: 700; }}
QLabel#eventLead {{ color: {TEXT_MUTED}; font-size: 19px; }}
QLabel#eventNumber {{ color: {ACCENT}; font-size: 60px; font-weight: 700; }}
QPushButton#eventButton {{ background-color: {ACCENT}; color: white; border: 1px solid {ACCENT}; border-radius: 12px; padding: 14px 24px; font-size: 20px; font-weight: 700; min-height: 30px; }}
QPushButton#eventButton:hover {{ background-color: #11576C; }}
QPushButton#eventButton:disabled {{ background-color: #AFC3CC; color: #F5F7FA; border-color: #AFC3CC; }}
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 9px; margin: 0; }}
QScrollBar::handle:vertical {{ background: #C4D0D8; border-radius: 4px; min-height: 28px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
QPushButton {{
    background-color: {BG_PANEL}; border: 1px solid {BORDER}; border-radius: 8px;
    padding: 11px 18px; font-size: 14px; font-weight: 600;
}}
QPushButton:hover {{ background-color: #EAF1F4; border-color: {ACCENT}; }}
QPushButton:pressed {{ background-color: #D7E5EB; }}
QPushButton#primaryButton {{ background-color: {ACCENT}; color: white; border-color: {ACCENT}; }}
QPushButton#primaryButton:hover {{ background-color: #11576C; }}
QPushButton#modeButton {{
    background-color: {BG_PANEL}; border: 1px solid {BORDER}; border-radius: 12px;
    padding: 14px; text-align: left; font-size: 16px; font-weight: 650;
}}
QPushButton#modeButton:hover {{ border-color: {ACCENT}; background-color: #EDF4F6; }}
QDoubleSpinBox, QSpinBox, QLineEdit, QComboBox {{
    background-color: white; border: 1px solid #C6D2D9; border-radius: 7px;
    padding: 9px 11px; min-height: 20px; font-size: 15px;
}}
QDoubleSpinBox:focus, QSpinBox:focus, QLineEdit:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
"""
