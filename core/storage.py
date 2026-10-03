"""Persistencia de sesiones, exportaciones CSV y respaldos verificables.

El manifiesto y cada artefacto se escriben completos antes de publicarse. Los
CSV de resultados son exportaciones conciliables por un identificador estable.
"""
import csv
import datetime as dt
import hashlib
import io
import json
import math
import os
import re
import shutil
import sys
import tempfile
import time
import uuid
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from core import __version__

if getattr(sys, "frozen", False):
    user_data = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    BASE_DATA_DIR = str(user_data / "AdquisicionMMS" / "data")
else:
    BASE_DATA_DIR = str(Path(__file__).resolve().parent.parent / "data")
DATA_DIR = BASE_DATA_DIR
DATA_SOURCE = "sensor"
RESULTS_LOG = os.path.join(DATA_DIR, "resultados_ciclovia_v2.csv")
TIMED_RESULTS_LOG = os.path.join(DATA_DIR, "resultados_pruebas_funcionales.csv")
REFERENCE_ORIENTATION_FILE = os.path.join(DATA_DIR, "orientacion_referencia.json")
REPORTS_DIR = os.path.join(DATA_DIR, "reportes")

METRIC_COLUMNS = [
    "altura_salto_cm", "tiempo_vuelo_ms", "velocidad_pico_m_s", "desplazamiento_cm",
    "potencia_pico_w", "potencia_relativa_w_kg", "potencia_media_w", "aceleracion_pico_g", "vel_angular_pico_dps",
]
QUALITY_COLUMNS = ["frecuencia_efectiva_hz", "muestras_perdidas_pct", "muestras_saturadas"]
PROVENANCE_COLUMNS = ["session_id", "session_timestamp", "data_source", "app_version"]
RESULTS_HEADER = [
    "fecha", "hora", "sub", "task", "run", "version_algoritmo", "valido", "motivos",
    "duration_s", *METRIC_COLUMNS, *QUALITY_COLUMNS, "masa_kg", "age_years", *PROVENANCE_COLUMNS,
]
TIMED_RESULTS_HEADER = [
    "fecha", "hora", "sub", "task", "run", "duration_s", "sample_count",
    "ended_by", "condition", "age_years", *QUALITY_COLUMNS,
    "valido", "motivos", "version_algoritmo", *PROVENANCE_COLUMNS,
]
RAW_OPTIONAL_COLUMNS = ["gyro_pairing", "gyro_saturated", "gyro_saturado", "signal_valid", "device_time", "sequence"]
CSV_WRITE_ENCODING = "utf-8-sig"
CSV_READ_ENCODING = "utf-8-sig"
SUB_PATTERN = re.compile(r"^[A-Za-z0-9]{1,12}$")
TASK_PATTERN = re.compile(r"^[A-Za-z0-9-]{1,40}$")
BACKUP_MANIFEST = "backup_manifest.json"


class SaveError(Exception):
    """No se pudo guardar; el mensaje es apto para mostrar al personal."""


@dataclass(frozen=True)
class SessionContext:
    session_id: str
    timestamp: dt.datetime
    sub: str
    task: str
    run: str
    origin: str
    data_dir: str
    metadata: dict = field(default_factory=dict)


def configure_storage(simulate: bool = False, *, base_dir: str | None = None) -> str:
    """Selecciona datos reales o simulados antes de cargar configuracion/calibracion.

    No crea carpetas ni lee datos. base_dir permite entornos de prueba aislados.
    """
    global BASE_DATA_DIR, DATA_DIR, DATA_SOURCE, RESULTS_LOG, TIMED_RESULTS_LOG
    global REFERENCE_ORIENTATION_FILE, REPORTS_DIR
    if base_dir is not None:
        BASE_DATA_DIR = os.path.abspath(base_dir)
    DATA_DIR = os.path.join(BASE_DATA_DIR, "simulacion") if simulate else BASE_DATA_DIR
    DATA_SOURCE = "simulacion" if simulate else "sensor"
    RESULTS_LOG = os.path.join(DATA_DIR, "resultados_ciclovia_v2.csv")
    TIMED_RESULTS_LOG = os.path.join(DATA_DIR, "resultados_pruebas_funcionales.csv")
    REFERENCE_ORIENTATION_FILE = os.path.join(DATA_DIR, "orientacion_referencia.json")
    REPORTS_DIR = os.path.join(DATA_DIR, "reportes")
    return DATA_DIR


