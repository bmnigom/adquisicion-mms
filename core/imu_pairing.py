"""Emparejamiento de las muestras del acelerometro y del giroscopio.

Ambos sensores estan en el mismo chip (BMI160/BMI270) y miden a la misma
frecuencia, pero llegan por Bluetooth en paquetes separados (3 muestras por
paquete). La version anterior asignaba a cada aceleracion el ULTIMO giroscopio
recibido: hasta ~30 ms de desfase y tres aceleraciones con el mismo giro.

Aqui la muestra i del acelerometro se une a la muestra i del giroscopio
(orden de llegada). Limites:
  - Si se pierde un paquete de un solo sensor, el emparejamiento queda
    desplazado 3 muestras hasta el siguiente hueco grande (igual que antes).
  - Si el giroscopio se atrasa mas de MAX_WAIT muestras, la aceleracion no se
    retiene: se emite con el ultimo giroscopio conocido (se cuenta en fallbacks).
"""
from collections import deque

MAX_WAIT = 6  # dos paquetes: retraso maximo que se agrega a la senal en vivo (60 ms)


class ImuPairer:
    def __init__(self, max_wait: int = MAX_WAIT):
        self.max_wait = max_wait
        self._acc: deque = deque()
        self._gyro: deque = deque()
        self._last_gyro = (0.0, 0.0, 0.0)
        self._acc_started = False
        self.paired = 0
        self.fallbacks = 0

    def add_gyro(self, gyro: tuple) -> list:
        # El giroscopio se inicia antes que el acelerometro: sus muestras previas a la
        # primera aceleracion no tienen pareja y desplazarian todo el emparejamiento.
        self._last_gyro = gyro
        if self._acc_started:
            self._gyro.append(gyro)
        return self._drain()

    def add_acc(self, acc: tuple, meta, resync: bool = False) -> list:
        """meta: datos que acompanan a la muestra (tiempo, perdidas).
        resync=True tras un hueco grande: se descarta lo pendiente del giroscopio."""
        self._acc_started = True
        if resync:
            self._gyro.clear()
        self._acc.append((acc, meta))
        return self._drain()

    def _drain(self) -> list:
        """Devuelve [(acc, gyro, meta, emparejado)] listos para emitir, en orden."""
        out = []
        while self._acc and self._gyro:
            acc, meta = self._acc.popleft()
            out.append((acc, self._gyro.popleft(), meta, True))
            self.paired += 1
        while len(self._acc) > self.max_wait:
            acc, meta = self._acc.popleft()
            out.append((acc, self._last_gyro, meta, False))
            self.fallbacks += 1
        while len(self._gyro) > self.max_wait:
            self._gyro.popleft()
        return out
