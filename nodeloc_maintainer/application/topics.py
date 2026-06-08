from __future__ import annotations

from nodeloc_maintainer.application.ports import AccountClientFactory
from nodeloc_maintainer.domain.models import Account, TopicCandidate
from nodeloc_maintainer.domain.site import BASE_URL


class TopicDiscoveryService:
    """Finds candidate topics for future reading sessions."""

    def __init__(self, client_factory: AccountClientFactory):
        self.client_factory = client_factory

    def latest(self, account: Account, limit: int = 20) -> list[TopicCandidate]:
        client = self.client_factory.create(account)
        topics = client.latest_topics()
        candidates: list[TopicCandidate] = []
        for topic in topics[:limit]:
            topic_id = int(topic.get("id") or 0)
            slug = str(topic.get("slug") or "")
            candidates.append(
                TopicCandidate(
                    topic_id=topic_id,
                    title=str(topic.get("title") or ""),
                    url=f"{BASE_URL}/t/{slug}/{topic_id}",
                    posts_count=int(topic.get("posts_count") or 0),
                    unread_posts=int(topic.get("unread_posts") or 0),
                )
            )
        return candidates
