import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from ReachOps import launcher


class ReachOpsLauncherTests(unittest.TestCase):
    def test_default_entry_starts_unified_web_client(self):
        with patch.object(launcher, "_launch_web_client", return_value=7) as web_client, patch.object(
            launcher, "_launch_legacy_tk_client", return_value=3
        ) as legacy_client:
            self.assertEqual(launcher.main([]), 7)
        web_client.assert_called_once_with()
        legacy_client.assert_not_called()

    def test_legacy_tk_flag_remains_native_compatibility_alias(self):
        with patch.object(launcher, "_launch_web_client", return_value=7) as web_client, patch.object(
            launcher, "_launch_legacy_tk_client", return_value=3
        ) as legacy_client:
            self.assertEqual(launcher.main(["--legacy-tk"]), 3)
        web_client.assert_not_called()
        legacy_client.assert_called_once_with()

    def test_legacy_tk_env_remains_diagnostic_alias(self):
        with patch.object(launcher, "_launch_web_client", return_value=7) as web_client, patch.object(
            launcher, "_launch_legacy_tk_client", return_value=3
        ) as legacy_client, patch.dict("os.environ", {"REACHOPS_LEGACY_TK": "1"}, clear=False):
            self.assertEqual(launcher.main([]), 3)
        web_client.assert_not_called()
        legacy_client.assert_called_once_with()

    def test_help_does_not_start_any_client(self):
        with patch.object(launcher, "_launch_web_client", return_value=7) as web_client, patch.object(
            launcher, "_launch_legacy_tk_client", return_value=3
        ) as legacy_client, patch("sys.stdout", new_callable=StringIO) as stdout:
            self.assertEqual(launcher.main(["--help"]), 0)
        web_client.assert_not_called()
        legacy_client.assert_not_called()
        self.assertIn("Start the unified Web console", stdout.getvalue())
        self.assertIn("Start the legacy Tk diagnostic client", stdout.getvalue())

    def test_unknown_argument_does_not_start_any_client(self):
        with patch.object(launcher, "_launch_web_client", return_value=7) as web_client, patch.object(
            launcher, "_launch_legacy_tk_client", return_value=3
        ) as legacy_client, patch("sys.stderr", new_callable=StringIO) as stderr:
            self.assertEqual(launcher.main(["--bad-option"]), 2)
        web_client.assert_not_called()
        legacy_client.assert_not_called()
        self.assertIn("未知启动参数", stderr.getvalue())

    def test_missing_web_launcher_does_not_silently_fallback_to_legacy_tk(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(launcher, "_project_root", return_value=root), patch.object(
                launcher, "_launch_legacy_tk_client", return_value=0
            ) as legacy_client, patch("sys.stderr", new_callable=StringIO) as stderr:
                self.assertEqual(launcher._launch_web_client(), 2)
        legacy_client.assert_not_called()
        self.assertIn("Web 控制台启动器不存在", stderr.getvalue())
        self.assertIn("tools/reachops_mac_self_check.py", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
