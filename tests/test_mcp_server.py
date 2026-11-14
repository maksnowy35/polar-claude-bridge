import asyncio
import importlib.util
import shutil
import tempfile
import unittest
from pathlib import Path

from healthctx.config import Settings
from healthctx.db import Database
from healthctx.mcp_server import MAX_DAYS, HealthTools, create_server
from healthctx.pipeline import build_context, import_journal_csv, import_raw_files
from tests.make_fixtures import generate


class HealthToolsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="healthctx-mcp-"))
        generate(str(cls.tmp / "fixtures"))
        cls.settings = Settings(
            database_url=f"sqlite:///{cls.tmp / 'health.db'}",
            raw_dir=cls.tmp / "fixtures" / "raw",
            context_dir=cls.tmp / "context",
            journal_csv=cls.tmp / "fixtures" / "journal" / "log.csv",
            medical_dir=cls.tmp / "fixtures" / "medical",
            sports_file=cls.tmp / "missing-sports.json",
        )
        db = Database(cls.settings.database_url)
        db.migrate()
        import_raw_files(db, cls.settings.raw_dir)
        import_journal_csv(db, cls.settings.journal_csv)
        build_context(db, cls.settings)
        db.close()
        cls.tools = HealthTools(cls.settings)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_status_and_day(self):
        self.assertIn("Health status", self.tools.get_status())
        self.assertIn("Nightly Recharge", self.tools.get_day("2026-10-16"))
        self.assertEqual(self.tools.get_day("2020-01-01"), "no data for 2020-01-01")

    def test_bad_date_is_rejected(self):
        with self.assertRaises(ValueError):
            self.tools.get_day("16.10.2026")

    def test_get_days_selected_columns(self):
        csv_text = self.tools.get_days("2026-10-07", "2026-10-16", "sleep_h,rhr,flags")
        lines = csv_text.strip().splitlines()

        self.assertEqual(lines[0], "date,sleep_h,rhr,flags")
        self.assertEqual(len(lines), 11)
        self.assertIn("MULTI", lines[-1])

    def test_get_days_limits_range_and_columns(self):
        self.assertIn(f"last {MAX_DAYS} days", self.tools.get_days("2025-01-01", "2026-10-16", "steps"))
        self.assertIn("unknown columns: hr_raw", self.tools.get_days("2026-10-01", "2026-10-02", "hr_raw"))

    def test_get_sessions(self):
        lines = self.tools.get_sessions("2026-10-15", "2026-10-15").strip().splitlines()

        self.assertEqual(lines[0].split(",")[:4], ["date", "start", "end", "sport"])
        self.assertIn("tennis", lines[1])

    def test_journal_entry_lands_in_daily_metrics(self):
        result = self.tools.add_journal_entry("2026-10-15", "21:00", "alcohol", "wino", "2")

        self.assertTrue(result.startswith("saved"))
        row = self.tools.get_days("2026-10-15", "2026-10-15", "alc").strip().splitlines()[1]
        self.assertEqual(row, "2026-10-15,2.0")

    def test_journal_entry_validation(self):
        self.assertIn("unknown type", self.tools.add_journal_entry("2026-10-15", "", "party"))
        self.assertIn("HH:MM", self.tools.add_journal_entry("2026-10-15", "9pm", "mood", "", "6"))


@unittest.skipUnless(importlib.util.find_spec("mcp"), "mcp package not installed")
class ServerTest(unittest.TestCase):
    def test_tools_are_registered(self):
        server = create_server(Settings(
            database_url="sqlite:///:memory:", raw_dir=Path("."), context_dir=Path("."),
            journal_csv=Path("x.csv"), medical_dir=Path("."), sports_file=Path("x.json"),
        ))

        names = {tool.name for tool in asyncio.run(server.list_tools())}

        self.assertEqual(names, {"get_status", "get_day", "get_days", "get_sessions", "add_journal_entry"})


if __name__ == "__main__":
    unittest.main()
