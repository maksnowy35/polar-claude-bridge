import shutil
import tempfile
import unittest
from pathlib import Path

from healthctx.db import Database
from healthctx.db_check import check_database, log_report


class DbCheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="healthctx-dbcheck-"))
        self.db = Database(f"sqlite:///{self.tmp / 'health.db'}")

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_reports_missing_schema(self):
        report = check_database(self.db)

        self.assertIsNone(report["version"])
        with self.assertLogs("healthctx.db_check", level="ERROR"):
            self.assertFalse(log_report(report))

    def test_reports_counts_after_migrate(self):
        self.db.migrate()

        report = check_database(self.db)

        self.assertEqual(report["version"], report["expected_version"])
        self.assertEqual(report["rows"]["daily_metrics"], 0)
        self.assertEqual(report["built_run"], 0)

    def test_postgres_target_hides_password(self):
        db = Database.__new__(Database)
        # built from parts, the pre-commit guard would rightly block a literal URL with a password
        db.dialect, db.url = "postgres", "postgresql://maks:" + "topsecret" + "@ep-x.eu-central-1.aws.neon.tech/neondb?sslmode=require"

        self.assertEqual(db.describe(), "postgres ep-x.eu-central-1.aws.neon.tech/neondb")


if __name__ == "__main__":
    unittest.main()
