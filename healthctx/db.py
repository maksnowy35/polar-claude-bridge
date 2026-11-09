import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


class Database:
    """Thin wrapper so the rest of the code does not care if it talks to SQLite or Postgres.

    Queries are written with '?' placeholders (SQLite style) and translated for psycopg.
    """

    def __init__(self, url):
        self.url = url
        if url.startswith("sqlite:///"):
            self.dialect = "sqlite"
            path = Path(url.removeprefix("sqlite:///"))
            path.parent.mkdir(parents=True, exist_ok=True)
            self.conn = sqlite3.connect(path)
            self.conn.execute("PRAGMA foreign_keys = ON")
        elif url.startswith(("postgres://", "postgresql://")):
            import psycopg  # only needed in production, keep SQLite usable without it

            self.dialect = "postgres"
            self.conn = psycopg.connect(url)
        else:
            raise ValueError(f"Unsupported DATABASE_URL scheme: {url.split(':', 1)[0]}")
        logger.debug("connected to %s database", self.dialect)

    def _sql(self, query):
        if self.dialect == "postgres":
            return query.replace("?", "%s")
        return query

    def execute(self, query, params=()):
        cur = self.conn.cursor()
        cur.execute(self._sql(query), params)
        return cur

    def executemany(self, query, rows):
        if not rows:
            return
        cur = self.conn.cursor()
        cur.executemany(self._sql(query), rows)

    def fetch_all(self, query, params=()):
        cur = self.execute(query, params)
        columns = [c[0] for c in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]

    def fetch_value(self, query, params=()):
        row = self.execute(query, params).fetchone()
        return row[0] if row else None

    def commit(self):
        self.conn.commit()

    def close(self):
        self.conn.close()

    def migrate(self):
        self.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY)")
        applied = {r["version"] for r in self.fetch_all("SELECT version FROM schema_migrations")}
        for path in sorted((MIGRATIONS_DIR / self.dialect).glob("*.sql")):
            version = int(path.name.split("_", 1)[0])
            if version in applied:
                continue
            logger.info("applying migration %s", path.name)
            script = path.read_text(encoding="utf-8")
            if self.dialect == "sqlite":
                self.conn.executescript(script)
            else:
                self.execute(script)
            self.execute("INSERT INTO schema_migrations (version) VALUES (?)", (version,))
            self.commit()

    def get_meta(self, key, default=None):
        value = self.fetch_value("SELECT value FROM meta WHERE key = ?", (key,))
        return default if value is None else value

    def set_meta(self, key, value):
        self.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
        )
