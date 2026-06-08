from __future__ import annotations

from nodeloc_maintainer.domain.models import AccountStats, MaintenanceRunReport


class ReportFormatter:
    """Formats maintainer results without owning collection or automation logic."""

    def stats_lines(self, stats: list[AccountStats]) -> list[str]:
        lines = []
        for item in stats:
            lines.append(
                (
                    f"{item.account_name}: user={item.username}, tl={item.trust_level}, "
                    f"read={item.time_read_minutes}m, topics={item.topics_entered}, "
                    f"posts={item.posts_read_count}, days={item.days_visited}"
                )
            )
        return lines

    def maintenance_report(self, report: MaintenanceRunReport) -> str:
        mode = "dry-run" if report.dry_run else "real"
        lines = [
            f"NodeLoc daily maintainer report",
            f"date: {report.date_key}",
            f"mode: {mode}",
            f"accounts: {len(report.results)}",
            "",
        ]
        for result in report.results:
            lines.extend(self._account_lines(result))
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    def _account_lines(self, result) -> list[str]:
        lines = [f"[{result.account_name}]"]
        lines.append(f"cookie: {'ok' if result.cookie_ok else 'failed'} - {result.cookie_message}")

        if result.checkin_result:
            status = "ok" if result.checkin_result.ok else "failed"
            lines.append(f"checkin: {status} - {result.checkin_result.message}")

        if result.stats_before:
            lines.append(f"stats before: {format_stats(result.stats_before)}")

        if result.reading_decision:
            decision = "read" if result.reading_decision.should_read else "skip"
            lines.append(f"reading decision: {decision} - {result.reading_decision.reason}")

        if result.reading_result:
            status = "ok" if result.reading_result.ok else "failed"
            timing_requests = result.reading_result.data.get("timing_requests", 0)
            lines.append(
                (
                    f"reading: {status} - {result.reading_result.message}; "
                    f"topics={result.reading_result.topics_visited}, "
                    f"seconds={result.reading_result.seconds_spent}, "
                    f"timing_requests={timing_requests}, "
                    f"attempts={result.reading_result.attempts}"
                )
            )

        if result.stats_after and result.reading_result:
            lines.append(f"stats after: {format_stats(result.stats_after)}")
        if result.metrics_delta and result.reading_result:
            marker = "" if result.metrics_delta.changed else " metrics_not_changed"
            lines.append(f"delta: {format_delta(result.metrics_delta)}{marker}")

        return lines


def format_stats(stats: AccountStats) -> str:
    return (
        f"user={stats.username}, tl={stats.trust_level}, read={stats.time_read_minutes}m, "
        f"topics={stats.topics_entered}, posts={stats.posts_read_count}, days={stats.days_visited}"
    )


def format_delta(delta) -> str:
    return (
        f"read +{delta.time_read_seconds}s, topics +{delta.topics_entered}, "
        f"posts +{delta.posts_read_count}, days +{delta.days_visited}"
    )
