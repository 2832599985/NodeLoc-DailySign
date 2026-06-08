from __future__ import annotations

from typing import Any, Protocol

from nodeloc_maintainer.domain.models import Account, ReadingSessionResult, ReadingSettings, TopicCandidate


class AccountClient(Protocol):
    def get_csrf_token(self) -> str: ...

    def checkin(self, csrf_token: str) -> tuple[int, dict[str, Any]]: ...

    def current_user(self) -> dict[str, Any]: ...

    def user_summary(self, username: str) -> dict[str, Any]: ...

    def user_detail(self, username: str) -> dict[str, Any]: ...

    def latest_topics(self, page: int = 0) -> list[dict[str, Any]]: ...


class AccountClientFactory(Protocol):
    def create(self, account: Account) -> AccountClient: ...


class CompletionStore(Protocol):
    def load(self) -> dict[str, Any]: ...

    def save(self, state: dict[str, Any]) -> None: ...

    def completed_today(self, account: Account, date_key: str, state: dict[str, Any] | None = None) -> bool: ...

    def mark_completed(self, account: Account, date_key: str, state: dict[str, Any]) -> None: ...


class DateProvider(Protocol):
    def today_key(self) -> str: ...


class BrowserReader(Protocol):
    def run(
        self,
        account: Account,
        topics: list[TopicCandidate],
        settings: ReadingSettings,
        target_seconds: int,
    ) -> ReadingSessionResult: ...


class ReportWriter(Protocol):
    def write(self, date_key: str, content: str) -> str: ...
