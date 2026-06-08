from __future__ import annotations

from nodeloc_maintainer.domain.models import AccountStats, ReadingDecision, ReadingSettings


class ReadingPlanner:
    """Decides whether a real browser reading session should run."""

    def decide(
        self,
        stats: AccountStats,
        settings: ReadingSettings,
        force: bool = False,
    ) -> ReadingDecision:
        if force:
            return ReadingDecision(
                account_name=stats.account_name,
                should_read=True,
                reason="forced by command line",
                target_seconds=minutes_to_seconds(settings.minutes_per_account),
            )

        if not settings.enabled:
            return ReadingDecision(
                account_name=stats.account_name,
                should_read=False,
                reason="reading disabled",
            )

        missing = []
        if settings.target_time_read_minutes and stats.time_read_minutes < settings.target_time_read_minutes:
            missing.append(
                f"time_read {stats.time_read_minutes}m < {settings.target_time_read_minutes}m"
            )
        if settings.target_topics_entered and stats.topics_entered < settings.target_topics_entered:
            missing.append(
                f"topics_entered {stats.topics_entered} < {settings.target_topics_entered}"
            )
        if settings.target_posts_read_count and stats.posts_read_count < settings.target_posts_read_count:
            missing.append(
                f"posts_read_count {stats.posts_read_count} < {settings.target_posts_read_count}"
            )

        has_targets = any(
            [
                settings.target_time_read_minutes,
                settings.target_topics_entered,
                settings.target_posts_read_count,
            ]
        )
        if has_targets and not missing:
            return ReadingDecision(
                account_name=stats.account_name,
                should_read=False,
                reason="reading targets already met",
            )

        reason = "; ".join(missing) if missing else "daily reading enabled"
        return ReadingDecision(
            account_name=stats.account_name,
            should_read=True,
            reason=reason,
            target_seconds=minutes_to_seconds(settings.minutes_per_account),
        )


def minutes_to_seconds(minutes: float) -> int:
    return max(0, int(round(minutes * 60)))
