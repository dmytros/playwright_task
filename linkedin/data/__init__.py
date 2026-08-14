from __future__ import annotations

import random
from abc import ABC, abstractmethod

from linkedin.models import Post, ProfileBits
from linkedin.parsers import create_feed_parser
from linkedin.resilience import get_logger, pause_range
from linkedin.settings import Settings

log = get_logger("data")


class FeedSource(ABC):
    """Data-access abstraction over a concrete feed source / DOM format."""

    @abstractmethod
    def read_posts(self, page, *, limit: int | None = None) -> list[Post]:
        raise NotImplementedError


class ProfileSource(ABC):
    @abstractmethod
    def read_profile(self, page, post: Post) -> ProfileBits:
        raise NotImplementedError


class PlaywrightFeedSource(FeedSource):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._parser = create_feed_parser(
            settings.parsing,
            base_url=settings.base_url,
        )

    def read_posts(self, page, *, limit: int | None = None) -> list[Post]:
        from playwright.sync_api import TimeoutError as PWTimeout

        feed_cfg = self.settings.parsing.get("feed") or {}
        default_limit = int(feed_cfg.get("default_limit") or 35)
        limit = default_limit if limit is None else limit
        max_scrolls = int(feed_cfg.get("max_scrolls") or 4)
        stagnant_limit = int(feed_cfg.get("stagnant_limit") or 2)
        scroll_delta = feed_cfg.get("scroll_delta") or [700, 1100]
        wait_ms = int(feed_cfg.get("wait_attached_ms") or 30_000)
        ready_sel = (self.settings.selectors.get("feed_ready") or "").strip()

        print("[feed] loading home feed…", flush=True)
        page.goto(self.settings.feed_url, wait_until="domcontentloaded")
        try:
            page.bring_to_front()
        except Exception:
            pass
        pause_range(self.settings.pause("feed_settle"))
        print(f"[feed] url={page.url}", flush=True)

        if ready_sel:
            try:
                page.locator(ready_sel).first.wait_for(state="attached", timeout=wait_ms)
            except PWTimeout:
                print("[feed] no posts appeared after wait", flush=True)
                log.warning("no posts appeared after wait")

        posts: list[Post] = []
        seen: set[str] = set()
        stagnant = 0
        target = max(limit, self.settings.like_target * 2, 12)

        for scroll in range(max_scrolls):
            before = len(posts)
            batch = self._parser.parse(page)
            for item in batch:
                if not item.urn or not item.text or item.urn in seen:
                    continue
                seen.add(item.urn)
                posts.append(item.to_post())
                if len(posts) >= target:
                    print(f"[feed] parsed {len(posts)} posts (target reached)", flush=True)
                    return posts

            gained = len(posts) - before
            print(
                f"[feed] pass {scroll + 1}/{max_scrolls} — {len(posts)} posts "
                f"(+{gained} new, batch={len(batch)})",
                flush=True,
            )
            if gained == 0:
                stagnant += 1
                if stagnant >= stagnant_limit:
                    print("[feed] no new posts — stop scrolling", flush=True)
                    break
            else:
                stagnant = 0
            if scroll + 1 < max_scrolls:
                page.mouse.wheel(
                    0, random.randint(int(scroll_delta[0]), int(scroll_delta[1]))
                )
                pause_range(self.settings.pause("after_scroll"))

        print(f"[feed] parsed {len(posts)} posts", flush=True)
        return posts


class PlaywrightProfileSource(ProfileSource):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def read_profile(self, page, post: Post) -> ProfileBits:
        info = ProfileBits()
        if not post.author_url:
            info.friction = "no author url"
            return info

        try:
            page.goto(post.author_url, wait_until="domcontentloaded")
            pause_range(self.settings.pause("profile_settle"))
        except Exception as exc:
            info.friction = f"nav failed: {exc!s}"[:100]
            return info

        if "login" in page.url or "authwall" in page.url:
            info.friction = "authwall"
            return info

        sel = self.settings.selectors
        info.headline = self._page_text(page, sel.get("headline", ""), limit=240)
        info.about = self._page_text(page, sel.get("about", ""), limit=400)
        missing = []
        if not info.headline:
            missing.append("headline")
        if not info.about:
            missing.append("about")
        if missing:
            info.friction = "missing: " + ", ".join(missing)
        return info

    @staticmethod
    def _page_text(page, selector: str, limit: int = 240) -> str:
        if not selector:
            return ""
        loc = page.locator(selector)
        if loc.count() == 0:
            return ""
        try:
            return " ".join(loc.first.inner_text(timeout=2_000).split())[:limit]
        except Exception:
            return ""


def create_feed_source(settings: Settings, kind: str = "playwright") -> FeedSource:
    """Factory for data sources."""
    if kind == "playwright":
        return PlaywrightFeedSource(settings)
    raise ValueError(f"Unknown feed source: {kind!r}")


def create_profile_source(settings: Settings, kind: str = "playwright") -> ProfileSource:
    if kind == "playwright":
        return PlaywrightProfileSource(settings)
    raise ValueError(f"Unknown profile source: {kind!r}")
