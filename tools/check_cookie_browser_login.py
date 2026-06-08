import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from nodeloc_maintainer.infrastructure.browser import cookie_header_to_playwright_cookies


def main() -> None:
    config = json.loads(Path("accounts.json").read_text(encoding="utf-8-sig"))
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for account in config["accounts"]:
                context = browser.new_context(
                    user_agent=account.get("user_agent")
                    or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
                    locale="zh-CN",
                    timezone_id="Asia/Shanghai",
                )
                context.add_cookies(cookie_header_to_playwright_cookies(account["cookie"]))
                page = context.new_page()
                result = {"name": account["name"], "ok": False}
                try:
                    response = page.goto(
                        "https://www.nodeloc.com/session/current.json",
                        wait_until="domcontentloaded",
                        timeout=30000,
                    )
                    result["status"] = response.status if response else None
                    data = json.loads(page.locator("body").inner_text(timeout=5000))
                    user = data.get("current_user") or {}
                    if user.get("username"):
                        result.update(
                            {
                                "ok": True,
                                "username": user.get("username"),
                                "trust_level": user.get("trust_level"),
                            }
                        )
                    else:
                        result["message"] = "no current_user"
                except Exception as exc:
                    result["message"] = str(exc)
                print(json.dumps(result, ensure_ascii=False))
                context.close()
        finally:
            browser.close()


if __name__ == "__main__":
    main()
