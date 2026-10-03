"""Reprocesa registros IMU con el algoritmo actual, sin modificar originales.

No modifica ningun archivo original. Genera:
  - data/reprocesado_datos_anteriores.csv : un renglon por registro, con el
    resultado anterior, el nuevo y las verificaciones de calidad.
  - data/reportes/reprocesado_datos_anteriores.html : resumen para el personal.

Uso (desde la carpeta del proyecto):
    python reprocesar_datos.py
    python reprocesar_datos.py --include-current

Por defecto se seleccionan registros 1.x. --include-current permite revisar
también CSV actuales. Las horas del PC no certifican continuidad ni sincronía:
sin identidad nativa solo puede informarse una estimación. La masa ausente no
se recupera del movimiento: se usa 70 kg y la potencia queda como ilustrativa.
"""
import argparse
import csv
import datetime as dt
import glob
import os
import math
from html import escape

from core import quality as signal_quality
from core import storage
from core.kinematics import ALGORITHM_VERSION, Check, RepDetector
from core.pipeline import SignalProcessor
from core.report import BACKGROUNDS, COLORS, ICON_FONT, ICONS, verdict
from core.sample_clock import reconstruct

RATE_HZ = 100.0
OLD_ACC_RANGE_G = 4.0     # rango configurado en la version anterior
# El CSV anterior no guardaba el peso: la potencia reprocesada usa este valor para todos
# y NO es comparable entre personas (la altura del salto y el ascenso no dependen de el).
DEFAULT_MASS_KG = 70.0
OLD_RESULTS = os.path.join(storage.DATA_DIR, "resultados_ciclovia.csv")
OUT_CSV = os.path.join(storage.DATA_DIR, "reprocesado_datos_anteriores.csv")
OUT_HTML = os.path.join(storage.REPORTS_DIR, "reprocesado_datos_anteriores.html")
POWER_TASKS = {"jump", "sts", "punch"}


def parse_name(path):
    parts = dict(p.split("-", 1) for p in os.path.basename(path).split("_") if "-" in p)
    return parts.get("sub", ""), parts.get("ses", ""), parts.get("task", ""), parts.get("run", "")


def load_old_results():
    old = {}
    if os.path.exists(OLD_RESULTS):
        with open(OLD_RESULTS, newline="", encoding=storage.CSV_READ_ENCODING) as f:
            for row in csv.DictReader(f):
                old[(row["fecha"], row["sub"], row["task"], row["run"])] = row
    return old


def analyze_file(path, task, *, include_current=False):
    with open(path, newline="", encoding=storage.CSV_READ_ENCODING) as f:
        rows = list(csv.DictReader(f))
    if not rows or ("host_time" in rows[0] and not include_current):
        return None  # vacio, o ya grabado con la version nueva
    return analyze_rows(rows, task, acc_range_g=16.0 if "host_time" in rows[0] else OLD_ACC_RANGE_G)


