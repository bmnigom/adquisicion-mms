"""Reporte de cada intento, pensado para que el personal lo interprete.

Estructura: veredicto (valida / con observaciones / repetir) -> resultados ->
que significan -> calidad de la medicion -> metodo. El mismo HTML se muestra
en la aplicacion (Qt rich text: solo tablas y estilos simples) y se guarda en
data/reportes para revisarlo despues.
"""
import datetime as dt
import math
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
    participant_text: str = ""
    save_warnings: list[str] = field(default_factory=list)
    timestamp: dt.datetime = field(default_factory=dt.datetime.now)
    session_id: str = ""
    data_source: str = "sensor"


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


def effective_checks(ctx: ReportContext) -> list[Check]:
    """Alinea el veredicto de pantalla, CSV y HTML frente a valores no finitos."""
    checks = list(ctx.checks)
    def finite(value):
        try:
            return value is None or math.isfinite(float(value))
        except (TypeError, ValueError, OverflowError):
            return False
    bad_metrics = [m.label for m in ctx.metrics if m.value is None or not finite(m.value)]
    if ctx.duration_s is not None and not finite(ctx.duration_s):
        bad_metrics.append("duración")
    if bad_metrics and not any(c.label == "Resultados numéricos" for c in checks):
        checks.append(Check("Resultados numéricos", "fail",
                            "El cálculo produjo valores no finitos: " + ", ".join(bad_metrics) + ". Repita la captura."))
    return checks


def _finite_metrics(metrics: list[Metric]) -> bool:
    try:
        return all(math.isfinite(float(m.value)) for m in metrics)
    except (TypeError, ValueError, OverflowError):
        return False


def measurement_verdict(ctx: ReportContext) -> tuple[str, str, str]:
    checks = effective_checks(ctx)
    return verdict(checks, bool(ctx.metrics) and _finite_metrics(ctx.metrics))


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


def _num(value: float, decimals: int) -> str:
    """Numero con coma decimal, como se lee en espanol."""
    return f"{value:.{decimals}f}".replace(".", ",")


def participant_summary(mode_key: str, state: str, metrics: list[Metric],
                        age_years: int | None = None) -> str:
    """Explicacion breve, en lenguaje llano, para la persona evaluada.

    No diagnostica: solo usa los puntos de referencia ya aplicados en el reporte
    (STEADI para TUG y EWGSOP2 para marcha, en mayores de 65 años) y remite a un
    profesional de salud cuando corresponde.
    """
    if state == "fail" or not metrics:
        return ("Este intento no se pudo medir bien (por ejemplo, por la señal del sensor o por "
                "moverse antes de tiempo). No dice nada sobre ti: lo repetimos.")
    by_key = {m.key: m.value for m in metrics}
    older = age_years is not None and age_years >= 65
    seconds = by_key.get("duration_s", 0.0)

    if mode_key == "jump":
        text = (f"Saltaste {_num(by_key['altura_salto_cm'], 0)} cm. Lo calculamos con el tiempo que "
                "estuviste en el aire. Sirve para compararte contigo: entre un intento y otro es "
                "normal que cambie 1 o 2 cm.")
    elif mode_key == "sts":
        text = (f"Al ponerte de pie generaste {_num(by_key['potencia_pico_w'], 0)} W de potencia "
                f"({_num(by_key['potencia_relativa_w_kg'], 1)} W por kilo de peso). Refleja la fuerza "
                "y la rapidez de tus piernas, que se entrenan, por ejemplo, levantándote de una silla "
                "varias veces.")
    elif mode_key == "punch":
        speed = by_key["velocidad_pico_m_s"]
        text = (f"Tu puño alcanzó {_num(speed, 1)} m/s (unos {_num(speed * 3.6, 0)} km/h). Es un "
                "resultado de juego para comparar tus intentos, no una evaluación de salud.")
    elif mode_key == "tug":
        text = f"Tardaste {_num(seconds, 1)} s en levantarte, caminar 3 m, girar, volver y sentarte."
        if older and seconds >= 12.0:
            text += (" En personas de 65 años o más, 12 s o más es una señal para revisar el "
                     "equilibrio y la prevención de caídas con un profesional de salud. No es un "
                     "diagnóstico.")
        elif older:
            text += " Es menos que el punto de referencia de 12 s para personas de 65 años o más."
        else:
            text += " Sirve para comparar tus propios resultados en el tiempo."
    elif mode_key == "walk":
        speed = by_key.get("velocidad_marcha", 0.0)
        text = f"Caminaste 5 m a {_num(speed, 2)} m/s (unos {_num(speed * 3.6, 1)} km/h)."
        if older and speed <= 0.8:
            text += (" En personas de 65 años o más, 0,8 m/s o menos es una velocidad que conviene "
                     "comentar con un profesional de salud. No es un diagnóstico.")
        elif older:
            text += " Es más que 0,8 m/s, el valor de referencia para personas de 65 años o más."
    elif mode_key == "stand":
        text = ("Te mantuviste de pie los 2 minutos completos." if seconds >= 119.5 else
                f"Te mantuviste de pie {_num(seconds, 0)} s; la prueba busca completar 2 minutos. "
                "Detenerse antes es válido si lo necesitabas.")
    elif mode_key == "single_leg":
        text = (f"Te sostuviste {_num(seconds, 1)} s sobre una pierna. Compáralo con tus próximos "
                "intentos usando la misma pierna.")
    elif mode_key == "event":
        return (f"Registramos {_num(seconds, 0)} segundos de tu movimiento con un sensor que mide "
                "aceleración y giro, como el de un teléfono. Es una experiencia demostrativa, no una "
                "evaluación de salud.")
    else:
        return ""
    if state == "warn":
        text += " El equipo revisará una observación sobre la calidad de la medición."
    return text


