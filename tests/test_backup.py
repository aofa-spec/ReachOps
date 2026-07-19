import io
import json
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path

from ReachOps.backup import create_reachops_backup, inspect_reachops_backup, restore_reachops_backup, validate_backup_manifest
from ReachOps.runtime_paths import RuntimePaths


class ReachOpsBackupTests(unittest.TestCase):
    def _runtime_with_files(self, root: str) -> RuntimePaths:
        paths = RuntimePaths.build(root).ensure_dirs()
        db_path = Path(paths.db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(db_path) as conn:
            conn.execute("CREATE TABLE campaigns (id TEXT PRIMARY KEY, name TEXT)")
            conn.execute("INSERT INTO campaigns VALUES (?, ?)", ("campaign-1", "Serum"))
        Path(paths.config_dir, "operator_preferences.json").write_text(json.dumps({"language": "zh-CN"}), encoding="utf-8")
        Path(paths.config_dir, "reachops_activation_status.json").write_text("real activation secret", encoding="utf-8")
        Path(paths.config_dir, "proxy_secret.json").write_text("proxy-secret", encoding="utf-8")
        evidence_dir = Path(paths.reports_dir, "evidence")
        evidence_dir.mkdir(parents=True, exist_ok=True)
        Path(evidence_dir, "raw_dom.html").write_text("<html>raw customer DOM</html>", encoding="utf-8")
        Path(evidence_dir, "screenshot.png").write_bytes(b"fake screenshot")
        Path(paths.data_dir, "cookies.sqlite").write_bytes(b"cookie-db")
        return paths

    def test_encrypted_backup_excludes_secrets_and_restores_sqlite_and_config(self):
        with tempfile.TemporaryDirectory() as source, tempfile.TemporaryDirectory() as target:
            source_paths = self._runtime_with_files(source)
            backup_path = Path(source) / "reachops-test.reachops-backup"

            created = create_reachops_backup(source_paths, backup_path, "correct horse battery staple")
            inspected = inspect_reachops_backup(backup_path, "correct horse battery staple")
            restored_preview = restore_reachops_backup(backup_path, "correct horse battery staple", RuntimePaths.build(target), preview=True)

            self.assertEqual(created["status"], "created")
            self.assertTrue(created["encrypted"])
            self.assertTrue(created["authenticated"])
            self.assertEqual(created["forbidden_entries"], [])
            self.assertNotIn(b"Serum", backup_path.read_bytes())
            self.assertNotIn(b"proxy-secret", backup_path.read_bytes())
            self.assertEqual(inspected["status"], "valid")
            self.assertTrue(inspected["validation"]["passed"])
            archived_paths = {row["path"] for row in inspected["manifest"]["files"]}
            self.assertIn("data/growth_intelligence/growth_intelligence.db", archived_paths)
            self.assertIn("config/operator_preferences.json", archived_paths)
            self.assertNotIn("config/reachops_activation_status.json", archived_paths)
            self.assertFalse(any("secret" in path or "cookie" in path or "screenshot" in path or "raw_dom" in path for path in archived_paths))
            self.assertEqual(restored_preview["status"], "preview")
            self.assertFalse(Path(target, "data", "growth_intelligence", "growth_intelligence.db").exists())
            restored = restore_reachops_backup(backup_path, "correct horse battery staple", RuntimePaths.build(target), preview=False)
            self.assertEqual(restored["status"], "restored")
            restored_db = Path(target, "data", "growth_intelligence", "growth_intelligence.db")
            with sqlite3.connect(restored_db) as conn:
                self.assertEqual(conn.execute("SELECT name FROM campaigns WHERE id='campaign-1'").fetchone()[0], "Serum")
            self.assertEqual(json.loads(Path(target, "config", "operator_preferences.json").read_text(encoding="utf-8"))["language"], "zh-CN")
            self.assertFalse(Path(target, "config", "reachops_activation_status.json").exists())

    def test_wrong_password_and_corrupted_archive_are_rejected(self):
        with tempfile.TemporaryDirectory() as source:
            source_paths = self._runtime_with_files(source)
            backup_path = Path(source) / "reachops-test.reachops-backup"
            create_reachops_backup(source_paths, backup_path, "correct horse battery staple")

            with self.assertRaises(ValueError):
                inspect_reachops_backup(backup_path, "wrong password")

            data = bytearray(backup_path.read_bytes())
            data[-10] ^= 0x01
            backup_path.write_bytes(bytes(data))
            with self.assertRaises(ValueError):
                inspect_reachops_backup(backup_path, "correct horse battery staple")

    def test_short_password_is_rejected(self):
        with tempfile.TemporaryDirectory() as source:
            paths = RuntimePaths.build(source).ensure_dirs()
            with self.assertRaises(ValueError):
                create_reachops_backup(paths, Path(source) / "bad.reachops-backup", "short")

    def test_manifest_validation_requires_encryption_contract_and_safe_paths(self):
        manifest = {
            "schema_version": "reachops.backup.v1",
            "encryption": {
                "kdf": "pbkdf2_hmac_sha256",
                "iterations": 1,
                "cipher": "plaintext",
                "mac": "",
            },
            "exclusions": {
                "windows_credential_manager_secrets": True,
                "activation_status": True,
                "tiktok_cookies_sessions": True,
                "raw_screenshots_dom": True,
                "proxy_credentials": True,
            },
            "files": [
                {"path": "../escape.sqlite3", "sha256": "x", "size": 1},
                {"path": "config/operator_preferences.json", "sha256": "x", "size": 1},
                {"path": "config/operator_preferences.json", "sha256": "x", "size": 1},
            ],
        }

        validation = validate_backup_manifest(manifest)

        self.assertFalse(validation["passed"])
        self.assertIn("unsupported_encryption:iterations", validation["errors"])
        self.assertIn("unsupported_encryption:cipher", validation["errors"])
        self.assertIn("unsupported_encryption:mac", validation["errors"])
        self.assertIn("unsafe_backup_path:../escape.sqlite3", validation["errors"])
        self.assertIn("duplicate_backup_path:config/operator_preferences.json", validation["errors"])

    def test_restore_preview_blocks_unsafe_manifest_paths_without_writing(self):
        with tempfile.TemporaryDirectory() as source, tempfile.TemporaryDirectory() as target:
            source_paths = self._runtime_with_files(source)
            backup_path = Path(source) / "reachops-test.reachops-backup"
            create_reachops_backup(source_paths, backup_path, "correct horse battery staple")

            plaintext = _decrypt_test_backup(backup_path, "correct horse battery staple")
            rewritten = io.BytesIO()
            with zipfile.ZipFile(io.BytesIO(plaintext), "r") as original, zipfile.ZipFile(rewritten, "w", compression=zipfile.ZIP_DEFLATED) as patched:
                manifest = json.loads(original.read("manifest.json").decode("utf-8"))
                manifest["files"].append({"path": "../escape.sqlite3", "sha256": "0", "size": 0})
                patched.writestr("manifest.json", json.dumps(manifest))
                for name in original.namelist():
                    if name != "manifest.json":
                        patched.writestr(name, original.read(name))
            tampered_path = Path(source) / "unsafe.reachops-backup"
            _write_test_backup(tampered_path, "correct horse battery staple", rewritten.getvalue())

            preview = restore_reachops_backup(tampered_path, "correct horse battery staple", RuntimePaths.build(target), preview=True)

            self.assertEqual(preview["status"], "blocked")
            self.assertIn("unsafe_backup_path:../escape.sqlite3", preview["validation"]["errors"])
            self.assertFalse(Path(target, "data", "growth_intelligence", "growth_intelligence.db").exists())


def _decrypt_test_backup(path: Path, password: str) -> bytes:
    from ReachOps import backup as backup_module

    data = path.read_bytes()
    salt_start = len(backup_module.BACKUP_MAGIC)
    salt = data[salt_start : salt_start + backup_module.SALT_BYTES]
    nonce = data[salt_start + backup_module.SALT_BYTES : salt_start + backup_module.SALT_BYTES + backup_module.NONCE_BYTES]
    ciphertext = data[salt_start + backup_module.SALT_BYTES + backup_module.NONCE_BYTES : -backup_module.TAG_BYTES]
    return backup_module._xor_bytes(
        ciphertext,
        backup_module._keystream(backup_module._derive_key(password, salt, b"enc"), nonce, len(ciphertext)),
    )


def _write_test_backup(path: Path, password: str, plaintext: bytes) -> None:
    import hashlib
    import hmac
    import os

    from ReachOps import backup as backup_module

    salt = os.urandom(backup_module.SALT_BYTES)
    nonce = os.urandom(backup_module.NONCE_BYTES)
    header = backup_module.BACKUP_MAGIC + salt + nonce
    ciphertext = backup_module._xor_bytes(
        plaintext,
        backup_module._keystream(backup_module._derive_key(password, salt, b"enc"), nonce, len(plaintext)),
    )
    tag = hmac.new(backup_module._derive_key(password, salt, b"mac"), header + ciphertext, hashlib.sha256).digest()
    path.write_bytes(header + ciphertext + tag)


if __name__ == "__main__":
    unittest.main()
