from __future__ import annotations

from nodeloc_maintainer.application.ports import AccountClientFactory
from nodeloc_maintainer.domain.models import Account, AccountStats


class StatsService:
    """Collects account-level profile and reading statistics."""

    def __init__(self, client_factory: AccountClientFactory):
        self.client_factory = client_factory

    def collect(self, account: Account) -> AccountStats:
        client = self.client_factory.create(account)
        current_user = client.current_user()
        username = str(current_user.get("username") or "")
        summary = client.user_summary(username) if username else {}
        detail = client.user_detail(username) if username else {}
        time_read = detail.get("time_read")
        if time_read is None:
            time_read = summary.get("time_read")
        return AccountStats(
            account_name=account.name,
            username=username,
            trust_level=current_user.get("trust_level"),
            time_read_seconds=int(time_read or 0),
            topics_entered=int(summary.get("topics_entered") or 0),
            posts_read_count=int(summary.get("posts_read_count") or 0),
            days_visited=int(summary.get("days_visited") or 0),
            likes_given=int(summary.get("likes_given") or 0),
            likes_received=int(summary.get("likes_received") or 0),
            post_count=int(summary.get("post_count") or 0),
        )
