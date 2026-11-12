import argparse
import logging
import sys
from pathlib import Path

import requests

from .config import Settings
from .db import Database
from .db_check import check_database, log_report
from .drive_sync import DriveClient, DriveError, pull_dir, push_context, push_dir, resolve_root
from .fetch_polar import PolarApiError, PolarClient, fetch_all
from .pipeline import build_context, import_journal_csv, import_raw_files

logger = logging.getLogger("healthctx")


def _parser():
    parser = argparse.ArgumentParser(prog="healthctx", description="Polar data -> database -> context files")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("migrate", help="create or update the database schema")
    sub.add_parser("db-check", help="connection, schema version and row counts (no health values)")

    fetch = sub.add_parser("fetch", help="download recent data from Polar AccessLink into raw/api")
    fetch.add_argument("--days", type=int, default=7, help="days back for range endpoints (max 28)")

    imp = sub.add_parser("import", help="import raw Polar JSON and the journal CSV")
    imp.add_argument("--raw", type=Path, help="raw data folder (default from settings)")
    imp.add_argument("--journal", type=Path, help="journal CSV to upsert")

    build = sub.add_parser("build", help="recompute changed days and write context files")
    build.add_argument("--full", action="store_true", help="rebuild everything, not only changed days")
    build.add_argument("--end", help="last date shown in status.md (YYYY-MM-DD)")
    build.add_argument("--out", type=Path, help="context output folder")

    for name, help_text in (("push-context", "upload changed context files to Google Drive"),
                            ("push-raw", "archive database/private/raw on Google Drive"),
                            ("pull-raw", "restore database/private/raw from Google Drive")):
        drive = sub.add_parser(name, help=help_text)
        drive.add_argument("--dry-run", action="store_true", help="only report what would be transferred")
        if name != "push-context":
            drive.add_argument("--with-confidential", action="store_true",
                               help="also sync database/confidential (journal CSV, medical files)")

    run = sub.add_parser("run", help="fetch (if POLAR_ACCESS_TOKEN is set) + migrate + import + build")
    run.add_argument("--full", action="store_true")
    run.add_argument("--days", type=int, default=7)
    return parser


def _fetch(settings, days):
    # A failed fetch must not block building from the data we already have, so report and go on.
    try:
        fetch_all(PolarClient(settings.polar_access_token), settings.raw_dir / "api", days=days)
    except (PolarApiError, requests.RequestException) as exc:
        logger.error("fetch failed: %s", exc)
        return False
    return True


def _drive(settings, args):
    try:
        client = DriveClient(settings.gdrive_client_id, settings.gdrive_client_secret, settings.gdrive_refresh_token)
        root_id = resolve_root(client, settings.gdrive_folder_id, args.dry_run)
        if root_id is None:
            logger.info("dry run: root folder would be created on the first real run")
            return True
        if args.command == "push-context":
            push_context(client, root_id, settings.context_dir, args.dry_run)
            return True

        folders = [(settings.raw_dir, "raw")]
        if args.with_confidential:
            folders.append((settings.confidential_dir, "confidential"))
        for local_dir, remote_name in folders:
            if args.command == "push-raw":
                push_dir(client, root_id, local_dir, remote_name, args.dry_run)
            else:
                pull_dir(client, root_id, remote_name, local_dir, args.dry_run)
    except (DriveError, requests.RequestException) as exc:
        logger.error("%s failed: %s", args.command, exc)
        return False
    return True


def main(argv=None):
    args = _parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    settings = Settings.from_env()
    if getattr(args, "out", None):
        settings.context_dir = args.out

    if args.command == "fetch":
        return 0 if _fetch(settings, args.days) else 1
    if args.command in ("push-context", "push-raw", "pull-raw"):
        return 0 if _drive(settings, args) else 1

    fetch_ok = True
    if args.command == "run":
        if settings.polar_access_token:
            fetch_ok = _fetch(settings, args.days)
        else:
            logger.info("POLAR_ACCESS_TOKEN not set, skipping fetch")

    try:
        db = Database(settings.database_url)
    except Exception as exc:
        # psycopg puts host and user in the message, but never the password
        logger.error("cannot connect to the database: %s", exc)
        return 1

    try:
        if args.command == "db-check":
            return 0 if log_report(check_database(db)) else 1
        if args.command in ("migrate", "run"):
            db.migrate()
        if args.command in ("import", "run"):
            import_raw_files(db, getattr(args, "raw", None) or settings.raw_dir)
            import_journal_csv(db, getattr(args, "journal", None) or settings.journal_csv)
        if args.command in ("build", "run"):
            build_context(db, settings, full=args.full, end_date=getattr(args, "end", None))
    except Exception:
        logger.exception("%s failed", args.command)
        return 1
    finally:
        db.close()
    return 0 if fetch_ok else 1


if __name__ == "__main__":
    sys.exit(main())
