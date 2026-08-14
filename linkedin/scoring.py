from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Any

from linkedin.enums import ScoringStrategyName
from linkedin.models import Post


class ScoringStrategy(ABC):
    name: str

    @abstractmethod
    def score(self, post: Post, interests: tuple[str, ...], cfg: dict[str, Any]) -> Post:
        raise NotImplementedError


class SubstanceInterestStrategy(ScoringStrategy):
    name = ScoringStrategyName.SUBSTANCE_INTEREST.value

    def score(self, post: Post, interests: tuple[str, ...], cfg: dict[str, Any]) -> Post:
        weights = cfg.get("weights") or {}
        signal_patterns = cfg.get("signal_patterns") or []
        bait_patterns = cfg.get("bait_patterns") or []

        text = post.text.strip()
        lower = text.lower()
        score = 0.0
        reasons: list[str] = []

        min_chars = int(weights.get("min_substance_chars") or 80)
        if len(text) >= min_chars:
            score += min(
                len(text) / float(weights.get("substance_divisor") or 400),
                float(weights.get("substance_cap") or 2.5),
            )
            reasons.append("has_substance")
        else:
            score -= float(weights.get("too_short_penalty") or 1.5)
            reasons.append("too_short")

        hits = [kw for kw in interests if kw in lower]
        if hits:
            cap = int(weights.get("interest_hit_cap") or 3)
            score += float(weights.get("interest_per_hit") or 1.2) * min(len(hits), cap)
            reasons.append("interests=" + ",".join(hits[:cap]))

        if any(re.search(p, lower, re.I) for p in signal_patterns):
            score += float(weights.get("signal_bonus") or 0.8)
            reasons.append("signal_words")

        if any(re.search(p, lower, re.I) for p in bait_patterns):
            score -= float(weights.get("bait_penalty") or 2.0)
            reasons.append("engagement_bait")

        post.score = round(score, 3)
        post.reasons = reasons
        return post


class LengthOnlyStrategy(ScoringStrategy):
    name = ScoringStrategyName.LENGTH_ONLY.value

    def score(self, post: Post, interests: tuple[str, ...], cfg: dict[str, Any]) -> Post:
        text = post.text.strip()
        post.score = round(min(len(text) / 200, 5.0), 3)
        post.reasons = ["length_only"]
        return post


_REGISTRY: dict[str, ScoringStrategy] = {
    SubstanceInterestStrategy.name: SubstanceInterestStrategy(),
    LengthOnlyStrategy.name: LengthOnlyStrategy(),
}


def get_scoring_strategy(name: str | None = None) -> ScoringStrategy:
    key = (name or ScoringStrategyName.SUBSTANCE_INTEREST.value).strip()
    strategy = _REGISTRY.get(key)
    if strategy is None:
        raise ValueError(f"Unknown scoring strategy: {key!r}")
    return strategy


def score_post(
    post: Post,
    interests: tuple[str, ...],
    scoring_cfg: dict[str, Any] | None = None,
    strategy_name: str | None = None,
) -> Post:
    cfg = scoring_cfg or {}
    strategies = cfg.get("strategies") or {}
    name = strategy_name or strategies.get("default") or ScoringStrategyName.SUBSTANCE_INTEREST.value
    return get_scoring_strategy(name).score(post, interests, cfg)


def top_posts(
    posts: list[Post],
    interests: tuple[str, ...],
    n: int,
    scoring_cfg: dict[str, Any] | None = None,
) -> list[Post]:
    ranked = sorted(
        (score_post(p, interests, scoring_cfg) for p in posts),
        key=lambda p: p.score,
        reverse=True,
    )
    picked: list[Post] = []
    seen: set[str] = set()
    for post in ranked:
        key = f"{post.author}|{post.preview[:60]}"
        if key in seen:
            continue
        seen.add(key)
        picked.append(post)
        if len(picked) >= n:
            break
    return picked
