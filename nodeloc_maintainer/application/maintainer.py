from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from typing import Any

from nodeloc_maintainer.application.checkin import CheckinService
from nodeloc_maintainer.application.ports import BrowserReader, CompletionStore, DateProvider
from nodeloc_maintainer.application.reader import ReadingPlanner
from nodeloc_maintainer.application.stats import StatsService
from nodeloc_maintainer.application.topics import TopicDiscoveryService
from nodeloc_maintainer.domain.models import (
    Account,
    AccountMaintenanceResult,
    AccountStats,
    CheckinResult,
    MaintenanceRunReport,
    MetricDelta,
    ReadingSessionResult,
    Settings,
)

EventSink = Callable[[str, str, str | None, dict[str, Any]], None]


class DailyMaintainer:
    """Coordinates the full daily maintenance flow."""

    def __init__(
        self,
        settings: Settings,
        state_store: CompletionStore,
        date_provider: DateProvider,
        checkin_service: CheckinService,
        stats_service: StatsService,
        topic_service: TopicDiscoveryService,
        reading_planner: ReadingPlanner,
        browser_reader: BrowserReader,
        sleep_fn: Callable[[float], None] = time.sleep,
        jitter_fn: Callable[[float, float], float] = random.uniform,
        event_sink: EventSink | None = None,
    ):
        self.settings = settings
        self.state_store = state_store
        self.date_provider = date_provider
        self.checkin_service = checkin_service
        self.stats_service = stats_service
        self.topic_service = topic_service
        self.reading_planner = reading_planner
        self.browser_reader = browser_reader
        self.sleep_fn = sleep_fn
        self.jitter_fn = jitter_fn
        self.event_sink = event_sink

    def run_once(
        self,
        dry_run: bool = False,
        skip_delays: bool = False,
        force_checkin: bool = False,
        force_reading: bool = False,
        max_accounts: int | None = None,
    ) -> MaintenanceRunReport:
        date_key = self.date_provider.today_key()
        state = self.state_store.load()
        accounts = limit_accounts(self.settings.accounts, max_accounts)
        results: list[AccountMaintenanceResult] = []

        for index, account in enumerate(accounts, start=1):
            logging.info("[%s] maintenance start", account.name)
            self.emit("account_start", "account maintenance started", account.name, {"index": index})
            results.append(
                self._run_account(
                    account=account,
                    date_key=date_key,
                    state=state,
                    dry_run=dry_run,
                    force_checkin=force_checkin,
                    force_reading=force_reading,
                )
            )
            if not skip_delays and index < len(accounts):
                self.sleep_between_accounts()

        report = MaintenanceRunReport(date_key=date_key, dry_run=dry_run, results=results)
        logging.info("Maintenance done: %s/%s accounts healthy", healthy_count(report), len(results))
        self.emit("run_complete", "maintenance run completed", None, {"healthy": healthy_count(report), "total": len(results)})
        return report

    def _run_account(
        self,
        account: Account,
        date_key: str,
        state: dict,
        dry_run: bool,
        force_checkin: bool,
        force_reading: bool,
    ) -> AccountMaintenanceResult:
        try:
            stats_before = self.stats_service.collect(account)
        except Exception as exc:
            self.emit("cookie_failed", str(exc), account.name)
            return AccountMaintenanceResult(
                account_name=account.name,
                cookie_ok=False,
                cookie_message=f"cookie/current user failed: {exc}",
            )

        if not stats_before.username:
            self.emit("cookie_failed", "no current user returned", account.name)
            return AccountMaintenanceResult(
                account_name=account.name,
                cookie_ok=False,
                cookie_message="no current user returned",
                stats_before=stats_before,
            )

        cookie_message = f"logged in as {stats_before.username}, tl={stats_before.trust_level}"
        self.emit("cookie_ok", cookie_message, account.name, {"username": stats_before.username, "trust_level": stats_before.trust_level})
        self.emit("stats_before", "stats collected before reading", account.name, stats_payload(stats_before))
        checkin_result = self._run_checkin(account, date_key, state, dry_run, force_checkin)
        self.emit(
            "checkin",
            checkin_result.message,
            account.name,
            {"ok": checkin_result.ok, "completed": checkin_result.completed, "busy": checkin_result.busy},
        )
        reading_decision = self.reading_planner.decide(
            stats_before,
            self.settings.reading,
            force=force_reading,
        )
        self.emit(
            "reading_decision",
            reading_decision.reason,
            account.name,
            {"should_read": reading_decision.should_read, "target_seconds": reading_decision.target_seconds},
        )
        reading_result: ReadingSessionResult | None = None
        stats_after = stats_before

        if reading_decision.should_read:
            try:
                candidate_limit = self.settings.reading.topics_per_account * self.settings.reading.rescue_topic_multiplier
                topics = self.topic_service.latest(account, limit=candidate_limit)
                self.emit("topics_found", f"{len(topics)} topic candidates found", account.name, {"count": len(topics)})
                if dry_run:
                    reading_result = ReadingSessionResult(
                        account_name=account.name,
                        ok=True,
                        message=f"dry-run: {len(topics)} topic candidates found, browser skipped",
                        topics_visited=0,
                        seconds_spent=0,
                        topic_urls=[topic.url for topic in topics],
                    )
                else:
                    reading_result, stats_after = self.run_reading_with_rescue(
                        account=account,
                        topics=topics,
                        stats_before=stats_before,
                        target_seconds=reading_decision.target_seconds,
                    )
            except Exception as exc:
                reading_result = ReadingSessionResult(
                    account_name=account.name,
                    ok=False,
                    message=f"reading failed: {exc}",
                )
                self.emit("reading_failed", str(exc), account.name)

        metrics_delta = calculate_delta(stats_before, stats_after)
        if reading_result:
            self.emit("metrics_delta", "reading metrics delta calculated", account.name, delta_payload(metrics_delta))

        return AccountMaintenanceResult(
            account_name=account.name,
            cookie_ok=True,
            cookie_message=cookie_message,
            checkin_result=checkin_result,
            stats_before=stats_before,
            stats_after=stats_after,
            metrics_delta=metrics_delta,
            reading_decision=reading_decision,
            reading_result=reading_result,
        )

    def _run_checkin(
        self,
        account: Account,
        date_key: str,
        state: dict,
        dry_run: bool,
        force_checkin: bool,
    ) -> CheckinResult:
        if not dry_run and not force_checkin and self.state_store.completed_today(account, date_key, state):
            return CheckinResult(
                account_name=account.name,
                ok=True,
                completed=True,
                message=f"skipped locally for {date_key}",
            )

        result = self.checkin_service.check_account(account, dry_run=dry_run)
        if result.ok and not dry_run:
            self.state_store.mark_completed(account, date_key, state)
            self.state_store.save(state)
        return result

    def run_reading_with_rescue(
        self,
        account: Account,
        topics,
        stats_before: AccountStats,
        target_seconds: int,
    ) -> tuple[ReadingSessionResult, AccountStats]:
        stats_after = stats_before
        final_result: ReadingSessionResult | None = None
        attempts = self.settings.reading.rescue_attempts + 1
        chunk_size = self.settings.reading.topics_per_account
        all_urls: list[str] = []
        timing_requests = 0
        seconds_spent = 0
        topics_visited = 0
        attempts_run = 0

        for attempt in range(1, attempts + 1):
            start = (attempt - 1) * chunk_size
            selected = topics[start : start + chunk_size]
            if not selected:
                self.emit("reading_rescue_exhausted", "no more topic candidates", account.name, {"attempt": attempt})
                break

            if attempt > 1:
                self.emit(
                    "reading_rescue_start",
                    "metrics did not change; retrying with different topics",
                    account.name,
                    {"attempt": attempt, "topic_count": len(selected)},
                )

            self.emit(
                "reading_start",
                "browser reading session started",
                account.name,
                {"target_seconds": target_seconds, "topic_count": len(selected), "attempt": attempt},
            )
            result = self.browser_reader.run(
                account=account,
                topics=selected,
                settings=self.settings.reading,
                target_seconds=target_seconds,
            )
            attempts_run = attempt
            final_result = result
            all_urls.extend(result.topic_urls)
            timing_requests += int(result.data.get("timing_requests") or 0)
            seconds_spent += result.seconds_spent
            topics_visited += result.topics_visited

            try:
                stats_after = self.collect_stats_after_reading(account, stats_before)
            except Exception as exc:
                logging.warning("[%s] stats refresh after reading failed: %s", account.name, exc)
                self.emit("stats_after_failed", str(exc), account.name)

            delta = calculate_delta(stats_before, stats_after)
            self.emit(
                "reading_complete",
                result.message,
                account.name,
                {
                    "ok": result.ok,
                    "topics_visited": result.topics_visited,
                    "seconds_spent": result.seconds_spent,
                    "attempt": attempt,
                    **result.data,
                },
            )
            if delta.changed or not result.ok:
                break

        if final_result is None:
            return (
                ReadingSessionResult(
                    account_name=account.name,
                    ok=False,
                    message="reading failed: no topic candidates",
                    attempts=0,
                ),
                stats_after,
            )

        merged = ReadingSessionResult(
            account_name=account.name,
            ok=final_result.ok,
            message=final_result.message,
            topics_visited=topics_visited,
            seconds_spent=seconds_spent,
            topic_urls=all_urls,
            data={"timing_requests": timing_requests},
            attempts=attempts_run,
        )
        return merged, stats_after

    def collect_stats_after_reading(self, account: Account, stats_before: AccountStats) -> AccountStats:
        stats_after = stats_before
        for attempt in range(1, 5):
            if attempt > 1:
                self.sleep_fn(8)
            stats_after = self.stats_service.collect(account)
            delta = calculate_delta(stats_before, stats_after)
            self.emit(
                "stats_after",
                f"stats collected after reading, attempt {attempt}",
                account.name,
                {**stats_payload(stats_after), "attempt": attempt, "delta": delta_payload(delta)},
            )
            if delta.changed:
                return stats_after
        return stats_after

    def emit(
        self,
        event_type: str,
        message: str,
        account_name: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        if self.event_sink:
            self.event_sink(event_type, message, account_name, data or {})

    def sleep_between_accounts(self) -> None:
        wait = self.jitter_fn(self.settings.delay.min_seconds, self.settings.delay.max_seconds)
        if wait > 0:
            logging.info("wait %.1f seconds before next account", wait)
            self.sleep_fn(wait)


def limit_accounts(accounts: list[Account], max_accounts: int | None) -> list[Account]:
    if max_accounts is None or max_accounts <= 0:
        return accounts
    return accounts[:max_accounts]


def healthy_count(report: MaintenanceRunReport) -> int:
    count = 0
    for result in report.results:
        checkin_ok = result.checkin_result is None or result.checkin_result.ok
        reading_ok = result.reading_result is None or result.reading_result.ok
        if result.cookie_ok and checkin_ok and reading_ok:
            count += 1
    return count


def calculate_delta(before: AccountStats, after: AccountStats) -> MetricDelta:
    return MetricDelta(
        time_read_seconds=max(0, after.time_read_seconds - before.time_read_seconds),
        topics_entered=max(0, after.topics_entered - before.topics_entered),
        posts_read_count=max(0, after.posts_read_count - before.posts_read_count),
        days_visited=max(0, after.days_visited - before.days_visited),
    )


def stats_payload(stats: AccountStats) -> dict[str, Any]:
    return {
        "username": stats.username,
        "trust_level": stats.trust_level,
        "time_read_seconds": stats.time_read_seconds,
        "time_read_minutes": stats.time_read_minutes,
        "topics_entered": stats.topics_entered,
        "posts_read_count": stats.posts_read_count,
        "days_visited": stats.days_visited,
    }


def delta_payload(delta: MetricDelta) -> dict[str, Any]:
    return {
        "time_read_seconds": delta.time_read_seconds,
        "topics_entered": delta.topics_entered,
        "posts_read_count": delta.posts_read_count,
        "days_visited": delta.days_visited,
        "changed": delta.changed,
    }
