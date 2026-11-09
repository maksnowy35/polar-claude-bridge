import hashlib
import json
import logging
from datetime import timedelta
from pathlib import Path

from . import repository as repo
from .aggregate import build_rows, collect, latest_profile
from .journal import journal_by_day, load_journal
from .parsers import parse_file
from .render import (Writer, render_daily_csvs, render_day, render_index, render_monthly,
                     render_status)
from .util import d2s, s2d

logger = logging.getLogger(__name__)

# Status needs 60 days of rows and every row needs 28 days of history for its flags,
# so an incremental build loads this much context before the first changed day.
STATUS_DAYS = 60
HISTORY_DAYS = 40


def _sha1(path):
    digest = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def import_raw_files(db, raw_dir):
    raw_dir = Path(raw_dir)
    if not raw_dir.exists():
        logger.warning("raw dir %s does not exist, nothing to import", raw_dir)
        return 0

    run = repo.start_import_run(db)
    seen = parsed = facts_total = 0
    for path in sorted(raw_dir.rglob("*.json")):
        seen += 1
        rel_path = path.relative_to(raw_dir).as_posix()
        sha1 = _sha1(path)
        if repo.is_file_imported(db, rel_path, sha1):
            continue
        try:
            facts = parse_file(path)
        except (ValueError, KeyError, TypeError) as exc:
            # Not registered, so the file is retried on the next run after a parser fix.
            logger.warning("skipping %s: %s: %s", rel_path, type(exc).__name__, exc)
            continue
        facts_total += repo.save_file_facts(db, rel_path, sha1, path.stat().st_size, facts, run)
        db.commit()
        parsed += 1
        skipped = [f["why"] for f in facts if f["k"] == "skip"]
        if skipped:
            logger.debug("%s: skipped %s", rel_path, skipped)

    logger.info("raw import: %d files seen, %d parsed, %d facts stored", seen, parsed, facts_total)
    return parsed


def import_journal_csv(db, csv_path):
    entries = load_journal(csv_path)
    if not entries:
        logger.info("journal csv %s missing or empty", csv_path)
        return 0
    count = repo.save_journal_entries(db, entries)
    db.commit()
    logger.info("journal: %d entries upserted from %s", count, csv_path)
    return count


def _window_start(dirty_from, latest):
    start = min(s2d(dirty_from), s2d(latest) - timedelta(days=STATUS_DAYS)) - timedelta(days=HISTORY_DAYS)
    return d2s(start.replace(day=1))      # whole months, so monthly CSVs are always complete


def _load_sports(path):
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if not k.startswith("_")}


def build_context(db, settings, full=False, end_date=None):
    latest = repo.latest_day(db)
    if latest is None:
        logger.warning("database is empty, run the import first")
        return []

    full = full or not repo.was_ever_built(db)
    dirty_from = None if full else repo.dirty_since(db)
    if not full and dirty_from is None:
        logger.info("nothing changed since the last build")
        return []

    since = None if full else _window_start(dirty_from, latest)
    facts = repo.load_facts(db, since)
    days, sessions, profiles, tests, _ = collect(facts, _load_sports(settings.sports_file))
    journal_rows = repo.load_journal_entries(db)
    journal_by_date = {}
    for entry in journal_rows:
        journal_by_date.setdefault(entry["date"], []).append(entry)
    if since:
        days = {d: v for d, v in days.items() if d >= since}

    profile = latest_profile(profiles, tests)
    rows = build_rows(days, journal_by_day(journal_rows), profile)
    if since:
        rows = [r for r in rows if r["date"] >= since]
    changed_from = dirty_from or rows[0]["date"]
    changed_rows = [r for r in rows if r["date"] >= changed_from]
    logger.info("build: %s, %d facts loaded, %d days recomputed from %s",
                "full" if full else "incremental", len(facts), len(changed_rows), changed_from)

    repo.save_daily_metrics(db, changed_rows)
    repo.save_sessions(db, [s for s in sessions if s["date"] >= changed_from])
    db.commit()

    writer = Writer(settings.context_dir)
    render_daily_csvs(writer, rows, sessions)
    render_monthly(writer, repo.load_daily_metrics(db))
    for day in sorted(set(days) | set(journal_by_date)):
        if day >= changed_from:
            render_day(writer, day, days, {r["date"]: r for r in rows}, journal_by_date)

    end = end_date or rows[-1]["date"]
    coverage = _coverage_text(db, len(journal_rows))
    render_status(writer, rows, profile, coverage, journal_by_date, settings.medical_dir, end)
    render_index(writer, coverage, repo.count_days(db), end)
    writer.save_changed_list()

    repo.mark_built(db)
    db.commit()
    logger.info("build done: %d files written, %d unchanged", len(writer.changed), writer.total - len(writer.changed))
    return writer.changed


def _coverage_text(db, journal_count):
    labels = {"sleep": "sleep", "recharge": "nightly_recharge", "activity": "activity", "hr": "hr24/7",
              "skin": "skin_temp", "skin_night": "skin_temp"}
    coverage = {}
    for kind, (first, last, n_days) in repo.fact_coverage(db).items():
        label = labels.get(kind)
        if label and label not in coverage:
            coverage[label] = f"{first}→{last} ({n_days} d)"
    for label in ("sleep", "nightly_recharge", "activity", "hr24/7", "skin_temp"):
        coverage.setdefault(label, "none")
    coverage["trainings"] = str(repo.count_sessions(db))
    coverage["journal"] = f"{journal_count} entries" if journal_count else "none"
    return coverage
