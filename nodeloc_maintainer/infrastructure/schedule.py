from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime, timedelta


def parse_run_time(value: str) -> tuple[int, int]:
    try:
        hour_text, minute_text = value.split(":", 1)
        hour = int(hour_text)
        minute = int(minute_text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Use HH:MM, for example 08:10.") from exc
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise argparse.ArgumentTypeError("Run time must be between 00:00 and 23:59.")
    return hour, minute


def next_run_datetime(run_at: tuple[int, int]) -> datetime:
    now = datetime.now()
    hour, minute = run_at
    next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if next_run <= now:
        next_run += timedelta(days=1)
    return next_run


def sleep_until_next_run(run_at: tuple[int, int]) -> None:
    next_run = next_run_datetime(run_at)
    seconds = max(0.0, (next_run - datetime.now()).total_seconds())
    logging.info("Next run at %s, sleeping %.1f hours", next_run.strftime("%Y-%m-%d %H:%M:%S"), seconds / 3600)
    time.sleep(seconds)

