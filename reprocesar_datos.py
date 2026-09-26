"""Reprocesa los registros IMU grabados con la version anterior (algoritmo 1.x).

No modifica ningun archivo original. Genera:
  - data/reprocesado_datos_anteriores.csv : un renglon por registro, con el
    resultado anterior, el nuevo y las verificaciones de calidad.
  - data/reportes/reprocesado_datos_anteriores.html : resumen para el personal.

Uso (desde la carpeta del proyecto):
    python reprocesar_datos.py
"""
import csv
import datetime as dt
import glob
import os
from html import escape

from core import quality as signal_quality
from core import storage
from core.kinematics import ALGORITHM_VERSION, Check, RepDetector
from core.pipeline import SignalProcessor
from core.report import BACKGROUNDS, COLORS, ICON_FONT, ICONS, verdict
from core.sample_clock import reconstruct

RATE_HZ = 100.0
OLD_ACC_RANGE_G = 4.0     # rango configurado en la version anterior
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
        with open(OLD_RESULTS, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                old[(row["fecha"], row["sub"], row["task"], row["run"])] = row
    return old


def analyze_file(path, task):
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if "host_time" in rows[0]:
        return None  # ya grabado con la version nueva
    host = [float(r["time"]) for r in rows]
    times, lost = reconstruct(host, RATE_HZ)
    proc = SignalProcessor(RATE_HZ, OLD_ACC_RANGE_G)
    samples = []
    for r, t, h, k in zip(rows, times, host, lost):
        s = proc.process({**r, "time": t, "host_time": h, "lost_before": int(k)})
        samples.append(s)
    q_rows = [{"time": s.t, "host_time": s.host_time, "lost_before": s.lost_before,
               "saturado": int(s.saturated)} for s in samples]
    quality = signal_quality.assess(q_rows, RATE_HZ)
    checks = [signal_quality.transmission_check(quality, strict=task in POWER_TASKS)]
    if quality.saturated:
        checks.append(Check("Saturación (rango ±4 g anterior)", "warn" if task not in POWER_TASKS else "ok",
                            f"{quality.saturated} muestras en el límite del sensor."))
    if task not in POWER_TASKS:
        return {"quality": quality, "checks": checks, "rep": None}

    detector = RepDetector(task, 70.0, RATE_HZ)
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
                                "anterior cortaba la captura demasiado pronto.")]
        else:
            rep = detector.timeout_result(quality.duration_s)
    rep.checks = checks + rep.checks
    return {"quality": quality, "checks": rep.checks, "rep": rep}


def main():
    old = load_old_results()
    results = []
    for path in sorted(glob.glob(os.path.join(storage.DATA_DIR, "sub-*_imu.csv"))):
        sub, ses, task, run = parse_name(path)
        analysis = analyze_file(path, task)
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

    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "archivo", "sub", "fecha", "task", "run", "veredicto_v2", "motivo",
            "recibidas_pct", "muestras_saturadas",
            "anterior_potencia_w", "anterior_velocidad_m_s", "anterior_desplazamiento_m",
            "nuevo_metrica", "nuevo_valor", "nuevo_unidad",
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
            ])

    os.makedirs(storage.REPORTS_DIR, exist_ok=True)
    rows_html = []
    for r in results:
        q, rep, o = r["quality"], r["rep"], r["old"]
        old_txt = (f'{float(o["peak_power_w"]):.0f} W · {float(o["peak_velocity_m_s"]):.2f} m/s · '
                   f'{float(o["max_displacement_m"]) * 100:.0f} cm') if o else "—"
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
        "Los archivos originales no se modificaron. «Recibidas» es el porcentaje de muestras que llegaron "
        "por Bluetooth (reconstruido a partir de las horas de llegada). La columna «Resultado anterior» "
        "muestra lo que se guardó en resultados_ciclovia.csv con el algoritmo 1.x.</p>"
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
