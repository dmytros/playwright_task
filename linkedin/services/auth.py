from __future__ import annotations

import subprocess
import sys

from playwright.sync_api import Page

from linkedin.resilience import get_logger, pause_range
from linkedin.services.browser import in_docker
from linkedin.settings import Settings

log = get_logger("auth")


def _focus_browser() -> None:
    if sys.platform != "darwin" or in_docker():
        return
    script = (
        'tell application "System Events" to set frontmost of '
        'first process whose name contains "Chrome for Testing" to true'
    )
    subprocess.run(["osascript", "-e", script], check=False, capture_output=True)


class AuthService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def ensure_login(self, page: Page) -> None:
        print("[auth] opening feed…", flush=True)
        page.goto(self.settings.feed_url, wait_until="domcontentloaded")
        if not self.settings.headless:
            try:
                page.bring_to_front()
            except Exception:
                pass
            _focus_browser()
        pause_range(self.settings.pause("after_nav"))
        if self._logged_in(page):
            print("[auth] already logged in", flush=True)
            return

        if in_docker() or self.settings.headless:
            try:
                page.screenshot(path="feed_debug_auth.png")
            except Exception:
                pass
            raise RuntimeError(
                "Not logged in inside container. Run once on the host (headed) to refresh "
                ".linkedin_storage.json, then re-run: docker compose up --build agent"
            )

        print("[auth] >>> Log in inside Google Chrome for Testing", flush=True)
        page.goto(self.settings.login_url, wait_until="domcontentloaded")
        page.bring_to_front()
        _focus_browser()
        self._wait_until_feed(page)

    def _logged_in(self, page: Page) -> bool:
        auth_cfg = self.settings.runtime.get("auth") or {}
        blocked = tuple(auth_cfg.get("blocked_url_parts") or ())
        url = page.url.lower()
        if any(p in url for p in blocked):
            return False
        if "/feed" in url:
            return True
        nav = self.settings.selectors.get("nav", "")
        try:
            if nav and page.locator(nav).count() > 0:
                return True
        except Exception:
            pass
        try:
            if page.locator('[data-testid="mainFeed"]').count() > 0:
                return True
        except Exception:
            pass
        try:
            if "linkedin.com" in url and any(
                c.get("name") == "li_at" for c in page.context.cookies()
            ):
                return True
        except Exception:
            pass
        return self._is_feed(page)

    def _wait_until_feed(self, page: Page) -> None:
        auth_cfg = self.settings.runtime.get("auth") or {}
        timeout_s = int(auth_cfg.get("wait_timeout_s") or 1200)
        interval_s = float(auth_cfg.get("poll_interval_s") or 3.0)
        rounds = int(timeout_s / interval_s)
        print(
            f"[auth] waiting up to {timeout_s // 60} min for /feed/ "
            "in Google Chrome for Testing (not regular Chrome)…",
            flush=True,
        )
        for i in range(rounds):
            try:
                for p in list(page.context.pages):
                    if self._logged_in(p):
                        if "/feed" not in p.url.lower():
                            try:
                                p.goto(self.settings.feed_url, wait_until="domcontentloaded")
                            except Exception:
                                pass
                        print(f"[auth] logged in → {p.url}", flush=True)
                        return
            except Exception as exc:
                print(f"[auth] check failed: {exc}", flush=True)
                log.warning("auth check failed: %s", exc)
                pause_range([interval_s, interval_s])
                continue

            if i % 20 == 0:
                try:
                    urls = " | ".join(p.url for p in page.context.pages)
                except Exception:
                    urls = "(browser closed?)"
                print(f"[auth] still waiting… ({i * interval_s:.0f}s) tabs={urls}", flush=True)
            pause_range([interval_s, interval_s])

        raise RuntimeError(
            "Timed out waiting for feed — finish login/2FA in Google Chrome for Testing"
        )

    def _is_feed(self, page: Page) -> bool:
        from playwright.sync_api import TimeoutError as PWTimeout

        if "/feed" not in page.url.lower():
            return False
        nav = self.settings.selectors.get("nav", "")
        try:
            if nav:
                page.locator(nav).first.wait_for(timeout=4_000)
            return True
        except PWTimeout:
            return "/feed" in page.url
