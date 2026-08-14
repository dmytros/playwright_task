from __future__ import annotations

import os
from pathlib import Path

from playwright.sync_api import Browser, BrowserContext, Playwright

from linkedin.resilience import get_logger
from linkedin.settings import Settings

log = get_logger("browser")


def in_docker() -> bool:
    return os.getenv("IN_DOCKER", "").strip().lower() in {"1", "true", "yes"}


class BrowserService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def launch(self, playwright: Playwright) -> tuple[Browser, BrowserContext]:
        cfg = self.settings.runtime.get("browser") or {}
        headless = self.settings.headless
        use_storage_context = in_docker() or headless
        args = list(cfg.get("launch_args") or [])
        timeout_ms = int(cfg.get("default_timeout_ms") or 60_000)

        if use_storage_context:
            browser = playwright.chromium.launch(
                headless=headless,
                slow_mo=int(cfg.get("slow_mo_storage") or 20),
                args=args,
            )
            viewport = cfg.get("viewport") or {"width": 1280, "height": 900}
            kwargs: dict = {
                "viewport": viewport,
                "locale": cfg.get("locale") or "en-US",
                "user_agent": cfg.get("user_agent")
                or (
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                ),
            }
            if self.settings.storage_state.exists():
                kwargs["storage_state"] = str(self.settings.storage_state)
                print(f"[boot] storage_state ← {self.settings.storage_state}", flush=True)
            else:
                print("[boot] no storage_state — login required", flush=True)
            context = browser.new_context(**kwargs)
            context.set_default_timeout(timeout_ms)
            return browser, context

        profile = Path(".linkedin_profile").resolve()
        profile.mkdir(parents=True, exist_ok=True)
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile),
            headless=False,
            slow_mo=int(cfg.get("slow_mo_persistent") or 40),
            locale=cfg.get("locale") or "en-US",
            no_viewport=True,
            args=args + ["--start-maximized"],
        )
        context.set_default_timeout(timeout_ms)
        browser = context.browser
        assert browser is not None
        return browser, context

    def save_session(self, context: BrowserContext) -> Path:
        path = self.settings.storage_state
        context.storage_state(path=str(path))
        return path
