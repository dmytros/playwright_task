from __future__ import annotations

from pathlib import Path

from playwright.sync_api import Browser, BrowserContext, Page, Playwright

from linkedin.data import (
    FeedSource,
    ProfileSource,
    create_feed_source,
    create_profile_source,
)
from linkedin.models import Post, ProfileBits
from linkedin.services.auth import AuthService
from linkedin.services.browser import BrowserService
from linkedin.services.engagement import EngagementService
from linkedin.settings import Settings


class LinkedIn:
    """Facade composing browser, auth, feed, engagement, and profile services."""

    def __init__(
        self,
        settings: Settings,
        *,
        feed_source: FeedSource | None = None,
        profile_source: ProfileSource | None = None,
    ) -> None:
        self.settings = settings
        self.browser = BrowserService(settings)
        self.auth = AuthService(settings)
        self.engagement = EngagementService(settings)
        self.feed_source = feed_source or create_feed_source(settings)
        self.profile_source = profile_source or create_profile_source(settings)

    def launch(self, playwright: Playwright) -> tuple[Browser, BrowserContext]:
        return self.browser.launch(playwright)

    def save_session(self, context: BrowserContext) -> Path:
        return self.browser.save_session(context)

    def ensure_login(self, page: Page) -> None:
        self.auth.ensure_login(page)

    def read_feed(self, page: Page, limit: int = 35) -> list[Post]:
        return self.feed_source.read_posts(page, limit=limit)

    def like(self, page: Page, post: Post) -> str:
        return self.engagement.like(page, post)

    def profile_bits(self, page: Page, post: Post) -> dict[str, str]:
        bits = self.profile_source.read_profile(page, post)
        if isinstance(bits, ProfileBits):
            return bits.as_dict()
        return bits
