import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from ReachOps.backup import create_reachops_backup, inspect_reachops_backup, restore_reachops_backup
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


if __name__ == "__main__":
    unittest.main()
