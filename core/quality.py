"""Calidad de la senal de un intento: muestras recibidas, perdidas y saturadas."""
from dataclasses import dataclass
import math

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
    invalid: int = 0
    gyro_fallbacks: int = 0
    gyro_uncertain: int = 0
    gyro_saturated: int = 0
    timing_native: bool = False

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
    if not math.isfinite(rate_hz) or rate_hz <= 0:
        raise ValueError("La frecuencia debe ser positiva y finita.")
    def finite(value):
        try:
            return math.isfinite(float(value))
        except (ValueError, TypeError, OverflowError):
            return False
    def flag(value, default=True):
        if value is None or value == "":
            return default
        return value.strip().lower() not in {"0", "false", "no"} if isinstance(value, str) else bool(value)
    invalid = sum(not flag(r.get("signal_valid")) or not finite(r.get("time"))
                  or any(k in r and not finite(r[k]) for k in
                         ("host_time", "acc_x", "acc_y", "acc_z", "gyr_x", "gyr_y", "gyr_z"))
                  or any(r.get(k) not in (None, "") and not finite(r[k]) for k in ("device_time", "sequence"))
                  for r in rows)
    lost = sum(max(0, int(r.get("lost_before", 0))) for r in rows[1:]
               if finite(r.get("lost_before", 0)))
    timing_native = (all(r.get("device_time") is not None and finite(r["device_time"]) for r in rows)
                     or all(r.get("sequence") is not None and finite(r["sequence"]) for r in rows))
    if "host_time" in rows[0] and finite(rows[0]["host_time"]) and finite(rows[-1]["host_time"]) and not timing_native:
        # Control global: con el tiempo transcurrido en el PC no pueden haber llegado
        # menos muestras que las que el sensor genero (con tolerancia por latencia).
        span = float(rows[-1]["host_time"]) - float(rows[0]["host_time"])
        missing = int(round((span - HOST_SPAN_TOLERANCE_S) * rate_hz)) + 1 - len(rows)
        lost = max(lost, missing)
    times = [float(r["time"]) for r in rows if finite(r.get("time"))]
    gaps = [b - a for a, b in zip(times, times[1:])]
    return SignalQuality(
        received=len(rows), lost=lost,
        duration_s=max(0, times[-1] - times[0] + 1.0 / rate_hz) if times else 0.0,
        max_gap_ms=1000 * max(gaps, default=0.0),
        saturated=sum(int(r.get("saturado", 0)) for r in rows),
        invalid=invalid,
        gyro_fallbacks=sum(r.get("gyro_pairing") == "fallback" or
                           ("gyro_emparejado" in r and not flag(r["gyro_emparejado"])) for r in rows),
        gyro_uncertain=sum(r.get("gyro_pairing", "unknown") not in {"native", "fallback"}
                           and flag(r.get("gyro_emparejado", 1)) for r in rows),
        gyro_saturated=sum(flag(r.get("gyro_saturated", r.get("gyro_saturado", False))) for r in rows),
        timing_native=timing_native,
    )


def transmission_check(q: SignalQuality, strict: bool, *, requires_gyro: bool = False) -> Check:
    """strict=True en pruebas cuyo resultado se calcula con la senal IMU."""
    if q.received == 0:
        return Check("Transmisión Bluetooth", "fail", "No se recibieron datos del sensor.")
    received_pct = 100.0 - q.lost_pct
    detail = (f"Cobertura {'medida' if q.timing_native else 'estimada'}: {received_pct:.1f} % "
              f"({q.received} de {q.expected}); "
              f"mayor hueco {q.max_gap_ms:.0f} ms.")
    if not q.timing_native:
        detail += " Las horas del PC pueden omitir pérdidas pequeñas o confundirlas con cambios de latencia."
    problems = []
    if q.invalid:
        problems.append(f"{q.invalid} muestras no válidas")
    if requires_gyro and q.gyro_fallbacks:
        problems.append(f"{q.gyro_fallbacks} giros sustituidos sin pareja")
    if requires_gyro and q.gyro_saturated:
        problems.append(f"{q.gyro_saturated} muestras con giroscopio saturado")
    if problems:
        return Check("Transmisión Bluetooth", "fail" if strict else "warn",
                     detail + " " + "; ".join(problems) + ". Repita la captura.")
    if requires_gyro and q.gyro_uncertain:
        detail += f" {q.gyro_uncertain} parejas IMU tienen sincronía estimada, sin identidad nativa verificada."
        return Check("Transmisión Bluetooth", "warn" if received_pct >= MIN_RECEIVED_PCT or not strict else "fail", detail)
    if received_pct >= GOOD_RECEIVED_PCT:
        return Check("Transmisión Bluetooth", "ok", detail)
    if received_pct >= MIN_RECEIVED_PCT or not strict:
        return Check("Transmisión Bluetooth", "warn",
                     detail + " Acerque el computador al sensor y evite obstáculos entre ambos.")
    return Check("Transmisión Bluetooth", "fail",
                 detail + " Demasiadas pérdidas para calcular resultados fiables.")
