import os
import shutil
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlparse

from healthctx.config import Settings
from healthctx.db import Database
from healthctx.pipeline import build_context, import_journal_csv, import_raw_files
from tests.make_fixtures import generate


class PipelineTestMixin:
    """Same scenario for every backend: 35 synthetic days, sick night on the last one."""

    def make_database_url(self):
        raise NotImplementedError

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="healthctx-"))
        generate(str(self.tmp / "fixtures"))
        self.settings = Settings(
            database_url=self.make_database_url(),
            raw_dir=self.tmp / "fixtures" / "raw",
            context_dir=self.tmp / "context",
            journal_csv=self.tmp / "fixtures" / "journal" / "log.csv",
            medical_dir=self.tmp / "fixtures" / "medical",
            sports_file=self.tmp / "missing-sports.json",
        )
        self.db = Database(self.settings.database_url)
        self.db.migrate()

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_pipeline(self, full=False):
        import_raw_files(self.db, self.settings.raw_dir)
        import_journal_csv(self.db, self.settings.journal_csv)
        return build_context(self.db, self.settings, full=full)

    def test_full_build_flags_the_sick_night(self):
        changed = self.run_pipeline()

        self.assertIn("status.md", changed)
        status = (self.settings.context_dir / "status.md").read_text(encoding="utf-8")
        self.assertIn("MULTI", status)
        self.assertIn("LATE_HARD(tennis", status)
        self.assertEqual(self.db.fetch_value("SELECT count(*) FROM daily_metrics"), 35)
        flags = self.db.fetch_value("SELECT flags FROM daily_metrics WHERE day = ?", ("2026-10-16",))
        self.assertIn("RHR+", flags)

    def test_second_run_without_changes_does_nothing(self):
        self.run_pipeline()
        self.assertEqual(self.run_pipeline(), [])

    def test_new_journal_entry_rebuilds_only_from_its_day(self):
        self.run_pipeline()
        with open(self.settings.journal_csv, "a", encoding="utf-8") as f:
            f.write("2026-10-14,22:00,alcohol,piwo,2,,\n")

        changed = self.run_pipeline()

        day_files = sorted(c for c in changed if c.startswith("days/"))
        self.assertEqual(day_files[0], "days/day_2026-10-14.md")
        self.assertNotIn("days/day_2026-10-13.md", changed)
        self.assertEqual(self.db.fetch_value("SELECT alc FROM daily_metrics WHERE day = ?", ("2026-10-14",)), 2)


class SqlitePipelineTest(PipelineTestMixin, unittest.TestCase):
    def make_database_url(self):
        return f"sqlite:///{self.tmp / 'health.db'}"


@unittest.skipUnless(os.getenv("TEST_DATABASE_URL"), "TEST_DATABASE_URL not set")
class PostgresPipelineTest(PipelineTestMixin, unittest.TestCase):
    def make_database_url(self):
        url = os.environ["TEST_DATABASE_URL"]
        # The schema is dropped before every test, refuse anything that is not clearly a test database.
        if "test" not in urlparse(url).path:
            raise RuntimeError("TEST_DATABASE_URL must point to a database with 'test' in its name")
        db = Database(url)
        db.execute("DROP SCHEMA public CASCADE")
        db.execute("CREATE SCHEMA public")
        db.commit()
        db.close()
        return url


if __name__ == "__main__":
    unittest.main()
