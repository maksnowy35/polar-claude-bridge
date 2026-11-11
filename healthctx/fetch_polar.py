"""Daily pull from Polar AccessLink v3 into database/private/raw/api/<kind>/.

Every item is stored as its own file named after its date, so a re-run overwrites the
same files and the importer skips them by sha1. Only counts are logged, the logs of a
public repo's CI are public.
"""
import json
import logging
import os
import tempfile
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

API_URL = "https://www.polaraccesslink.com"
TIMEOUT_S = 30
MAX_RANGE_DAYS = 28      # AccessLink rejects longer from/to ranges


class PolarApiError(RuntimeError):
    pass


@dataclass(frozen=True)
class Endpoint:
    kind: str
    path: str
    list_key: str | None = None      # key holding the list in the response, None = response is the list
    uses_range: bool = False
    extra_params: tuple = ()


ENDPOINTS = (
    Endpoint("sleep", "/v3/users/sleep", list_key="nights"),
    Endpoint("nightly_recharge", "/v3/users/nightly-recharge", list_key="recharges"),
    Endpoint("activity", "/v3/users/activities", uses_range=True,
             extra_params=(("steps", "true"), ("activity_zones", "true"))),
    Endpoint("exercise", "/v3/exercises", extra_params=(("samples", "true"), ("zones", "true"))),
    Endpoint("heart_rate", "/v3/users/continuous-heart-rate", list_key="heart_rates", uses_range=True),
    Endpoint("cardio_load", "/v3/users/cardio-load"),
)


class PolarClient:
    def __init__(self, access_token, session=None):
        if not access_token:
            raise PolarApiError("POLAR_ACCESS_TOKEN is empty, fill it in .env (token from test_files/auth_script.py)")
        self.session = session or requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {access_token}", "Accept": "application/json"})

    def get(self, path, params=None):
        response = self.session.get(API_URL + path, params=params, timeout=TIMEOUT_S)
        status = response.status_code
        if status == 204:
            return None
        if status == 401:
            raise PolarApiError("401 from Polar: access token rejected or revoked, run test_files/auth_script.py again")
        if status == 403:
            raise PolarApiError("403 from Polar: user not registered for this client or consent missing in Polar Flow")
        if status == 429:
            retry = response.headers.get("Retry-After", "?")
            raise PolarApiError(f"429 from Polar: rate limit hit, retry after {retry} s")
        if status >= 400:
            raise PolarApiError(f"{status} from Polar for {path}")
        return response.json()


def _items(payload, endpoint):
    if payload is None:
        return []
    if endpoint.list_key and isinstance(payload, dict):
        return payload.get(endpoint.list_key) or []
    if isinstance(payload, dict):
        return [payload]
    return payload


def _item_date(item):
    for field in ("date", "start_time", "sleep_end_time"):
        value = item.get(field)
        if value:
            return str(value)[:10]
    return None


def _file_name(endpoint, item, item_date):
    if endpoint.kind == "exercise":
        # several trainings per day, the id keeps them apart
        exercise_id = "".join(c for c in str(item.get("id", "")) if c.isalnum())[:32] or "noid"
        return f"{item_date}_{exercise_id}.json"
    return f"{item_date}.json"


def _write_if_changed(path, item):
    text = json.dumps(item, ensure_ascii=False, sort_keys=True, indent=1)
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    # write + rename, so an interrupted run never leaves half a JSON for the importer
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp_name, path)
    return True


def fetch_all(client, raw_api_dir, days=7, today=None):
    raw_api_dir = Path(raw_api_dir)
    days = max(1, min(days, MAX_RANGE_DAYS))
    end = today or date.today()
    start = end - timedelta(days=days - 1)

    summary = {}
    for endpoint in ENDPOINTS:
        params = dict(endpoint.extra_params)
        if endpoint.uses_range:
            params.update({"from": start.isoformat(), "to": end.isoformat()})

        items = _items(client.get(endpoint.path, params or None), endpoint)
        written = 0
        for item in items:
            item_date = _item_date(item)
            if item_date is None:
                logger.warning("%s: item without a date skipped", endpoint.kind)
                continue
            target = raw_api_dir / endpoint.kind / _file_name(endpoint, item, item_date)
            written += _write_if_changed(target, item)
        summary[endpoint.kind] = (len(items), written)
        logger.info("fetch %-16s %3d items, %3d files changed", endpoint.kind, len(items), written)
    return summary
