"""Conexion en background al sensor MetaWear (MMS) y emision de muestras via Qt signals.

Cambios de confiabilidad respecto a la version anterior:
  - Acelerometro en +-16 g (antes +-4 g, que se saturaba en saltos y golpes).
  - Senales "empaquetadas" (3 muestras por paquete BLE) y parametros de conexion
    de 7,5 ms: menos paquetes, menos perdidas. Se quita el magnetometro (no se
    usa y ocupaba ancho de banda).
  - Cada muestra lleva el tiempo de medicion reconstruido (SampleClock) y el
    numero de muestras perdidas antes de ella.
  - Se detecta la desconexion (on_disconnect) y la falta de datos (watchdog):
    antes el estado seguia en "transmitiendo" aunque el sensor se hubiera caido.
  - Si falla la configuracion despues de conectar, igual se desconecta, para que
    "Reintentar conexion" funcione.
  - Cada aceleracion se empareja con el giroscopio del mismo instante (ImuPairer),
    no con el ultimo recibido.
"""
import os
import threading
import time

from PyQt6.QtCore import QThread, pyqtSignal

from core import simulation, storage
from core.config import DEFAULT_MAC as MAC_ADDRESS
from core.imu_pairing import ImuPairer
from core.sample_clock import SampleClock

SCAN_DURATION_S = 6.0
SAMPLE_RATE_HZ = 100.0
ACC_RANGE_G = 16.0
NO_DATA_TIMEOUT_S = 1.0

# Valores de mbl_mw_metawearboard_lookup_module(board, Module.GYRO)
_GYRO_BMI160 = 0
_GYRO_BMI270 = 1


