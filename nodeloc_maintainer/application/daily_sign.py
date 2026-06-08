from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable

from nodeloc_maintainer.application.checkin import CheckinService
from nodeloc_maintainer.application.ports import CompletionStore, DateProvider
from nodeloc_maintainer.domain.models import Settings


class DailySignRunner:
    """Coordinates account-level check-in flow."""

    def __init__(
        self,
        settings: Settings,
        state_store: CompletionStore,
        checkin_service: CheckinService,
        date_provider: DateProvider,
        sleep_fn: Callable[[float], None] = time.sleep,
        jitter_fn: Callable[[float, float], float] = random.uniform,
    ):
        self.settings = settings
        self.state_store = state_store
        self.checkin_service = checkin_service
        self.date_provider = date_provider
        self.sleep_fn = sleep_fn
        self.jitter_fn = jitter_fn

    def run_once(self, dry_run: bool = False, skip_delays: bool = False, force: bool = False) -> bool:
        date_key = self.date_provider.today_key()
        state = self.state_store.load()
        success_count = 0

        for index, account in enumerate(self.settings.accounts, start=1):
            if not dry_run and not force and self.state_store.completed_today(account, date_key, state):
                logging.info("[%s] skip: already completed locally for %s", account.name, date_key)
                success_count += 1
                continue

            result = self.checkin_service.check_account(account, dry_run=dry_run)
            if result.message and dry_run:
                logging.info("[%s] %s", account.name, result.message)
            if result.ok:
                success_count += 1
                if not dry_run:
                    self.state_store.mark_completed(account, date_key, state)
                    self.state_store.save(state)

            if not skip_delays and index < len(self.settings.accounts):
                self.sleep_between_accounts()

        total = len(self.settings.accounts)
        logging.info("Done: %s/%s accounts completed", success_count, total)
        return success_count == total

    def sleep_between_accounts(self) -> None:
        wait = self.jitter_fn(self.settings.delay.min_seconds, self.settings.delay.max_seconds)
        if wait > 0:
            logging.info("wait %.1f seconds before next account", wait)
            self.sleep_fn(wait)
