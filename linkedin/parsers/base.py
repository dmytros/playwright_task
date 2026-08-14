from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from linkedin.models import ParsedCard


class FeedParser(ABC):
    """Strategy: extract structured posts from a page using config rules."""

    kind: str

    def __init__(self, rule: dict[str, Any], *, base_url: str, selectors: dict[str, str]) -> None:
        self.rule = rule
        self.base_url = base_url
        self.selectors = selectors

    @abstractmethod
    def parse(self, page) -> list[ParsedCard]:
        raise NotImplementedError


class CompositeFeedParser(FeedParser):
    """Try parsers in order until one returns results."""

    kind = "composite"

    def __init__(self, parsers: list[FeedParser]) -> None:
        self.parsers = parsers
        # Dummy for ABC — unused
        super().__init__({}, base_url="", selectors={})

    def parse(self, page) -> list[ParsedCard]:
        for parser in self.parsers:
            batch = parser.parse(page)
            if batch:
                return batch
        return []
