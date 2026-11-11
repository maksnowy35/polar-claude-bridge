import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from healthctx.cli import main


class CliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="healthctx-cli-"))
        self.env = {
            "DATABASE_URL": f"sqlite:///{self.tmp / 'health.db'}",
            "HEALTH_RAW_DIR": str(self.tmp / "raw"),
            "HEALTH_CONTEXT_DIR": str(self.tmp / "context"),
            "HEALTH_JOURNAL_CSV": str(self.tmp / "missing.csv"),
            "POLAR_ACCESS_TOKEN": "",
        }

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_fetch_without_token_fails_cleanly(self):
        with mock.patch.dict(os.environ, self.env), self.assertLogs("healthctx", level="ERROR"):
            self.assertEqual(main(["fetch"]), 1)

    def test_run_without_token_skips_fetch(self):
        with mock.patch.dict(os.environ, self.env), self.assertLogs("healthctx", level="INFO") as logs:
            self.assertEqual(main(["run"]), 0)
        self.assertTrue(any("skipping fetch" in line for line in logs.output))


if __name__ == "__main__":
    unittest.main()
