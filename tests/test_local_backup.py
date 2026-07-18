# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ReachOps.workbench import local_backup
from ReachOps.workbench.local_backup import (
    BackupIntegrityError,
    BackupPathError,
    build_backup_preview,
    create_encrypted_backup,
    inspect_encrypted_backup,
    restore_encrypted_backup,
)


class LocalBackupTests(unittest.TestCase):
    def _runtime(self, base: Path) -> Path:
        runtime = base / "runtime"
        (runtime / "data" / "growth_intelligence" / "reports" / "evidence").mkdir(parents=True)
        (runtime / "data" / "growth_intelligence").mkdir(parents=True, exist_ok=True)
        (runtime / "config").mkdir(parents=True, exist_ok=True)
        (runtime / "logs").mkdir(parents=True, exist_ok=True)
        (runtime / "ixbrowser" / "cookies").mkdir(parents=True, exist_ok=True)
        (runtime / "data" / "growth_intelligence" / "growth_intelligence.db").write_bytes(b"sqlite customer rows")
        (runtime / "data" / "growth_intelligence" / "growth_intelligence.db-wal").write_bytes(b"wal sidecar")
        (runtime / "config" / "templates.json").write_text('{"template":"safe"}', encoding="utf-8")
        (runtime / "config" / "reachops_activation_status.json").write_text('{"license_secret":"no"}', encoding="utf-8")
        (runtime / "logs" / "runtime.log").write_text("operator log\n", encoding="utf-8")
        (runtime / "tools").mkdir(parents=True, exist_ok=True)
        (runtime / "tools" / "reachops_acceptance_inputs.local.ps1").write_text("$TargetUsername='real-user'", encoding="utf-8")
        (runtime / "ixbrowser" / "cookies" / "session.cookie").write_text("tiktok-cookie", encoding="utf-8")
        (runtime / "config" / "proxy_password.txt").write_text("proxy-password", encoding="utf-8")
        (runtime / "data" / "growth_intelligence" / "reports" / "evidence" / "sidecar.json").write_text('{"ok":true}', encoding="utf-8")
        (runtime / "data" / "growth_intelligence" / "reports" / "evidence" / "raw.png").write_bytes(b"raw screenshot")
        return runtime

    def test_preview_excludes_sensitive_files_from_lightweight_backup(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            runtime = self._runtime(Path(td))
            preview = build_backup_preview(runtime, full=False)

            selected = {row["path"] for row in preview["selected_files"]}
            excluded = {row["path"]: row["reason"] for row in preview["excluded_files"]}
            self.assertIn("data/growth_intelligence/growth_intelligence.db", selected)
            self.assertIn("config/templates.json", selected)
            self.assertNotIn("data/growth_intelligence/reports/evidence/raw.png", selected)
            self.assertEqual(excluded["ixbrowser/cookies/session.cookie"], "sensitive_path")
            self.assertEqual(excluded["config/reachops_activation_status.json"], "local_authorization_or_license_state")
            self.assertEqual(excluded["tools/reachops_acceptance_inputs.local.ps1"], "local_authorization_or_license_state")
            self.assertTrue(preview["exclusion_policy"]["credential_material_excluded"])
            self.assertTrue(preview["no_submit"])

    def test_full_backup_includes_evidence_index_but_excludes_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            runtime = self._runtime(Path(td))
            preview = build_backup_preview(runtime, full=True)

            selected = {row["path"] for row in preview["selected_files"]}
            self.assertIn("data/growth_intelligence/reports/evidence/sidecar.json", selected)
            self.assertIn("data/growth_intelligence/reports/evidence/raw.png", selected)
            self.assertNotIn("ixbrowser/cookies/session.cookie", selected)
            self.assertNotIn("config/proxy_password.txt", selected)

    def test_create_inspect_and_restore_round_trip_without_plaintext_archive(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            runtime = self._runtime(base)
            archive = base / "reachops.reachops-backup"
            result = create_encrypted_backup(runtime, archive, "correct horse battery staple", full=False)

            archive_bytes = archive.read_bytes()
            self.assertEqual(result["status"], "created")
            self.assertNotIn(b"sqlite customer rows", archive_bytes)
            self.assertNotIn(b"tiktok-cookie", archive_bytes)
            inspected = inspect_encrypted_backup(archive, "correct horse battery staple")
            self.assertEqual(inspected["file_count"], result["manifest"]["selected_count"])

            restored = base / "restored"
            preview = restore_encrypted_backup(archive, restored, "correct horse battery staple", preview_only=True)
            self.assertEqual(preview["status"], "preview")
            restore = restore_encrypted_backup(archive, restored, "correct horse battery staple")
            self.assertEqual(restore["status"], "restored")
            self.assertEqual((restored / "data" / "growth_intelligence" / "growth_intelligence.db").read_bytes(), b"sqlite customer rows")
            self.assertFalse((restored / "ixbrowser" / "cookies" / "session.cookie").exists())
            self.assertFalse((restored / "tools" / "reachops_acceptance_inputs.local.ps1").exists())

    def test_wrong_password_and_tamper_raise_integrity_error(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            runtime = self._runtime(base)
            archive = base / "reachops.reachops-backup"
            create_encrypted_backup(runtime, archive, "good-password")

            with self.assertRaises(BackupIntegrityError):
                inspect_encrypted_backup(archive, "bad-password")

            envelope = json.loads(archive.read_text(encoding="utf-8"))
            envelope["ciphertext"] = envelope["ciphertext"][:-2] + "AA"
            tampered = base / "tampered.reachops-backup"
            tampered.write_text(json.dumps(envelope), encoding="utf-8")
            with self.assertRaises(BackupIntegrityError):
                inspect_encrypted_backup(tampered, "good-password")

    def test_restore_rejects_path_traversal(self) -> None:
        payload = {
            "schema_version": "reachops.backup.v1",
            "created_at": "2026-07-19T00:00:00Z",
            "backup_variant": "lightweight",
            "manifest": {},
            "files": [
                {
                    "path": "../escape.txt",
                    "size_bytes": 4,
                    "sha256": local_backup._sha256_bytes(b"evil"),
                    "kind": "config",
                    "data_b64": "ZXZpbA==",
                }
            ],
        }
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            archive = base / "unsafe.reachops-backup"
            archive.write_bytes(local_backup._encrypt_payload(payload, "pw"))
            with self.assertRaises(BackupPathError):
                restore_encrypted_backup(archive, base / "restore", "pw")
            self.assertFalse((base / "escape.txt").exists())

    def test_restore_failure_keeps_existing_destination(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            runtime = self._runtime(base)
            archive = base / "reachops.reachops-backup"
            create_encrypted_backup(runtime, archive, "pw")
            destination = base / "existing"
            destination.mkdir()
            (destination / "keep.txt").write_text("keep", encoding="utf-8")

            original_write_bytes = local_backup.Path.write_bytes

            def failing_write(path: Path, data: bytes) -> int:
                if path.name == "growth_intelligence.db":
                    raise OSError("simulated interrupted restore")
                return original_write_bytes(path, data)

            with mock.patch.object(local_backup.Path, "write_bytes", failing_write):
                with self.assertRaises(OSError):
                    restore_encrypted_backup(archive, destination, "pw")
            self.assertEqual((destination / "keep.txt").read_text(encoding="utf-8"), "keep")

    def test_older_supported_schema_can_be_previewed_and_restored(self) -> None:
        data = b"old schema"
        payload = {
            "schema_version": "reachops.backup.v0",
            "created_at": "2026-07-18T00:00:00Z",
            "backup_variant": "lightweight",
            "manifest": {"schema_version": "reachops.backup.v0"},
            "files": [
                {
                    "path": "config/templates.json",
                    "size_bytes": len(data),
                    "sha256": local_backup._sha256_bytes(data),
                    "kind": "config",
                    "data_b64": "b2xkIHNjaGVtYQ==",
                }
            ],
        }
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            archive = base / "old.reachops-backup"
            archive.write_bytes(local_backup._encrypt_payload(payload, "pw"))

            preview = restore_encrypted_backup(archive, base / "restore", "pw", preview_only=True)
            self.assertEqual(preview["schema_version"], "reachops.backup.v0")
            restored = restore_encrypted_backup(archive, base / "restore", "pw")
            self.assertEqual(restored["status"], "restored")
            self.assertEqual((base / "restore" / "config" / "templates.json").read_bytes(), data)


if __name__ == "__main__":
    unittest.main()
