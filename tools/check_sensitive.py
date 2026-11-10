"""Pre-commit guard: refuse commits that would publish health data or credentials.

The repo is public, so this runs on the staged version of every added/changed file.
Usage: python tools/check_sensitive.py          (staged files, used by the hook)
       python tools/check_sensitive.py --all    (every tracked file, e.g. in CI)
"""
import logging
import re
import subprocess
import sys
from pathlib import PurePosixPath

logger = logging.getLogger("check_sensitive")

BLOCKED_DIRS = ("database/private/", "database/confidential/")
ALLOWED_IN_BLOCKED_DIRS = {"README.md"}
DATA_DIRS_ALLOWED = ("database/public/", "tests/")
BLOCKED_SUFFIXES = (".db", ".sqlite", ".sqlite3")

POLAR_MARKERS = ('"polar_user"', '"deviceDays"', '"exportVersion"', '"hypnogram"')
SECRET_PATTERNS = [
    ("hardcoded secret", re.compile(
        # braces excluded: f-string templates like ACCESS_TOKEN = "{token}" only print a value
        r"""\b(CLIENT_SECRET|ACCESS_TOKEN|REFRESH_TOKEN|API_KEY|PASSWORD)\s*[:=]\s*["'][^"'\s{}]{8,}["']""")),
    ("bearer token", re.compile(r"Bearer\s+[A-Za-z0-9\-_.=]{20,}")),
    # placeholders used in docs (user:...@, user:***@, user:<password>@) are not secrets
    ("database url with password", re.compile(
        r"postgres(?:ql)?://[^\s:/@]+:(?!(?:\.{3}|\*+|<[^>]*>|password|haslo)@)[^\s@/]+@")),
]
TEXT_SUFFIXES = {".py", ".md", ".txt", ".json", ".csv", ".yml", ".yaml", ".toml", ".ini", ".cfg", ".sh", ".sql", ""}


def check_path(path):
    p = PurePosixPath(path)
    if path.startswith(BLOCKED_DIRS) and p.name not in ALLOWED_IN_BLOCKED_DIRS:
        return ["file inside a private/confidential data folder"]
    if p.name == ".env" or (p.name.startswith(".env.") and p.name != ".env.example"):
        return ["environment file with credentials"]
    if p.suffix in BLOCKED_SUFFIXES:
        return ["database file"]
    return []


def check_content(path, content):
    problems = []
    if path.endswith(".json") and not path.startswith(DATA_DIRS_ALLOWED):
        found = [m for m in POLAR_MARKERS if m in content]
        if found:
            problems.append(f"looks like Polar data ({', '.join(found)})")
    for line_no, line in enumerate(content.splitlines(), start=1):
        for label, pattern in SECRET_PATTERNS:
            if pattern.search(line):
                problems.append(f"line {line_no}: {label}")
    return problems


def _git(*args):
    return subprocess.run(["git", *args], capture_output=True, check=True).stdout


def _files_to_check(check_all):
    if check_all:
        out = _git("ls-files")
    else:
        out = _git("diff", "--cached", "--name-only", "--diff-filter=ACMR")
    return [f for f in out.decode("utf-8").splitlines() if f]


def _staged_content(path, check_all):
    # The hook must look at what is about to be committed, not at the working tree.
    spec = f"HEAD:{path}" if check_all else f":{path}"
    try:
        return _git("show", spec).decode("utf-8", errors="replace")
    except subprocess.CalledProcessError:
        return ""


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
    check_all = "--all" in (argv if argv is not None else sys.argv[1:])

    findings = {}
    for path in _files_to_check(check_all):
        problems = check_path(path)
        if not problems and PurePosixPath(path).suffix in TEXT_SUFFIXES:
            problems = check_content(path, _staged_content(path, check_all))
        if problems:
            findings[path] = problems

    if not findings:
        return 0
    logger.error("Commit blocked, sensitive content found:")
    for path, problems in findings.items():
        for problem in problems:
            logger.error("  %s: %s", path, problem)
    logger.error("Move the data to database/private or database/confidential, secrets to .env.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
