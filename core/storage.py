"""Guardado de datos de sesion: crudo (IMU), resumen de resultados y reportes."""
import csv
import datetime as dt
import json
import os
import re
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


# Los CSV se escriben con BOM (utf-8-sig) para que Excel muestre bien las tildes;
# al leer, utf-8-sig acepta tambien los archivos antiguos sin BOM.
CSV_WRITE_ENCODING = "utf-8-sig"
CSV_READ_ENCODING = "utf-8-sig"
# Identificador de participante: solo letras y numeros (se usa en nombres de archivo).
SUB_PATTERN = re.compile(r"^[A-Za-z0-9]{1,12}$")


class SaveError(Exception):
    """No se pudo guardar un archivo; el mensaje es apto para mostrar al personal."""


def _ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def normalize_sub(text: str) -> str | None:
    """Identificador valido (relleno a 2 digitos si es numerico) o None."""
    sub = text.strip()
    if not SUB_PATTERN.match(sub):
        return None
    return sub.zfill(2) if sub.isdigit() else sub


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
    """Busca el siguiente numero de intento (run) disponible para este sub/task.

    Cuenta tambien los reportes: un intento sin muestras no deja archivo IMU,
    pero su reporte no debe sobrescribirse con el intento siguiente.
    """
    _ensure_data_dir()
    run = 1
    while any(os.path.exists(p) for p in (_raw_path(sub, task, str(run).zfill(2)),
                                           _report_path(sub, task, str(run).zfill(2)))):
        run += 1
    return str(run).zfill(2)


def _raw_path(sub: str, task: str, run: str) -> str:
    today = dt.date.today().isoformat()
    return os.path.join(DATA_DIR, f"sub-{sub}_ses-{today}_task-{task}_run-{run}_imu.csv")


def _report_path(sub: str, task: str, run: str) -> str:
    today = dt.date.today().isoformat()
    return os.path.join(REPORTS_DIR, f"sub-{sub}_ses-{today}_task-{task}_run-{run}_reporte.html")


def save_raw_session(sub: str, task: str, run: str, samples: list[dict]) -> str:
    _ensure_data_dir()
    path = _raw_path(sub, task, run)
    if not samples:
        return path
    try:
        with open(path, "w", newline="", encoding=CSV_WRITE_ENCODING) as f:
            writer = csv.DictWriter(f, fieldnames=list(samples[0].keys()), extrasaction="ignore")
            writer.writeheader()
            writer.writerows(samples)
    except OSError as exc:
        raise SaveError(f"No se pudo guardar el archivo IMU ({exc.strerror or exc}).") from exc
    return path