class SensorStream(QThread):
    """Hilo que conecta al MMS, transmite acc+gyro y los reenvia como senales Qt."""

    # {"time": s (medicion), "host_time": s, "lost_before": int, "acc_x/y/z": g, "gyr_x/y/z": dps}
    sample_ready = pyqtSignal(dict)
    status_changed = pyqtSignal(str)  # "conectando", "conectado", "transmitiendo", "desconectado"
    error = pyqtSignal(str)

    def __init__(self, mac_address: str = MAC_ADDRESS, parent=None):
        super().__init__(parent)
        self.mac_address = mac_address
        self._stop_requested = False

    def request_stop(self):
        self._stop_requested = True

    def set_profile(self, task: str):
        """Solo tiene efecto en el simulador."""

    def run(self):
        self._stop_requested = False
        try:
            self._run_real_sensor()
        except Exception as exc:  # noqa: BLE001 - queremos capturar cualquier fallo de hardware
            self.status_changed.emit("desconectado")
            self.error.emit(str(exc))

    # -- Sensor real ---------------------------------------------------
    def _run_real_sensor(self):
        from mbientlab.metawear import MetaWear, libmetawear, parse_value
        from mbientlab.metawear.cbindings import (
            c_float, FnVoid_VoidP_DataP, GyroBoschOdr, GyroBoschRange, Module,
        )

        self.status_changed.emit("conectando")
        # La cache del SDK va con los datos: la carpeta del programa puede ser de solo lectura.
        device = MetaWear(self.mac_address, cache_path=os.path.join(storage.DATA_DIR, ".metawear"))
        device.connect()
        if self._stop_requested:
            # Se pidio detener mientras connect() estaba bloqueado: liberar el sensor ya.
            try:
                device.disconnect()
            finally:
                self.status_changed.emit("desconectado")
            return
        disconnected = {"flag": False}
        device.on_disconnect = lambda status: disconnected.update(flag=True)
        self.status_changed.emit("conectado")

        board = device.board
        started = False
        signals = []
        try:
            libmetawear.mbl_mw_settings_set_connection_parameters(board, 7.5, 7.5, 0, 6000)
            time.sleep(1.0)

            gyro_type = libmetawear.mbl_mw_metawearboard_lookup_module(board, Module.GYRO)
            if gyro_type == _GYRO_BMI270:
                gyro = {
                    "set_odr": libmetawear.mbl_mw_gyro_bmi270_set_odr,
                    "set_range": libmetawear.mbl_mw_gyro_bmi270_set_range,
                    "write": libmetawear.mbl_mw_gyro_bmi270_write_config,
                    "signal": libmetawear.mbl_mw_gyro_bmi270_get_packed_rotation_data_signal,
                    "enable": libmetawear.mbl_mw_gyro_bmi270_enable_rotation_sampling,
                    "disable": libmetawear.mbl_mw_gyro_bmi270_disable_rotation_sampling,
                    "start": libmetawear.mbl_mw_gyro_bmi270_start,
                    "stop": libmetawear.mbl_mw_gyro_bmi270_stop,
                }
            elif gyro_type == _GYRO_BMI160:
                gyro = {
                    "set_odr": libmetawear.mbl_mw_gyro_bmi160_set_odr,
                    "set_range": libmetawear.mbl_mw_gyro_bmi160_set_range,
                    "write": libmetawear.mbl_mw_gyro_bmi160_write_config,
                    "signal": libmetawear.mbl_mw_gyro_bmi160_get_packed_rotation_data_signal,
                    "enable": libmetawear.mbl_mw_gyro_bmi160_enable_rotation_sampling,
                    "disable": libmetawear.mbl_mw_gyro_bmi160_disable_rotation_sampling,
                    "start": libmetawear.mbl_mw_gyro_bmi160_start,
                    "stop": libmetawear.mbl_mw_gyro_bmi160_stop,
                }
            else:
                raise RuntimeError(f"El sensor no tiene un giroscopio compatible (tipo {gyro_type})")

            libmetawear.mbl_mw_acc_set_odr(board, c_float(SAMPLE_RATE_HZ))
            libmetawear.mbl_mw_acc_set_range(board, c_float(ACC_RANGE_G))
            libmetawear.mbl_mw_acc_write_acceleration_config(board)
            gyro["set_odr"](board, GyroBoschOdr._100Hz)
            gyro["set_range"](board, GyroBoschRange._2000dps)
            gyro["write"](board)

            acc_signal = libmetawear.mbl_mw_acc_get_packed_acceleration_data_signal(board)
            gyro_signal = gyro["signal"](board)
            signals = [acc_signal, gyro_signal]

            clock = SampleClock(SAMPLE_RATE_HZ)
            pairer = ImuPairer()
            # Las notificaciones de cada senal pueden llegar por hilos distintos del SDK.
            lock = threading.Lock()
            last_arrival = {"t": time.perf_counter()}

            def emit(ready):
                for acc, gyro, (t, host_t, lost), paired in ready:
                    self.sample_ready.emit({
                        "time": t, "host_time": host_t, "lost_before": lost,
                        "acc_x": acc[0], "acc_y": acc[1], "acc_z": acc[2],
                        "gyr_x": gyro[0], "gyr_y": gyro[1], "gyr_z": gyro[2],
                        "gyro_emparejado": int(paired),
                    })

            def on_gyro(ctx, data):
                v = parse_value(data)
                with lock:
                    emit(pairer.add_gyro((float(v.x), float(v.y), float(v.z))))

            def on_acc(ctx, data):
                host_t = time.perf_counter()
                last_arrival["t"] = host_t
                v = parse_value(data)
                with lock:
                    t, lost = clock.stamp(host_t)
                    emit(pairer.add_acc((float(v.x), float(v.y), float(v.z)), (t, host_t, lost),
                                        resync=lost > 0))

            cb_gyro = FnVoid_VoidP_DataP(on_gyro)
            cb_acc = FnVoid_VoidP_DataP(on_acc)
            libmetawear.mbl_mw_datasignal_subscribe(gyro_signal, None, cb_gyro)
            libmetawear.mbl_mw_datasignal_subscribe(acc_signal, None, cb_acc)

            libmetawear.mbl_mw_acc_enable_acceleration_sampling(board)
            gyro["enable"](board)
            gyro["start"](board)
            libmetawear.mbl_mw_acc_start(board)
            started = True
            last_arrival["t"] = time.perf_counter()

            first_sample_seen = False
            while not self._stop_requested:
                self.msleep(50)
                if disconnected["flag"]:
                    raise RuntimeError("El sensor se desconectó (Bluetooth). Acérquelo al computador y reintente")
                silent = time.perf_counter() - last_arrival["t"]
                if clock.stats.received and not first_sample_seen:
                    first_sample_seen = True
                    self.status_changed.emit("transmitiendo")
                if silent > NO_DATA_TIMEOUT_S + (2.0 if not first_sample_seen else 0.0):
                    raise RuntimeError(f"El sensor dejó de enviar datos durante {silent:.1f} s")
        finally:
            if not disconnected["flag"]:
                for step in (
                    lambda: libmetawear.mbl_mw_acc_stop(board) if started else None,
                    lambda: gyro["stop"](board) if started else None,
                    lambda: libmetawear.mbl_mw_acc_disable_acceleration_sampling(board) if started else None,
                    lambda: gyro["disable"](board) if started else None,
                    *[lambda s=s: libmetawear.mbl_mw_datasignal_unsubscribe(s) for s in signals],
                ):
                    try:
                        step()
                    except Exception:  # noqa: BLE001 - la limpieza no debe ocultar el error original
                        pass
            try:
                device.disconnect()
            except Exception:  # noqa: BLE001
                pass
            self.status_changed.emit("desconectado")


