"""Deteccion de repeticiones y calculo de metricas para salto, STS y golpe.

Cada resultado incluye verificaciones de calidad (Check). Un resultado con
alguna verificacion "fail" no se debe interpretar: la pantalla pide repetir.

Metodos:
  - Salto: altura por tiempo de vuelo, h = g * t^2 / 8. No requiere integrar
    ni conocer la orientacion; solo detectar despegue y aterrizaje (punto medio
    entre la ultima muestra en apoyo y la primera en caida libre).
    Potencia estimada con la ecuacion de Sayers et al. (1999).
  - STS: doble integracion de la aceleracion vertical entre dos reposos, con
    correccion lineal de deriva (velocidad cero al inicio y al final).
    Potencia = fuerza de la persona * velocidad = m * (a + g) * v, solo la fase
    concentrica (positiva).
  - Golpe: velocidad 3D de la muneca por integracion con la misma correccion
    de deriva, mas aceleracion y velocidad angular pico (medidas directas).
"""
from collections import deque
from dataclasses import dataclass, field, replace

import numpy as np

from core.orientation import G
from core.pipeline import ProcessedSample
from core.sample_clock import WINDOW_S, reconstruct

ALGORITHM_VERSION = "2.1"

# -- Deteccion de reposo / movimiento ----------------------------------------
REST_WINDOW_SAMPLES = 10       # ventana para la desviacion estandar de |a|
REST_STD_G = 0.035             # |a| estable
REST_GRAVITY_TOL_G = 0.10      # |a| cerca de 1 g
REST_GYRO_DPS = 25.0           # sin giros apreciables
MOVING_STD_G = 0.06
MOVING_DEVIATION_G = 0.25
SUSTAINED_DEVIATION_G = 0.07   # desviacion moderada pero sostenida (movimientos lentos)
SUSTAINED_SAMPLES = 5
MOVING_GYRO_DPS = 45.0
ARM_REST_S = 0.5               # reposo necesario antes del movimiento (referencia y ZUPT)
# Reposo que cierra la repeticion. 0,6 s porque (1) a mitad del ascenso del STS la
# velocidad es casi constante y el acelerometro puede parecer quieto un instante, y
# (2) confirmar una perdida de datos requiere ~0,5 s de datos posteriores.
END_REST_S = {"jump": 0.6, "punch": 0.6, "sts": 0.6}
PRE_ROLL_S = 0.3               # muestras previas a la deteccion que se incluyen
MAX_REP_S = 6.0
MIN_REP_S = 0.15
ONSET_DEVIATION_G = 0.06

# -- Salto --------------------------------------------------------------------
FREEFALL_G = 0.3
MIN_FLIGHT_S = 0.15            # ~3 cm
MAX_FLIGHT_S = 0.90            # ~99 cm
EXCEPTIONAL_HEIGHT_M = 0.70

# -- STS ----------------------------------------------------------------------
STS_MIN_RISE_M = 0.15
STS_MAX_RISE_M = 0.75
STS_MAX_VELOCITY = 2.0
STS_DRIFT_WARN = 0.3
STS_DRIFT_FAIL = 0.8

# -- Golpe --------------------------------------------------------------------
PUNCH_MAX_SPEED = 15.0
PUNCH_DRIFT_WARN = 1.5


@dataclass
class Metric:
    key: str
    label: str
    value: float
    unit: str
    decimals: int = 1
    primary: bool = False
    note: str = ""

    def text(self) -> str:
        return f"{self.value:.{self.decimals}f}"


@dataclass
class Check:
    label: str
    status: str   # "ok" | "warn" | "fail"
    detail: str


@dataclass
class RepResult:
    task: str
    duration_s: float
    metrics: list[Metric] = field(default_factory=list)
    checks: list[Check] = field(default_factory=list)
    method: str = ""
    timestamp: float = 0.0

    @property
    def valid(self) -> bool:
        return bool(self.metrics) and all(c.status != "fail" for c in self.checks)

    @property
    def primary(self) -> Metric | None:
        return next((m for m in self.metrics if m.primary), None)

    def metric(self, key: str) -> Metric | None:
        return next((m for m in self.metrics if m.key == key), None)