def analyze_rows(rows, task, *, mass_kg=None, acc_range_g=OLD_ACC_RANGE_G):
    """Analiza filas en memoria; conserva metadatos y rechaza datos mal formados.

    device_time son segundos del reloj común del sensor, sequence un índice
    común verificado. Nunca se promueve host_time/epoch de llegada a nativo.
    Sin gyro_pairing el registro histórico queda con sincronía desconocida.
    """
    timing_error = None
    try:
        host = [float(r.get("host_time") or r["time"]) for r in rows]
        device_times = [r.get("device_time") for r in rows]
        sequences = [r.get("sequence") for r in rows]
        times, lost = reconstruct(host, RATE_HZ, device_times=device_times, sequences=sequences)
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        # Un archivo defectuoso debe dejar un veredicto de fallo, sin detener el
        # resto del lote ni reinterpretar sus tiempos como si fueran correctos.
        timing_error = str(exc)
        host = [i / RATE_HZ for i in range(len(rows))]
        times, lost = reconstruct(host, RATE_HZ)
    proc = SignalProcessor(RATE_HZ, acc_range_g)
    samples = []
    for r, t, h, k in zip(rows, times, host, lost):
        record = {**r, "time": t, "host_time": h, "lost_before": int(k)}
        if timing_error is not None:
            record["signal_valid"] = False
        s = proc.process(record)
        samples.append(s)
    q_rows = [{"time": s.t, "host_time": s.host_time, "lost_before": s.lost_before,
               "saturado": int(s.saturated), "signal_valid": s.signal_valid,
               "gyro_pairing": s.gyro_pairing, "gyro_saturated": s.gyro_saturated,
               "device_time": s.device_time, "sequence": s.sequence} for s in samples]
    quality = signal_quality.assess(q_rows, RATE_HZ)
    checks = [signal_quality.transmission_check(quality, strict=task in POWER_TASKS,
                                               requires_gyro=task in {"sts", "punch"})]
    if timing_error is not None:
        checks.append(Check("Tiempos del registro", "fail", "Información temporal inválida: " + timing_error))
    if mass_kg is None and task in {"jump", "sts"}:
        checks.append(Check("Masa de referencia", "warn",
                            f"Masa no registrada: la potencia usa {DEFAULT_MASS_KG:.0f} kg y es solo ilustrativa; no compare personas."))
    if quality.saturated:
        status = "fail" if task == "sts" else "ok" if task == "jump" else "warn"
        checks.append(Check(f"Saturación (rango ±{acc_range_g:g} g)", status,
                            f"{quality.saturated} muestras en el límite del sensor."))
    if task not in POWER_TASKS:
        return {"quality": quality, "checks": checks, "rep": None}

    detector = RepDetector(task, DEFAULT_MASS_KG if mass_kg is None else mass_kg, RATE_HZ)
    rep = None
    for s in samples:
        _, rep = detector.update(s)
        if rep is not None:
            break
    if rep is None:
        if detector.phase == "moving":
            rep = detector.timeout_result(quality.duration_s)
            rep.checks = [Check("Reposo final", "fail",
                                "El registro terminó antes de que la persona quedara quieta; la versión "
                                "requiere conservar el reposo final completo.")]
        else:
            rep = detector.timeout_result(quality.duration_s)
    rep.checks = checks + rep.checks
    return {"quality": quality, "checks": rep.checks, "rep": rep}


