"""Reporte de cada intento, pensado para que el personal lo interprete.

Estructura: veredicto (valida / con observaciones / repetir) -> resultados ->
que significan -> calidad de la medicion -> metodo. El mismo HTML se muestra
en la aplicacion (Qt rich text: solo tablas y estilos simples) y se guarda en
data/reportes para revisarlo despues.
"""
import datetime as dt
from dataclasses import dataclass, field
from html import escape

from core.kinematics import ALGORITHM_VERSION, Check, Metric

COLORS = {"ok": "#247A64", "warn": "#A56819", "fail": "#B44949"}
BACKGROUNDS = {"ok": "#E6F2EE", "warn": "#FBF1E3", "fail": "#F8E6E6"}
ICONS = {"ok": "✔", "warn": "⚠", "fail": "✖"}
ICON_FONT = "font-family:'Segoe UI Symbol','Segoe UI Emoji',sans-serif;"


@dataclass
class ReportContext:
    mode_key: str
    test_label: str
    sensor_pos: str
    sub: str
    run: str
    duration_s: float | None
    metrics: list[Metric]
    checks: list[Check]
    method: str = ""
    interpretation: list[str] = field(default_factory=list)
    comparison_html: str = ""
    previous: tuple[str, float, float, str] | None = None  # (etiqueta, anterior, actual, unidad)
    mass_kg: float | None = None
    age_years: int | None = None
    condition: str = ""
    raw_file: str = ""
    timestamp: dt.datetime = field(default_factory=dt.datetime.now)


def verdict(checks: list[Check], has_metrics: bool) -> tuple[str, str, str]:
    """(estado, titulo, accion) a partir de las verificaciones."""
    fails = [c for c in checks if c.status == "fail"]
    warns = [c for c in checks if c.status == "warn"]
    if fails or not has_metrics:
        reason = fails[0].detail if fails else "No se obtuvo un resultado."
        return "fail", "Repetir la prueba", reason
    if warns:
        return "warn", "Válida con observaciones", "Revise las observaciones antes de interpretar o comparar."
    return "ok", "Medición válida", "Todas las verificaciones de calidad fueron correctas."


def interpretation_for(mode_key: str) -> list[str]:
    texts = {
        "jump": [
            "La <b>altura</b> es el dato principal: se calcula solo con el tiempo que la persona "
            "estuvo en el aire, el mismo principio de las plataformas de contacto.",
            "Para comparar a una persona consigo misma use el <b>mejor de 2–3 intentos</b> con la "
            "misma técnica (manos en la cintura, aterrizar con piernas extendidas). Aterrizar con "
            "rodillas flexionadas alarga el vuelo y exagera la altura.",
            "La <b>potencia</b> sale de una ecuación poblacional (Sayers, 1999) que usa la altura y la "
            "masa indicada. Es una estimación orientativa, no una medición directa; la potencia "
            "relativa (W/kg) permite comparar personas de distinto peso.",
        ],
        "sts": [
            "La <b>potencia pico</b> es la mayor potencia al levantarse de la silla en una "
            "repetición (fuerza × velocidad del centro de masa, aproximado por la cadera).",
            "La <b>potencia relativa</b> (W/kg) permite comparar entre personas de distinto peso. "
            "El ascenso de la cadera sirve para confirmar que el movimiento se midió completo.",
            "Es una sola repetición: compare siempre con la misma altura de silla y la misma "
            "consigna («lo más rápido posible»). No se aplica un punto de corte clínico.",
        ],
        "punch": [
            "La <b>velocidad pico del puño</b> es el dato principal. La aceleración y la velocidad "
            "angular pico son medidas directas del sensor y ayudan a comparar la «explosividad».",
            "Resultado lúdico/demostrativo: no existe un valor de referencia para un golpe al aire.",
        ],
        "event": [
            "Experiencia demostrativa de 20 segundos. No es una evaluación y no se interpreta "
            "clínicamente; el archivo IMU queda disponible para análisis posteriores.",
        ],
    }
    return texts.get(mode_key, [
        "El <b>tiempo</b> lo marca el operador con el cronómetro; la calidad de la señal IMU no "
        "cambia el tiempo, solo la utilidad del archivo de datos para análisis posteriores.",
    ])


def _check_rows(checks: list[Check]) -> str:
    rows = []
    for c in checks:
        rows.append(
            f'<tr><td width="28" style="{ICON_FONT} color:{COLORS[c.status]}; font-weight:700;">{ICONS[c.status]}</td>'
            f'<td width="190"><b>{escape(c.label)}</b></td><td>{escape(c.detail)}</td></tr>'
        )
    return "".join(rows)