def _check_rows(checks: list[Check]) -> str:
    rows = []
    for c in checks:
        rows.append(
            f'<tr><td width="28" style="{ICON_FONT} color:{COLORS[c.status]}; font-weight:700;">{ICONS[c.status]}</td>'
            f'<td width="190"><b>{escape(c.label)}</b></td><td>{escape(c.detail)}</td></tr>'
        )
    return "".join(rows)


def render_html(ctx: ReportContext, standalone: bool = False) -> str:
    checks = effective_checks(ctx)
    state, title, action = verdict(checks, bool(ctx.metrics) and _finite_metrics(ctx.metrics))
    stamp = ctx.timestamp.strftime("%Y-%m-%d %H:%M")
    who = [f"Participante <b>{escape(ctx.sub)}</b>", f"intento {escape(ctx.run)}", stamp,
           f"sensor: {escape(ctx.sensor_pos.lower())}"]
    if ctx.age_years:
        who.append(f"{ctx.age_years} años")
    if ctx.mass_kg:
        who.append(f"{ctx.mass_kg:g} kg")
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
    if ctx.data_source == "simulacion":
        parts.insert(0, '<p style="color:#A56819;font-weight:700;">SIMULACIÓN · Datos sintéticos de demostración</p>')
    for warning in ctx.save_warnings:
        parts.append(f'<p style="color:{COLORS["warn"]};"><b>Guardado:</b> {escape(warning)}</p>')
    if ctx.participant_text:
        parts.append('<h3 style="margin-bottom:4px;">Para la persona evaluada</h3>')
        parts.append(f'<p style="font-size:15px;">{escape(ctx.participant_text)}</p>')

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
    parts.append(f'<table width="100%" cellpadding="4" cellspacing="0">{_check_rows(checks)}</table>')

    if ctx.method:
        parts.append('<h3 style="margin-bottom:4px;">Método</h3>')
        parts.append(f'<p style="color:#637586;">{escape(ctx.method)}</p>')
    footer = f"Algoritmo v{ALGORITHM_VERSION}."
    if ctx.session_id:
        footer += f" Sesión: {escape(ctx.session_id)}."
    if ctx.raw_file:
        footer += f" Datos IMU: {escape(ctx.raw_file)}"
    parts.append(f'<p style="color:#637586; font-size:11px;">{footer}</p>')

    body = "\n".join(parts)
    if not standalone:
        palette = {
            "#637586": "#9CB0C3", "#247A64": "#68D8A0", "#A56819": "#F3C778",
            "#B44949": "#FF8990", "#E6F2EE": "#153C32", "#FBF1E3": "#3C3020",
            "#F8E6E6": "#3C252D",
        }
        for before, after in palette.items():
            body = body.replace(before, after)
        return f'<div style="color:#E6EDF5;font-family:Segoe UI;">{body}</div>'
    return (
        "<!doctype html><html lang='es'><head><meta charset='utf-8'>"
        f"<title>Reporte {escape(ctx.test_label)} · {escape(ctx.sub)}</title>"
        "<style>body{font-family:Segoe UI,Arial,sans-serif;color:#172B3A;max-width:820px;margin:32px auto;"
        "padding:0 16px;line-height:1.45}td{vertical-align:top;border-bottom:1px solid #EEF2F5}"
        "h1{margin-bottom:4px}</style></head><body>"
        f"<h1>{escape(ctx.test_label)}</h1>{body}</body></html>"
    )
