"""Pruebas de persistencia con datos sintéticos y carpetas aisladas del proyecto."""
import csv
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from core import config, storage


class StorageIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.saved = {key: getattr(storage, key) for key in (
            "BASE_DATA_DIR", "DATA_DIR", "DATA_SOURCE", "RESULTS_LOG", "TIMED_RESULTS_LOG",
            "REFERENCE_ORIENTATION_FILE", "REPORTS_DIR")}
        workspace_tmp = Path(__file__).resolve().parent.parent / "tests_TMP"
        workspace_tmp.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=workspace_tmp)
        self.root = Path(self.temporary.name)
        self.data = self.root / "data"
        storage.configure_storage(False, base_dir=str(self.data))

    def tearDown(self):
        for key, value in self.saved.items():
            setattr(storage, key, value)
        self.temporary.cleanup()

    def result(self, seconds=10.5, ended_by="manual", count=900):
        return SimpleNamespace(duration_s=seconds, sample_count=count, ended_by=ended_by)

    def rows(self, path=None):
        with open(path or storage.TIMED_RESULTS_LOG, newline="", encoding="utf-8-sig") as handle:
            return list(csv.DictReader(handle))

    def test_simulation_has_separate_results_configuration_and_calibration(self):
        config.save({"mac_address": "AA:BB:CC:DD:EE:01"})
        storage.save_reference_orientation("Cadera", [1, 0, 0, 0])
        storage.append_timed_result("01", "tug", "01", self.result(12.0))
        storage.configure_storage(True)
        self.assertIsNone(storage.previous_value("01", "tug", timed=True))
        self.assertIsNone(storage.load_reference_orientation("Cadera"))
        self.assertEqual(config.load()["mac_address"], config.DEFAULT_MAC)
        config.save({"mac_address": "AA:BB:CC:DD:EE:02"})
        storage.save_reference_orientation("Cadera", [0, 1, 0, 0])
        storage.append_timed_result("01", "tug", "01", self.result(2.0))
        self.assertEqual(self.rows()[0]["data_source"], "simulacion")
        storage.configure_storage(False)
        self.assertEqual(storage.previous_value("01", "tug", timed=True), 12.0)
        self.assertEqual(config.load()["mac_address"], "AA:BB:CC:DD:EE:01")
        self.assertEqual(storage.load_reference_orientation("Cadera"), [1.0, 0.0, 0.0, 0.0])

    def test_report_only_and_csv_only_participants_are_counted(self):
        storage.save_report("04", "jump", "01", "<p>Sin muestras</p>")
        self.assertEqual(storage.next_participant_number(), "05")
        storage.append_timed_result("07", "tug", "01", self.result())
        self.assertEqual(storage.next_participant_number(), "08")
        storage.create_session("09", "jump")
        self.assertEqual(storage.next_participant_number(), "10")

    def test_run_reservation_is_exclusive_between_threads(self):
        with ThreadPoolExecutor(max_workers=6) as executor:
            sessions = list(executor.map(lambda _: storage.create_session("01", "jump"), range(18)))
        self.assertEqual(len({s.run for s in sessions}), 18)
        self.assertEqual(len({s.session_id for s in sessions}), 18)
        self.assertEqual(storage.next_run_number("01", "jump"), "19")

    def test_canceled_session_can_be_discarded_without_leaving_manifest(self):
        session = storage.create_session("11", "jump")
        manifest = Path(storage._manifest_path(session))
        reservation = Path(storage._reservation_path(session.sub, session.task, session.run,
                                                      session.timestamp, session.data_dir))
        self.assertTrue(manifest.exists() and reservation.exists())
        storage.discard_session(session)
        self.assertFalse(manifest.exists() or reservation.exists())
        self.assertEqual(storage.create_session("11", "jump").run, "01")

    def test_run_reservation_is_exclusive_between_processes(self):
        script = ("import json,sys; from core import storage; "
                  "storage.configure_storage(False,base_dir=sys.argv[1]); "
                  "s=storage.create_session('01','jump'); print(json.dumps([s.run,s.session_id]))")
        processes = [subprocess.Popen([sys.executable, "-B", "-c", script, str(self.data)],
                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(4)]
        sessions = []
        for process in processes:
            stdout, stderr = process.communicate(timeout=20)
            self.assertEqual(process.returncode, 0, stderr)
            sessions.append(json.loads(stdout))
        self.assertEqual(len({s[0] for s in sessions}), 4)

    def test_fixed_session_timestamp_links_manifest_raw_report_and_csv(self):
        stamp = dt.datetime(2026, 9, 30, 23, 59, 59, tzinfo=dt.timezone(dt.timedelta(hours=-5)))
        session = storage.create_session("01", "tug", timestamp=stamp,
                                         metadata={"sensor_mac": "AA:BB:CC:DD:EE:01", "sample_rate_hz": 100})
        raw = storage.save_raw_session("01", "tug", session.run,
                    [{"time": 0.0, "ax": 1.0, "gyro_emparejado": 1, "gyro_saturated": False},
                     {"time": 0.01, "ax": 2.0, "extra": 5, "gyro_saturado": 1}],
                    session=session)
        storage.append_timed_result("01", "tug", session.run, self.result(), session=session)
        report = storage.save_report("01", "tug", session.run, "<p>Resultado</p>", session=session)
        self.assertIn("ses-2026-09-30", raw)
        self.assertIn("ses-2026-09-30", report)
        rows = self.rows()
        self.assertEqual(rows[0]["session_id"], session.session_id)
        self.assertEqual(rows[0]["session_timestamp"], stamp.isoformat())
        self.assertEqual(rows[0]["fecha"], "2026-09-30")
        raw_rows = self.rows(raw)
        self.assertEqual(raw_rows[0]["gyro_pairing"], "estimated")
        self.assertEqual(raw_rows[1]["extra"], "5")
        self.assertEqual(raw_rows[0]["signal_valid"], "")
        self.assertEqual(raw_rows[0]["gyro_saturado"], "0")
        self.assertEqual(raw_rows[1]["gyro_saturated"], "1")
        self.assertEqual(raw_rows[0]["session_id"], session.session_id)
        manifest = json.loads(Path(storage._manifest_path(session)).read_text(encoding="utf-8"))
        self.assertEqual(manifest["metadata"]["sample_rate_hz"], 100)
        self.assertEqual(manifest["status"], "guardada")
        self.assertEqual(manifest["artifacts"]["raw"]["sha256"], hashlib.sha256(Path(raw).read_bytes()).hexdigest())
        self.assertEqual(set(manifest["artifacts"]), {"raw", "report", "results"})

    def test_raw_and_report_refuse_overwrite(self):
        raw = storage.save_raw_session("01", "jump", "01", [{"time": 1.0}])
        report = storage.save_report("01", "jump", "01", "original")
        before = Path(raw).read_bytes()
        with self.assertRaises(storage.SaveError):
            storage.save_raw_session("01", "jump", "01", [{"time": 999.0}])
        with self.assertRaises(storage.SaveError):
            storage.save_report("01", "jump", "01", "replacement")
        self.assertEqual(Path(raw).read_bytes(), before)
        self.assertEqual(Path(report).read_text(), "original")

    def test_failed_json_publication_preserves_previous_configuration(self):
        config.save({"mac_address": "AA:BB:CC:DD:EE:01"})
        original = Path(config._path()).read_bytes()
        with patch.object(storage.os, "replace", side_effect=PermissionError("injected")):
            with self.assertRaises(PermissionError):
                config.save({"mac_address": "AA:BB:CC:DD:EE:02"})
        self.assertEqual(Path(config._path()).read_bytes(), original)
        self.assertEqual(list(self.data.glob(".mms-*.tmp")), [])

    def test_failed_csv_publication_does_not_truncate_existing_rows(self):
        storage.append_timed_result("01", "tug", "01", self.result())
        original = Path(storage.TIMED_RESULTS_LOG).read_bytes()
        with patch.object(storage.os, "replace", side_effect=OSError("disk failure")):
            with self.assertRaises(storage.SaveError):
                storage.append_timed_result("01", "tug", "02", self.result(11.0))
        self.assertEqual(Path(storage.TIMED_RESULTS_LOG).read_bytes(), original)

    def test_pending_replay_after_cleanup_interruption_is_idempotent(self):
        real_write = storage._write_rows
        def blocked(path, header, rows):
            if path == storage.TIMED_RESULTS_LOG:
                raise PermissionError("Excel lock")
            real_write(path, header, rows)
        with patch.object(storage, "_write_rows", side_effect=blocked):
            self.assertIn("Excel", storage.append_timed_result("01", "tug", "01", self.result()))
        pending = storage._pending_path(storage.TIMED_RESULTS_LOG)
        real_remove = storage.os.remove
        def interrupted_remove(path):
            if os.fspath(path) == pending:
                raise PermissionError("pending still open")
            return real_remove(path)
        with patch.object(storage.os, "remove", side_effect=interrupted_remove):
            storage.append_timed_result("01", "tug", "02", self.result(11.0))
        self.assertTrue(os.path.exists(pending))
        self.assertEqual(storage.previous_value("01", "tug", timed=True), 11.0)
        storage.append_timed_result("01", "tug", "03", self.result(12.0))
        self.assertEqual([r["run"] for r in self.rows()], ["01", "02", "03"])
        self.assertFalse(os.path.exists(pending))

    def test_pending_manifest_keeps_canonical_result_reference_after_reconciliation(self):
        session = storage.create_session("01", "tug")
        real_write = storage._write_rows
        def blocked(path, header, rows):
            if path == storage.TIMED_RESULTS_LOG:
                raise PermissionError("Excel lock")
            real_write(path, header, rows)
        with patch.object(storage, "_write_rows", side_effect=blocked):
            storage.append_timed_result("01", "tug", session.run, self.result(), session=session)
        storage.append_timed_result("01", "tug", "02", self.result(11.0))
        manifest = json.loads(Path(storage._manifest_path(session)).read_text(encoding="utf-8"))
        reference = manifest["artifacts"]["results"]
        self.assertEqual(reference["path"], "resultados_pruebas_funcionales.csv")
        self.assertTrue((self.data / reference["path"]).is_file())
        self.assertEqual(reference["session_id"], session.session_id)

    def test_repeated_result_with_same_session_is_written_once(self):
        session = storage.create_session("01", "tug")
        for _ in range(3):
            storage.append_timed_result("01", "tug", session.run, self.result(), session=session)
        self.assertEqual(len(self.rows()), 1)

    def test_concurrent_results_from_processes_do_not_lose_rows(self):
        script = ("import sys; from types import SimpleNamespace; from core import storage; "
                  "storage.configure_storage(False,base_dir=sys.argv[1]); "
                  "s=storage.create_session('01','tug'); "
                  "r=SimpleNamespace(duration_s=10.5,sample_count=900,ended_by='manual'); "
                  "storage.append_timed_result('01','tug',s.run,r,session=s)")
        processes = [subprocess.Popen([sys.executable, "-B", "-c", script, str(self.data)],
                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(4)]
        for process in processes:
            _, stderr = process.communicate(timeout=20)
            self.assertEqual(process.returncode, 0, stderr)
        self.assertEqual(len(self.rows()), 4)
        self.assertEqual(len({row["session_id"] for row in self.rows()}), 4)

    def test_legacy_columns_migrate_by_name_and_keep_values(self):
        self.data.mkdir()
        with open(storage.TIMED_RESULTS_LOG, "w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle)
            writer.writerow(["task", "sub", "hora", "fecha", "run", "duration_s", "ended_by", "condition"])
            writer.writerow(["tug", "01", "08:00:00", "2026-09-30", "01", "13.2", "manual", ""])
        storage.append_timed_result("01", "tug", "02", self.result())
        rows = self.rows()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["duration_s"], "13.2")
        self.assertEqual(rows[0]["task"], "tug")
        self.assertEqual(rows[0]["data_source"], "legacy-desconocido")
        self.assertTrue(rows[0]["session_id"])

    def test_legacy_power_csv_without_algorithm_column_migrates(self):
        self.data.mkdir()
        old_header = [key for key in storage.RESULTS_HEADER
                      if key != "version_algoritmo" and key not in storage.PROVENANCE_COLUMNS]
        with open(storage.RESULTS_LOG, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=old_header)
            writer.writeheader()
            writer.writerow({"fecha": "2026-09-30", "hora": "08:00:00", "sub": "01",
                             "task": "jump", "run": "01", "valido": "si", "altura_salto_cm": "25.3"})
        storage._upgrade_header(storage.RESULTS_LOG, storage.RESULTS_HEADER)
        row = self.rows(storage.RESULTS_LOG)[0]
        self.assertEqual(row["altura_salto_cm"], "25.3")
        self.assertEqual(row["version_algoritmo"], "")

    def test_unknown_columns_are_preserved_and_rejected(self):
        self.data.mkdir()
        original = b"sub,task,mystery\n01,tug,keep-me\n"
        Path(storage.TIMED_RESULTS_LOG).write_bytes(original)
        with self.assertRaises(storage.SaveError):
            storage.append_timed_result("01", "tug", "02", self.result())
        self.assertEqual(Path(storage.TIMED_RESULTS_LOG).read_bytes(), original)

    def test_invalid_timed_results_and_nonfinite_values_are_not_comparisons(self):
        storage.append_timed_result("01", "tug", "01", self.result(12.0))
        storage.append_timed_result("01", "tug", "02", self.result(3.0, "desconexion"))
        storage.append_timed_result("01", "tug", "03", self.result(4.0), valid=False, reasons="interrumpida")
        storage.append_timed_result("01", "tug", "04", self.result(float("nan")))
        self.assertEqual(storage.previous_value("01", "tug", timed=True), 12.0)

    def test_invalid_reference_quaternion_does_not_replace_previous(self):
        storage.save_reference_orientation("Cadera", [1, 0, 0, 0])
        for quaternion in ([0, 0, 0, 0], [1, 2, 3], [float("nan"), 0, 0, 0]):
            with self.assertRaises(ValueError):
                storage.save_reference_orientation("Cadera", quaternion)
        self.assertEqual(storage.load_reference_orientation("Cadera"), [1.0, 0.0, 0.0, 0.0])

    def test_backup_is_reproducible_excludes_simulation_and_roundtrips(self):
        storage.save_report("01", "tug", "01", "<p>Sintético</p>")
        (self.data / "simulacion").mkdir()
        (self.data / "simulacion" / "synthetic.txt").write_text("simulation")
        first = storage.export_backup(str(self.root / "one.zip"))
        second = storage.export_backup(str(self.root / "two.zip"))
        self.assertEqual(Path(first).read_bytes(), Path(second).read_bytes())
        with zipfile.ZipFile(first) as archive:
            self.assertFalse(any(name.startswith("simulacion/") for name in archive.namelist()))
        restored = storage.restore_backup(first, destination=str(self.root / "restored"))
        relative = Path(storage._report_path("01", "tug", "01")).relative_to(self.data)
        self.assertEqual((Path(restored) / relative).read_text(encoding="utf-8"), "<p>Sintético</p>")
        self.assertEqual(storage.DATA_DIR, str(self.data))

    def test_backup_refuses_overwrite_or_destination_inside_data(self):
        existing = self.root / "existing.zip"
        existing.write_bytes(b"existing")
        with self.assertRaises(storage.SaveError):
            storage.export_backup(str(existing))
        with self.assertRaises(storage.SaveError):
            storage.export_backup(str(self.data / "recursive.zip"))
        self.assertEqual(existing.read_bytes(), b"existing")

    def make_zip(self, entries, *, manifest=None):
        archive_path = self.root / "injected.zip"
        if manifest is None:
            manifest = {"schema_version": 1, "files": {name: {
                "sha256": hashlib.sha256(content).hexdigest(), "size_bytes": len(content)}
                for name, content in entries}}
        with zipfile.ZipFile(archive_path, "w") as archive:
            for name, content in entries:
                archive.writestr(name, content)
            archive.writestr(storage.BACKUP_MANIFEST, json.dumps(manifest))
        return str(archive_path)

    def test_restore_rejects_traversal_absolute_and_windows_alias_paths(self):
        for name in ("../escape.txt", "/absolute.txt", "C:/escape.txt", "folder\\escape.txt",
                     "foo//bar.txt", "CON.txt", "folder/name. "):
            with self.subTest(name=name):
                path = self.make_zip([(name, b"bad")])
                destination = self.root / "rejected"
                with self.assertRaises(storage.SaveError):
                    storage.restore_backup(path, destination=str(destination))
                self.assertFalse(destination.exists())
        self.assertEqual(list(self.root.glob(".mms-restore-*")), [])

    def test_restore_rejects_case_collisions_and_damaged_checksums(self):
        path = self.make_zip([("a.txt", b"one"), ("A.txt", b"two")])
        with self.assertRaises(storage.SaveError):
            storage.restore_backup(path, destination=str(self.root / "case"))
        path = self.make_zip([("safe.txt", b"changed")], manifest={"schema_version": 1, "files": {
            "safe.txt": {"size_bytes": 7, "sha256": "0" * 64}}})
        with self.assertRaises(storage.SaveError):
            storage.restore_backup(path, destination=str(self.root / "checksum"))
        self.assertFalse((self.root / "checksum").exists())

    def test_restore_refuses_existing_or_active_folder(self):
        path = self.make_zip([("safe.txt", b"safe")])
        self.data.mkdir()
        (self.data / "keep.txt").write_text("keep")
        with self.assertRaises(storage.SaveError):
            storage.restore_backup(path, destination=str(self.data))
        self.assertEqual((self.data / "keep.txt").read_text(), "keep")


if __name__ == "__main__":
    unittest.main()
