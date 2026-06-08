from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from nodeloc_maintainer.domain.models import Account


class CompletionStateStore:
    """Stores same-day completion to avoid repeated check-in requests."""

    def __init__(self, path: Path):
        self.path = path

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"accounts": {}}
        with self.path.open("r", encoding="utf-8-sig") as file:
            data = json.load(file)
        if not isinstance(data, dict):
            return {"accounts": {}}
        if not isinstance(data.get("accounts"), dict):
            data["accounts"] = {}
        return data

    def save(self, state: dict[str, Any]) -> None:
        with self.path.open("w", encoding="utf-8") as file:
            json.dump(state, file, ensure_ascii=False, indent=2)
            file.write("\n")

    def completed_today(self, account: Account, date_key: str, state: dict[str, Any] | None = None) -> bool:
        state = state if state is not None else self.load()
        record = state.get("accounts", {}).get(account.name)
        return isinstance(record, dict) and record.get("date") == date_key

    def mark_completed(self, account: Account, date_key: str, state: dict[str, Any]) -> None:
        state.setdefault("accounts", {})[account.name] = {
            "date": date_key,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }


def today_key() -> str:
    return datetime.now().date().isoformat()

