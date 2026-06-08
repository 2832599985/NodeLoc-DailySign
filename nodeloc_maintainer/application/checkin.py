from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from typing import Any

from nodeloc_maintainer.application.ports import AccountClientFactory
from nodeloc_maintainer.domain.models import Account, CheckinResult, Settings
from nodeloc_maintainer.domain.site import ALREADY_DONE_TEXT, BUSY_TEXT, LOGIN_TEXT


class CheckinService:
    """Business logic for daily check-in and retry handling."""

    def __init__(
        self,
        settings: Settings,
        client_factory: AccountClientFactory,
        sleep_fn: Callable[[float], None] = time.sleep,
        jitter_fn: Callable[[float, float], float] = random.uniform,
    ):
        self.settings = settings
        self.client_factory = client_factory
        self.sleep_fn = sleep_fn
        self.jitter_fn = jitter_fn

    def check_account(self, account: Account, dry_run: bool = False) -> CheckinResult:
        logging.info("[%s] start", account.name)
        if dry_run:
            return CheckinResult(
                account_name=account.name,
                ok=True,
                completed=True,
                message="dry-run: config loaded, real check-in skipped",
            )

        client = self.client_factory.create(account)
        try:
            csrf_token = client.get_csrf_token()
        except Exception as exc:
            return CheckinResult(account_name=account.name, ok=False, message=f"csrf token failed: {exc}")

        attempts = self.settings.retry.on_busy + 1
        last_result: CheckinResult | None = None
        for attempt in range(1, attempts + 1):
            try:
                status_code, data = client.checkin(csrf_token)
            except Exception as exc:
                return CheckinResult(account_name=account.name, ok=False, message=f"request failed: {exc}")

            message = classify_result(status_code, data)
            result = CheckinResult(
                account_name=account.name,
                ok=data.get("success") is True or is_already_done(data),
                completed=data.get("success") is True or is_already_done(data),
                busy=is_busy(status_code, data),
                status_code=status_code,
                data=data,
                message=message,
            )
            logging.info(
                "[%s] attempt %s/%s: HTTP %s, %s",
                account.name,
                attempt,
                attempts,
                status_code,
                message,
            )

            if result.completed:
                return result
            if result.busy and attempt < attempts:
                wait = self.settings.retry.delay_seconds + self.jitter_fn(0, 10)
                logging.info("[%s] wait %.1f seconds before retry", account.name, wait)
                self.sleep_fn(wait)
                last_result = result
                continue
            return result

        return last_result or CheckinResult(account_name=account.name, ok=False, message="check-in failed")


def classify_result(status_code: int, data: dict[str, Any]) -> str:
    if data.get("success") is True:
        points = data.get("points")
        date = data.get("user_date")
        return f"check-in succeeded, points={points}, date={date}"

    message = str(data.get("message") or "").strip()
    if status_code == 429 or BUSY_TEXT in message:
        return f"busy or too fast: {message or 'HTTP 429'}"
    if ALREADY_DONE_TEXT in message:
        return f"already checked in today: {message}"
    if LOGIN_TEXT in message or "log" in message.lower():
        return f"possibly logged out or cookie expired: {message or data}"
    return f"check-in failed: {message or data}"


def is_busy(status_code: int, data: dict[str, Any]) -> bool:
    message = str(data.get("message") or "")
    return status_code == 429 or BUSY_TEXT in message


def is_already_done(data: dict[str, Any]) -> bool:
    return ALREADY_DONE_TEXT in str(data.get("message") or "")
