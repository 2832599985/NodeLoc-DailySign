from __future__ import annotations

from nodeloc_maintainer.domain.site import BASE_URL


def cookie_header_to_playwright_cookies(cookie_header: str, base_url: str = BASE_URL) -> list[dict]:
    domain = base_url.removeprefix("https://").removeprefix("http://")
    cookies = []
    for part in cookie_header.split(";"):
        part = part.strip()
        if not part:
            continue
        name, _, value = part.partition("=")
        cookies.append(
            {
                "name": name,
                "value": value,
                "domain": domain,
                "path": "/",
                "secure": base_url.startswith("https://"),
                "sameSite": "Lax",
            }
        )
    return cookies

