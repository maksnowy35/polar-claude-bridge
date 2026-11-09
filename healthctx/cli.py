import argparse
import logging
import sys
from pathlib import Path

from .config import Settings
from .db import Database
from .pipeline import build_context, import_journal_csv, import_raw_files

logger = logging.getLogger("healthctx")


def _parser():
    parser = argparse.ArgumentParser(prog="healthctx", description="Polar data -> database -> context files")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("migrate", help="create or update the database schema")

    imp = sub.add_parser("import", help="import raw Polar JSON and the journal CSV")
    imp.add_argument("--raw", type=Path, help="raw data folder (default from settings)")
    imp.add_argument("--journal", type=Path, help="journal CSV to upsert")

    build = sub.add_parser("build", help="recompute changed days and write context files")
    build.add_argument("--full", action="store_true", help="rebuild everything, not only changed days")
    build.add_argument("--end", help="last date shown in status.md (YYYY-MM-DD)")
    build.add_argument("--out", type=Path, help="context output folder")

    run = sub.add_parser("run", help="migrate + import + build")
    run.add_argument("--full", action="store_true")
    return parser


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

    db = Database(settings.database_url)
    try:
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
