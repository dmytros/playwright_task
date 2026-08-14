from __future__ import annotations

import re

from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PWTimeout

from linkedin.enums import LikeOutcome
from linkedin.models import Post
from linkedin.resilience import get_logger, pause_range
from linkedin.settings import Settings

log = get_logger("engagement")


class EngagementService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def like(self, page: Page, post: Post) -> str:
        attempts = int(
            (self.settings.runtime.get("engagement") or {}).get("like_attempts") or 4
        )
        last = LikeOutcome.FAILED_TIMEOUT.value
        for _ in range(attempts):
            try:
                page.keyboard.press("Escape")
            except Exception:
                pass
            pause_range(self.settings.pause("before_like"))

            card = self._locate_post_card(page, post)
            if card is None:
                last = LikeOutcome.FAILED_NOT_FOUND.value
                self._hunt_post(page, post)
                continue

            try:
                outcome = self._like_on_card(card)
                try:
                    page.keyboard.press("Escape")
                except Exception:
                    pass
                if outcome.startswith("failed"):
                    last = outcome
                    pause_range(self.settings.pause("like_retry"))
                    continue
                return outcome
            except PWTimeout:
                last = LikeOutcome.FAILED_TIMEOUT.value
            except Exception as exc:
                last = LikeOutcome.failed(str(exc))
            pause_range(self.settings.pause("like_retry"))
        return last

    def _like_on_card(self, card) -> str:
        try:
            card.scroll_into_view_if_needed(timeout=5_000)
        except Exception:
            pass
        pause_range(self.settings.pause("before_like"))

        btn = self._reaction_button(card)
        if btn is None:
            return LikeOutcome.FAILED_NO_BUTTON.value

        label = (btn.get_attribute("aria-label", timeout=3_000) or "").lower()
        pressed = (btn.get_attribute("aria-pressed", timeout=1_000) or "").lower()
        if pressed == "true":
            return LikeOutcome.ALREADY_LIKED.value
        if "state:" in label and "no reaction" not in label:
            return LikeOutcome.ALREADY_LIKED.value

        try:
            btn.click(timeout=6_000)
        except PWTimeout:
            btn.click(timeout=4_000, force=True)
        pause_range(self.settings.pause("after_like_click"))
        return LikeOutcome.LIKED.value

    def _reaction_button(self, card):
        selectors = list(self.settings.parsing.get("reaction_button_selectors") or [])
        for sel in selectors:
            loc = card.locator(sel)
            for i in range(min(loc.count(), 4)):
                cand = loc.nth(i)
                try:
                    if cand.is_visible(timeout=800):
                        return cand
                except Exception:
                    continue
        role = card.get_by_role(
            "button", name=re.compile(r"reaction|like|реакц|подоба", re.I)
        )
        try:
            if role.count() > 0 and role.first.is_visible(timeout=800):
                return role.first
        except Exception:
            pass
        return None

    def _hunt_post(self, page: Page, post: Post) -> None:
        feed_cfg = self.settings.parsing.get("feed") or {}
        snippet_len = int(feed_cfg.get("snippet_len") or 36)
        snippet = (post.preview or "")[:snippet_len]
        if not snippet:
            return
        deltas = list(feed_cfg.get("hunt_deltas") or [-900, -900, 1100, 1100, 1100, 1100])
        for delta in deltas:
            if self._locate_post_card(page, post) is not None:
                return
            page.mouse.wheel(0, int(delta))
            pause_range(self.settings.pause("hunt_scroll"))

    def _locate_post_card(self, page: Page, post: Post):
        card = self._find_card(page, post)
        if card is not None:
            return card
        feed_cfg = self.settings.parsing.get("feed") or {}
        snippet_len = int(feed_cfg.get("snippet_len") or 36)
        snippet = (post.preview or "")[:snippet_len]
        if not snippet:
            return None
        try:
            hit = page.get_by_text(snippet, exact=False)
            if hit.count() == 0:
                return None
            node = hit.first.locator(
                'xpath=ancestor::*[@role="listitem" or @data-view-name="feed-full-update" '
                'or contains(@class,"feed-shared-update") or @data-urn][1]'
            )
            if node.count() > 0:
                return node.first
        except Exception:
            return None
        return None

    def _card_id(self, card) -> str:
        urn = card.get_attribute("data-urn") or ""
        if urn:
            return urn
        key = card.get_attribute("componentkey") or ""
        if key:
            return key
        parent = card.locator("xpath=ancestor-or-self::*[@componentkey][1]")
        if parent.count():
            key = parent.first.get_attribute("componentkey") or ""
            if key:
                return key
        try:
            return (card.inner_text(timeout=800) or "")[:80]
        except Exception:
            return ""

    def _find_card(self, page: Page, post: Post):
        selectors = list(self.settings.parsing.get("card_locate_selectors") or [])
        snippet = (post.preview or "")[:40]
        for sel in selectors:
            cards = page.locator(sel)
            for i in range(cards.count()):
                card = cards.nth(i)
                try:
                    if post.urn and self._card_id(card) == post.urn:
                        return card
                except Exception:
                    continue
        if not snippet:
            return None
        for sel in selectors:
            cards = page.locator(sel)
            for i in range(cards.count()):
                card = cards.nth(i)
                try:
                    text = card.inner_text(timeout=800) or ""
                except Exception:
                    continue
                if snippet in text and self._reaction_button(card) is not None:
                    return card
        for sel in selectors:
            cards = page.locator(sel)
            for i in range(cards.count()):
                card = cards.nth(i)
                try:
                    if snippet in (card.inner_text(timeout=500) or ""):
                        return card
                except Exception:
                    continue
        loc = page.locator(f'[componentkey="{post.urn}"]')
        if loc.count() > 0:
            return loc.first
        return None