def _old_text(old: dict | None) -> str:
    """Resultado anterior legible; tolera celdas vacias o no numericas."""
    if not old:
        return "—"
    try:
        power, velocity, displacement = [float(old[key]) for key in
                                         ("peak_power_w", "peak_velocity_m_s", "max_displacement_m")]
        if not all(math.isfinite(value) for value in (power, velocity, displacement)):
            return "—"
        return f'{power:.0f} W · {velocity:.2f} m/s · {displacement * 100:.0f} cm'
    except (KeyError, ValueError, TypeError, OverflowError):
        return "—"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--include-current", action="store_true",
                        help="Revisar también registros con host_time; los originales se conservan.")
    args = parser.parse_args(argv)
    old = load_old_results()
    results = []
    for path in sorted(glob.glob(os.path.join(storage.DATA_DIR, "sub-*_imu.csv"))):
        sub, ses, task, run = parse_name(path)
        analysis = analyze_file(path, task, include_current=args.include_current)
        if analysis is None:
            continue
        rep = analysis["rep"]
        state, title, action = verdict(analysis["checks"], bool(rep.metrics) if rep else True)
        old_row = old.get((ses, sub, task, run))
        results.append({
            "archivo": os.path.basename(path), "sub": sub, "fecha": ses, "task": task, "run": run,
            "estado": state, "veredicto": title, "motivo": action,
            "quality": analysis["quality"], "rep": rep, "old": old_row,
            "checks": analysis["checks"],
        })

    with open(OUT_CSV, "w", newline="", encoding=storage.CSV_WRITE_ENCODING) as f:
        writer = csv.writer(f)
        writer.writerow([
            "archivo", "sub", "fecha", "task", "run", "veredicto_v2", "motivo",
            "recibidas_pct", "muestras_saturadas",
            "anterior_potencia_w", "anterior_velocidad_m_s", "anterior_desplazamiento_m",
            "nuevo_metrica", "nuevo_valor", "nuevo_unidad", "version_algoritmo",
            "tiempo_nativo", "muestras_invalidas", "giros_fallback", "giros_inciertos", "giros_saturados",
        ])
        for r in results:
            q, rep, o = r["quality"], r["rep"], r["old"] or {}
            primary = rep.primary if rep is not None and rep.valid else None
            writer.writerow([
                r["archivo"], r["sub"], r["fecha"], r["task"], r["run"], r["veredicto"], r["motivo"],
                round(100 - q.lost_pct, 1), q.saturated,
                o.get("peak_power_w", ""), o.get("peak_velocity_m_s", ""), o.get("max_displacement_m", ""),
                primary.label if primary else "", round(primary.value, 2) if primary else "",
                primary.unit if primary else "",
                ALGORITHM_VERSION, int(q.timing_native), q.invalid,
                q.gyro_fallbacks, q.gyro_uncertain, q.gyro_saturated,
            ])

    os.makedirs(storage.REPORTS_DIR, exist_ok=True)
    rows_html = []
    for r in results:
        q, rep, o = r["quality"], r["rep"], r["old"]
        old_txt = _old_text(o)
        primary = rep.primary if rep is not None and rep.valid else None
        new_txt = f"{primary.label}: {primary.text()} {primary.unit}" if primary else "—"
        rows_html.append(
            f'<tr style="background:{BACKGROUNDS[r["estado"]]}">'
            f'<td>{escape(r["archivo"])}</td><td>{escape(r["task"])}</td>'
            f'<td>{100 - q.lost_pct:.0f} %</td><td>{old_txt}</td>'
            f'<td style="color:{COLORS[r["estado"]]}; font-weight:700;"><span style="{ICON_FONT}">'
            f'{ICONS[r["estado"]]}</span> {escape(r["veredicto"])}</td>'
            f'<td>{escape(new_txt)}</td><td>{escape(r["motivo"])}</td></tr>'
        )
    html = (
        "<!doctype html><html lang='es'><head><meta charset='utf-8'><title>Reprocesado de datos</title>"
        "<style>body{font-family:Arial,sans-serif;color:#172B3A;margin:32px;line-height:1.4}"
        "table{border-collapse:collapse;width:100%;font-size:13px}td,th{padding:7px;border-bottom:1px solid #DCE4EA;"
        "text-align:left;vertical-align:top}th{background:#EEF4F7}</style></head><body>"
        "<h1>Reprocesado de los registros anteriores</h1>"
        f"<p>Generado el {dt.datetime.now():%Y-%m-%d %H:%M} con el algoritmo v{ALGORITHM_VERSION}. "
        "Los archivos originales no se modificaron. «Recibidas» es una cobertura estimada cuando no hay "
        "índices o tiempos nativos del sensor: puede omitir pérdidas pequeñas o confundirlas con latencia. "
        "El orden de llegada de aceleración y giro no demuestra sincronía. Las verificaciones señalan "
        "parejas inciertas, giros sustituidos, saturación y datos no finitos. La columna «Resultado anterior» "
        "muestra lo que se guardó en resultados_ciclovia.csv con el algoritmo 1.x. La potencia reprocesada se "
        f"calculó con {DEFAULT_MASS_KG:.0f} kg para todos (el registro anterior no guardaba el peso): "
        "no la compare entre personas.</p>"
        "<table><tr><th>Archivo</th><th>Prueba</th><th>Recibidas</th><th>Resultado anterior</th>"
        "<th>Veredicto v2</th><th>Resultado v2</th><th>Motivo</th></tr>"
        + "".join(rows_html) + "</table></body></html>"
    )
    with open(OUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)
    for r in results:
        print(f'{r["archivo"]:50s} {r["veredicto"]:26s} {r["motivo"][:110]}')
    print(f"\nCSV:  {OUT_CSV}\nHTML: {OUT_HTML}")


if __name__ == "__main__":
    main()