@dataclass
class LiveState:
    phase: str               # "wait_rest" | "armed" | "moving" | "done"
    a_vertical: float
    intensity_g: float       # |a| - 1 g, para el indicador en vivo


class RepDetector:
    """Reposo (>= 0,5 s) -> movimiento -> reposo. Entrega el resultado analizado."""

    def __init__(self, task: str, mass_kg: float, sample_rate_hz: float = 100.0):
        self.task = task
        self.mass_kg = mass_kg
        self.rate_hz = sample_rate_hz
        self.phase = "wait_rest"
        self._window: deque[float] = deque(maxlen=REST_WINDOW_SAMPLES)
        # Historia suficiente para reconstruir perdidas justo antes del movimiento.
        self._history: deque[ProcessedSample] = deque(maxlen=int((PRE_ROLL_S + WINDOW_S) * sample_rate_hz) + 1)
        self._context: list[ProcessedSample] = []
        self._rest_time = 0.0
        self._baseline_av = 0.0
        self._rep: list[ProcessedSample] = []
        self._move_start_t = 0.0
        self._deviation_streak = 0

    def update(self, s: ProcessedSample) -> tuple[LiveState, RepResult | None]:
        self._window.append(s.acc_mag)
        std = float(np.std(self._window)) if len(self._window) >= 4 else 0.0
        at_rest = (
            len(self._window) >= REST_WINDOW_SAMPLES and std < REST_STD_G
            and abs(s.acc_mag - 1.0) < REST_GRAVITY_TOL_G and s.gyro_mag_dps < REST_GYRO_DPS
        )
        self._deviation_streak = self._deviation_streak + 1 if abs(s.acc_mag - 1.0) > SUSTAINED_DEVIATION_G else 0
        moving = (
            std > MOVING_STD_G or abs(s.acc_mag - 1.0) > MOVING_DEVIATION_G
            or self._deviation_streak >= SUSTAINED_SAMPLES or s.gyro_mag_dps > MOVING_GYRO_DPS
        )
        result = None

        if self.phase in ("wait_rest", "armed"):
            if self.phase == "armed" and moving:
                rest_samples = [h for h in self._history][-int(ARM_REST_S * self.rate_hz):]
                self._baseline_av = float(np.mean([h.a_vertical for h in rest_samples])) if rest_samples else 0.0
                pre_roll = int(PRE_ROLL_S * self.rate_hz)
                self._rep = list(self._history)[-pre_roll:] + [s]
                self._context = list(self._history)[:-pre_roll]
                self._move_start_t = s.t
                self._rest_time = 0.0
                self.phase = "moving"
            else:
                self._rest_time = self._rest_time + s.dt if at_rest else 0.0
                # Una vez armado, pequenos ajustes por debajo del umbral de movimiento no lo desarman.
                if self._rest_time >= ARM_REST_S:
                    self.phase = "armed"
        elif self.phase == "moving":
            self._rep.append(s)
            self._rest_time = self._rest_time + s.dt if at_rest else 0.0
            if self._rest_time >= END_REST_S.get(self.task, 0.3):
                self.phase = "done"
                result = self._analyze()
            elif s.t - self._move_start_t > MAX_REP_S:
                self.phase = "done"
                result = RepResult(self.task, s.t - self._move_start_t, checks=[Check(
                    "Reposo final", "fail",
                    f"No hubo reposo final en {MAX_REP_S:.0f} s. La persona debe quedar quieta al terminar.",
                )], timestamp=s.t)

        self._history.append(s)
        live = LiveState(self.phase, s.a_vertical - self._baseline_av, abs(s.acc_mag - 1.0))
        return live, result

    def timeout_result(self, elapsed_s: float) -> RepResult:
        if self.phase == "wait_rest":
            detail = (
                "La persona no permaneció quieta 0,5 s antes de moverse. Sin ese reposo no hay "
                "referencia de gravedad ni velocidad inicial cero."
            )
        elif self.phase == "moving":
            detail = ("El movimiento empezó, pero la persona no quedó quieta al terminar. "
                      "Debe permanecer inmóvil hasta que la pantalla muestre el resultado.")
        else:
            detail = "Hubo reposo, pero no se detectó un movimiento claro."
        return RepResult(self.task, elapsed_s, checks=[Check("Detección del movimiento", "fail", detail)])

    # -- Analisis ---------------------------------------------------------
    def _reconstruct_times(self) -> list[ProcessedSample]:
        """Tiempos y perdidas definitivos del tramo, usando la historia previa como contexto."""
        span = self._context + self._rep
        times, lost = reconstruct([s.host_time for s in span], self.rate_hz)
        n0 = len(self._context)
        t0 = self._rep[0].t - times[n0]
        return [replace(s, t=float(times[n0 + i] + t0), lost_before=int(lost[n0 + i]))
                for i, s in enumerate(self._rep)]

    def _analyze(self) -> RepResult:
        rep = self._reconstruct_times()
        t = np.array([s.t for s in rep])
        acc_mag = np.array([s.acc_mag for s in rep])
        deviating = np.nonzero(np.abs(acc_mag - 1.0) > ONSET_DEVIATION_G)[0]
        i0, i1 = (int(deviating[0]), int(deviating[-1])) if len(deviating) else (0, len(rep) - 1)
        duration = float(t[i1] - t[i0])

        checks = [_continuity_check(rep, "durante el movimiento")]
        if duration < MIN_REP_S:
            checks.append(Check("Duración del movimiento", "fail",
                                f"{duration:.2f} s: demasiado breve para ser la prueba (posible sacudida)."))
            return RepResult(self.task, duration, checks=checks, timestamp=float(t[-1]))

        analyzers = {"jump": _analyze_jump, "sts": _analyze_sts, "punch": _analyze_punch}
        metrics, extra_checks, method = analyzers[self.task](rep, self._baseline_av, self.mass_kg)
        if self.task == "jump":
            # La continuidad que importa en el salto es la del vuelo (la revisa _analyze_jump).
            checks = []
        return RepResult(self.task, duration, metrics, checks + extra_checks, method, float(t[-1]))


