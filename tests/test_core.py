import json

from nodeloc_maintainer.application.checkin import is_already_done, is_busy
from nodeloc_maintainer.application.daily_sign import DailySignRunner
from nodeloc_maintainer.application.maintainer import DailyMaintainer, calculate_delta
from nodeloc_maintainer.application.reader import ReadingPlanner
from nodeloc_maintainer.application.reporting import ReportFormatter
from nodeloc_maintainer.application.stats import StatsService
from nodeloc_maintainer.application.tasks import TaskBusyError, TaskOptions, TaskSupervisor
from nodeloc_maintainer.application.topics import TopicDiscoveryService
from nodeloc_maintainer.domain.models import AccountStats, CheckinResult, ReadingSessionResult, ReadingSettings, TopicCandidate
from nodeloc_maintainer.infrastructure.config import load_settings
from nodeloc_maintainer.infrastructure.config_writer import read_config_sanitized, save_config_with_backup
from nodeloc_maintainer.infrastructure.playwright_reader import per_topic_stay_seconds
from nodeloc_maintainer.infrastructure.state import CompletionStateStore
from nodeloc_maintainer.interfaces.web import safe_report_path, validate_web_security


class FakeCheckinService:
    def __init__(self):
        self.calls = []

    def check_account(self, account, dry_run=False):
        self.calls.append(account.name)
        return CheckinResult(account_name=account.name, ok=True, completed=True, message="ok")


class FixedDateProvider:
    def today_key(self):
        return "2026-06-08"


class FakeClient:
    def __init__(self, time_read=125):
        self.time_read = time_read

    def current_user(self):
        return {"username": "user1", "trust_level": 0}

    def user_summary(self, username):
        return {
            "time_read": self.time_read,
            "topics_entered": 3,
            "posts_read_count": 12,
            "days_visited": 2,
            "likes_given": 1,
            "likes_received": 2,
            "post_count": 4,
        }

    def user_detail(self, username):
        return {"time_read": self.time_read + 10}

    def latest_topics(self, page=0):
        return [
            {
                "id": 123,
                "slug": "hello-world",
                "title": "Hello World",
                "posts_count": 5,
                "unread_posts": 2,
            }
        ]


class FakeClientFactory:
    def __init__(self):
        self.accounts = []

    def create(self, account):
        self.accounts.append(account.name)
        return FakeClient()


class FakeBrowserReader:
    def __init__(self):
        self.calls = []

    def run(self, account, topics, settings, target_seconds):
        self.calls.append((account.name, len(topics), target_seconds))
        return ReadingSessionResult(
            account_name=account.name,
            ok=True,
            message="fake reading ok",
            topics_visited=len(topics),
            seconds_spent=target_seconds,
            topic_urls=[topic.url for topic in topics],
            data={"timing_requests": 1},
        )


class RescueBrowserReader:
    def __init__(self):
        self.topic_batches = []

    def run(self, account, topics, settings, target_seconds):
        self.topic_batches.append([topic.topic_id for topic in topics])
        return ReadingSessionResult(
            account_name=account.name,
            ok=True,
            message="fake rescue reading ok",
            topics_visited=len(topics),
            seconds_spent=target_seconds,
            topic_urls=[topic.url for topic in topics],
            data={"timing_requests": len(self.topic_batches)},
        )


class RescueStatsService:
    def __init__(self):
        self.calls = 0

    def collect(self, account):
        self.calls += 1
        time_read = 100 if self.calls < 7 else 130
        return AccountStats(account.name, "user1", 0, time_read_seconds=time_read)


class RescueTopicService:
    def latest(self, account, limit=20):
        return [
            TopicCandidate(topic_id=index, title=f"topic {index}", url=f"https://www.nodeloc.com/t/topic/{index}")
            for index in range(1, limit + 1)
        ]


