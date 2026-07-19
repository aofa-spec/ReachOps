import json
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path

from ReachOps.runtime_paths import RuntimePaths
from ReachOps.support_bundle import create_support_bundle, preview_support_bundle


class ReachOpsSupportBundleTests(unittest.TestCase):
    def _runtime_with_sensitive_files(self, root: str) -> RuntimePaths:
        paths = RuntimePaths.build(root).ensure_dirs()
        db_path = Path(paths.db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(db_path) as conn:
            conn.execute("CREATE TABLE leads (username TEXT, comment TEXT)")
            conn.execute("INSERT INTO leads VALUES (?, ?)", ("@realbuyer", "Need this serum today"))
        Path(paths.config_dir, "reachops_activation_status.json").write_text(
            json.dumps({"license_key": "real-license-secret"}),
            encoding="utf-8",
        )
        Path(paths.logs_dir, "runtime.log").write_text(
            "profile=@realbuyer target=https://www.tiktok.com/@creator/video/123 "
            "api_key=sk-real-secret status=blocked\n",
            encoding="utf-8",
        )
        Path(paths.reports_dir, "latest_status.json").write_text(
            json.dumps(
                {
                    "status": "blocked",
                    "username": "@realbuyer",
                    "comment_text": "Need this serum today",
                    "target_url": "https://www.tiktok.com/@creator/video/123",
                    "license_key": "real-license-secret",
                    "proxy_password": "proxy-secret",
                    "safe_count": 1,
                }
            ),
            encoding="utf-8",
        )
        evidence_dir = Path(paths.reports_dir, "evidence")
        evidence_dir.mkdir(parents=True, exist_ok=True)
        Path(evidence_dir, "screenshot.png").write_bytes(b"raw screenshot")
        Path(evidence_dir, "raw_dom.html").write_text("<html>@realbuyer</html>", encoding="utf-8")
        Path(paths.data_dir, "cookies.sqlite").write_bytes(b"cookie-db")
        Path(paths.config_dir, "proxy_secret.txt").write_text("proxy-secret", encoding="utf-8")
        return paths

    def test_preview_blocks_packaging_until_customer_confirms_share(self):
        with tempfile.TemporaryDirectory() as td:
            paths = self._runtime_with_sensitive_files(td)

            preview = preview_support_bundle(paths)
            blocked = create_support_bundle(paths, Path(td) / "support.zip")

            self.assertEqual(preview["status"], "preview")
            self.assertTrue(preview["explicit_customer_share_required"])
            self.assertTrue(preview["telemetry_default_off"])
            self.assertTrue(preview["redaction_applied_before_packaging"])
            self.assertGreaterEqual(preview["file_count"], 2)
            self.assertEqual(blocked["status"], "blocked")
            self.assertEqual(blocked["reason"], "customer_share_confirmation_required")

    def test_support_bundle_redacts_text_and_excludes_forbidden_customer_artifacts(self):
        with tempfile.TemporaryDirectory() as td:
            paths = self._runtime_with_sensitive_files(td)
            output = Path(td) / "reachops-support.zip"

            created = create_support_bundle(paths, output, customer_confirmed_share=True)

            self.assertEqual(created["status"], "created")
            self.assertTrue(created["manifest"]["redaction_applied_before_packaging"])
            self.assertTrue(created["manifest"]["exclusions"]["sqlite_databases"])
            self.assertTrue(created["manifest"]["exclusions"]["tiktok_cookies_sessions"])
            with zipfile.ZipFile(output, "r") as archive:
                names = set(archive.namelist())
                combined = b"\n".join(archive.read(name) for name in archive.namelist())
            self.assertIn("manifest.json", names)
            self.assertIn("logs/runtime.log", names)
            self.assertIn("data/growth_intelligence/reports/latest_status.json", names)
            self.assertFalse(any("growth_intelligence.db" in name for name in names))
            self.assertFalse(any("screenshot" in name for name in names))
            self.assertFalse(any("raw_dom" in name for name in names))
            self.assertFalse(any("cookie" in name for name in names))
            self.assertFalse(any("activation_status" in name for name in names))
            self.assertFalse(any("proxy_secret" in name for name in names))
            self.assertNotIn(b"@realbuyer", combined)
            self.assertNotIn(b"Need this serum today", combined)
            self.assertNotIn(b"https://www.tiktok.com/@creator/video/123", combined)
            self.assertNotIn(b"sk-real-secret", combined)
            self.assertNotIn(b"real-license-secret", combined)
            self.assertNotIn(b"proxy-secret", combined)
            self.assertIn(b"***redacted***", combined)


if __name__ == "__main__":
    unittest.main()
