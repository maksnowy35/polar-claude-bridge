import logging

from .db import MIGRATIONS_DIR

logger = logging.getLogger(__name__)

TABLES = ("raw_files", "facts", "daily_metrics", "training_sessions", "journal_entries")


def latest_migration(dialect):
    versions = [int(p.name.split("_", 1)[0]) for p in (MIGRATIONS_DIR / dialect).glob("*.sql")]
    return max(versions, default=0)


def check_database(db):
    """Connection and schema health only. Never reads health values, the output can end up in CI logs."""
    report = {"target": db.describe(), "expected_version": latest_migration(db.dialect)}
    try:
        report["version"] = db.fetch_value("SELECT max(version) FROM schema_migrations")
    except Exception:
        db.conn.rollback()      # postgres aborts the transaction after a failed statement
        report["version"] = None
        return report

    report["rows"] = {table: db.fetch_value(f"SELECT count(*) FROM {table}") for table in TABLES}
    report["built_run"] = int(db.get_meta("built_run", 0))
    return report


def log_report(report):
    logger.info("database: %s", report["target"])
    if report["version"] is None:
        logger.error("schema not created, run: python -m healthctx migrate")
        return False
    if report["version"] < report["expected_version"]:
        logger.warning("schema version %s, code expects %s, run migrate",
                       report["version"], report["expected_version"])
    else:
        logger.info("schema version %s (up to date)", report["version"])
    for table, count in report["rows"].items():
        logger.info("  %-18s %8d rows", table, count)
    logger.info("last build run: %s", report["built_run"] or "never")
    return report["version"] >= report["expected_version"]
