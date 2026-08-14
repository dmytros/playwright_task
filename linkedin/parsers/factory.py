from __future__ import annotations

from typing import Any

from linkedin.parsers.base import CompositeFeedParser, FeedParser
from linkedin.parsers.strategies import PARSER_REGISTRY, build_parser


def create_feed_parser(
    parsing_config: dict[str, Any],
    *,
    base_url: str,
) -> FeedParser:
    """Factory: build the right parser chain from config."""
    selectors = dict(parsing_config.get("selectors") or {})
    rules = list(parsing_config.get("parsers") or [])
    parsers = [
        build_parser(rule, base_url=base_url, selectors=selectors) for rule in rules
    ]
    if not parsers:
        raise ValueError("parsing config has no parsers")
    if len(parsers) == 1:
        return parsers[0]
    return CompositeFeedParser(parsers)


def available_parser_kinds() -> list[str]:
    return sorted(PARSER_REGISTRY.keys())
