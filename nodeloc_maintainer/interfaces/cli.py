from __future__ import annotations

import argparse
import logging
import os
from dataclasses import replace
from pathlib import Path

from nodeloc_maintainer.application.checkin import CheckinService
from nodeloc_maintainer.application.daily_sign import DailySignRunner
from nodeloc_maintainer.application.maintainer import DailyMaintainer
from nodeloc_maintainer.application.reader import ReadingPlanner
from nodeloc_maintainer.application.reporting import ReportFormatter
from nodeloc_maintainer.application.stats import StatsService
from nodeloc_maintainer.application.topics import TopicDiscoveryService
from nodeloc_maintainer.domain.models import ReadingSessionResult, Settings
from nodeloc_maintainer.infrastructure.client_factory import NodeLocClientFactory
from nodeloc_maintainer.infrastructure.config import load_settings, validate_reading
from nodeloc_maintainer.infrastructure.report_store import FileReportWriter, FixedPathReportWriter
from nodeloc_maintainer.infrastructure.schedule import parse_run_time, sleep_until_next_run
from nodeloc_maintainer.infrastructure.state import CompletionStateStore
from nodeloc_maintainer.infrastructure.time_provider import SystemDateProvider


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="NodeLoc daily check-in script")
    parser.add_argument(
        "-c",
        "--config",
        default="accounts.json",
        help="Account config file path. Default: accounts.json.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Validate config without real check-in.")
    parser.add_argument("--force", action="store_true", help="Ignore local state and request check-in again.")
    parser.add_argument("--maintain", action="store_true", help="Run the full daily maintainer flow.")
    reading_group = parser.add_mutually_exclusive_group()
    reading_group.add_argument("--reading", action="store_true", help="Enable browser reading for this run.")
    reading_group.add_argument("--no-reading", action="store_true", help="Disable browser reading for this run.")
    parser.add_argument("--force-reading", action="store_true", help="Run browser reading even if targets are met.")
    parser.add_argument("--reading-minutes", type=float, help="Override reading minutes per account.")
    parser.add_argument("--topics-per-account", type=int, help="Override topic count per reading session.")
    parser.add_argument("--headed", action="store_true", help="Run Playwright with a visible browser window.")
    parser.add_argument("--max-accounts", type=int, help="Limit accounts processed in this run.")
    parser.add_argument("--report-dir", default="reports", help="Directory for maintainer reports.")
    parser.add_argument("--report-file", help="Write the maintainer report to this exact file.")
    parser.add_argument("--web", action="store_true", help="Start the Web task console.")
    parser.add_argument("--host", default="127.0.0.1", help="Web host. Default: 127.0.0.1.")
    parser.add_argument("--port", default=8787, type=int, help="Web port. Default: 8787.")
    parser.add_argument("--web-token", help="Bearer token required for non-local Web access.")
    parser.add_argument(
        "--state-file",
        default=".nodeloc_state.json",
        help="Local completion state file. Default: .nodeloc_state.json.",
    )
    parser.add_argument("--daemon", action="store_true", help="Keep running and check in once per day.")
    parser.add_argument(
        "--run-at",
        default="08:10",
        type=parse_run_time,
        help="Daily run time for --daemon, local server time. Format: HH:MM. Default: 08:10.",
    )
    parser.add_argument("--run-now", action="store_true", help="With --daemon, run once immediately before sleeping.")
    parser.add_argument("--once", action="store_true", help="Skip delays between accounts for testing.")
    parser.add_argument("--verbose", action="store_true", help="Print more detailed logs.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    try:
        settings = apply_cli_overrides(load_settings(Path(args.config)), args)
    except Exception as exc:
        logging.error("Failed to load config: %s", exc)
        return 2

    if args.web:
        try:
            from nodeloc_maintainer.interfaces.web import run_web_server

            run_web_server(
                config_path=Path(args.config),
                state_file=Path(args.state_file),
                report_dir=Path(args.report_dir),
                host=args.host,
                port=args.port,
                token=args.web_token or os.environ.get("NODELOC_WEB_TOKEN"),
            )
            return 0
        except Exception as exc:
            logging.error("Failed to start Web console: %s", exc)
            return 2

    client_factory = NodeLocClientFactory(settings)
    state_store = CompletionStateStore(Path(args.state_file))
    date_provider = SystemDateProvider()
    checkin_service = CheckinService(settings, client_factory=client_factory)

    if args.maintain:
        maintainer = DailyMaintainer(
            settings=settings,
            state_store=state_store,
            date_provider=date_provider,
            checkin_service=checkin_service,
            stats_service=StatsService(client_factory),
            topic_service=TopicDiscoveryService(client_factory),
            reading_planner=ReadingPlanner(),
            browser_reader=build_browser_reader(settings, args),
        )

        def run_once() -> bool:
            report = maintainer.run_once(
                dry_run=args.dry_run,
                skip_delays=args.once,
                force_checkin=args.force,
                force_reading=args.force_reading,
                max_accounts=args.max_accounts,
            )
            content = ReportFormatter().maintenance_report(report)
            print(content, end="")
            path = build_report_writer(args).write(report.date_key, content)
            logging.info("report saved: %s", path)
            return report.ok

    else:
        runner = DailySignRunner(
            settings=settings,
            state_store=state_store,
            checkin_service=checkin_service,
            date_provider=date_provider,
        )

        def run_once() -> bool:
            return runner.run_once(dry_run=args.dry_run, skip_delays=args.once, force=args.force)

    if args.daemon:
        logging.info("Daemon mode enabled. Daily run time: %02d:%02d", args.run_at[0], args.run_at[1])
        if args.run_now:
            run_once()
        while True:
            sleep_until_next_run(args.run_at)
            run_once()

    return 0 if run_once() else 1


def apply_cli_overrides(settings: Settings, args: argparse.Namespace) -> Settings:
    reading = settings.reading
    if args.reading:
        reading = replace(reading, enabled=True)
    if args.no_reading:
        reading = replace(reading, enabled=False)
    if args.reading_minutes is not None:
        reading = replace(reading, minutes_per_account=args.reading_minutes)
    if args.topics_per_account is not None:
        reading = replace(reading, topics_per_account=args.topics_per_account)
    if args.headed:
        reading = replace(reading, headless=False)
    validate_reading(reading)
    return replace(settings, reading=reading)


def build_report_writer(args: argparse.Namespace):
    if args.report_file:
        return FixedPathReportWriter(Path(args.report_file))
    return FileReportWriter(Path(args.report_dir))


def build_browser_reader(settings: Settings, args: argparse.Namespace):
    if args.dry_run or (not settings.reading.enabled and not args.force_reading):
        return DisabledBrowserReader()
    try:
        from nodeloc_maintainer.infrastructure.playwright_reader import PlaywrightBrowserReader
    except ImportError as exc:
        raise RuntimeError("Playwright is required for browser reading. Run: python -m pip install playwright") from exc
    return PlaywrightBrowserReader(timeout_ms=int(settings.timeout_seconds * 1000))


class DisabledBrowserReader:
    def run(self, account, topics, settings, target_seconds):
        return ReadingSessionResult(
            account_name=account.name,
            ok=False,
            message="browser reading is disabled for this run",
        )