def _continuity_check(samples: list[ProcessedSample], where: str) -> Check:
    lost = sum(s.lost_before for s in samples[1:])
    if lost == 0:
        return Check("Continuidad de datos", "ok", f"Sin muestras perdidas {where}.")
    return Check("Continuidad de datos", "fail",
                 f"Se perdieron datos {where} (unas {lost} muestras). El Bluetooth no entregó "
                 "todos los datos; repita acercando el computador al sensor.")


def _saturation_count(samples) -> int:
    return sum(1 for s in samples if s.saturated)


def _integrate(a: np.ndarray, t: np.ndarray) -> tuple[np.ndarray, float]:
    """Integral trapezoidal con correccion lineal para que termine en cero.

    Devuelve (serie corregida, valor final antes de corregir). Ese valor final
    mide la deriva: si la persona termino quieta, deberia ser ~0.
    """
    dt = np.diff(t, prepend=t[0])
    a_prev = np.concatenate([a[:1], a[:-1]])
    raw = np.cumsum(0.5 * (a + a_prev) * (dt[:, None] if a.ndim == 2 else dt), axis=0)
    span = t[-1] - t[0]
    ramp = (t - t[0]) / span if span > 0 else np.zeros_like(t)
    end = raw[-1]
    corrected = raw - (np.outer(ramp, end) if a.ndim == 2 else ramp * end)
    return corrected, end


