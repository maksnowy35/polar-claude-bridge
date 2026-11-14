"""Local MCP server for Claude Desktop.

Answers from the database and the generated context files, never from the raw Polar API,
so one question costs a few hundred tokens instead of a JSON dump.

Run: python -m healthctx.mcp_server   (stdio transport, see README for the Desktop config)
"""
import csv
import io
import logging
import re
import sys
from datetime import date, timedelta

from . import repository as repo
from .columns import DAILY_COLS, DAILY_DB_NAMES, SESSION_COLS, SESSION_DB_NAMES
from .config import Settings
from .db import Database
from .pipeline import build_context

logger = logging.getLogger(__name__)

MAX_DAYS = 60
MAX_SESSIONS = 100
JOURNAL_TYPES = {"supp", "med", "symptom", "mood", "energy", "stress", "alcohol", "caffeine",
                 "illness", "rpe", "weight", "note"}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _parse_date(value):
    if not DATE_RE.match(value or ""):
        raise ValueError(f"expected YYYY-MM-DD, got {value!r}")
    return date.fromisoformat(value)


def _as_csv(columns, rows):
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(columns)
    for row in rows:
        writer.writerow(["" if v is None else (v.isoformat() if isinstance(v, date) else v) for v in row])
    return buf.getvalue()


class HealthTools:
    def __init__(self, settings):
        self.settings = settings

    def _connect(self):
        # A new connection per call: Neon suspends an idle compute and drops its connections,
        # so a connection kept open by a desktop app for hours would be dead on the next question.
        return Database(self.settings.database_url)

    def get_status(self):
        path = self.settings.context_dir / "status.md"
        if not path.exists():
            return "status.md does not exist yet, run: python -m healthctx run"
        return path.read_text(encoding="utf-8")

    def get_day(self, day):
        _parse_date(day)
        path = self.settings.context_dir / "days" / f"day_{day}.md"
        if not path.exists():
            return f"no data for {day}"
        return path.read_text(encoding="utf-8")

    def get_days(self, date_from, date_to, columns=None):
        start, end = _parse_date(date_from), _parse_date(date_to)
        if start > end:
            start, end = end, start
        note = ""
        if (end - start).days >= MAX_DAYS:
            start = end - timedelta(days=MAX_DAYS - 1)
            note = f"# range cut to the last {MAX_DAYS} days\n"

        wanted = [c.strip() for c in (columns or "").split(",") if c.strip()] or DAILY_COLS
        unknown = [c for c in wanted if c not in DAILY_COLS]
        if unknown:
            return f"unknown columns: {', '.join(unknown)}. Available: {', '.join(DAILY_COLS)}"
        if "date" not in wanted:
            wanted = ["date"] + wanted

        db_columns = ", ".join(DAILY_DB_NAMES.get(c, c) for c in wanted)
        db = self._connect()
        try:
            rows = db.execute(f"SELECT {db_columns} FROM daily_metrics WHERE day BETWEEN ? AND ? ORDER BY day",
                              (start.isoformat(), end.isoformat())).fetchall()
        finally:
            db.close()
        return note + _as_csv(wanted, rows)

    def get_sessions(self, date_from, date_to):
        start, end = sorted((_parse_date(date_from), _parse_date(date_to)))
        db_columns = ", ".join(SESSION_DB_NAMES.get(c, c) for c in SESSION_COLS)
        db = self._connect()
        try:
            rows = db.execute(f"SELECT {db_columns} FROM training_sessions WHERE day BETWEEN ? AND ? "
                              f"ORDER BY day, start_time LIMIT {MAX_SESSIONS}",
                              (start.isoformat(), end.isoformat())).fetchall()
        finally:
            db.close()
        return _as_csv(SESSION_COLS, rows)

    def add_journal_entry(self, day, time="", entry_type="note", item="", value="", unit="", note=""):
        _parse_date(day)
        if time and not TIME_RE.match(time):
            return f"time must be HH:MM, got {time!r}"
        if entry_type not in JOURNAL_TYPES:
            return f"unknown type {entry_type!r}. Allowed: {', '.join(sorted(JOURNAL_TYPES))}"

        db = self._connect()
        try:
            repo.save_journal_entries(db, [{"date": day, "time": time, "type": entry_type, "item": item,
                                            "value": value, "unit": unit, "note": note}])
            db.commit()
            # Rebuild right away so get_status/get_day already show the entry; incremental,
            # so it only touches days from this one on.
            build_context(db, self.settings)
        finally:
            db.close()
        return f"saved {entry_type} {item} for {day}; context files rebuilt locally (push-context sends them to Drive)"


def create_server(settings=None):
    from mcp.server.mcpserver import MCPServer

    tools = HealthTools(settings or Settings.from_env())
    server = MCPServer(
        "polar-claude-bridge",
        instructions="Health data of one person from a Polar watch, journal and medical notes. "
                     "Start with get_status, then get_day or get_days only for what the question needs.",
    )

    @server.tool()
    def get_status() -> str:
        """Baselines, 7 vs 28 day trends, last 14 days, flags, journal and current meds (~1.5k tokens). Read first."""
        return tools.get_status()

    @server.tool()
    def get_day(day: str) -> str:
        """One day in detail: night (hypnogram, HR, HRV, breathing, skin temp), evening before, trainings. day=YYYY-MM-DD."""
        return tools.get_day(day)

    @server.tool()
    def get_days(date_from: str, date_to: str, columns: str = "") -> str:
        """Daily rows as CSV, max 60 days. columns: comma separated names from INDEX.md, empty = all."""
        return tools.get_days(date_from, date_to, columns)

    @server.tool()
    def get_sessions(date_from: str, date_to: str) -> str:
        """Trainings as CSV: sport, duration, HR, minutes in zones Z1-Z5, cardio load."""
        return tools.get_sessions(date_from, date_to)

    @server.tool()
    def add_journal_entry(day: str, entry_type: str, item: str = "", value: str = "", unit: str = "",
                          time: str = "", note: str = "") -> str:
        """Log supplement, med, symptom, mood/energy/stress (1-10), alcohol, caffeine, illness, rpe, weight or note."""
        return tools.add_journal_entry(day, time, entry_type, item, value, unit, note)

    return server


def main():
    # stdout belongs to the MCP protocol on stdio, any print there breaks the session.
    logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    create_server().run()


if __name__ == "__main__":
    main()
