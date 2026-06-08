from __future__ import annotations

import logging
import math
import random
import time
from collections.abc import Callable

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from nodeloc_maintainer.domain.models import Account, ReadingSessionResult, ReadingSettings, TopicCandidate
from nodeloc_maintainer.domain.site import BASE_URL
from nodeloc_maintainer.infrastructure.browser import cookie_header_to_playwright_cookies


class PlaywrightBrowserReader:
    """Runs a real browser reading session for Discourse frontend metrics."""

    def __init__(
        self,
        timeout_ms: int = 30000,
        sleep_fn: Callable[[float], None] = time.sleep,
        jitter_fn: Callable[[float, float], float] = random.uniform,
    ):
        self.timeout_ms = timeout_ms
        self.sleep_fn = sleep_fn
        self.jitter_fn = jitter_fn

    def run(
        self,
        account: Account,
        topics: list[TopicCandidate],
        settings: ReadingSettings,
        target_seconds: int,
    ) -> ReadingSessionResult:
        if not topics:
            return ReadingSessionResult(
                account_name=account.name,
                ok=False,
                message="no readable topic candidates",
            )
        if target_seconds <= 0:
            return ReadingSessionResult(
                account_name=account.name,
                ok=True,
                message="target reading time is 0 seconds",
            )

        selected = topics[: settings.topics_per_account]
        started = time.monotonic()
        visited: list[str] = []
        timing_requests: list[str] = []

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=settings.headless)
            context = browser.new_context(
                user_agent=account.user_agent,
                locale="zh-CN",
                timezone_id="Asia/Shanghai",
            )
            context.add_cookies(cookie_header_to_playwright_cookies(account.cookie, BASE_URL))
            page = context.new_page()
            page.on("request", lambda request: track_timing_request(request.url, timing_requests))
            try:
                self._verify_login(page)
                for index, topic in enumerate(selected, start=1):
                    remaining = target_seconds - int(time.monotonic() - started)
                    if remaining <= 0:
                        break
                    stay = per_topic_stay_seconds(
                        remaining=remaining,
                        remaining_topics=len(selected) - index + 1,
                        settings=settings,
                    )
                    logging.info("[%s] reading topic %s for %.1fs: %s", account.name, index, stay, topic.url)
                    self._read_topic(page, topic.url, stay, settings)
                    visited.append(topic.url)
            finally:
                context.close()
                browser.close()

        spent = int(time.monotonic() - started)
        return ReadingSessionResult(
            account_name=account.name,
            ok=True,
            message="browser reading session completed",
            topics_visited=len(visited),
            seconds_spent=spent,
            topic_urls=visited,
            data={"timing_requests": len(timing_requests)},
        )

    def _verify_login(self, page) -> None:
        response = page.goto(
            f"{BASE_URL}/session/current.json",
            wait_until="domcontentloaded",
            timeout=self.timeout_ms,
        )
        if response and response.status >= 400:
            raise RuntimeError(f"current user request failed with HTTP {response.status}")
        body = page.locator("body").inner_text(timeout=5000)
        if '"username"' not in body:
            raise RuntimeError("browser cookie did not load a logged-in user")

    def _read_topic(self, page, url: str, stay_seconds: float, settings: ReadingSettings) -> None:
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            page.locator("body").wait_for(state="visible", timeout=5000)
            page.locator("#topic, .topic-post, article").first.wait_for(state="visible", timeout=10000)
        except PlaywrightTimeoutError:
            logging.warning("topic load timed out, continuing with visible page: %s", url)

        scroll_count = max(1, settings.scrolls_per_topic)
        segment = stay_seconds / scroll_count if scroll_count else stay_seconds
        for step in range(scroll_count):
            self.sleep_fn(max(0, segment * 0.65))
            scroll_px = int(self.jitter_fn(320, 900))
            page.mouse.wheel(0, scroll_px)
            page.wait_for_timeout(int(max(100, segment * 350)))
            if step % 3 == 2:
                page.mouse.wheel(0, -int(scroll_px / 3))
        page.wait_for_timeout(1500)


def per_topic_stay_seconds(remaining: int, remaining_topics: int, settings: ReadingSettings) -> float:
    fair_share = remaining / max(1, remaining_topics)
    lower = min(settings.min_stay_seconds, remaining)
    upper = min(settings.max_stay_seconds, remaining)
    if upper <= lower:
        return max(0, upper)
    target = min(max(fair_share, lower), upper)
    return math.floor(target)


def track_timing_request(url: str, timing_requests: list[str]) -> None:
    if "/topics/timings" in url:
        timing_requests.append(url)
