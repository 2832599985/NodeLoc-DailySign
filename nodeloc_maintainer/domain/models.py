from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .site import DEFAULT_USER_AGENT


@dataclass(frozen=True)
class Account:
    name: str
    cookie: str
    csrf_token: str | None = None
    user_agent: str = DEFAULT_USER_AGENT


@dataclass(frozen=True)
class DelaySettings:
    min_seconds: float = 8.0
    max_seconds: float = 25.0


@dataclass(frozen=True)
class RetrySettings:
    on_busy: int = 2
    delay_seconds: float = 60.0


@dataclass(frozen=True)
class Settings:
    accounts: list[Account]
    delay: DelaySettings = field(default_factory=DelaySettings)
    retry: RetrySettings = field(default_factory=RetrySettings)
    reading: "ReadingSettings" = field(default_factory=lambda: ReadingSettings())
    timeout_seconds: float = 30.0
    proxy: str | None = None


@dataclass(frozen=True)
class CheckinResult:
    account_name: str
    ok: bool
    message: str
    status_code: int | None = None
    data: dict[str, Any] = field(default_factory=dict)
    completed: bool = False
    busy: bool = False


@dataclass(frozen=True)
class AccountStats:
    account_name: str
    username: str
    trust_level: int | None
    time_read_seconds: int = 0
    topics_entered: int = 0
    posts_read_count: int = 0
    days_visited: int = 0
    likes_given: int = 0
    likes_received: int = 0
    post_count: int = 0

    @property
    def time_read_minutes(self) -> float:
        return round(self.time_read_seconds / 60, 2)


@dataclass(frozen=True)
class MetricDelta:
    time_read_seconds: int = 0
    topics_entered: int = 0
    posts_read_count: int = 0
    days_visited: int = 0

    @property
    def changed(self) -> bool:
        return any(
            [
                self.time_read_seconds > 0,
                self.topics_entered > 0,
                self.posts_read_count > 0,
                self.days_visited > 0,
            ]
        )


@dataclass(frozen=True)
class TopicCandidate:
    topic_id: int
    title: str
    url: str
    posts_count: int = 0
    unread_posts: int = 0


@dataclass(frozen=True)
class ReadingSettings:
    enabled: bool = False
    minutes_per_account: float = 5.0
    topics_per_account: int = 3
    min_stay_seconds: float = 30.0
    max_stay_seconds: float = 75.0
    scrolls_per_topic: int = 8
    headless: bool = True
    target_time_read_minutes: float = 0.0
    target_topics_entered: int = 0
    target_posts_read_count: int = 0
    rescue_attempts: int = 2
    rescue_topic_multiplier: int = 3


@dataclass(frozen=True)
class ReadingDecision:
    account_name: str
    should_read: bool
    reason: str
    target_seconds: int = 0


@dataclass(frozen=True)
class ReadingSessionResult:
    account_name: str
    ok: bool
    message: str
    topics_visited: int = 0
    seconds_spent: int = 0
    topic_urls: list[str] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)
    attempts: int = 1


@dataclass(frozen=True)
class AccountMaintenanceResult:
    account_name: str
    cookie_ok: bool
    cookie_message: str
    checkin_result: CheckinResult | None = None
    stats_before: AccountStats | None = None
    stats_after: AccountStats | None = None
    metrics_delta: MetricDelta | None = None
    reading_decision: ReadingDecision | None = None
    reading_result: ReadingSessionResult | None = None


@dataclass(frozen=True)
class MaintenanceRunReport:
    date_key: str
    dry_run: bool
    results: list[AccountMaintenanceResult]
    report_path: str | None = None

    @property
    def ok(self) -> bool:
        for result in self.results:
            checkin_ok = result.checkin_result is None or result.checkin_result.ok
            reading_ok = result.reading_result is None or result.reading_result.ok
            if not result.cookie_ok or not checkin_ok or not reading_ok:
                return False
        return True
