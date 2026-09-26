"""Reconstruccion del instante de medicion de cada muestra.

Al transmitir por Bluetooth, las muestras llegan al PC en rafagas (varias en
1 ms y luego un hueco de 50-100 ms). La hora de llegada no es la hora de
medicion, y el sensor puede descartar paquetes si el enlace se satura.

El acelerometro mide con su propio reloj a frecuencia fija (ODR), asi que la
muestra i se midio en i/ODR... salvo que se hayan perdido muestras antes.

Distinguir perdida de retraso:
  - Si un paquete solo se RETRASA (Bluetooth o el propio PC ocupado), llega
    tarde y luego la cola se pone al dia: el retraso minimo de llegada vuelve
    a su nivel normal.
  - Si se PIERDEN k muestras, todas las siguientes llegan k/ODR "tarde"
    respecto a su indice, de forma permanente.
Por eso se compara el retraso minimo en una ventana antes y despues de cada
punto; un escalon permanente indica perdida. Esto necesita ver datos
posteriores, asi que se aplica al terminar la repeticion o la captura
(reconstruct). En vivo, SampleClock solo marca huecos grandes y evidentes.

Limites (validados con rafagas simuladas de 5-40 ms de latencia): se detectan
perdidas de 3 o mas muestras; la posicion se conoce con la precision de una
rafaga Bluetooth. Por eso los analisis no "corrigen" una perdida dentro del
movimiento: la marcan y piden repetir.
"""
from dataclasses import dataclass

import numpy as np

LIVE_MAX_LATENCY_S = 0.5     # un bloqueo del PC mas corto que esto no se toma como perdida
BIG_GAP_S = 0.5
WINDOW_S = 1.0
MIN_LOSS_SAMPLES = 3


@dataclass
class ClockStats:
    received: int = 0
    lost: int = 0


class SampleClock:
    """Tiempo provisional en vivo: indice / ODR, abriendo solo huecos grandes."""

    def __init__(self, rate_hz: float, max_latency_s: float = LIVE_MAX_LATENCY_S):
        self.period = 1.0 / rate_hz
        self.max_latency_s = max_latency_s
        self.reset()

    def reset(self):
        self._origin: float | None = None
        self._t: float | None = None
        self.stats = ClockStats()

    def stamp(self, host_t: float) -> tuple[float, int]:
        """Devuelve (tiempo provisional en s, muestras perdidas evidentes justo antes)."""
        self.stats.received += 1
        if self._t is None:
            self._origin = host_t
            self._t = 0.0
            return 0.0, 0
        earliest_possible = host_t - self._origin - self.max_latency_s
        steps = max(1, round((earliest_possible - self._t) / self.period))
        self._t += steps * self.period
        self.stats.lost += steps - 1
        return self._t, steps - 1


def reconstruct(host_times, rate_hz: float, window_s: float = WINDOW_S,
                min_loss: int = MIN_LOSS_SAMPLES) -> tuple[np.ndarray, np.ndarray]:
    """Tiempos de medicion y perdidas a partir de las horas de llegada.

    Devuelve (t, lost_before): t[0] = 0; lost_before[i] = muestras perdidas
    entre la muestra i-1 y la i. Detecta perdidas de >= min_loss muestras;
    perdidas de 1 muestra no se distinguen del jitter del Bluetooth.
    """
    host = np.asarray(host_times, dtype=float)
    n = len(host)
    lost_before = np.zeros(n, dtype=int)
    if n < 2:
        return np.zeros(n), lost_before
    period = 1.0 / rate_hz
    w = max(3, int(round(window_s * rate_hz)))

    lag = host - np.arange(n) * period
    # Retraso minimo en la ventana anterior (sin incluir i) y posterior (incluyendo i)
    pre = np.full(n, lag[0])
    suf = np.full(n, lag[0])
    for i in range(1, n):
        pre[i] = lag[max(0, i - w):i].min()
        suf[i] = lag[i:min(n, i + w)].min()
    # Cerca de los bordes una ventana tiene pocas muestras y su minimo no es
    # representativo: solo se evalua con al menos media ventana a cada lado.
    half = w // 2
    evaluable = np.zeros(n, dtype=bool)
    evaluable[half:max(half, n - half + 1)] = True

    def steps():
        return np.where(evaluable, suf - pre, 0.0)

    step = steps()
    threshold = (min_loss - 0.5) * period
    i = 1
    while i < n:
        if step[i] > threshold:
            # El escalon se ve en varias muestras seguidas: su tamano se toma donde es
            # maximo y la posicion donde empieza (el primer indice que supera el umbral).
            j_end = min(n, i + w)
            peak = i + int(np.argmax(step[i:j_end]))
            k = int(round(step[peak] / period))
            zone = np.arange(max(1, peak - w // 2), min(n, peak + w // 2))
            zone = zone[step[zone] > threshold]
            j = int(zone[0])
            lost_before[j] = k
            # Las muestras siguientes ya incluyen este escalon.
            lag[j:] -= k * period
            for m in range(max(1, j - w), min(n, j + 2 * w)):
                pre[m] = lag[max(0, m - w):m].min()
                suf[m] = lag[m:min(n, m + w)].min()
            step = steps()
            i = j + 1
        else:
            i += 1
    # Donde no hay datos suficientes para las ventanas (bordes, o transmision muy
    # escasa) solo se pueden afirmar las perdidas evidentes: silencios de mas de 0,5 s.
    for i in np.nonzero(~evaluable)[0]:
        gap = host[i] - host[i - 1] if i > 0 else 0.0
        if gap > BIG_GAP_S and lost_before[i] == 0:
            lost_before[i] = int(round((gap - BIG_GAP_S / 2) / period))
    t = (np.arange(n) + np.cumsum(lost_before)) * period
    return t, lost_before