def _ensure_data_dir():
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
    except OSError as exc:
        raise SaveError(f"No se pudo abrir la carpeta de datos ({exc.strerror or exc}).") from exc


@contextmanager
def _file_lock(path: str, timeout_s: float = 5.0):
    """Bloqueo liberado por el sistema al salir, incluso tras una interrupcion."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "a+b") as handle:
        if os.path.getsize(path) == 0:
            handle.write(b"\0")
            handle.flush()
        deadline = time.monotonic() + timeout_s
        while True:
            try:
                if os.name == "nt":
                    import msvcrt
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise SaveError("Otra instancia está guardando datos. Intente nuevamente.")
                time.sleep(0.02)
        try:
            yield
        finally:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _atomic_write(path: str, write, *, encoding: str = "utf-8", exclusive: bool = False) -> None:
    """Publica un archivo completo, preservando el anterior si falla la escritura."""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".mms-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", newline="", encoding=encoding) as handle:
            write(handle)
            handle.flush()
            os.fsync(handle.fileno())
        if exclusive:
            # rename en Windows rehusa destinos existentes; link hace lo mismo en POSIX.
            if os.name == "nt":
                os.rename(temporary, path)
            else:
                os.link(temporary, path)
        else:
            os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)


def save_json_atomic(path: str, data: dict, *, exclusive: bool = False) -> None:
    _atomic_write(path, lambda f: json.dump(data, f, indent=2, ensure_ascii=False, allow_nan=False),
                  exclusive=exclusive)


def normalize_sub(text: str) -> str | None:
    sub = text.strip()
    if not SUB_PATTERN.fullmatch(sub):
        return None
    return sub.zfill(2) if sub.isdigit() else sub


def _validate_identity(sub: str, task: str, run: str | None = None):
    if normalize_sub(sub) != sub or not TASK_PATTERN.fullmatch(task):
        raise SaveError("El participante o el protocolo no tienen un identificador válido.")
    if run is not None and (not run.isdigit() or int(run) < 1 or len(run) > 12):
        raise SaveError("El número de intento no es válido.")


def _session_stem(sub: str, task: str, run: str, timestamp=None) -> str:
    date = (timestamp or dt.datetime.now()).date().isoformat()
    return f"sub-{sub}_ses-{date}_task-{task}_run-{run}"


def _manifest_path(session: SessionContext) -> str:
    return os.path.join(session.data_dir, "sesiones", session.session_id + ".json")


def _reservation_path(sub: str, task: str, run: str, timestamp=None, data_dir=None) -> str:
    return os.path.join(data_dir or DATA_DIR, "sesiones", "reservas",
                        _session_stem(sub, task, run, timestamp) + ".json")


def _raw_path(sub: str, task: str, run: str, *, session: SessionContext | None = None) -> str:
    return os.path.join(session.data_dir if session else DATA_DIR,
                        _session_stem(sub, task, run, session.timestamp if session else None) + "_imu.csv")


def _report_path(sub: str, task: str, run: str, *, session: SessionContext | None = None) -> str:
    directory = os.path.join(session.data_dir, "reportes") if session else REPORTS_DIR
    return os.path.join(directory, _session_stem(sub, task, run,
                        session.timestamp if session else None) + "_reporte.html")


def next_run_number(sub: str, task: str) -> str:
    _validate_identity(sub, task)
    _ensure_data_dir()
    run = 1
    while any(os.path.exists(path) for path in (
        _raw_path(sub, task, f"{run:02d}"), _report_path(sub, task, f"{run:02d}"),
        _reservation_path(sub, task, f"{run:02d}"),
    )):
        run += 1
    return f"{run:02d}"


def create_session(sub: str, task: str, *, timestamp: dt.datetime | None = None,
                   metadata: dict | None = None) -> SessionContext:
    """Reserva un intento sin reutilizacion; todos sus artefactos comparten identidad."""
    _validate_identity(sub, task)
    _ensure_data_dir()
    stamp = timestamp or dt.datetime.now().astimezone()
    session_id = str(uuid.uuid4())
    run = 1
    while True:
        context = SessionContext(session_id, stamp, sub, task, f"{run:02d}", DATA_SOURCE,
                                 os.path.abspath(DATA_DIR), dict(metadata or {}))
        if any(os.path.exists(p) for p in (_raw_path(sub, task, context.run, session=context),
                                          _report_path(sub, task, context.run, session=context))):
            run += 1
            continue
        reservation = _reservation_path(sub, task, context.run, stamp, context.data_dir)
        try:
            save_json_atomic(reservation, {"session_id": session_id, "sub": sub}, exclusive=True)
        except FileExistsError:
            run += 1
            continue
        except OSError as exc:
            raise SaveError(f"No se pudo reservar el intento ({exc.strerror or exc}).") from exc
        try:
            save_json_atomic(_manifest_path(context), {
                "schema_version": 1, "session_id": session_id, "timestamp": stamp.isoformat(),
                "sub": sub, "task": task, "run": context.run, "data_source": context.origin,
                "app_version": __version__, "metadata": context.metadata, "artifacts": {},
                "status": "reservada",
            }, exclusive=True)
        except (OSError, ValueError, TypeError) as exc:
            raise SaveError(f"No se pudo crear el manifiesto del intento ({exc}).") from exc
        return context


def _check_session(session, sub, task, run):
    _validate_identity(sub, task, run)
    if session is not None and (session.sub, session.task, session.run) != (sub, task, run):
        raise SaveError("La identidad del intento no coincide con su sesión.")


def discard_session(session: SessionContext) -> None:
    """Elimina una reserva cancelada antes de escribir cualquier artefacto."""
    manifest = _manifest_path(session)
    reservation = _reservation_path(session.sub, session.task, session.run,
                                    session.timestamp, session.data_dir)
    with _file_lock(manifest + ".lock"):
        if any(os.path.exists(path) for path in (
            _raw_path(session.sub, session.task, session.run, session=session),
            _report_path(session.sub, session.task, session.run, session=session),
        )):
            raise SaveError("No se puede descartar una sesión que ya contiene datos guardados.")
        for path in (manifest, reservation):
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
            except OSError as exc:
                raise SaveError(f"No se pudo liberar la reserva ({exc.strerror or exc}).") from exc


def _record_artifact(session: SessionContext | None, key: str, path: str, **extra):
    if session is None:
        return
    manifest = _manifest_path(session)
    with _file_lock(manifest + ".lock"):
        with open(manifest, encoding="utf-8") as handle:
            data = json.load(handle)
        relative = os.path.relpath(path, session.data_dir).replace(os.sep, "/")
        artifact = {"path": relative, **extra}
        if key != "results" and os.path.isfile(path):
            artifact.update({"sha256": _file_digest(path), "size_bytes": os.path.getsize(path)})
        data["artifacts"][key] = artifact
        data["status"] = "guardada" if key == "report" else "parcial"
        save_json_atomic(manifest, data)


def next_participant_number() -> str:
    """Incluye reportes sin muestras, manifiestos, reservas y CSV anteriores."""
    _ensure_data_dir()
    max_sub = 0
    for folder in (DATA_DIR, REPORTS_DIR, os.path.join(DATA_DIR, "sesiones", "reservas")):
        if not os.path.isdir(folder):
            continue
        for name in os.listdir(folder):
            match = re.match(r"^sub-(\d+)_", name)
            if match:
                max_sub = max(max_sub, int(match.group(1)))
    for source in (RESULTS_LOG, TIMED_RESULTS_LOG, _pending_path(RESULTS_LOG),
                   _pending_path(TIMED_RESULTS_LOG)):
        try:
            with open(source, newline="", encoding=CSV_READ_ENCODING) as handle:
                for row in csv.DictReader(handle):
                    sub = row.get("sub", "")
                    if sub.isdigit():
                        max_sub = max(max_sub, int(sub))
        except (OSError, UnicodeError, csv.Error):
            continue
    return f"{max_sub + 1:02d}"


def _provenance(session: SessionContext | None, now: dt.datetime, sub: str, task: str, run: str):
    if session:
        return [session.session_id, session.timestamp.isoformat(), session.origin, __version__]
    # Compatibilidad con llamadores antiguos: el mismo intento tiene un ID estable.
    key = f"{os.path.abspath(DATA_DIR)}|{now.date()}|{sub}|{task}|{run}"
    return [str(uuid.uuid5(uuid.NAMESPACE_URL, key)), now.isoformat(), DATA_SOURCE, __version__]


def save_raw_session(sub: str, task: str, run: str, samples: list[dict], *,
                     session: SessionContext | None = None) -> str:
    _check_session(session, sub, task, run)
    path = _raw_path(sub, task, run, session=session)
    if not samples:
        return path
    now = session.timestamp if session else dt.datetime.now().astimezone()
    provenance = dict(zip(PROVENANCE_COLUMNS, _provenance(session, now, sub, task, run)))
    fields = list(dict.fromkeys([key for sample in samples for key in sample] +
                               RAW_OPTIONAL_COLUMNS + PROVENANCE_COLUMNS))
    def write(handle):
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for sample in samples:
            row = {key: "" for key in RAW_OPTIONAL_COLUMNS}
            row.update(sample)
            if "gyro_pairing" not in sample and "gyro_emparejado" in sample:
                row["gyro_pairing"] = "estimated" if sample["gyro_emparejado"] else "fallback"
            if "gyro_saturado" not in sample and "gyro_saturated" in sample:
                row["gyro_saturado"] = sample["gyro_saturated"]
            if "gyro_saturated" not in sample and "gyro_saturado" in sample:
                row["gyro_saturated"] = sample["gyro_saturado"]
            for flag in ("signal_valid", "gyro_saturated", "gyro_saturado", "gyro_emparejado"):
                if isinstance(row.get(flag), bool):
                    row[flag] = int(row[flag])
            row.update(provenance)
            writer.writerow(row)
    try:
        _atomic_write(path, write, encoding=CSV_WRITE_ENCODING, exclusive=True)
        _record_artifact(session, "raw", path, sample_count=len(samples))
    except (OSError, ValueError, TypeError) as exc:
        raise SaveError(f"No se pudo guardar el archivo IMU ({exc}).") from exc
    return path


def save_report(sub: str, task: str, run: str, html: str, *,
                session: SessionContext | None = None) -> str:
    _check_session(session, sub, task, run)
    path = _report_path(sub, task, run, session=session)
    try:
        _atomic_write(path, lambda f: f.write(html), exclusive=True)
        _record_artifact(session, "report", path)
    except (OSError, ValueError, TypeError) as exc:
        raise SaveError(f"No se pudo guardar el reporte ({exc}).") from exc
    return path


def save_reference_orientation(position: str, quaternion) -> None:
    values = [float(v) for v in quaternion]
    if len(values) != 4 or not all(math.isfinite(v) for v in values) or not any(values):
        raise ValueError("La orientación de referencia no es un cuaternión válido.")
    _ensure_data_dir()
    with _file_lock(REFERENCE_ORIENTATION_FILE + ".lock"):
        references = _load_reference_file()
        references[position] = values
        save_json_atomic(REFERENCE_ORIENTATION_FILE, {"por_ubicacion": references})


def load_reference_orientation(position: str):
    return _load_reference_file().get(position)


def _load_reference_file() -> dict:
    try:
        with open(REFERENCE_ORIENTATION_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    refs = data.get("por_ubicacion") if isinstance(data, dict) else None
    if not isinstance(refs, dict):
        return {}
    return {k: v for k, v in refs.items()
            if isinstance(v, list) and len(v) == 4 and any(v)
            and all(isinstance(x, (int, float)) and math.isfinite(x) for x in v)}


def _quality_values(quality) -> list:
    if quality is None:
        return ["", "", ""]
    return [round(quality.effective_rate_hz, 1), round(quality.lost_pct, 1), quality.saturated]


def _legacy_id(row: dict) -> str:
    identity = {key: row.get(key, "") for key in ("fecha", "hora", "sub", "task", "run")}
    if not any(identity.values()):
        identity = {k: v for k, v in row.items() if k not in PROVENANCE_COLUMNS}
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "mms-legacy:" +
                         json.dumps(identity, sort_keys=True, ensure_ascii=False)))


def _read_csv_rows(path: str, header: list[str]) -> tuple[list[list], bool]:
    """Migra por nombres de columna, sin descartar columnas o filas desconocidas."""
    if not os.path.exists(path):
        return [], False
    with open(path, newline="", encoding=CSV_READ_ENCODING) as handle:
        reader = csv.reader(handle)
        old_header = next(reader, [])
        if len(set(old_header)) != len(old_header) or any(c not in header for c in old_header):
            raise SaveError(f"{os.path.basename(path)} tiene columnas desconocidas o repetidas; "
                            "consérvelo y revise su formato antes de continuar.")
        migrated = old_header != header
        rows = []
        for values in reader:
            if not values:
                continue
            if len(values) > len(old_header):
                raise SaveError(f"{os.path.basename(path)} tiene una fila con columnas adicionales.")
            row = dict(zip(old_header, values))
            if "session_id" in header and not row.get("session_id"):
                row["session_id"] = _legacy_id(row)
                row["data_source"] = row.get("data_source") or "legacy-desconocido"
                migrated = True
            if "valido" in header and not row.get("valido") and "ended_by" in row:
                row["valido"] = "no" if row.get("ended_by") == "desconexion" else "si"
            rows.append([row.get(key, "") for key in header])
        return rows, migrated


def _write_csv_atomic(path: str, header: list[str], rows: list[list]) -> None:
    def write(handle):
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)
    _atomic_write(path, write, encoding=CSV_WRITE_ENCODING)


def _upgrade_header(path: str, header: list[str]) -> None:
    rows, migrated = _read_csv_rows(path, header)
    if migrated:
        _write_csv_atomic(path, header, rows)


def _pending_path(path: str) -> str:
    return path[:-len(".csv")] + "_pendiente.csv"


def _write_rows(path: str, header: list[str], rows: list[list]) -> None:
    existing, _ = _read_csv_rows(path, header)
    index = header.index("session_id") if "session_id" in header else None
    seen = {str(row[index]) for row in existing if index is not None and row[index]}
    for row in rows:
        if len(row) != len(header):
            raise SaveError("El resultado no coincide con el formato del archivo.")
        identifier = str(row[index]) if index is not None else ""
        if identifier and identifier in seen:
            continue
        existing.append(row)
        if identifier:
            seen.add(identifier)
    _write_csv_atomic(path, header, existing)


def _read_pending(pending: str, header: list[str]) -> list[list]:
    return _read_csv_rows(pending, header)[0]


def _append_row(path: str, header: list[str], row: list) -> str:
    _ensure_data_dir()
    pending = _pending_path(path)
    try:
        with _file_lock(path + ".lock"):
            rows = _read_pending(pending, header) + [row]
            try:
                _write_rows(path, header, rows)
            except PermissionError:
                _write_rows(pending, header, [row])
                return (f"{os.path.basename(path)} estaba abierto en otro programa (¿Excel?). El resultado "
                        f"se guardó en {os.path.basename(pending)} y se incorporará automáticamente "
                        "en la próxima medición con el archivo cerrado.")
            if os.path.exists(pending):
                try:
                    os.remove(pending)
                except OSError:
                    # Puede conservarse: session_id impide una segunda incorporación.
                    pass
    except OSError as exc:
        raise SaveError(f"No se pudo guardar el resultado en {os.path.basename(path)} ({exc}).") from exc
    return ""


def _result_path(timed: bool, session: SessionContext | None):
    if session:
        return os.path.join(session.data_dir, "resultados_pruebas_funcionales.csv" if timed
                            else "resultados_ciclovia_v2.csv")
    return TIMED_RESULTS_LOG if timed else RESULTS_LOG


def append_result(sub: str, task: str, run: str, rep_result, quality=None,
                  mass_kg: float | None = None, age_years: int | None = None,
                  algorithm_version: str = "", *, session: SessionContext | None = None) -> str:
    _check_session(session, sub, task, run)
    now = session.timestamp if session else dt.datetime.now().astimezone()
    by_key = {m.key: m for m in rep_result.metrics}
    reasons = " | ".join(c.detail for c in rep_result.checks if c.status == "fail")
    path = _result_path(False, session)
    warning = _append_row(path, RESULTS_HEADER, [
        now.date().isoformat(), now.strftime("%H:%M:%S"), sub, task, run, algorithm_version,
        "si" if rep_result.valid else "no", reasons, round(rep_result.duration_s, 3),
        *[round(by_key[k].value, 3) if k in by_key else "" for k in METRIC_COLUMNS],
        *_quality_values(quality), mass_kg if mass_kg is not None else "",
        age_years if age_years is not None else "", *_provenance(session, now, sub, task, run),
    ])
    try:
        _record_artifact(session, "results", path,
                         pending_path=os.path.relpath(_pending_path(path), session.data_dir).replace(os.sep, "/")
                         if session else "", session_id=session.session_id if session else "",
                         algorithm_version=algorithm_version, valid=rep_result.valid)
    except (OSError, ValueError) as exc:
        raise SaveError(f"El resultado se guardó, pero no se pudo actualizar su manifiesto ({exc}).") from exc
    return warning


def append_timed_result(sub: str, task: str, run: str, result, condition: str = "",
                        age_years: int | None = None, quality=None, *,
                        session: SessionContext | None = None, valid: bool | None = None,
                        reasons: str = "", algorithm_version: str = "") -> str:
    _check_session(session, sub, task, run)
    now = session.timestamp if session else dt.datetime.now().astimezone()
    if valid is None:
        valid = bool(result.sample_count) and result.ended_by != "desconexion"
    path = _result_path(True, session)
    warning = _append_row(path, TIMED_RESULTS_HEADER, [
        now.date().isoformat(), now.strftime("%H:%M:%S"), sub, task, run,
        round(result.duration_s, 3), result.sample_count, result.ended_by, condition,
        age_years if age_years is not None else "", *_quality_values(quality),
        "si" if valid else "no", reasons, algorithm_version,
        *_provenance(session, now, sub, task, run),
    ])
    try:
        _record_artifact(session, "results", path,
                         pending_path=os.path.relpath(_pending_path(path), session.data_dir).replace(os.sep, "/")
                         if session else "", session_id=session.session_id if session else "",
                         algorithm_version=algorithm_version, valid=valid)
    except (OSError, ValueError) as exc:
        raise SaveError(f"El resultado se guardó, pero no se pudo actualizar su manifiesto ({exc}).") from exc
    return warning


def previous_value(sub: str, task: str, *, timed: bool, condition: str = "",
                   metric_key: str = "duration_s") -> float | None:
    path = TIMED_RESULTS_LOG if timed else RESULTS_LOG
    latest = _latest_value(path, sub, task, timed, condition, metric_key, None)
    committed = set()
    try:
        with open(path, newline="", encoding=CSV_READ_ENCODING) as handle:
            committed = {row.get("session_id") or _legacy_id(row) for row in csv.DictReader(handle)}
    except (OSError, UnicodeError, csv.Error):
        pass
    return _latest_value(_pending_path(path), sub, task, timed, condition, metric_key, latest,
                         exclude_ids=committed)


def _latest_value(path, sub, task, timed, condition, metric_key, latest, *, exclude_ids=None):
    try:
        f = open(path, newline="", encoding=CSV_READ_ENCODING)
    except OSError:
        return latest
    with f:
        for row in csv.DictReader(f):
            if exclude_ids and (row.get("session_id") or _legacy_id(row)) in exclude_ids:
                continue
            if row.get("sub") != sub or row.get("task") != task:
                continue
            if timed and (row.get("condition", "") != condition or row.get("ended_by") == "desconexion"
                          or row.get("valido") == "no"):
                continue
            if not timed and row.get("valido") != "si":
                continue
            origin = row.get("data_source", "")
            if origin and origin not in (DATA_SOURCE, "legacy-desconocido"):
                continue
            try:
                value = float(row[metric_key])
            except (KeyError, ValueError, TypeError):
                continue
            if math.isfinite(value):
                latest = value
    return latest


def _file_digest(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def export_backup(destination: str, *, include_simulation: bool = False) -> str:
    """Exporta la carpeta activa a ZIP sin reemplazar archivos; contiene datos privados.

    El ZIP usa orden/fechas constantes e incluye hashes. No incorpora bloqueos,
    temporales ni la carpeta simulacion desde el almacenamiento real por defecto.
    """
    root = Path(DATA_DIR).resolve()
    destination_path = Path(destination).resolve()
    if destination_path == root or root in destination_path.parents:
        raise SaveError("Guarde el respaldo fuera de la carpeta de datos.")
    os.makedirs(destination_path.parent, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".mms-backup-", suffix=".tmp", dir=destination_path.parent)
    os.close(fd)
    try:
        files = []
        if root.exists():
            for path in sorted(root.rglob("*")):
                relative = path.relative_to(root).as_posix()
                if path.is_symlink() or not path.is_file() or path.name.endswith((".lock", ".tmp")):
                    continue
                resolved = path.resolve()
                if root not in resolved.parents:
                    # Tampoco incluir archivos a través de una unión de directorios Windows.
                    continue
                if not include_simulation and DATA_SOURCE == "sensor" and relative.startswith("simulacion/"):
                    continue
                files.append((path, relative))
        manifest = {"schema_version": 1, "app_version": __version__, "data_source": DATA_SOURCE,
                    "files": {}}
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path, relative in files:
                content = path.read_bytes()
                manifest["files"][relative] = {"sha256": hashlib.sha256(content).hexdigest(),
                                                "size_bytes": len(content)}
                info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, content)
            info = zipfile.ZipInfo(BACKUP_MANIFEST, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, json.dumps(manifest, sort_keys=True, ensure_ascii=False).encode("utf-8"))
        with open(temporary, "r+b") as handle:
            os.fsync(handle.fileno())
        if os.name == "nt":
            os.rename(temporary, destination_path)
        else:
            os.link(temporary, destination_path)
        return str(destination_path)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        raise SaveError(f"No se pudo crear el respaldo ({exc}).") from exc
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)


def _safe_archive_name(name: str) -> bool:
    path = PurePosixPath(name)
    reserved = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])$", re.I)
    return (bool(name) and not path.is_absolute() and ".." not in path.parts
            and "\\" not in name and ":" not in name and "\0" not in name
            and path.as_posix() == name and not name.endswith("/")
            and all(part == part.rstrip(" .") and not reserved.fullmatch(part.split(".")[0])
                    for part in path.parts))


def restore_backup(archive_path: str, *, destination: str | None = None) -> str:
    """Valida el ZIP y restaura en una carpeta NUEVA; nunca reemplaza datos activos.

    Devuelve la carpeta recuperada para inspeccion/importacion posterior. No cambia
    DATA_DIR ni mezcla participantes de equipos distintos automaticamente.
    """
    target = Path(destination or (str(Path(DATA_DIR).parent / ("MMS-restaurado-" + uuid.uuid4().hex)))).resolve()
    active = Path(DATA_DIR).resolve()
    if target == active or active in target.parents or target.exists():
        raise SaveError("La restauración necesita una carpeta nueva fuera de los datos activos.")
    os.makedirs(target.parent, exist_ok=True)
    staging = tempfile.mkdtemp(prefix=".mms-restore-", dir=target.parent)
    try:
        with zipfile.ZipFile(archive_path, "r") as archive:
            infos = archive.infolist()
            names = [entry.filename for entry in infos]
            if len(names) != len({name.casefold() for name in names}) or len(names) > 50000:
                raise SaveError("El respaldo contiene nombres repetidos o demasiados archivos.")
            if sum(entry.file_size for entry in infos) > 2 * 1024 ** 3:
                raise SaveError("El respaldo supera el límite de restauración de 2 GB.")
            for entry in infos:
                if not _safe_archive_name(entry.filename) or (entry.external_attr >> 16) & 0o170000 == 0o120000:
                    raise SaveError("El respaldo contiene una ruta o un enlace no permitido.")
            manifest = json.loads(archive.read(BACKUP_MANIFEST))
            expected = manifest.get("files") if isinstance(manifest, dict) else None
            if (not isinstance(manifest, dict) or manifest.get("schema_version") != 1 or not isinstance(expected, dict)
                    or set(names) != set(expected) | {BACKUP_MANIFEST}):
                raise SaveError("El manifiesto del respaldo no coincide con sus archivos.")
            for name, record in expected.items():
                content = archive.read(name)
                if (not isinstance(record, dict) or record.get("size_bytes") != len(content)
                        or record.get("sha256") != hashlib.sha256(content).hexdigest()):
                    raise SaveError(f"El archivo {name} no supera la verificación del respaldo.")
                restored = Path(staging).joinpath(*PurePosixPath(name).parts)
                restored.parent.mkdir(parents=True, exist_ok=True)
                restored.write_bytes(content)
        # Los datos solo se hacen visibles una vez verificados todos los archivos.
        if target.exists():
            raise SaveError("La carpeta de restauración ya existe; no se reemplazó.")
        os.rename(staging, target)
        return str(target)
    except (OSError, KeyError, ValueError, zipfile.BadZipFile) as exc:
        raise SaveError(f"No se pudo restaurar el respaldo ({exc}).") from exc
    finally:
        if os.path.isdir(staging):
            shutil.rmtree(staging)
