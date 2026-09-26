"""Guardado de datos de sesion: crudo (IMU), resumen de resultados y reportes."""
import csv
import datetime as dt
import json
import os
import sys
import tempfile
from pathlib import Path

if getattr(sys, "frozen", False):
    # El directorio de un ejecutable instalado puede ser de solo lectura.
    user_data = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    DATA_DIR = str(user_data / "AdquisicionMMS" / "data")
else:
    DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
# resultados_ciclovia.csv queda como historico del algoritmo anterior (no fiable).
RESULTS_LOG = os.path.join(DATA_DIR, "resultados_ciclovia_v2.csv")
TIMED_RESULTS_LOG = os.path.join(DATA_DIR, "resultados_pruebas_funcionales.csv")
REFERENCE_ORIENTATION_FILE = os.path.join(DATA_DIR, "orientacion_referencia.json")
REPORTS_DIR = os.path.join(DATA_DIR, "reportes")

METRIC_COLUMNS = [
    "altura_salto_cm", "tiempo_vuelo_ms", "velocidad_pico_m_s", "desplazamiento_cm",
    "potencia_pico_w", "potencia_relativa_w_kg", "potencia_media_w", "aceleracion_pico_g", "vel_angular_pico_dps",
]
QUALITY_COLUMNS = ["frecuencia_efectiva_hz", "muestras_perdidas_pct", "muestras_saturadas"]
RESULTS_HEADER = [
    "fecha", "hora", "sub", "task", "run", "version_algoritmo", "valido", "motivos",
    "duration_s", *METRIC_COLUMNS, *QUALITY_COLUMNS, "masa_kg", "age_years",
]
TIMED_RESULTS_HEADER = [
    "fecha", "hora", "sub", "task", "run", "duration_s", "sample_count",
    "ended_by", "condition", "age_years", *QUALITY_COLUMNS,
]


def _ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def next_participant_number() -> str:
    """Escanea data/ y devuelve el proximo numero de participante (sub)."""
    _ensure_data_dir()
    max_sub = 0
    for name in os.listdir(DATA_DIR):
        if name.startswith("sub-") and "_" in name:
            try:
                max_sub = max(max_sub, int(name.split("_")[0].split("-")[1]))
            except (ValueError, IndexError):
                continue
    return str(max_sub + 1).zfill(2)


def next_run_number(sub: str, task: str) -> str:
    """Busca el siguiente numero de intento (run) disponible para este sub/task."""
    _ensure_data_dir()
    run = 1
    while os.path.exists(_raw_path(sub, task, str(run).zfill(2))):
        run += 1
    return str(run).zfill(2)


def _raw_path(sub: str, task: str, run: str) -> str:
    today = dt.date.today().isoformat()
    return os.path.join(DATA_DIR, f"sub-{sub}_ses-{today}_task-{task}_run-{run}_imu.csv")


def save_raw_session(sub: str, task: str, run: str, samples: list[dict]) -> str:
    _ensure_data_dir()
    path = _raw_path(sub, task, run)
    if not samples:
        return path
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(samples[0].keys()), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(samples)
    return path


def save_report(sub: str, task: str, run: str, html: str) -> str:
    os.makedirs(REPORTS_DIR, exist_ok=True)
    today = dt.date.today().isoformat()
    path = os.path.join(REPORTS_DIR, f"sub-{sub}_ses-{today}_task-{task}_run-{run}_reporte.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path


def save_reference_orientation(quaternion) -> None:
    """Guarda la orientacion 'estandar' del sensor (calibrada una vez por el operador)
    para poder compararla contra la de cada participante y guiar la colocacion."""
    _ensure_data_dir()
    with open(REFERENCE_ORIENTATION_FILE, "w", encoding="utf-8") as f:
        json.dump({"q": list(quaternion)}, f)


def load_reference_orientation():
    if not os.path.exists(REFERENCE_ORIENTATION_FILE):
        return None
    with open(REFERENCE_ORIENTATION_FILE, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("q")


def _quality_values(quality) -> list:
    if quality is None:
        return ["", "", ""]
    return [round(quality.effective_rate_hz, 1), round(quality.lost_pct, 1), quality.saturated]


def _upgrade_header(path: str, header: list[str]) -> None:
    """Agrega columnas nuevas al final de un CSV existente, sin perder filas."""
    with open(path, newline="", encoding="utf-8") as existing:
        reader = csv.reader(existing)
        old_header = next(reader, [])
        if old_header == header:
            return
        old_rows = list(reader)
    if old_header != header[:len(old_header)]:
        raise ValueError(f"Formato desconocido de {os.path.basename(path)}")
    padding = [""] * (len(header) - len(old_header))
    fd, temp_path = tempfile.mkstemp(prefix="resultados_", suffix=".tmp", dir=DATA_DIR)
    with os.fdopen(fd, "w", newline="", encoding="utf-8") as upgraded:
        writer = csv.writer(upgraded)
        writer.writerow(header)
        writer.writerows([row + padding for row in old_rows])
    os.replace(temp_path, path)


def _append_row(path: str, header: list[str], row: list) -> None:
    _ensure_data_dir()
    is_new = not os.path.exists(path)
    if not is_new:
        _upgrade_header(path, header)
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if is_new:
            writer.writerow(header)
        writer.writerow(row)


def append_result(sub: str, task: str, run: str, rep_result, quality=None,
                  mass_kg: float | None = None, age_years: int | None = None,
                  algorithm_version: str = "") -> None:
    now = dt.datetime.now()
    by_key = {m.key: m for m in rep_result.metrics}
    reasons = " | ".join(c.detail for c in rep_result.checks if c.status == "fail")
    _append_row(RESULTS_LOG, RESULTS_HEADER, [
        now.date().isoformat(), now.strftime("%H:%M:%S"), sub, task, run, algorithm_version,
        "si" if rep_result.valid else "no", reasons, round(rep_result.duration_s, 3),
        *[round(by_key[k].value, 3) if k in by_key else "" for k in METRIC_COLUMNS],
        *_quality_values(quality),
        mass_kg if mass_kg is not None else "", age_years if age_years is not None else "",
    ])


def append_timed_result(
    sub: str, task: str, run: str, result, condition: str = "",
    age_years: int | None = None, quality=None,
) -> None:
    """Resume una captura cronometrada sin asignarle métricas clínicas no validadas."""
    now = dt.datetime.now()
    _append_row(TIMED_RESULTS_LOG, TIMED_RESULTS_HEADER, [
        now.date().isoformat(), now.strftime("%H:%M:%S"), sub, task, run,
        round(result.duration_s, 3), result.sample_count, result.ended_by, condition,
        age_years if age_years is not None else "", *_quality_values(quality),
    ])


def previous_value(sub: str, task: str, *, timed: bool, condition: str = "",
                   metric_key: str = "duration_s") -> float | None:
    """Devuelve el ultimo valor valido del mismo participante y protocolo."""
    path = TIMED_RESULTS_LOG if timed else RESULTS_LOG
    if not os.path.exists(path):
        return None
    latest = None
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("sub") != sub or row.get("task") != task:
                continue
            if timed and row.get("condition", "") != condition:
                continue
            if not timed and row.get("valido") != "si":
                continue
            try:
                latest = float(row[metric_key])
            except (KeyError, ValueError, TypeError):
                continue
    return latest