def write_config(path):
    path.write_text(
        json.dumps(
            {
                "accounts": [
                    {"name": "a1", "cookie": "_t=fake; _forum_session=fake"},
                    {"name": "a2", "cookie": "_t=fake2; _forum_session=fake2"},
                ],
                "delay_seconds": {"min": 8, "max": 25},
                "retry": {"on_busy": 2, "delay_seconds": 60},
                "reading": {
                    "enabled": False,
                    "minutes_per_account": 1,
                    "topics_per_account": 2,
                    "min_stay_seconds": 1,
                    "max_stay_seconds": 3,
                    "scrolls_per_topic": 2,
                    "headless": True,
                    "target_time_read_minutes": 0,
                    "target_topics_entered": 0,
                    "target_posts_read_count": 0,
                },
                "timeout_seconds": 30,
                "proxy": "",
            }
        ),
        encoding="utf-8",
    )


def test_response_classification():
    assert is_busy(429, {"success": False, "message": "please wait"})
    assert is_busy(200, {"success": False, "message": "\u8bf7\u7a0d\u7b49\u518d\u8bd5"})
    assert is_already_done({"success": False, "message": "\u60a8\u4eca\u5929\u5df2\u7ecf\u7b7e\u5230\u8fc7\u4e86"})


def test_settings_loads_accounts(tmp_path):
    config_path = tmp_path / "accounts.json"
    write_config(config_path)
    settings = load_settings(config_path)
    assert len(settings.accounts) == 2
    assert settings.delay.min_seconds == 8
    assert settings.retry.on_busy == 2
    assert settings.reading.minutes_per_account == 1
    assert settings.reading.topics_per_account == 2


def test_runner_skips_locally_completed_accounts(tmp_path):
    config_path = tmp_path / "accounts.json"
    write_config(config_path)
    settings = load_settings(config_path)
    state_store = CompletionStateStore(tmp_path / "state.json")
    state = {"accounts": {}}
    date_provider = FixedDateProvider()
    state_store.mark_completed(settings.accounts[0], date_provider.today_key(), state)
    state_store.save(state)

    service = FakeCheckinService()
    runner = DailySignRunner(settings, state_store, checkin_service=service, date_provider=date_provider)

    assert runner.run_once(skip_delays=True)
    assert service.calls == [settings.accounts[1].name]


def test_report_formatter_keeps_stats_presentation_separate(tmp_path):
    config_path = tmp_path / "accounts.json"
    write_config(config_path)
    settings = load_settings(config_path)

    lines = ReportFormatter().stats_lines(
        [
            AccountStats(
                account_name=settings.accounts[0].name,
                username="user1",
                trust_level=0,
                time_read_seconds=125,
                topics_entered=3,
                posts_read_count=12,
                days_visited=2,
            )
        ]
    )

    assert lines == ["a1: user=user1, tl=0, read=2.08m, topics=3, posts=12, days=2"]


def test_stats_and_topics_use_client_factory(tmp_path):
    config_path = tmp_path / "accounts.json"
    write_config(config_path)
    settings = load_settings(config_path)
    factory = FakeClientFactory()

    stats = StatsService(factory).collect(settings.accounts[0])
    topics = TopicDiscoveryService(factory).latest(settings.accounts[0])

    assert stats == AccountStats(
        account_name="a1",
        username="user1",
        trust_level=0,
        time_read_seconds=135,
        topics_entered=3,
        posts_read_count=12,
        days_visited=2,
        likes_given=1,
        likes_received=2,
        post_count=4,
    )
    assert topics[0].url == "https://www.nodeloc.com/t/hello-world/123"
    assert factory.accounts == ["a1", "a1"]


