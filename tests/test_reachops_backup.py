# -*- coding: utf-8 -*-
from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path

from ReachOps.runtime_paths import RuntimePaths
from ReachOps.security.backup import (
    BACKUP_SCHEMA_VERSION,
    BackupError,
    BackupIntegrityError,
    BackupPasswordError,
    preview_backup,
    restore_backup,
    write_encrypted_backup,
)


class ReachOpsBackupTests(unittest.TestCase):
    def _runtime_with_data(self, root: str) -> RuntimePaths:
        paths = RuntimePaths.build(root).ensure_dirs()
        conn = sqlite3.connect(paths.db_path)
        conn.execute("CREATE TABLE IF NOT EXISTS sample (id TEXT PRIMARY KEY, value TEXT)")
        conn.execute("INSERT OR REPLACE INTO sample (id, value) VALUES ('one', 'local customer row')")
        conn.commit()
        conn.close()
        config_dir = Path(paths.config_dir)
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "reachops_client_config.json").write_text(json.dumps({"locale": "zh-CN"}), encoding="utf-8")
        (config_dir / "reachops_activation_status.json").write_text("license-secret", encoding="utf-8")
        (config_dir / "openai_api_key.txt").write_text("sk-should-not-export", encoding="utf-8")
        evidence_dir = Path(paths.reports_dir) / "action_submit_evidence"
        evidence_dir.mkdir(parents=True, exist_ok=True)
        (evidence_dir / "real-screenshot.png").write_bytes(b"raw screenshot")
        return paths

    def test_encrypted_backup_preview_excludes_secrets_and_raw_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as source, tempfile.TemporaryDirectory() as output_dir:
            self._runtime_with_data(source)
            backup_path = Path(output_dir) / "customer-data.reachops-backup"
            result = write_encrypted_backup(source, backup_path, "customer-password")
            preview = preview_backup(backup_path, "customer-password")

            self.assertEqual(result["schema_version"], BACKUP_SCHEMA_VERSION)
            self.assertEqual(preview["manifest"]["schema_version"], BACKUP_SCHEMA_VERSION)
            self.assertEqual(preview["header"]["mac"], "hmac_sha256")
            exported_paths = {row["path"] for row in preview["manifest"]["files"]}
            self.assertIn("data/growth_intelligence/growth_intelligence.db", exported_paths)
            self.assertIn("config/reachops_client_config.json", exported_paths)
            serialized = json.dumps(preview, ensure_ascii=False)
            self.assertNotIn("sk-should-not-export", serialized)
            self.assertNotIn("reachops_activation_status.json\", \"category\"", serialized)
            self.assertTrue(preview["manifest"]["privacy"]["secrets_excluded"])
            self.assertTrue(preview["manifest"]["privacy"]["cookies_excluded"])
            self.assertTrue(preview["manifest"]["privacy"]["raw_screenshots_excluded"])
            self.assertFalse(preview["customer_data_uploaded"])

    def test_restore_backup_recreates_sqlite_and_non_secret_config(self) -> None:
        with tempfile.TemporaryDirectory() as source, tempfile.TemporaryDirectory() as output_dir, tempfile.TemporaryDirectory() as target:
            self._runtime_with_data(source)
            backup_path = Path(output_dir) / "customer-data.reachops-backup"
            write_encrypted_backup(source, backup_path, "customer-password")
            preview = restore_backup(backup_path, "customer-password", target, preview_only=True)
            result = restore_backup(backup_path, "customer-password", target)

            self.assertEqual(preview["status"], "preview")
            self.assertEqual(result["status"], "restored")
            restored_paths = RuntimePaths.build(target)
            conn = sqlite3.connect(restored_paths.db_path)
            value = conn.execute("SELECT value FROM sample WHERE id='one'").fetchone()[0]
            conn.close()
            self.assertEqual(value, "local customer row")
            self.assertTrue((Path(restored_paths.config_dir) / "reachops_client_config.json").exists())
            self.assertFalse((Path(restored_paths.config_dir) / "reachops_activation_status.json").exists())

    def test_full_backup_includes_only_selected_evidence_files(self) -> None:
        with tempfile.TemporaryDirectory() as source, tempfile.TemporaryDirectory() as output_dir:
            paths = self._runtime_with_data(source)
            evidence_dir = Path(paths.reports_dir) / "action_submit_evidence"
            selected_sidecar = evidence_dir / "action-1.json"
            selected_screenshot = evidence_dir / "action-1.png"
            unselected_screenshot = evidence_dir / "action-2.png"
            selected_sidecar.write_text(
                json.dumps(
                    {
                        "action_id": "fixture-action-1",
                        "submitted_text": "synthetic comment",
                        "comment_visible_confirmed": True,
                    }
                ),
                encoding="utf-8",
            )
            selected_screenshot.write_bytes(b"synthetic selected evidence")
            unselected_screenshot.write_bytes(b"synthetic unselected evidence")
            backup_path = Path(output_dir) / "customer-full.reachops-backup"

            write_encrypted_backup(
                source,
                backup_path,
                "customer-password",
                variant="full",
                include_evidence_files=[selected_sidecar, selected_screenshot],
            )
            preview = preview_backup(backup_path, "customer-password")

            exported_paths = {row["path"] for row in preview["manifest"]["files"]}
            self.assertEqual(preview["manifest"]["variant"], "full")
            self.assertEqual(preview["manifest"]["selected_evidence_count"], 2)
            self.assertIn("data/growth_intelligence/reports/action_submit_evidence/action-1.json", exported_paths)
            self.assertIn("data/growth_intelligence/reports/action_submit_evidence/action-1.png", exported_paths)
            self.assertNotIn("data/growth_intelligence/reports/action_submit_evidence/action-2.png", exported_paths)
            self.assertFalse(preview["manifest"]["privacy"]["raw_screenshots_excluded"])
            self.assertTrue(preview["manifest"]["privacy"]["unselected_evidence_files_excluded"])

    def test_full_backup_restore_recreates_selected_evidence_under_reports(self) -> None:
        with tempfile.TemporaryDirectory() as source, tempfile.TemporaryDirectory() as output_dir, tempfile.TemporaryDirectory() as target:
            paths = self._runtime_with_data(source)
            evidence_dir = Path(paths.reports_dir) / "action_submit_evidence"
            selected_screenshot = evidence_dir / "action-restore.png"
            selected_screenshot.write_bytes(b"synthetic selected evidence")
            backup_path = Path(output_dir) / "customer-full.reachops-backup"
            write_encrypted_backup(
                source,
                backup_path,
                "customer-password",
                variant="full",
                include_evidence_files=[selected_screenshot],
            )

            result = restore_backup(backup_path, "customer-password", target)

            restored_paths = RuntimePaths.build(target)
            restored_file = Path(restored_paths.reports_dir) / "action_submit_evidence" / "action-restore.png"
            self.assertEqual(result["status"], "restored")
            self.assertEqual(restored_file.read_bytes(), b"synthetic selected evidence")

    def test_full_backup_excludes_selected_evidence_outside_reports_and_secret_paths(self) -> None:
        with tempfile.TemporaryDirectory() as source, tempfile.TemporaryDirectory() as output_dir:
            paths = self._runtime_with_data(source)
            outside_file = Path(source) / "outside-evidence.png"
            outside_file.write_bytes(b"outside")
            secret_evidence = Path(paths.reports_dir) / "action_submit_evidence" / "session-token-sidecar.json"
            secret_evidence.write_text("token material", encoding="utf-8")
            backup_path = Path(output_dir) / "customer-full.reachops-backup"

            write_encrypted_backup(
                source,
                backup_path,
                "customer-password",
                variant="full",
                include_evidence_files=[outside_file, secret_evidence],
            )
            preview = preview_backup(backup_path, "customer-password")

            exported_paths = {row["path"] for row in preview["manifest"]["files"]}
            reasons = {row["reason"] for row in preview["manifest"]["excluded"]}
            serialized = json.dumps(preview, ensure_ascii=False)
            self.assertNotIn("outside-evidence.png", exported_paths)
            self.assertNotIn(str(outside_file), serialized)
            self.assertNotIn("session-token-sidecar.json", serialized)
            self.assertNotIn("session-token-sidecar.json\", \"category\"", serialized)
            self.assertIn("selected_evidence_outside_reports_dir", reasons)
            self.assertIn("secret_or_activation_state_excluded", reasons)

    def test_wrong_password_and_corrupted_archive_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as source, tempfile.TemporaryDirectory() as output_dir:
            self._runtime_with_data(source)
            backup_path = Path(output_dir) / "customer-data.reachops-backup"
            write_encrypted_backup(source, backup_path, "customer-password")
            with self.assertRaises(BackupPasswordError):
                preview_backup(backup_path, "wrong-password")
            data = bytearray(backup_path.read_bytes())
            data[-40] ^= 1
            backup_path.write_bytes(data)
            with self.assertRaises(BackupPasswordError):
                preview_backup(backup_path, "customer-password")

    def test_interrupted_restore_rolls_back_existing_files(self) -> None:
        with tempfile.TemporaryDirectory() as source, tempfile.TemporaryDirectory() as output_dir, tempfile.TemporaryDirectory() as target:
            self._runtime_with_data(source)
            target_paths = RuntimePaths.build(target).ensure_dirs()
            target_config = Path(target_paths.config_dir) / "reachops_client_config.json"
            target_config.write_text("original config", encoding="utf-8")
            original_db_path = Path(target_paths.db_path)
            original_db_path.parent.mkdir(parents=True, exist_ok=True)
            original_db_path.write_bytes(b"original db")
            backup_path = Path(output_dir) / "customer-data.reachops-backup"
            write_encrypted_backup(source, backup_path, "customer-password")

            with self.assertRaises(BackupError):
                restore_backup(backup_path, "customer-password", target, fail_after_files=2)

            self.assertEqual(target_config.read_text(encoding="utf-8"), "original config")
            self.assertEqual(original_db_path.read_bytes(), b"original db")

    def test_invalid_magic_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.reachops-backup"
            path.write_bytes(b"not a reachops backup")
            with self.assertRaises(BackupIntegrityError):
                preview_backup(path, "customer-password")

    def test_restore_rejects_unsafe_manifest_paths(self) -> None:
        with tempfile.TemporaryDirectory() as source, tempfile.TemporaryDirectory() as output_dir, tempfile.TemporaryDirectory() as target:
            self._runtime_with_data(source)
            backup_path = Path(output_dir) / "customer-data.reachops-backup"
            write_encrypted_backup(source, backup_path, "customer-password")
            from ReachOps.security import backup as backup_module

            plain, _header = backup_module._decrypt_backup(backup_path, "customer-password")
            with zipfile.ZipFile(io.BytesIO(plain), "r") as archive:
                manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
            data = b"escape"
            manifest["files"] = [{"path": "../escape.txt", "category": "non_secret_config", "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}]
            tampered_buffer = io.BytesIO()
            with zipfile.ZipFile(tampered_buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("manifest.json", json.dumps(manifest))
                archive.writestr("../escape.txt", data)
            tampered_plain = tampered_buffer.getvalue()
            salt = b"1" * 16
            nonce = b"2" * 16
            enc_key, mac_key = backup_module._derive_keys("customer-password", salt)
            header = {
                "schema_version": BACKUP_SCHEMA_VERSION,
                "format": "reachops.encrypted_backup.v1",
                "kdf": "pbkdf2_hmac_sha256",
                "iterations": backup_module.PBKDF2_ITERATIONS,
                "salt": base64.b64encode(salt).decode("ascii"),
                "nonce": base64.b64encode(nonce).decode("ascii"),
                "cipher": "hmac_sha256_stream",
                "mac": "hmac_sha256",
            }
            header_bytes = backup_module._json_bytes(header)
            ciphertext = backup_module._xor(tampered_plain, backup_module._keystream(enc_key, nonce, len(tampered_plain)))
            tag = hmac.new(mac_key, header_bytes + ciphertext, hashlib.sha256).digest()
            bad_path = Path(output_dir) / "unsafe.reachops-backup"
            bad_path.write_bytes(backup_module.BACKUP_MAGIC + len(header_bytes).to_bytes(4, "big") + header_bytes + ciphertext + tag)

            with self.assertRaises(BackupIntegrityError):
                restore_backup(bad_path, "customer-password", target)


if __name__ == "__main__":
    unittest.main()