def save_report(sub: str, task: str, run: str, html: str) -> str:
    path = _report_path(sub, task, run)
    try:
        os.makedirs(REPORTS_DIR, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
    except OSError as exc:
        raise SaveError(f"No se pudo guardar el reporte ({exc.strerror or exc}).") from exc
    return path


def save_reference_orientation(position: str, quaternion) -> None:
    """Guarda la orientacion 'estandar' del sensor para una ubicacion (cadera, muneca...),
    calibrada por el operador, para guiar la colocacion en cada participante."""
    _ensure_data_dir()
    references = _load_reference_file()
    references[position] = [float(v) for v in quaternion]
    with open(REFERENCE_ORIENTATION_FILE, "w", encoding="utf-8") as f:
        json.dump({"por_ubicacion": references}, f, indent=2, ensure_ascii=False)


def load_reference_orientation(position: str):
    return _load_reference_file().get(position)


def _load_reference_file() -> dict:
    """Referencias por ubicacion. Un archivo danado o del formato anterior (una sola
    referencia sin ubicacion) se trata como 'sin calibrar', sin impedir el arranque."""
    try:
        with open(REFERENCE_ORIENTATION_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    refs = data.get("por_ubicacion") if isinstance(data, dict) else None
    if not isinstance(refs, dict):
        return {}
    return {k: v for k, v in refs.items()
            if isinstance(v, list) and len(v) == 4 and all(isinstance(x, (int, float)) for x in v)}


def _quality_values(quality) -> list:
    if quality is None:
        return ["", "", ""]
    return [round(quality.effective_rate_hz, 1), round(quality.lost_pct, 1), quality.saturated]


def _upgrade_header(path: str, header: list[str]) -> None:
    """Agrega columnas nuevas al final de un CSV existente, sin perder filas."""
    with open(path, newline="", encoding=CSV_READ_ENCODING) as existing:
        reader = csv.reader(existing)
        old_header = next(reader, [])
        if old_header == header:
            return
        old_rows = list(reader)
    if old_header != header[:len(old_header)]:
        raise SaveError(f"{os.path.basename(path)} tiene columnas que no corresponden a esta versión "
                        "de la aplicación; renómbrelo para que se cree uno nuevo.")
    padding = [""] * (len(header) - len(old_header))
    fd, temp_path = tempfile.mkstemp(prefix="resultados_", suffix=".tmp", dir=os.path.dirname(path))
    with os.fdopen(fd, "w", newline="", encoding=CSV_WRITE_ENCODING) as upgraded:
        writer = csv.writer(upgraded)
        writer.writerow(header)
        writer.writerows([row + padding for row in old_rows])
    try:
        os.replace(temp_path, path)
    except OSError:
        os.remove(temp_path)
        raise


def _pending_path(path: str) -> str:
    return path[:-len(".csv")] + "_pendiente.csv"


def _write_rows(path: str, header: list[str], rows: list[list]) -> None:
    is_new = not os.path.exists(path)
    if not is_new:
        _upgrade_header(path, header)
    with open(path, "a", newline="", encoding=CSV_WRITE_ENCODING) as f:
        writer = csv.writer(f)
        if is_new:
            writer.writerow(header)
        writer.writerows(rows)


def _read_pending(pending: str, header: list[str]) -> list[list]:
    if not os.path.exists(pending):
        return []
    _upgrade_header(pending, header)
    with open(pending, newline="", encoding=CSV_READ_ENCODING) as f:
        reader = csv.reader(f)
        next(reader, None)
        return [row for row in reader if row]


def _append_row(path: str, header: list[str], row: list) -> str:
    """Agrega la fila. Devuelve "" o un aviso si quedo guardada en el archivo pendiente.

    Si el CSV esta bloqueado (tipicamente, abierto en Excel), la fila se guarda en
    <nombre>_pendiente.csv y se incorpora al principal en el siguiente guardado.
    """
    _ensure_data_dir()
    pending = _pending_path(path)
    try:
        rows = _read_pending(pending, header) + [row]
        _write_rows(path, header, rows)
    except PermissionError:
        try:
            _write_rows(pending, header, [row])
        except OSError as exc:
            raise SaveError(f"No se pudo guardar el resultado: {os.path.basename(path)} y su archivo "
                            f"pendiente están bloqueados ({exc.strerror or exc}). Cierre Excel.") from exc
        return (f"{os.path.basename(path)} estaba abierto en otro programa (¿Excel?). El resultado se "
                f"guardó en {os.path.basename(pending)} y se incorporará automáticamente en la próxima "
                "medición con el archivo cerrado.")
    except OSError as exc:
        raise SaveError(f"No se pudo guardar el resultado en {os.path.basename(path)} "
                        f"({exc.strerror or exc}).") from exc
    if len(rows) > 1:
        try:
            os.remove(pending)
        except OSError:
            # Evita duplicar esas filas la proxima vez: el pendiente queda vacio.
            with open(pending, "w", newline="", encoding=CSV_WRITE_ENCODING):
                pass
    return ""


def append_result(sub: str, task: str, run: str, rep_result, quality=None,
                  mass_kg: float | None = None, age_years: int | None = None,
                  algorithm_version: str = "") -> str:
    now = dt.datetime.now()
    by_key = {m.key: m for m in rep_result.metrics}
    reasons = " | ".join(c.detail for c in rep_result.checks if c.status == "fail")
    return _append_row(RESULTS_LOG, RESULTS_HEADER, [
        now.date().isoformat(), now.strftime("%H:%M:%S"), sub, task, run, algorithm_version,
        "si" if rep_result.valid else "no", reasons, round(rep_result.duration_s, 3),
        *[round(by_key[k].value, 3) if k in by_key else "" for k in METRIC_COLUMNS],
        *_quality_values(quality),
        mass_kg if mass_kg is not None else "", age_years if age_years is not None else "",
    ])


def append_timed_result(
    sub: str, task: str, run: str, result, condition: str = "",
    age_years: int | None = None, quality=None,
) -> str:
    """Resume una captura cronometrada sin asignarle métricas clínicas no validadas."""
    now = dt.datetime.now()
    return _append_row(TIMED_RESULTS_LOG, TIMED_RESULTS_HEADER, [
        now.date().isoformat(), now.strftime("%H:%M:%S"), sub, task, run,
        round(result.duration_s, 3), result.sample_count, result.ended_by, condition,
        age_years if age_years is not None else "", *_quality_values(quality),
    ])


def previous_value(sub: str, task: str, *, timed: bool, condition: str = "",
                   metric_key: str = "duration_s") -> float | None:
    """Devuelve el ultimo valor valido del mismo participante y protocolo."""
    path = TIMED_RESULTS_LOG if timed else RESULTS_LOG
    latest = None
    for source in (path, _pending_path(path)):  # el pendiente tiene las filas mas recientes
        latest = _latest_value(source, sub, task, timed, condition, metric_key, latest)
    return latest


def _latest_value(path, sub, task, timed, condition, metric_key, latest):
    if not os.path.exists(path):
        return latest
    try:
        f = open(path, newline="", encoding=CSV_READ_ENCODING)
    except OSError:
        return latest
    with f:
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
