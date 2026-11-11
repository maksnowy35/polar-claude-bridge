import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv():
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(REPO_ROOT / ".env")


def _env(name, default):
    # .env.example ships empty values; an empty variable means "use the default", not "use ''".
    return os.getenv(name) or default


@dataclass
class Settings:
    database_url: str
    raw_dir: Path
    context_dir: Path
    journal_csv: Path
    medical_dir: Path
    sports_file: Path
    polar_access_token: str = ""

    @classmethod
    def from_env(cls):
        _load_dotenv()
        private = REPO_ROOT / "database" / "private"
        confidential = REPO_ROOT / "database" / "confidential"
        return cls(
            database_url=_env("DATABASE_URL", f"sqlite:///{private / 'health.db'}"),
            raw_dir=Path(_env("HEALTH_RAW_DIR", private / "raw")),
            context_dir=Path(_env("HEALTH_CONTEXT_DIR", private / "context")),
            journal_csv=Path(_env("HEALTH_JOURNAL_CSV", confidential / "journal" / "log.csv")),
            medical_dir=Path(_env("HEALTH_MEDICAL_DIR", confidential / "medical")),
            sports_file=Path(_env("HEALTH_SPORTS_FILE", REPO_ROOT / "sports.json")),
            polar_access_token=_env("POLAR_ACCESS_TOKEN", ""),
        )
