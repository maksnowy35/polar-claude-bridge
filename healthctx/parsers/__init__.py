"""Parsers: raw Polar JSON (Polar Flow data export) -> normalized "facts".

Detection is by content, not by filename, so any wrapper (your MCP cache, API list
responses, export files) works. Each fact is a small JSON-serializable dict with a
kind `k`; the aggregator merges facts into per-day records.

Fact kinds: activity, hr, skin, session, profile, fitness_test, skip.
"""
from __future__ import annotations

import json

from .export import (export_account, export_activity, export_fitness_test, export_generic_period,
                     export_hr247, export_session_physinfo, export_training_session)

__all__ = ["parse_file", "walk"]


def _match(o):
    """Return list of facts if `o` is a known object, else None."""
    if not isinstance(o, dict):
        return None
    k = o.keys()
    if "deviceDays" in k:
        return export_hr247(o)
    if "summary" in k and "samples" in k and "date" in k:
        return export_activity(o)
    if "exercises" in k and "durationMillis" in k:
        return export_training_session(o) + export_session_physinfo(o)
    if "exercises" in k and "done" in k:
        return [{"k": "skip", "why": "training-target (planned workout)"}]
    if "meta" in k and isinstance(o.get("data"), dict) and "measurementType" in o["data"]:
        return export_generic_period(o)
    if "fitnessTestResult" in k:
        return export_fitness_test(o)
    if "physicalInformation" in k and "username" in k:
        return export_account(o)       # name/e-mail deliberately dropped
    if "favouriteSports" in k:
        return [{"k": "skip", "why": "account-profile"}]
    return None


def walk(o, depth=0):
    m = _match(o)
    if m is not None:
        return m
    if depth > 4:
        return []
    out = []
    if isinstance(o, dict):
        for v in o.values():
            if isinstance(v, (dict, list)):
                out += walk(v, depth + 1)
    elif isinstance(o, list):
        for v in o:
            out += walk(v, depth + 1)
    return out


def parse_file(path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        o = json.load(f)
    if o == [] or o == {}:
        return [{"k": "skip", "why": "empty"}]
    facts = walk(o)
    return facts or [{"k": "skip", "why": "unrecognized: " + ",".join(list(o.keys())[:8]) if isinstance(o, dict) else "unrecognized list"}]
