from __future__ import annotations

from datetime import datetime


class SystemDateProvider:
    def today_key(self) -> str:
        return datetime.now().date().isoformat()

