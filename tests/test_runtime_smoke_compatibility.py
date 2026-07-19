import tempfile
import unittest
from unittest.mock import patch

from tools.reachops_web_panel_runtime_smoke import temporary_directory_ignoring_cleanup_errors


class RuntimeSmokeCompatibilityTests(unittest.TestCase):
    def test_temporary_directory_falls_back_when_ignore_cleanup_errors_is_unsupported(self):
        calls = []
        real_temporary_directory = tempfile.TemporaryDirectory

        def fake_temporary_directory(*args, **kwargs):
            calls.append(dict(kwargs))
            if kwargs.get("ignore_cleanup_errors"):
                raise TypeError("__init__() got an unexpected keyword argument 'ignore_cleanup_errors'")
            return real_temporary_directory(*args, **kwargs)

        with patch("tools.reachops_web_panel_runtime_smoke.tempfile.TemporaryDirectory", side_effect=fake_temporary_directory):
            with temporary_directory_ignoring_cleanup_errors(prefix="reachops-compat-") as tmp:
                self.assertTrue(tmp)

        self.assertEqual(calls[0]["ignore_cleanup_errors"], True)
        self.assertNotIn("ignore_cleanup_errors", calls[1])


if __name__ == "__main__":
    unittest.main()