def test_reading_planner_respects_enabled_and_targets():
    stats = AccountStats(
        account_name="a1",
        username="user1",
        trust_level=0,
        time_read_seconds=125,
        topics_entered=3,
        posts_read_count=12,
    )
    planner = ReadingPlanner()

    disabled = planner.decide(stats, ReadingSettings(enabled=False))
    assert not disabled.should_read

    target_met = planner.decide(stats, ReadingSettings(enabled=True, target_time_read_minutes=1))
    assert not target_met.should_read

    target_missing = planner.decide(stats, ReadingSettings(enabled=True, target_time_read_minutes=10))
    assert target_missing.should_read
    assert "time_read" in target_missing.reason

    forced = planner.decide(stats, ReadingSettings(enabled=False, minutes_per_account=0.5), force=True)
    assert forced.should_read
    assert forced.target_seconds == 30


def test_maintainer_runs_cookie_check_checkin_reading_and_report(tmp_path):
    config_path = tmp_path / "accounts.json"
    write_config(config_path)
    settings = load_settings(config_path)
    settings = settings.__class__(
        accounts=settings.accounts,
        delay=settings.delay,
        retry=settings.retry,
        reading=ReadingSettings(
            enabled=True,
            minutes_per_account=0.1,
            topics_per_account=1,
            min_stay_seconds=1,
            max_stay_seconds=2,
            scrolls_per_topic=1,
        ),
        timeout_seconds=settings.timeout_seconds,
        proxy=settings.proxy,
    )
    state_store = CompletionStateStore(tmp_path / "state.json")
    browser_reader = FakeBrowserReader()
    maintainer = DailyMaintainer(
        settings=settings,
        state_store=state_store,
        date_provider=FixedDateProvider(),
        checkin_service=FakeCheckinService(),
        stats_service=StatsService(FakeClientFactory()),
        topic_service=TopicDiscoveryService(FakeClientFactory()),
        reading_planner=ReadingPlanner(),
        browser_reader=browser_reader,
    )

    report = maintainer.run_once(skip_delays=True, max_accounts=1)
    text = ReportFormatter().maintenance_report(report)

    assert report.ok
    assert browser_reader.calls == [("a1", 1, 6)]
    assert "cookie: ok" in text
    assert "checkin: ok" in text
    assert "reading: ok" in text


def test_maintainer_dry_run_skips_real_browser(tmp_path):
    config_path = tmp_path / "accounts.json"
    write_config(config_path)
    settings = load_settings(config_path)
    settings = settings.__class__(
        accounts=settings.accounts,
        delay=settings.delay,
        retry=settings.retry,
        reading=ReadingSettings(enabled=True, minutes_per_account=0.1, topics_per_account=1),
        timeout_seconds=settings.timeout_seconds,
        proxy=settings.proxy,
    )
    browser_reader = FakeBrowserReader()
    maintainer = DailyMaintainer(
        settings=settings,
        state_store=CompletionStateStore(tmp_path / "state.json"),
        date_provider=FixedDateProvider(),
        checkin_service=FakeCheckinService(),
        stats_service=StatsService(FakeClientFactory()),
        topic_service=TopicDiscoveryService(FakeClientFactory()),
        reading_planner=ReadingPlanner(),
        browser_reader=browser_reader,
    )

    report = maintainer.run_once(dry_run=True, skip_delays=True, max_accounts=1)

    assert report.ok
    assert browser_reader.calls == []
    assert report.results[0].reading_result.message.startswith("dry-run")


