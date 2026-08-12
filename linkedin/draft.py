from __future__ import annotations

import re

import requests

from linkedin.score import Post
from linkedin.settings import Settings

SYSTEM = (
    "Write a short LinkedIn comment like a thoughtful senior engineer. "
    "1–3 sentences, max ~280 chars. Specific, no emojis/hashtags, "
    "no 'Great post!'. Output only the comment."
)


def draft_comment(
    settings: Settings,
    post: Post,
    profile: dict[str, str] | None = None,
) -> tuple[str, str]:
    try:
        return _ollama(settings, post, profile), "ollama"
    except Exception as exc:
        print(f"[draft] ollama failed ({exc!s}); using local_fallback", flush=True)
        return _fallback(post, profile), "local_fallback"


def _ollama(
    settings: Settings,
    post: Post,
    profile: dict[str, str] | None,
) -> str:
    user = f"Author: {post.author}\n\nPost:\n{post.text[:1000]}"
    if profile:
        user += (
            f"\n\nHeadline: {profile.get('headline', '')}\n"
            f"About: {profile.get('about', '')}"
        )
    user += "\n\nDraft the comment."

    resp = requests.post(
        settings.ollama_url,
        json={
            "model": settings.ollama_model,
            "stream": False,
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": user},
            ],
        },
        timeout=180,
    )
    resp.raise_for_status()
    text = ((resp.json().get("message") or {}).get("content") or "").strip()
    if not text:
        raise RuntimeError("empty response")
    return _clean(text)


def _fallback(post: Post, profile: dict[str, str] | None) -> str:
    snippet = " ".join(post.text.split())[:70].lower()
    if profile and profile.get("headline"):
        role = profile["headline"].split("|")[0].split(",")[0].strip()[:50]
        return _clean(
            f"The bit about {snippet} resonates — especially from someone "
            f"in {role}. How did you pressure-test that before committing?"
        )
    return _clean(
        f"The bit about {snippet} lands. I've seen teams miss this until "
        f"production. What made you confident enough to ship it?"
    )


def _clean(text: str) -> str:
    text = re.sub(r"\s+", " ", text.strip().strip('"'))
    return text[:317] + "…" if len(text) > 320 else text
