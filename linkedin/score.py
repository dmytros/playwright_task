from __future__ import annotations

import re
from dataclasses import dataclass, field

BAIT = (
    r"\bcomment\s+[\"']?yes[\"']?\b",
    r"\brepost\s+if\b",
    r"\btag\s+someone\b",
    r"\bdm\s+me\s+for\b",
)

SUBSTANCE = (
    r"\b(learned|trade[- ]?off|architecture|postmortem|shipped|migrated)\b",
    r"\b(lesson|mistake|failure|framework|mental model)\b",
)


@dataclass
class Post:
    urn: str
    author: str
    author_url: str
    text: str
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)

    @property
    def preview(self) -> str:
        return " ".join(self.text.split())[:200]


def score_post(post: Post, interests: tuple[str, ...]) -> Post:
    text = post.text.strip()
    lower = text.lower()
    score = 0.0
    reasons: list[str] = []

    if len(text) >= 80:
        score += min(len(text) / 400, 2.5)
        reasons.append("has_substance")
    else:
        score -= 1.5
        reasons.append("too_short")

    hits = [kw for kw in interests if kw in lower]
    if hits:
        score += 1.2 * min(len(hits), 3)
        reasons.append("interests=" + ",".join(hits[:3]))

    if any(re.search(p, lower, re.I) for p in SUBSTANCE):
        score += 0.8
        reasons.append("signal_words")

    if any(re.search(p, lower, re.I) for p in BAIT):
        score -= 2.0
        reasons.append("engagement_bait")

    post.score = round(score, 3)
    post.reasons = reasons
    return post


def top_posts(posts: list[Post], interests: tuple[str, ...], n: int) -> list[Post]:
    ranked = sorted(
        (score_post(p, interests) for p in posts),
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
