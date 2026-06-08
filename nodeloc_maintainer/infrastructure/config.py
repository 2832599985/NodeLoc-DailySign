from __future__ import annotations

import json
from pathlib import Path

from nodeloc_maintainer.domain.models import Account, DelaySettings, ReadingSettings, RetrySettings, Settings
from nodeloc_maintainer.domain.site import DEFAULT_USER_AGENT


def load_settings(path: Path) -> Settings:
    with path.open("r", encoding="utf-8-sig") as file:
        raw = json.load(file)

    account_items = raw.get("accounts")
    if not isinstance(account_items, list) or not account_items:
        raise ValueError("Config must contain a non-empty accounts list.")

    accounts: list[Account] = []
    for index, item in enumerate(account_items, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"accounts[{index}] must be an object.")

        name = str(item.get("name") or f"account-{index}")
        cookie = str(item.get("cookie") or "").strip()
        if not cookie or cookie.startswith("PASTE_"):
            raise ValueError(f"{name}: cookie is required.")

        csrf_token = str(item.get("csrf_token") or "").strip() or None
        user_agent = str(item.get("user_agent") or DEFAULT_USER_AGENT)
        accounts.append(Account(name=name, cookie=cookie, csrf_token=csrf_token, user_agent=user_agent))

    delay_raw = raw.get("delay_seconds", {})
    delay = DelaySettings(
        min_seconds=float(delay_raw.get("min", 8)),
        max_seconds=float(delay_raw.get("max", 25)),
    )
    if delay.min_seconds < 0 or delay.max_seconds < delay.min_seconds:
        raise ValueError("delay_seconds must satisfy min >= 0 and max >= min.")

    retry_raw = raw.get("retry", {})
    retry = RetrySettings(
        on_busy=int(retry_raw.get("on_busy", 2)),
        delay_seconds=float(retry_raw.get("delay_seconds", 60)),
    )

    reading_raw = raw.get("reading", {})
    reading = ReadingSettings(
        enabled=as_bool(reading_raw.get("enabled", False)),
        minutes_per_account=float(reading_raw.get("minutes_per_account", 5)),
        topics_per_account=int(reading_raw.get("topics_per_account", 3)),
        min_stay_seconds=float(reading_raw.get("min_stay_seconds", 30)),
        max_stay_seconds=float(reading_raw.get("max_stay_seconds", 75)),
        scrolls_per_topic=int(reading_raw.get("scrolls_per_topic", 8)),
        headless=as_bool(reading_raw.get("headless", True)),
        target_time_read_minutes=float(reading_raw.get("target_time_read_minutes", 0)),
        target_topics_entered=int(reading_raw.get("target_topics_entered", 0)),
        target_posts_read_count=int(reading_raw.get("target_posts_read_count", 0)),
        rescue_attempts=int(reading_raw.get("rescue_attempts", 2)),
        rescue_topic_multiplier=int(reading_raw.get("rescue_topic_multiplier", 3)),
    )
    validate_reading(reading)

    proxy = str(raw.get("proxy") or "").strip() or None
    return Settings(
        accounts=accounts,
        delay=delay,
        retry=retry,
        reading=reading,
        timeout_seconds=float(raw.get("timeout_seconds", 30)),
        proxy=proxy,
    )


def validate_reading(reading: ReadingSettings) -> None:
    if reading.minutes_per_account < 0:
        raise ValueError("reading.minutes_per_account must be >= 0.")
    if reading.topics_per_account < 1:
        raise ValueError("reading.topics_per_account must be >= 1.")
    if reading.min_stay_seconds < 0:
        raise ValueError("reading.min_stay_seconds must be >= 0.")
    if reading.max_stay_seconds < reading.min_stay_seconds:
        raise ValueError("reading.max_stay_seconds must be >= min_stay_seconds.")
    if reading.scrolls_per_topic < 0:
        raise ValueError("reading.scrolls_per_topic must be >= 0.")
    if reading.target_time_read_minutes < 0:
        raise ValueError("reading.target_time_read_minutes must be >= 0.")
    if reading.target_topics_entered < 0:
        raise ValueError("reading.target_topics_entered must be >= 0.")
    if reading.target_posts_read_count < 0:
        raise ValueError("reading.target_posts_read_count must be >= 0.")
    if reading.rescue_attempts < 0:
        raise ValueError("reading.rescue_attempts must be >= 0.")
    if reading.rescue_topic_multiplier < 1:
        raise ValueError("reading.rescue_topic_multiplier must be >= 1.")


def as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y", "on"}:
            return True
        if normalized in {"false", "0", "no", "n", "off", ""}:
            return False
    return bool(value)
