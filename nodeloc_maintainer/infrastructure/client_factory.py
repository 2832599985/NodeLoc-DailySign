from __future__ import annotations

from nodeloc_maintainer.domain.models import Account, Settings
from nodeloc_maintainer.infrastructure.http_client import NodeLocClient


class NodeLocClientFactory:
    def __init__(self, settings: Settings):
        self.settings = settings

    def create(self, account: Account) -> NodeLocClient:
        return NodeLocClient(account, self.settings)