def render_html(ctx: ReportContext, standalone: bool = False) -> str:
    state, title, action = verdict(ctx.checks, bool(ctx.metrics))
    stamp = ctx.timestamp.strftime("%Y-%m-%d %H:%M")
    who = [f"Participante <b>{escape(ctx.sub)}</b>", f"intento {escape(ctx.run)}", stamp,
           f"sensor: {escape(ctx.sensor_pos.lower())}"]
    if ctx.age_years:
        who.append(f"{ctx.age_years} años")
    if ctx.mass_kg:
        who.append(f"{ctx.mass_kg:.0f} kg")
    if ctx.condition:
        who.append(escape(ctx.condition))

    parts = [
        f'<p style="color:#637586; font-size:12px; margin:0;">{" · ".join(who)}</p>',
        f'<table width="100%" cellpadding="12" cellspacing="0" style="margin-top:10px; '
        f'background-color:{BACKGROUNDS[state]}; border-left:6px solid {COLORS[state]};">'
        f'<tr><td><span style="font-size:19px; font-weight:700; color:{COLORS[state]};">'
        f'<span style="{ICON_FONT}">{ICONS[state]}</span> {title}</span><br><span style="font-size:13px;">{escape(action)}</span>'
        f'</td></tr></table>',
    ]

    parts.append('<h3 style="margin-bottom:4px;">Resultados</h3>')
    if state == "fail" or not ctx.metrics:
        parts.append('<p style="color:#637586;">No se muestran valores porque la medición no superó '
                     'las verificaciones: podrían ser incorrectos.</p>')
    else:
        rows = []
        for m in ctx.metrics:
            weight = "700" if m.primary else "400"
            note = f'<br><span style="color:#637586; font-size:11px;">{escape(m.note)}</span>' if m.note else ""
            rows.append(
                f'<tr><td width="260">{escape(m.label)}{note}</td>'
                f'<td style="font-size:{"20" if m.primary else "15"}px; font-weight:{weight};">'
                f'{m.text()} <span style="font-size:12px; color:#637586;">{escape(m.unit)}</span></td></tr>'
            )
        if ctx.duration_s is not None and not any(m.key == "duration_s" for m in ctx.metrics):
            rows.append(f'<tr><td>Duración del movimiento</td><td>{ctx.duration_s:.2f} '
                        f'<span style="font-size:12px; color:#637586;">s</span></td></tr>')
        parts.append(f'<table cellpadding="5" cellspacing="0">{"".join(rows)}</table>')
        if ctx.previous:
            label, before, now, unit = ctx.previous
            parts.append(
                f'<p>{escape(label)} en el intento válido anterior: <b>{before:.1f} {escape(unit)}</b> · '
                f'diferencia: <b>{now - before:+.1f} {escape(unit)}</b> (sin calificarla como mejor o peor).</p>'
            )

    parts.append('<h3 style="margin-bottom:4px;">Cómo interpretarlo</h3>')
    parts.append("".join(f"<p>{t}</p>" for t in ctx.interpretation))
    if ctx.comparison_html and state != "fail":
        parts.append(ctx.comparison_html)

    parts.append('<h3 style="margin-bottom:4px;">Calidad de la medición</h3>')
    parts.append(f'<table width="100%" cellpadding="4" cellspacing="0">{_check_rows(ctx.checks)}</table>')

    if ctx.method:
        parts.append('<h3 style="margin-bottom:4px;">Método</h3>')
        parts.append(f'<p style="color:#637586;">{escape(ctx.method)}</p>')
    footer = f"Algoritmo v{ALGORITHM_VERSION}."
    if ctx.raw_file:
        footer += f" Datos IMU: {escape(ctx.raw_file)}"
    parts.append(f'<p style="color:#637586; font-size:11px;">{footer}</p>')

    body = "\n".join(parts)
    if not standalone:
        return body
    return (
        "<!doctype html><html lang='es'><head><meta charset='utf-8'>"
        f"<title>Reporte {escape(ctx.test_label)} · {escape(ctx.sub)}</title>"
        "<style>body{font-family:Arial,sans-serif;color:#172B3A;max-width:820px;margin:32px auto;"
        "padding:0 16px;line-height:1.45}td{vertical-align:top;border-bottom:1px solid #EEF2F5}"
        "h1{margin-bottom:4px}</style></head><body>"
        f"<h1>{escape(ctx.test_label)}</h1>{body}</body></html>"
    )