class SensorScanner(QThread):
    """Busca sensores MetaWear cercanos por Bluetooth durante unos segundos."""

    found = pyqtSignal(str, str, int)  # mac, nombre, rssi (dBm)
    error = pyqtSignal(str)

    def run(self):
        try:
            from mbientlab.metawear import MetaWear
            from mbientlab.warble import BleScanner

            seen = set()

            def handler(result):
                is_metawear = result.has_service_uuid(MetaWear.GATT_SERVICE) or "metawear" in result.name.lower()
                if is_metawear and result.mac not in seen:
                    seen.add(result.mac)
                    self.found.emit(result.mac.upper(), result.name or "MetaWear", int(result.rssi))

            BleScanner.set_handler(handler)
            BleScanner.start()
            try:
                self.msleep(int(SCAN_DURATION_S * 1000))
            finally:
                BleScanner.stop()
        except Exception as exc:  # noqa: BLE001 - Bluetooth apagado o sin adaptador
            self.error.emit(str(exc))


class SimulatedSensorScanner(QThread):
    found = pyqtSignal(str, str, int)
    error = pyqtSignal(str)

    def run(self):
        self.msleep(800)
        self.found.emit("E7:D7:CE:C3:E0:25", "MetaWear (simulado)", -55)


class SimulatedSensorStream(QThread):
    """Generador de datos sinteticos para probar la interfaz sin el sensor fisico.

    Emite muestras a 100 Hz segun el reloj real (en rafagas, como el Bluetooth),
    y repite el movimiento de la prueba activa (set_profile) cada pocos segundos.
    """

    sample_ready = pyqtSignal(dict)
    status_changed = pyqtSignal(str)
    error = pyqtSignal(str)

    PROFILES = {
        "jump": lambda: simulation.jump_profile(0.32),
        "sts": lambda: simulation.sts_profile(0.40, 0.9),
        "punch": lambda: simulation.punch_profile(0.5, 0.2),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stop_requested = False
        self._profile = "jump"

    def request_stop(self):
        self._stop_requested = True

    def set_profile(self, task: str):
        if task in self.PROFILES:
            self._profile = task

    def _next_movement(self):
        profile = self._profile
        return iter(simulation.to_sensor_samples(
            self.PROFILES[profile](), rest_before_s=2.0, rest_after_s=1.5,
        ))

    def run(self):
        self._stop_requested = False
        self.status_changed.emit("conectando")
        self.msleep(400)
        self.status_changed.emit("conectado")
        self.msleep(200)

        clock = SampleClock(SAMPLE_RATE_HZ)
        t0 = time.perf_counter()
        emitted = 0
        movement = self._next_movement()
        announced = False
        while not self._stop_requested:
            due = int((time.perf_counter() - t0) * SAMPLE_RATE_HZ)
            while emitted < due:
                try:
                    ax, ay, az, gx, gy, gz = next(movement)
                except StopIteration:
                    movement = self._next_movement()
                    continue
                host_t = time.perf_counter()
                t, lost = clock.stamp(host_t)
                self.sample_ready.emit({
                    "time": t, "host_time": host_t, "lost_before": lost,
                    "acc_x": ax, "acc_y": ay, "acc_z": az,
                    "gyr_x": gx, "gyr_y": gy, "gyr_z": gz, "gyro_emparejado": 1,
                })
                emitted += 1
            if not announced and emitted:
                announced = True
                self.status_changed.emit("transmitiendo")
            self.msleep(30)

        self.status_changed.emit("desconectado")
