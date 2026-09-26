"""Comparaciones orientativas, separadas de las mediciones y sus datos crudos.

Un punto de referencia sólo se aplica cuando coincide la población y el
protocolo. Ninguna de estas salidas constituye un diagnóstico.
"""

from dataclasses import dataclass


CDC_TUG_URL = "https://www.cdc.gov/steadi/media/pdfs/steadi-assessment-tug-508.pdf"
EWGSOP2_URL = "https://academic.oup.com/ageing/article/48/1/16/5126243"


@dataclass(frozen=True)
class Comparison:
    title: str
    explanation: str
    source_name: str = ""
    source_url: str = ""


def timed_comparison(mode_key: str, duration_s: float, age_years: int | None) -> Comparison:
    if mode_key == "tug":
        if age_years is None or age_years < 65:
            return Comparison(
                "Referencia clínica no aplicada",
                "El umbral STEADI de TUG está dirigido a personas de 65 años o más. Indique la edad para comparar el resultado.",
                "CDC STEADI", CDC_TUG_URL,
            )
        if duration_s >= 12.0:
            return Comparison(
                "Tamizaje TUG: ampliar la valoración",
                "En personas de 65 años o más, 12 s o más alcanza el punto de referencia STEADI para riesgo de caída. No establece un diagnóstico por sí solo.",
                "CDC STEADI", CDC_TUG_URL,
            )
        return Comparison(
            "TUG por debajo del umbral STEADI",
            "El tiempo es menor de 12 s. Esto no descarta riesgo de caída; la valoración considera otros factores.",
            "CDC STEADI", CDC_TUG_URL,
        )

    if mode_key == "walk":
        speed = 5.0 / duration_s if duration_s > 0 else 0.0
        if age_years is None or age_years < 65:
            return Comparison(
                f"Velocidad media estimada: {speed:.2f} m/s",
                "Se calcula como 5 m divididos por el tiempo registrado. No se aplica una clasificación clínica sin contexto de edad y protocolo.",
            )
        relation = "igual o inferior" if speed <= 0.8 else "superior"
        return Comparison(
            f"Velocidad media: {speed:.2f} m/s",
            f"Es {relation} a 0,8 m/s, referencia de desempeño físico del consenso EWGSOP2. Su protocolo habitual mide 4 m; esta medición de 5 m es una comparación orientativa, no un diagnóstico de sarcopenia.",
            "Consenso EWGSOP2", EWGSOP2_URL,
        )

    if mode_key == "stand":
        return Comparison(
            "Meta de registro: 120 segundos",
            "Se completó el intervalo de dos minutos." if duration_s >= 120 else
            "El registro terminó antes de los dos minutos. La duración por sí sola no clasifica el equilibrio.",
        )

    if mode_key == "single_leg":
        return Comparison(
            "Duración de apoyo registrada",
            "No se aplica un punto de corte clínico: faltaría estandarizar ojos abiertos o cerrados, número de intentos y edad de referencia.",
        )

    raise ValueError(f"No hay comparación cronometrada para {mode_key}")


def sts_comparison() -> Comparison:
    return Comparison(
        "STS de una repetición",
        "La referencia EWGSOP2 de más de 15 s corresponde a cinco levantadas. No se aplica al registro actual de una repetición.",
        "Consenso EWGSOP2", EWGSOP2_URL,
    )
