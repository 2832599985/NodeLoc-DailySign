from __future__ import annotations

import secrets
import string
import time
from typing import Any

import requests

from nodeloc_maintainer.domain.models import Account, Settings
from nodeloc_maintainer.domain.site import BASE_URL, CHECKIN_URL, CSRF_URL, CURRENT_USER_URL


class NodeLocClient:
    """Protocol-level HTTP client for NodeLoc and Discourse endpoints."""

    def __init__(self, account: Account, settings: Settings):
        self.account = account
        self.settings = settings
        self.session = self._make_session()

    def _make_session(self) -> requests.Session:
        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": self.account.user_agent,
                "Accept": "*/*",
                "Accept-Language": "zh-CN,zh;q=0.9",
                "Cookie": self.account.cookie,
                "Origin": BASE_URL,
                "Referer": f"{BASE_URL}/",
                "Discourse-Logged-In": "true",
                "Discourse-Present": "true",
                "X-Discourse-Checkin": "true",
                "X-Requested-With": "XMLHttpRequest",
            }
        )
        if self.settings.proxy:
            session.proxies.update({"http": self.settings.proxy, "https": self.settings.proxy})
        return session

    def get_csrf_token(self) -> str:
        if self.account.csrf_token:
            return self.account.csrf_token

        response = self.session.get(
            CSRF_URL,
            headers={"Accept": "application/json"},
            timeout=self.settings.timeout_seconds,
        )
        response.raise_for_status()
        token = str(response.json().get("csrf") or "").strip()
        if not token:
            raise RuntimeError("Could not fetch csrf token. Put x-csrf-token into csrf_token manually.")
        return token

    def checkin(self, csrf_token: str) -> tuple[int, dict[str, Any]]:
        nonce = random_nonce()
        payload = {"nonce": nonce, "timestamp": str(current_timestamp_ms())}
        headers = {
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-CSRF-Token": csrf_token,
            "X-Checkin-Nonce": nonce,
        }
        response = self.session.post(
            CHECKIN_URL,
            headers=headers,
            data=payload,
            timeout=self.settings.timeout_seconds,
        )
        return response.status_code, decode_response(response)

    def current_user(self) -> dict[str, Any]:
        response = self.session.get(
            CURRENT_USER_URL,
            headers={"Accept": "application/json"},
            timeout=self.settings.timeout_seconds,
        )
        response.raise_for_status()
        return response.json().get("current_user") or {}

    def user_summary(self, username: str) -> dict[str, Any]:
        response = self.session.get(
            f"{BASE_URL}/u/{username}/summary.json",
            headers={"Accept": "application/json"},
            timeout=self.settings.timeout_seconds,
        )
        response.raise_for_status()
        return response.json().get("user_summary") or {}

    def user_detail(self, username: str) -> dict[str, Any]:
        response = self.session.get(
            f"{BASE_URL}/u/{username}.json",
            headers={"Accept": "application/json"},
            timeout=self.settings.timeout_seconds,
        )
        response.raise_for_status()
        return response.json().get("user") or {}

    def latest_topics(self, page: int = 0) -> list[dict[str, Any]]:
        response = self.session.get(
            f"{BASE_URL}/latest.json",
            params={"page": page},
            headers={"Accept": "application/json"},
            timeout=self.settings.timeout_seconds,
        )
        response.raise_for_status()
        return response.json().get("topic_list", {}).get("topics") or []


def random_nonce(length: int = 22) -> str:
    alphabet = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def current_timestamp_ms() -> int:
    return int(time.time() * 1000)


def decode_response(response: requests.Response) -> dict[str, Any]:
    try:
        return response.json()
    except ValueError:
        return {"success": False, "message": response.text[:300]}
