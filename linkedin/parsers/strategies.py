from __future__ import annotations

import re
from typing import Any

from linkedin.enums import ParserKind
from linkedin.models import ParsedCard
from linkedin.parsers.base import FeedParser
from linkedin.parsers.dom import card_id, first_text, join_texts, resolve_author
from linkedin.parsers.textutil import body_from_text


class ViewNameParser(FeedParser):
    kind = ParserKind.VIEW_NAME.value

    def parse(self, page) -> list[ParsedCard]:
        out: list[ParsedCard] = []
        cards = page.locator(self.rule["card_selector"])
        text_selectors = self.rule.get("text_selectors") or []
        for i in range(cards.count()):
            card = cards.nth(i)
            try:
                raw = (card.inner_text(timeout=1_500) or "").strip()
                text = ""
                for sel in text_selectors:
                    text = join_texts(card, sel)
                    if text:
                        break
                if not text:
                    text = body_from_text(raw)
                if not text:
                    continue
                author, author_url = resolve_author(
                    card,
                    raw,
                    base_url=self.base_url,
                    author_selector=self.selectors.get("author", ""),
                    author_link_selector=self.selectors.get("author_link", ""),
                )
                urn = card_id(card) or f"{author}|{text[:60]}"
                out.append(
                    ParsedCard(
                        urn=urn,
                        author=(author or "Unknown").strip(),
                        author_url=author_url or "",
                        text=text.strip(),
                    )
                )
            except Exception:
                continue
        return out


class ListItemParser(FeedParser):
    kind = ParserKind.LISTITEM.value

    def parse(self, page) -> list[ParsedCard]:
        main = None
        for scope in self.rule.get("scope_selectors") or []:
            loc = page.locator(scope)
            if loc.count() > 0:
                main = loc.first
                break
        if main is None:
            return []

        out: list[ParsedCard] = []
        cards = main.locator(self.rule["card_selector"])
        reaction_sel = self.rule.get("reaction_selector") or ""
        min_raw = int(self.rule.get("min_raw_length") or 80)
        require_prefix = bool(self.rule.get("require_feed_post_prefix", True))

        for i in range(cards.count()):
            card = cards.nth(i)
            try:
                if reaction_sel and card.locator(reaction_sel).count() == 0:
                    continue
                raw = (card.inner_text(timeout=1_500) or "").strip()
                if require_prefix and (
                    not re.match(r"(?i)^Feed post", raw) or len(raw) < min_raw
                ):
                    continue
                author, author_url = resolve_author(
                    card,
                    raw,
                    base_url=self.base_url,
                    author_selector=self.selectors.get("author", ""),
                    author_link_selector=self.selectors.get("author_link", ""),
                )
                text = body_from_text(raw, author=author)
                if not text:
                    continue
                urn = card_id(card) or f"{author}|{text[:60]}"
                out.append(
                    ParsedCard(
                        urn=urn,
                        author=(author or "Unknown").strip(),
                        author_url=author_url or "",
                        text=text.strip(),
                    )
                )
            except Exception:
                continue
        return out


class LegacyParser(FeedParser):
    kind = ParserKind.LEGACY.value

    def parse(self, page) -> list[ParsedCard]:
        out: list[ParsedCard] = []
        cards = page.locator(self.rule["card_selector"])
        urn_attr = self.rule.get("urn_attribute") or "data-urn"
        text_selectors = self.rule.get("text_selectors") or []

        for i in range(cards.count()):
            card = cards.nth(i)
            try:
                urn = card.get_attribute(urn_attr) or ""
                raw = (card.inner_text(timeout=1_500) or "").strip()
                text = ""
                for sel in text_selectors:
                    text = first_text(card, sel)
                    if text:
                        break
                if not text:
                    text = body_from_text(raw)
                author, author_url = resolve_author(
                    card,
                    raw,
                    base_url=self.base_url,
                    author_selector=self.selectors.get("author", ""),
                    author_link_selector=self.selectors.get("author_link", ""),
                )
                if not urn or not text:
                    continue
                out.append(
                    ParsedCard(
                        urn=urn,
                        author=(author or "Unknown").strip(),
                        author_url=author_url or "",
                        text=text.strip(),
                    )
                )
            except Exception:
                continue
        return out


PARSER_REGISTRY: dict[str, type[FeedParser]] = {
    ParserKind.VIEW_NAME.value: ViewNameParser,
    ParserKind.LISTITEM.value: ListItemParser,
    ParserKind.LEGACY.value: LegacyParser,
}


def build_parser(
    rule: dict[str, Any],
    *,
    base_url: str,
    selectors: dict[str, str],
) -> FeedParser:
    kind = str(rule.get("kind") or "").strip()
    cls = PARSER_REGISTRY.get(kind)
    if cls is None:
        raise ValueError(f"Unknown parser kind: {kind!r}")
    return cls(rule, base_url=base_url, selectors=selectors)
