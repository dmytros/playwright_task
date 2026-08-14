from __future__ import annotations

from linkedin.client import LinkedIn
from linkedin.enums import LikeOutcome
from linkedin.models import Post
from linkedin.scoring import top_posts
from linkedin.services.draft import draft_comment


def level1(li: LinkedIn, page) -> list[tuple[Post, str]]:
    posts = li.read_feed(page)
    if not posts:
        raise RuntimeError("Parsed 0 posts — are you logged in? Did selectors drift?")

    picks = top_posts(
        posts,
        li.settings.interests,
        li.settings.like_target,
        scoring_cfg=li.settings.scoring,
    )
    try:
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(600)
    except Exception:
        pass

    results: list[tuple[Post, str]] = []
    print(f"\n=== LEVEL 1 — like interesting posts ({len(picks)} of {len(posts)}) ===", flush=True)
    for i, post in enumerate(picks, 1):
        print(f"[{i}/{len(picks)}] liking {post.author!r}…", flush=True)
        outcome = li.like(page, post)
        results.append((post, outcome))
        print(f"    → {outcome} | score={post.score}", flush=True)
        print(f"    {post.preview!r}", flush=True)
        print(f"    why: {', '.join(post.reasons)}", flush=True)
    return results


def _top_liked(liked: list[tuple[Post, str]], n: int) -> list[Post]:
    ok_values = {LikeOutcome.LIKED.value, LikeOutcome.ALREADY_LIKED.value}
    ok = [p for p, outcome in liked if outcome in ok_values]
    pool = ok or [p for p, _ in liked]
    n = max(2, min(n, 3))
    return sorted(pool, key=lambda p: p.score, reverse=True)[:n]


def level2(li: LinkedIn, page, liked: list[tuple[Post, str]]) -> None:
    picks = _top_liked(liked, li.settings.comment_pick)

    print("\n=== LEVEL 2 — draft comments (NOT posted) ===", flush=True)
    print(
        "Selection: highest scores among liked posts "
        "(substance + interest keywords − engagement bait).",
        flush=True,
    )
    for i, post in enumerate(picks, 1):
        print(f"[{i}/{len(picks)}] drafting via Ollama (may take 5–30s)…", flush=True)
        comment, provider = draft_comment(li.settings, post)
        print(f"\n[{i}] {post.author} | score={post.score} | via={provider}", flush=True)
        print(f"    post: {post.preview!r}", flush=True)
        print(f"    draft: {comment!r}", flush=True)


def level3(li: LinkedIn, page, liked: list[tuple[Post, str]]) -> None:
    picks = _top_liked(liked, li.settings.comment_pick)

    print("\n=== LEVEL 3 — profile-aware drafts (NOT posted) ===", flush=True)
    print(
        "Same selection rule as L2, plus a best-effort profile peek "
        "(headline/about). LinkedIn A/B and lazy sections make this flaky.",
        flush=True,
    )
    for i, post in enumerate(picks, 1):
        print(f"[{i}/{len(picks)}] opening profile…", flush=True)
        profile = li.profile_bits(page, post)
        print(f"[{i}/{len(picks)}] drafting via Ollama…", flush=True)
        comment, provider = draft_comment(li.settings, post, profile)
        print(f"\n[{i}] {post.author} | score={post.score} | via={provider}", flush=True)
        print(f"    post: {post.preview!r}", flush=True)
        print(f"    headline: {profile.get('headline')!r}", flush=True)
        if profile.get("friction"):
            print(f"    friction: {profile['friction']}", flush=True)
        print(f"    draft: {comment!r}", flush=True)
