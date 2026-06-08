from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from nodeloc_maintainer.infrastructure.config import load_settings


def read_config_sanitized(path: Path) -> dict[str, Any]:
    raw = read_raw_config(path)
    for account in raw.get("accounts", []):
        if isinstance(account, dict):
            account["cookie"] = mask_secret(str(account.get("cookie") or ""))
            account["csrf_token"] = mask_secret(str(account.get("csrf_token") or ""))
    return raw


def read_raw_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as file:
        return json.load(file)


def save_config_with_backup(path: Path, raw: dict[str, Any]) -> Path:
    raw = merge_preserved_secrets(read_raw_config(path), raw)
    backup_path = backup_config(path)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        load_settings(temp_path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
    temp_path.replace(path)
    return backup_path


def backup_config(path: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = path.with_name(f"{path.stem}.backup-{stamp}{path.suffix}")
    backup_path.write_text(path.read_text(encoding="utf-8-sig"), encoding="utf-8")
    return backup_path


def mask_secret(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    if len(value) <= 10:
        return "***"
    return f"{value[:6]}...{value[-4:]}"


def merge_preserved_secrets(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    existing_accounts = existing.get("accounts") if isinstance(existing.get("accounts"), list) else []
    incoming_accounts = incoming.get("accounts") if isinstance(incoming.get("accounts"), list) else []
    by_name = {
        str(account.get("name") or ""): account
        for account in existing_accounts
        if isinstance(account, dict)
    }

    for index, account in enumerate(incoming_accounts):
        if not isinstance(account, dict):
            continue
        existing_account = by_name.get(str(account.get("name") or ""))
        if existing_account is None and index < len(existing_accounts) and isinstance(existing_accounts[index], dict):
            existing_account = existing_accounts[index]
        if not existing_account:
            continue
        for key in ("cookie", "csrf_token"):
            value = str(account.get(key) or "")
            if is_masked_secret(value):
                account[key] = existing_account.get(key, "")
    return incoming


def is_masked_secret(value: str) -> bool:
    value = value.strip()
    return value == "***" or "..." in value