def _analyze_jump(rep, baseline_av, mass_kg):
    t = np.array([s.t for s in rep])
    mag = np.array([s.acc_mag for s in rep])
    below = mag < FREEFALL_G
    # Tramo continuo mas largo en caida libre
    best, start = (0, 0), None
    for i, b in enumerate(np.append(below, False)):
        if b and start is None:
            start = i
        elif not b and start is not None:
            if i - start > best[1] - best[0]:
                best = (start, i)
            start = None
    first, end = best  # indices [first, end) en caida libre
    checks = []
    method = (
        "Altura por tiempo de vuelo (h = g·t²/8): se detecta el despegue y el aterrizaje "
        "cuando el sensor mide caída libre (|a| < 0,3 g). Potencia estimada con la ecuación "
        "de Sayers (1999): P = 60,7·h[cm] + 45,3·masa[kg] − 2055."
    )
    if end - first < 2:
        checks.append(Check("Fase de vuelo", "fail",
                            "No se detectó una fase de vuelo. Verifique que el sensor esté firme en la "
                            "cadera y que ambos pies dejen el suelo."))
        return [], checks, method

    # Despegue y aterrizaje en el punto medio entre la ultima muestra en apoyo y la primera
    # en vuelo (y viceversa): cada muestra en caida libre representa un intervalo completo.
    # La interpolacion lineal del umbral suponia una transicion gradual y, con despegues
    # bruscos, restaba ~0,75 muestras de vuelo (-1 cm a 30 cm).
    takeoff = 0.5 * (t[first - 1] + t[first]) if first > 0 else t[first]
    landing = 0.5 * (t[end - 1] + t[end]) if end < len(rep) else t[end - 1]
    flight = float(landing - takeoff)

    # Margen de 0,2 s: la posicion de una perdida solo se conoce con la precision de una rafaga.
    margin = 20
    window = rep[max(0, first - margin):min(len(rep), end + margin)]
    checks.append(_continuity_check(window, "durante el vuelo"))
    if MIN_FLIGHT_S <= flight <= MAX_FLIGHT_S:
        checks.append(Check("Tiempo de vuelo plausible", "ok", f"{flight * 1000:.0f} ms."))
    else:
        checks.append(Check("Tiempo de vuelo plausible", "fail",
                            f"{flight * 1000:.0f} ms está fuera del rango posible "
                            f"({MIN_FLIGHT_S * 1000:.0f}–{MAX_FLIGHT_S * 1000:.0f} ms). Probablemente el "
                            "sensor se movió o no fue un salto."))
    landing_peak = float(mag[end:end + 20].max()) if end < len(rep) else 0.0
    if landing_peak < 1.5:
        checks.append(Check("Aterrizaje", "warn",
                            "No se registró un impacto claro al aterrizar; confirme que la persona "
                            "aterrizó sobre ambos pies."))
    else:
        checks.append(Check("Aterrizaje", "ok", f"Impacto de {landing_peak:.1f} g detectado."))

    height = G * flight ** 2 / 8.0
    if height > EXCEPTIONAL_HEIGHT_M and flight <= MAX_FLIGHT_S:
        checks.append(Check("Altura excepcional", "warn",
                            f"{height * 100:.0f} cm es un valor de atleta de élite. Si la persona aterrizó "
                            "con las rodillas flexionadas, el tiempo de vuelo se alarga y la altura se sobreestima."))
    sat = _saturation_count(rep)
    if sat:
        checks.append(Check("Saturación del acelerómetro", "ok",
                            f"{sat} muestras en el límite del sensor, en el despegue/aterrizaje. No afecta "
                            "al tiempo de vuelo."))

    metrics = [
        Metric("altura_salto_cm", "Altura del salto", height * 100, "cm", 1, primary=True),
        Metric("tiempo_vuelo_ms", "Tiempo de vuelo", flight * 1000, "ms", 0),
        Metric("velocidad_pico_m_s", "Velocidad de despegue", G * flight / 2, "m/s", 2),
    ]
    power = 60.7 * height * 100 + 45.3 * mass_kg - 2055
    if power > 0:
        metrics.append(Metric("potencia_pico_w", "Potencia pico estimada", power, "W", 0,
                              note="Ecuación de Sayers; depende de la masa indicada."))
        metrics.append(Metric("potencia_relativa_w_kg", "Potencia relativa estimada",
                              power / mass_kg, "W/kg", 1))
    return metrics, checks, method


