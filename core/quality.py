"""Calidad de la senal de un intento: muestras recibidas, perdidas y saturadas."""
from dataclasses import dataclass

from core.kinematics import Check

GOOD_RECEIVED_PCT = 98.0
MIN_RECEIVED_PCT = 90.0


@dataclass
class SignalQuality:
    received: int
    lost: int
    duration_s: float
    max_gap_ms: float
    saturated: int

    @property
    def expected(self) -> int:
        return self.received + self.lost

    @property
    def lost_pct(self) -> float:
        return 100.0 * self.lost / self.expected if self.expected else 0.0

    @property
    def effective_rate_hz(self) -> float:
        return self.received / self.duration_s if self.duration_s > 0 else 0.0


HOST_SPAN_TOLERANCE_S = 0.3


def assess(rows: list[dict], rate_hz: float) -> SignalQuality:
    """rows: filas del buffer crudo (con 'time', 'lost_before', 'saturado' y 'host_time')."""
    if not rows:
        return SignalQuality(0, 0, 0.0, 0.0, 0)
    lost = sum(int(r.get("lost_before", 0)) for r in rows[1:])
    if "host_time" in rows[0]:
        # Control global: con el tiempo transcurrido en el PC no pueden haber llegado
        # menos muestras que las que el sensor genero (con tolerancia por latencia).
        span = float(rows[-1]["host_time"]) - float(rows[0]["host_time"])
        missing = int(round((span - HOST_SPAN_TOLERANCE_S) * rate_hz)) + 1 - len(rows)
        lost = max(lost, missing)
    times = [float(r["time"]) for r in rows]
    gaps = [b - a for a, b in zip(times, times[1:])]
    return SignalQuality(
        received=len(rows), lost=lost,
        duration_s=times[-1] - times[0] + 1.0 / rate_hz,
        max_gap_ms=1000 * max(gaps, default=0.0),
        saturated=sum(int(r.get("saturado", 0)) for r in rows),
    )


def transmission_check(q: SignalQuality, strict: bool) -> Check:
    """strict=True en pruebas cuyo resultado se calcula con la senal IMU."""
    if q.received == 0:
        return Check("Transmisión Bluetooth", "fail", "No se recibieron datos del sensor.")
    received_pct = 100.0 - q.lost_pct
    detail = (f"Se recibió el {received_pct:.1f} % de las muestras ({q.received} de {q.expected}); "
              f"mayor hueco {q.max_gap_ms:.0f} ms.")
    if received_pct >= GOOD_RECEIVED_PCT:
        return Check("Transmisión Bluetooth", "ok", detail)
    if received_pct >= MIN_RECEIVED_PCT or not strict:
        return Check("Transmisión Bluetooth", "warn",
                     detail + " Acerque el computador al sensor y evite obstáculos entre ambos.")
    return Check("Transmisión Bluetooth", "fail",
                 detail + " Demasiadas pérdidas para calcular resultados fiables.")
