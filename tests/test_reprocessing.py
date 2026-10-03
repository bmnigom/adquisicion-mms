"""Reprocesado solo con señales sintéticas en memoria; no lee participantes."""
import csv
import io
import unittest
from unittest.mock import patch

from core import simulation
from reprocesar_datos import analyze_file, analyze_rows, _old_text


def synthetic_rows(task="sts", duration=2.0, *, current=False, native=False):
    profile = simulation.sts_profile(.4, duration) if task == "sts" else simulation.punch_profile(.2, .3)
    raw = simulation.to_sensor_samples(profile, noise_g=0, seed=4)
    rows = []
    for i, (ax, ay, az, gx, gy, gz) in enumerate(raw):
        row = dict(time=i / 100, acc_x=ax, acc_y=ay, acc_z=az, gyr_x=gx, gyr_y=gy, gyr_z=gz)
        if current:
            row["host_time"] = i / 100 + .04
        if native:
            row.update(device_time=i / 100, sequence=i, gyro_pairing="native")
        rows.append(row)
    return rows


def csv_text(rows):
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue()


class ReprocessingTests(unittest.TestCase):
    def test_legacy_slow_sts_has_unknown_pairing_and_illustrative_mass(self):
        result = analyze_rows(synthetic_rows(), "sts")
        self.assertTrue(result["rep"].valid, result["checks"])
        self.assertAlmostEqual(result["rep"].metric("desplazamiento_cm").value, 40, delta=3)
        self.assertGreater(result["quality"].gyro_uncertain, 0)
        self.assertFalse(result["quality"].timing_native)
        self.assertTrue(any(c.label == "Masa de referencia" and c.status == "warn" for c in result["checks"]))

    def test_current_files_are_opt_in_and_native_metadata_survives_csv(self):
        rows = synthetic_rows(current=True, native=True)
        text = csv_text(rows)
        with patch("builtins.open", return_value=io.StringIO(text)):
            self.assertIsNone(analyze_file("synthetic.csv", "sts"))
        with patch("builtins.open", return_value=io.StringIO(text)):
            result = analyze_file("synthetic.csv", "sts", include_current=True)
        self.assertTrue(result["quality"].timing_native)
        self.assertEqual(result["quality"].gyro_uncertain, 0)
        self.assertTrue(result["rep"].valid, result["checks"])

    def test_native_small_loss_is_not_hidden_by_pc_arrival(self):
        rows = synthetic_rows(current=True, native=True)
        del rows[180:182]
        result = analyze_rows(rows, "sts", mass_kg=70)
        self.assertEqual(result["quality"].lost, 2)
        self.assertFalse(result["rep"].valid)

    def test_missing_gyro_and_serialized_saturation_invalidate_integration(self):
        for flag in ({"gyro_emparejado": "0"}, {"gyro_saturado": "1"}):
            with self.subTest(flag=flag):
                rows = synthetic_rows("punch", current=True, native=True)
                rows[112].update(flag)
                result = analyze_rows(rows, "punch", acc_range_g=16)
                self.assertFalse(result["rep"].valid)
                self.assertTrue(any(c.status == "fail" for c in result["checks"]))

    def test_invalid_time_and_nan_acceleration_produce_failed_verdicts(self):
        for key, value in (("time", "malformado"), ("acc_x", float("nan"))):
            with self.subTest(key=key):
                rows = synthetic_rows("punch")
                rows[112][key] = value
                result = analyze_rows(rows, "punch", acc_range_g=16)
                self.assertFalse(result["rep"].valid)
                self.assertGreater(result["quality"].invalid, 0)

    def test_old_nonfinite_metric_is_not_printed_as_a_result(self):
        row = dict(peak_power_w="nan", peak_velocity_m_s="1", max_displacement_m=".4")
        self.assertEqual(_old_text(row), "—")


if __name__ == "__main__":
    unittest.main()
