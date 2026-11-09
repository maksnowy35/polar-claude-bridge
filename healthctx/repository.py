import json
import logging
from datetime import date

from .columns import DAILY_COLS, DAILY_DB_NAMES, SESSION_COLS, SESSION_DB_NAMES

logger = logging.getLogger(__name__)


def _iso(value):
    return value.isoformat() if isinstance(value, date) else value


def _upsert(db, table, key, columns, rows):
    col_list = ", ".join(columns)
    placeholders = ", ".join("?" for _ in columns)
    updates = ", ".join(f"{c} = excluded.{c}" for c in columns if c != key)
    db.executemany(
        f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) "
        f"ON CONFLICT ({key}) DO UPDATE SET {updates}",
        rows,
    )


# ----------------------------------------------------------------------------- raw files and facts

def fact_key(fact):
    if fact["k"] == "session":
        return f"{fact['date']} {fact['start']}"
    if fact["k"] == "sleep":
        return f"{fact['date']} {fact['on']}"          # naps share the date with the main night
    return fact.get("date") or "current"


def start_import_run(db):
    run = int(db.get_meta("import_run", 0)) + 1
    db.set_meta("import_run", run)
    return run


def is_file_imported(db, path, sha1):
    return db.fetch_value("SELECT 1 FROM raw_files WHERE path = ? AND sha1 = ?", (path, sha1)) is not None


def save_file_facts(db, path, sha1, size_bytes, facts, run):
    payload_param = "CAST(? AS JSONB)" if db.dialect == "postgres" else "?"
    rows = []
    for fact in facts:
        if fact["k"] == "skip":
            continue
        payload = json.dumps(fact, sort_keys=True, separators=(",", ":"))
        rows.append((fact["k"], fact_key(fact), fact.get("src") or "export", fact.get("date"), payload, run))

    # Only touch import_run when the payload really changed, otherwise a re-export of the
    # same month would mark the whole month dirty and the incremental build gains nothing.
    db.executemany(
        "INSERT INTO facts (kind, fact_key, source, fact_date, payload, import_run) "
        f"VALUES (?, ?, ?, ?, {payload_param}, ?) "
        "ON CONFLICT (kind, fact_key, source) DO UPDATE SET "
        "payload = excluded.payload, fact_date = excluded.fact_date, import_run = excluded.import_run "
        "WHERE facts.payload <> excluded.payload",
        rows,
    )
    _upsert(db, "raw_files", "path", ["path", "sha1", "size_bytes", "fact_count", "import_run"],
            [(path, sha1, size_bytes, len(rows), run)])
    return len(rows)


def load_facts(db, since=None):
    if since is None:
        records = db.fetch_all("SELECT payload FROM facts")
    else:
        records = db.fetch_all("SELECT payload FROM facts WHERE fact_date IS NULL OR fact_date >= ?", (since,))
    return [r["payload"] if isinstance(r["payload"], dict) else json.loads(r["payload"]) for r in records]


def fact_coverage(db):
    records = db.fetch_all(
        "SELECT kind, min(fact_date) AS first_day, max(fact_date) AS last_day, "
        "count(DISTINCT fact_date) AS days FROM facts WHERE fact_date IS NOT NULL GROUP BY kind"
    )
    return {r["kind"]: (_iso(r["first_day"]), _iso(r["last_day"]), r["days"]) for r in records}


def latest_day(db):
    candidates = [
        db.fetch_value("SELECT max(fact_date) FROM facts"),
        db.fetch_value("SELECT max(day) FROM journal_entries"),
    ]
    candidates = [_iso(c) for c in candidates if c is not None]
    return max(candidates) if candidates else None


# ----------------------------------------------------------------------------- incremental build state

def dirty_since(db):
    """Earliest date touched since the last build, or None when nothing changed."""
    built_run = int(db.get_meta("built_run", 0))
    built_journal_id = int(db.get_meta("built_journal_id", 0))
    candidates = [
        db.fetch_value("SELECT min(fact_date) FROM facts WHERE import_run > ?", (built_run,)),
        db.fetch_value("SELECT min(day) FROM journal_entries WHERE id > ?", (built_journal_id,)),
    ]
    candidates = [_iso(c) for c in candidates if c is not None]
    return min(candidates) if candidates else None


def was_ever_built(db):
    return int(db.get_meta("built_run", 0)) > 0


def mark_built(db):
    db.set_meta("built_run", db.fetch_value("SELECT coalesce(max(import_run), 0) FROM facts") or 1)
    db.set_meta("built_journal_id", db.fetch_value("SELECT coalesce(max(id), 0) FROM journal_entries"))


# ----------------------------------------------------------------------------- derived tables

def save_daily_metrics(db, rows):
    columns = [DAILY_DB_NAMES.get(c, c) for c in DAILY_COLS]
    values = [tuple(r.get(c) if c != "flags" else (r.get("flags") or "") for c in DAILY_COLS) for r in rows]
    _upsert(db, "daily_metrics", "day", columns, values)


def load_daily_metrics(db):
    back = {v: k for k, v in DAILY_DB_NAMES.items()}
    records = db.fetch_all("SELECT * FROM daily_metrics ORDER BY day")
    return [{back.get(k, k): _iso(v) for k, v in r.items()} for r in records]


def count_days(db):
    return db.fetch_value("SELECT count(*) FROM daily_metrics") or 0


def save_sessions(db, sessions):
    columns = ["session_key"] + [SESSION_DB_NAMES.get(c, c) for c in SESSION_COLS]
    values = []
    for s in sessions:
        zones = "/".join(str(z or 0) for z in (s.get("zones") or []))
        row = [f"{s['date']} {s['start']}"]
        row += [zones if c == "zones_min" else s.get(c) for c in SESSION_COLS]
        values.append(tuple(row))
    _upsert(db, "training_sessions", "session_key", columns, values)


def count_sessions(db):
    return db.fetch_value("SELECT count(*) FROM training_sessions") or 0


# ----------------------------------------------------------------------------- journal

def save_journal_entries(db, entries):
    columns = ["day", "entry_time", "entry_type", "item", "value", "unit", "note"]
    values = [
        (e["date"], e.get("time") or "", e["type"], e.get("item") or "", e.get("value") or None,
         e.get("unit") or None, e.get("note") or None)
        for e in entries
    ]
    db.executemany(
        f"INSERT INTO journal_entries ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)}) "
        "ON CONFLICT (day, entry_time, entry_type, item) DO UPDATE SET "
        "value = excluded.value, unit = excluded.unit, note = excluded.note",
        values,
    )
    return len(values)


def load_journal_entries(db):
    records = db.fetch_all(
        "SELECT day, entry_time, entry_type, item, value, unit, note FROM journal_entries ORDER BY day, entry_time"
    )
    return [
        {"date": _iso(r["day"]), "time": r["entry_time"], "type": r["entry_type"], "item": r["item"],
         "value": r["value"] or "", "unit": r["unit"] or "", "note": r["note"] or ""}
        for r in records
    ]
