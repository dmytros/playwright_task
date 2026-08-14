from __future__ import annotations

import re
from abc import ABC, abstractmethod

import requests

from linkedin.enums import DraftProvider
from linkedin.models import Post, ProfileBits
from linkedin.resilience import get_logger
from linkedin.settings import Settings

log = get_logger("draft")


class DraftStrategy(ABC):
    name: str

    @abstractmethod
    def draft(
        self,
        settings: Settings,
        post: Post,
        profile: ProfileBits | dict[str, str] | None = None,
    ) -> str:
        raise NotImplementedError


def _profile_map(
    profile: ProfileBits | dict[str, str] | None,
) -> dict[str, str] | None:
    if profile is None:
        return None
    if isinstance(profile, ProfileBits):
        return profile.as_dict()
    return profile


def _clean(text: str, max_chars: int = 320) -> str:
    text = re.sub(r"\s+", " ", text.strip().strip('"'))
    return text[: max_chars - 3] + "…" if len(text) > max_chars else text


class OllamaDraftStrategy(DraftStrategy):
    name = DraftProvider.OLLAMA.value

    def draft(
        self,
        settings: Settings,
        post: Post,
        profile: ProfileBits | dict[str, str] | None = None,
    ) -> str:
        draft_cfg = settings.runtime.get("draft") or {}
        system = draft_cfg.get("system_prompt") or (
            "Write a short LinkedIn comment like a thoughtful senior engineer. "
            "1–3 sentences, max ~280 chars. Specific, no emojis/hashtags, "
            "no 'Great post!'. Output only the comment."
        )
        max_post = int(draft_cfg.get("max_post_chars") or 1000)
        timeout_s = int(draft_cfg.get("ollama_timeout_s") or 180)
        max_comment = int(draft_cfg.get("max_comment_chars") or 320)
        profile_map = _profile_map(profile)

        user = f"Author: {post.author}\n\nPost:\n{post.text[:max_post]}"
        if profile_map:
            user += (
                f"\n\nHeadline: {profile_map.get('headline', '')}\n"
                f"About: {profile_map.get('about', '')}"
            )
        user += "\n\nDraft the comment."

        resp = requests.post(
            settings.ollama_url,
            json={
                "model": settings.ollama_model,
                "stream": False,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
            timeout=timeout_s,
        )
        resp.raise_for_status()
        text = ((resp.json().get("message") or {}).get("content") or "").strip()
        if not text:
            raise RuntimeError("empty response")
        return _clean(text, max_comment)


class LocalFallbackDraftStrategy(DraftStrategy):
    name = DraftProvider.LOCAL_FALLBACK.value

    def draft(
        self,
        settings: Settings,
        post: Post,
        profile: ProfileBits | dict[str, str] | None = None,
    ) -> str:
        draft_cfg = settings.runtime.get("draft") or {}
        max_comment = int(draft_cfg.get("max_comment_chars") or 320)
        profile_map = _profile_map(profile)
        snippet = " ".join(post.text.split())[:70].lower()
        if profile_map and profile_map.get("headline"):
            role = profile_map["headline"].split("|")[0].split(",")[0].strip()[:50]
            return _clean(
                f"The bit about {snippet} resonates — especially from someone "
                f"in {role}. How did you pressure-test that before committing?",
                max_comment,
            )
        return _clean(
            f"The bit about {snippet} lands. I've seen teams miss this until "
            f"production. What made you confident enough to ship it?",
            max_comment,
        )


_REGISTRY: dict[str, DraftStrategy] = {
    OllamaDraftStrategy.name: OllamaDraftStrategy(),
    LocalFallbackDraftStrategy.name: LocalFallbackDraftStrategy(),
}


def get_draft_strategy(name: str) -> DraftStrategy:
    strategy = _REGISTRY.get(name)
    if strategy is None:
        raise ValueError(f"Unknown draft strategy: {name!r}")
    return strategy


def draft_comment(
    settings: Settings,
    post: Post,
    profile: ProfileBits | dict[str, str] | None = None,
) -> tuple[str, str]:
    draft_cfg = settings.runtime.get("draft") or {}
    providers = list(draft_cfg.get("providers") or ["ollama", "local_fallback"])
    errors: list[str] = []
    for name in providers:
        strategy = get_draft_strategy(name)
        try:
            return strategy.draft(settings, post, profile), strategy.name
        except Exception as exc:
            errors.append(f"{name}: {exc!s}")
            print(f"[draft] {name} failed ({exc!s}); trying next", flush=True)
            log.warning("%s failed (%s); trying next", name, exc)
    fallback = get_draft_strategy(DraftProvider.LOCAL_FALLBACK.value)
    return fallback.draft(settings, post, profile), fallback.name
