"""Empareja IMU por identidad nativa cuando está disponible.

device_time: segundos del reloj del sensor, con referencia común a ambos canales.
sequence: índice común verificado, no contadores iniciados por separado. El epoch
del streaming packed de MetaWear es hora del PC y NO cumple este contrato.
Sin identidad se conserva FIFO como estimación explícitamente incierta.
"""
import math
from collections import deque
from dataclasses import dataclass
from enum import IntEnum

MAX_WAIT = 6


class PairingStatus(IntEnum):
    FALLBACK = 0
    ESTIMATED = 1
    NATIVE = 2


@dataclass
class _Entry:
    vector: tuple
    meta: object = None
    device_time: float | None = None
    sequence: int | None = None


def _entry(vector, meta=None, device_time=None, sequence=None):
    if device_time is not None and not math.isfinite(device_time):
        raise ValueError("device_time debe ser finito y proceder del sensor.")
    if sequence is not None and (isinstance(sequence, bool) or int(sequence) != sequence or sequence < 0):
        raise ValueError("sequence debe ser un entero no negativo del sensor.")
    return _Entry(vector, meta, device_time, sequence)


class ImuPairer:
    def __init__(self, max_wait: int = MAX_WAIT, match_tolerance_s: float = 0.004):
        if max_wait < 0 or int(max_wait) != max_wait or not math.isfinite(match_tolerance_s) or match_tolerance_s < 0:
            raise ValueError("La espera y tolerancia del emparejamiento no pueden ser negativas.")
        self.max_wait = max_wait
        self.match_tolerance_s = match_tolerance_s
        self._acc: deque[_Entry] = deque()
        self._gyro: deque[_Entry] = deque()
        self._last_gyro = (0.0, 0.0, 0.0)
        self._acc_started = False
        self.paired = 0
        self.verified = 0
        self.uncertain = 0
        self.fallbacks = 0

    def add_gyro(self, gyro: tuple, *, device_time=None, sequence=None) -> list:
        item = _entry(gyro, device_time=device_time, sequence=sequence)
        self._last_gyro = gyro
        if self._acc_started or device_time is not None or sequence is not None:
            self._gyro.append(item)
        return self._drain()

    def add_acc(self, acc: tuple, meta, resync: bool = False, *, device_time=None, sequence=None) -> list:
        item = _entry(acc, meta, device_time, sequence)
        self._acc_started = True
        out = self.flush() if resync else []
        self._acc.append(item)
        return out + self._drain()

    def _emit(self, acc, gyro, status):
        if status == PairingStatus.FALLBACK:
            self.fallbacks += 1
        else:
            self.paired += 1
            self.verified += status == PairingStatus.NATIVE
            self.uncertain += status == PairingStatus.ESTIMATED
        return (acc.vector, gyro, acc.meta, status)

    def _drain(self) -> list:
        """Salida [(acc, gyro, meta, status)]; bool(status) conserva la API anterior.

        Solo NATIVE indica identidad comparada. Guardar status.name.lower() para
        no confundir el indicador antiguo con verificación de sincronía.
        """
        out = []
        while self._acc and self._gyro:
            acc, gyro = self._acc[0], self._gyro[0]
            delta = None
            tolerance = 0
            if acc.sequence is not None and gyro.sequence is not None:
                delta = acc.sequence - gyro.sequence
            elif acc.device_time is not None and gyro.device_time is not None:
                delta = acc.device_time - gyro.device_time
                tolerance = self.match_tolerance_s
            if delta is not None and delta < -tolerance:
                out.append(self._emit(self._acc.popleft(), self._last_gyro, PairingStatus.FALLBACK))
            elif delta is not None and delta > tolerance:
                self._gyro.popleft()
            else:
                self._acc.popleft()
                self._gyro.popleft()
                status = PairingStatus.NATIVE if delta is not None else PairingStatus.ESTIMATED
                out.append(self._emit(acc, gyro.vector, status))
        while len(self._acc) > self.max_wait:
            out.append(self._emit(self._acc.popleft(), self._last_gyro, PairingStatus.FALLBACK))
        while len(self._gyro) > self.max_wait:
            self._gyro.popleft()
        return out

    def flush(self) -> list:
        """Emite aceleraciones pendientes como fallback y limpia ambas colas."""
        out = [self._emit(acc, self._last_gyro, PairingStatus.FALLBACK) for acc in self._acc]
        self._acc.clear()
        self._gyro.clear()
        return out