def _analyze_sts(rep, baseline_av, mass_kg):
    t = np.array([s.t for s in rep])
    a_v = np.array([s.a_vertical for s in rep]) - baseline_av
    method = (
        "Doble integración de la aceleración vertical entre el reposo sentado y el reposo de pie, "
        "con corrección de deriva (velocidad cero al inicio y al final). Potencia = m·(a + g)·v "
        "en la fase de ascenso. Requiere el sensor en la cadera/sacro."
    )
    checks = []
    sat = _saturation_count(rep)
    if sat:
        checks.append(Check("Saturación del acelerómetro", "fail",
                            f"{sat} muestras superaron el rango del sensor; la integración no es fiable."))
    v, v_end_raw = _integrate(a_v, t)
    # El desplazamiento no se corrige a cero: la cadera termina mas arriba que al inicio.
    dt = np.diff(t, prepend=t[0])
    d = np.cumsum(0.5 * (v + np.concatenate([v[:1], v[:-1]])) * dt)
    rise = float(d[-1])
    drift = abs(float(v_end_raw))
    if drift > STS_DRIFT_FAIL:
        checks.append(Check("Deriva de la integración", "fail",
                            f"La velocidad al final era {drift:.2f} m/s antes de corregir (debería ser ~0). "
                            "Hubo movimiento del sensor respecto al cuerpo o error de orientación."))
    elif drift > STS_DRIFT_WARN:
        checks.append(Check("Deriva de la integración", "warn",
                            f"Deriva moderada ({drift:.2f} m/s); los valores tienen mayor incertidumbre."))
    else:
        checks.append(Check("Deriva de la integración", "ok", f"Deriva baja ({drift:.2f} m/s)."))
    if STS_MIN_RISE_M <= rise <= STS_MAX_RISE_M:
        checks.append(Check("Ascenso plausible", "ok", f"La cadera subió {rise * 100:.0f} cm."))
    else:
        checks.append(Check("Ascenso plausible", "fail",
                            f"Ascenso calculado de {rise * 100:.0f} cm, fuera del rango esperado "
                            f"({STS_MIN_RISE_M * 100:.0f}–{STS_MAX_RISE_M * 100:.0f} cm). Revise que el "
                            "sensor esté en la cadera y la persona parta sentada y termine de pie."))
    peak_v = float(v.max())
    if peak_v > STS_MAX_VELOCITY:
        checks.append(Check("Velocidad plausible", "fail",
                            f"{peak_v:.2f} m/s supera lo posible al levantarse."))
    power = mass_kg * (a_v + G) * v
    rising = v > 0.05
    metrics = [
        Metric("potencia_pico_w", "Potencia pico", float(power.max()), "W", 0, primary=True),
        Metric("potencia_relativa_w_kg", "Potencia pico relativa", float(power.max()) / mass_kg, "W/kg", 1),
        Metric("potencia_media_w", "Potencia media de ascenso",
               float(power[rising].mean()) if rising.any() else 0.0, "W", 0),
        Metric("velocidad_pico_m_s", "Velocidad vertical pico", peak_v, "m/s", 2),
        Metric("desplazamiento_cm", "Ascenso de la cadera", rise * 100, "cm", 0),
    ]
    return metrics, checks, method


def _analyze_punch(rep, baseline_av, mass_kg):
    t = np.array([s.t for s in rep])
    a_w = np.array([s.a_world_dyn for s in rep])
    method = (
        "Velocidad 3D de la muñeca por integración de la aceleración sin gravedad (en todas las "
        "direcciones, no solo la vertical), con corrección de deriva entre dos reposos. La "
        "aceleración y la velocidad angular pico son medidas directas del sensor."
    )
    checks = []
    v, v_end_raw = _integrate(a_w, t)
    speed = np.linalg.norm(v, axis=1)
    peak_speed = float(speed.max())
    drift = float(np.linalg.norm(v_end_raw))
    sat = _saturation_count(rep)
    if sat:
        checks.append(Check("Saturación del acelerómetro", "warn",
                            f"{sat} muestras alcanzaron el límite del sensor (16 g): la aceleración pico y "
                            "la velocidad están subestimadas."))
    if drift > PUNCH_DRIFT_WARN:
        checks.append(Check("Deriva de la integración", "warn",
                            f"Deriva de {drift:.1f} m/s antes de corregir; la velocidad es aproximada."))
    else:
        checks.append(Check("Deriva de la integración", "ok", f"Deriva baja ({drift:.2f} m/s)."))
    if peak_speed > PUNCH_MAX_SPEED:
        checks.append(Check("Velocidad plausible", "fail",
                            f"{peak_speed:.1f} m/s no es posible para un golpe; revise la sujeción del sensor."))
    metrics = [
        Metric("velocidad_pico_m_s", "Velocidad pico del puño", peak_speed, "m/s", 1, primary=True),
        Metric("aceleracion_pico_g", "Aceleración pico",
               float(np.linalg.norm(a_w, axis=1).max() / G), "g", 1),
        Metric("vel_angular_pico_dps", "Velocidad angular pico",
               float(max(s.gyro_mag_dps for s in rep)), "°/s", 0),
    ]
    return metrics, checks, method
