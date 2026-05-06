#!/usr/bin/env python3
"""
manage_snooze.py — read/write the followup-snooze.json file.

The followup-meeting-requests skill uses this to:
  - load the active (non-expired) snooze list at the start of each run
  - record a new snooze when the user clicks "Don't follow up" in the artifact

Snooze entries auto-expire 60 days after the original meeting request date,
so a fresh request to the same person months later won't be auto-suppressed.

The JSON shape on disk:
  {"snoozed": [
    {"email": "alice@example.com",
     "request_date": "2026-04-12",
     "thread_id": "189f2abc...",
     "snoozed_at": "2026-05-05"}
  ]}

Commands:
  list                                       prune expired entries, save, print active list as JSON
  add --email --request-date --thread-id     append a new snooze entry
  prune                                      drop expired entries (silent)
  path                                       print the path to the snooze file
"""

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta

DEFAULT_SNOOZE_PATH = "/Users/you/Documents/meet-with-me-bot/snooze.json"
# Allow override via env var for testing. In production, leave unset.
SNOOZE_PATH = os.environ.get("FOLLOWUP_SNOOZE_PATH", DEFAULT_SNOOZE_PATH)
TTL_DAYS = 60


def _ensure_dir(path: str) -> None:
    parent = os.path.dirname(path)
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)


def _load() -> dict:
    if not os.path.exists(SNOOZE_PATH):
        return {"snoozed": []}
    try:
        with open(SNOOZE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        # Corrupted or unreadable — start clean rather than crash.
        return {"snoozed": []}
    if not isinstance(data, dict) or "snoozed" not in data:
        return {"snoozed": []}
    return data


def _save(data: dict) -> None:
    _ensure_dir(SNOOZE_PATH)
    with open(SNOOZE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def _is_active(entry: dict, today: date) -> bool:
    """Active = original request_date is within TTL_DAYS of today."""
    try:
        rd = _parse_date(entry["request_date"])
    except (KeyError, ValueError):
        return False
    return (today - rd) <= timedelta(days=TTL_DAYS)


def cmd_list() -> int:
    today = date.today()
    data = _load()
    before = len(data["snoozed"])
    data["snoozed"] = [e for e in data["snoozed"] if _is_active(e, today)]
    after = len(data["snoozed"])
    if before != after:
        _save(data)
    print(json.dumps({"snoozed": data["snoozed"]}, indent=2))
    return 0


def cmd_add(email: str, request_date: str, thread_id: str) -> int:
    # Validate the date format up front so we fail loudly on bad input.
    _parse_date(request_date)
    today = date.today().isoformat()

    data = _load()
    # Avoid duplicate entries on the same key.
    key = (email.lower().strip(), request_date)
    existing = {(e.get("email", "").lower().strip(), e.get("request_date", "")) for e in data["snoozed"]}
    if key in existing:
        print(json.dumps({"ok": True, "added": False, "reason": "already snoozed"}))
        return 0

    data["snoozed"].append({
        "email": email.strip(),
        "request_date": request_date,
        "thread_id": thread_id,
        "snoozed_at": today,
    })
    _save(data)
    print(json.dumps({"ok": True, "added": True}))
    return 0


def cmd_prune() -> int:
    today = date.today()
    data = _load()
    data["snoozed"] = [e for e in data["snoozed"] if _is_active(e, today)]
    _save(data)
    return 0


def cmd_path() -> int:
    print(SNOOZE_PATH)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage the meeting-followup snooze list.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="Prune expired entries and print the active snooze list as JSON.")

    add = sub.add_parser("add", help="Append a snooze entry.")
    add.add_argument("--email", required=True)
    add.add_argument("--request-date", required=True, help="ISO date YYYY-MM-DD of the original meeting request.")
    add.add_argument("--thread-id", required=True)

    sub.add_parser("prune", help="Silently drop expired entries.")
    sub.add_parser("path", help="Print the path to the snooze file.")

    args = parser.parse_args()

    if args.cmd == "list":
        return cmd_list()
    if args.cmd == "add":
        return cmd_add(args.email, args.request_date, args.thread_id)
    if args.cmd == "prune":
        return cmd_prune()
    if args.cmd == "path":
        return cmd_path()
    return 2


if __name__ == "__main__":
    sys.exit(main())
