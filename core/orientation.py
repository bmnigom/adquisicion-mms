"""Filtro de orientacion Mahony (giroscopio + acelerometro).

Se usa para:
  1) Proyectar la aceleracion sobre el eje vertical del mundo (y, en el golpe,
     obtener la aceleracion 3D sin gravedad).
  2) Mostrar la inclinacion del sensor para estandarizar la colocacion.

Correcciones respecto a la version anterior:
  - El acelerometro solo corrige la inclinacion cuando mide ~1 g. Durante un
    salto, un golpe o un aterrizaje el acelerometro no mide la gravedad, y
    usarlo como referencia desviaba la vertical justo cuando se media.
  - Ya no se usa el magnetometro: al aire libre (bicicletas, postes, estructuras
    metalicas) y sin calibracion hard-iron introducia errores, y el rumbo no es
    necesario para la componente vertical.
  - La orientacion inicial se toma del primer vector de gravedad, sin esperar
    a que el filtro converja desde la identidad.
"""
import math

import numpy as np

G = 9.81

# Rango de |a| (en g) en el que el acelerometro se considera medida de gravedad.
GRAVITY_GATE_G = 0.1


class MahonyAHRS:
    def __init__(self, kp: float = 2.0, ki: float = 0.005):
        self.kp = kp
        self.ki = ki
        self.q = np.array([1.0, 0.0, 0.0, 0.0])  # w, x, y, z
        self._e_int = np.zeros(3)
        self._initialized = False

    @property
    def initialized(self) -> bool:
        return self._initialized

    def update(self, gyro_rad_s, accel_g, dt: float = 0.01):
        a = np.asarray(accel_g, dtype=float)
        gyro = np.asarray(gyro_rad_s, dtype=float)
        if (a.shape != (3,) or gyro.shape != (3,) or not np.isfinite(a).all()
                or not np.isfinite(gyro).all() or not math.isfinite(dt) or dt <= 0):
            raise ValueError("La orientación requiere vectores finitos y un intervalo positivo.")
        a_norm = np.linalg.norm(a)
        if not self._initialized:
            if a_norm < 0.5:
                return self.q
            self.q = _quat_from_gravity(a / a_norm)
            self._initialized = True
            return self.q

        q0, q1, q2, q3 = self.q
        error = np.zeros(3)
        if abs(a_norm - 1.0) < GRAVITY_GATE_G:
            a = a / a_norm
            # direccion estimada de "arriba" (mundo) expresada en el marco del sensor
            v = np.array([
                2 * (q1 * q3 - q0 * q2),
                2 * (q0 * q1 + q2 * q3),
                q0 * q0 - q1 * q1 - q2 * q2 + q3 * q3,
            ])
            error = np.cross(a, v)
            self._e_int += error * self.ki * dt

        gyro_corr = gyro + self.kp * error + self._e_int
        q_dot = 0.5 * _quat_mult(self.q, np.array([0.0, *gyro_corr]))
        self.q = self.q + q_dot * dt
        self.q = self.q / np.linalg.norm(self.q)
        return self.q

    def rotate_to_world(self, vector_sensor_frame):
        return _rotate(self.q, np.asarray(vector_sensor_frame, dtype=float))

    def euler_deg(self):
        q0, q1, q2, q3 = self.q
        roll = math.degrees(math.atan2(2 * (q0 * q1 + q2 * q3), 1 - 2 * (q1 * q1 + q2 * q2)))
        pitch = math.degrees(math.asin(max(-1.0, min(1.0, 2 * (q0 * q2 - q3 * q1)))))
        yaw = math.degrees(math.atan2(2 * (q0 * q3 + q1 * q2), 1 - 2 * (q2 * q2 + q3 * q3)))
        return roll, pitch, yaw


def tilt_angle_diff_deg(q_a, q_b) -> float:
    """Angulo (grados) entre las inclinaciones de dos orientaciones.

    Compara solo hacia donde apunta la vertical en el marco del sensor, de modo
    que girar el cuerpo (mirar hacia otro lado) no cuenta como mala colocacion.
    """
    up = np.array([0.0, 0.0, 1.0])
    u_a = _rotate(_conjugate(np.asarray(q_a, dtype=float)), up)
    u_b = _rotate(_conjugate(np.asarray(q_b, dtype=float)), up)
    cos = float(np.dot(u_a, u_b) / (np.linalg.norm(u_a) * np.linalg.norm(u_b)))
    return math.degrees(math.acos(max(-1.0, min(1.0, cos))))


def _quat_from_gravity(a_unit):
    """Cuaternion (rumbo arbitrario) que alinea la gravedad medida con el eje Z del mundo."""
    ax, ay, az = a_unit
    roll = math.atan2(ay, az)
    pitch = math.atan2(-ax, math.hypot(ay, az))
    cr, sr = math.cos(roll / 2), math.sin(roll / 2)
    cp, sp = math.cos(pitch / 2), math.sin(pitch / 2)
    return np.array([cr * cp, sr * cp, cr * sp, -sr * sp])


def _quat_mult(a, b):
    a0, a1, a2, a3 = a
    b0, b1, b2, b3 = b
    return np.array([
        a0 * b0 - a1 * b1 - a2 * b2 - a3 * b3,
        a0 * b1 + a1 * b0 + a2 * b3 - a3 * b2,
        a0 * b2 - a1 * b3 + a2 * b0 + a3 * b1,
        a0 * b3 + a1 * b2 - a2 * b1 + a3 * b0,
    ])


def _conjugate(q):
    return np.array([q[0], -q[1], -q[2], -q[3]])


def _rotate(q, v):
    qv = np.array([0.0, v[0], v[1], v[2]])
    r = _quat_mult(_quat_mult(q, qv), _conjugate(q))
    return r[1:]