def test_maintainer_retries_reading_with_new_topics_when_metrics_do_not_change(tmp_path):
    config_path = tmp_path / "accounts.json"
    write_config(config_path)
    settings = load_settings(config_path)
    settings = settings.__class__(
        accounts=settings.accounts,
        delay=settings.delay,
        retry=settings.retry,
        reading=ReadingSettings(
            enabled=True,
            minutes_per_account=0.1,
            topics_per_account=1,
            min_stay_seconds=1,
            max_stay_seconds=2,
            scrolls_per_topic=1,
            rescue_attempts=2,
            rescue_topic_multiplier=3,
        ),
        timeout_seconds=settings.timeout_seconds,
        proxy=settings.proxy,
    )
    browser_reader = RescueBrowserReader()
    maintainer = DailyMaintainer(
        settings=settings,
        state_store=CompletionStateStore(tmp_path / "state.json"),
        date_provider=FixedDateProvider(),
        checkin_service=FakeCheckinService(),
        stats_service=RescueStatsService(),
        topic_service=RescueTopicService(),
        reading_planner=ReadingPlanner(),
        browser_reader=browser_reader,
        sleep_fn=lambda seconds: None,
    )

    report = maintainer.run_once(skip_delays=True, max_accounts=1)

    assert browser_reader.topic_batches == [[1], [2]]
    assert report.results[0].metrics_delta.time_read_seconds == 30
    assert report.results[0].reading_result.attempts == 2


def test_playwright_reader_stay_time_is_bounded():
    settings = ReadingSettings(min_stay_seconds=2, max_stay_seconds=5)
    assert per_topic_stay_seconds(remaining=30, remaining_topics=10, settings=settings) == 3
    assert per_topic_stay_seconds(remaining=3, remaining_topics=1, settings=settings) == 3
    assert per_topic_stay_seconds(remaining=30, remaining_topics=1, settings=settings) == 5


def test_report_formatter_shows_metric_delta():
    before = AccountStats("a1", "user1", 0, time_read_seconds=60, topics_entered=1, posts_read_count=2)
    after = AccountStats("a1", "user1", 0, time_read_seconds=90, topics_entered=2, posts_read_count=4)
    delta = calculate_delta(before, after)

    assert delta.time_read_seconds == 30
    assert delta.topics_entered == 1
    assert delta.posts_read_count == 2
    assert delta.changed


def test_task_supervisor_rejects_concurrent_jobs():
    supervisor = TaskSupervisor()

    def runner(task, emit):
        emit("info", "started", None, "started")
        return None

    first = supervisor.start(TaskOptions(mode="dry_run"), runner)
    first.status = "running"

    try:
        supervisor.start(TaskOptions(mode="dry_run"), runner)
        raised = False
    except TaskBusyError:
        raised = True

    assert raised


def test_task_options_include_reading_overrides_and_rounds():
    supervisor = TaskSupervisor()

    def runner(task, emit):
        return None

    task = supervisor.start(TaskOptions(mode="dry_run", reading_minutes=0.5, topics_per_account=1, rounds=3), runner)
    task.status = "succeeded"
    status = supervisor.status()

    assert status["current"]["options"]["reading_minutes"] == 0.5
    assert status["current"]["options"]["topics_per_account"] == 1
    assert status["current"]["options"]["rounds"] == 3


def test_web_security_requires_token_for_public_host():
    validate_web_security("127.0.0.1", None)

    try:
        validate_web_security("0.0.0.0", None)
        raised = False
    except ValueError:
        raised = True

    assert raised
    validate_web_security("0.0.0.0", "token")


def test_report_path_rejects_traversal(tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir()
    report = reports / "ok.txt"
    report.write_text("ok", encoding="utf-8")

    assert safe_report_path(reports, "ok.txt") == report.resolve()

    try:
        safe_report_path(reports, "..\\accounts.json")
        raised = False
    except Exception:
        raised = True

    assert raised


def test_config_writer_masks_and_preserves_existing_secrets(tmp_path):
    config_path = tmp_path / "accounts.json"
    write_config(config_path)

    sanitized = read_config_sanitized(config_path)
    assert "..." in sanitized["accounts"][0]["cookie"]

    sanitized["delay_seconds"]["min"] = 1
    backup = save_config_with_backup(config_path, sanitized)
    saved = json.loads(config_path.read_text(encoding="utf-8"))

    assert backup.exists()
    assert saved["accounts"][0]["cookie"] == "_t=fake; _forum_session=fake"
    assert saved["delay_seconds"]["min"] == 1
