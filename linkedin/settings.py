from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from linkedin.config import (
    load_parsing_config,
    load_runtime_config,
    load_scoring_config,
)

load_dotenv()


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


@dataclass(frozen=True)
class Settings:
    email: str
    password: str
    storage_state: Path
    level: int
    headless: bool
    base_url: str
    interests: tuple[str, ...]
    ollama_url: str
    ollama_model: str
    like_target: int
    comment_pick: int
    parsing: dict[str, Any] = field(default_factory=dict)
    scoring: dict[str, Any] = field(default_factory=dict)
    runtime: dict[str, Any] = field(default_factory=dict)

    @property
    def login_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/login"

    @property
    def feed_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/feed/"

    @property
    def selectors(self) -> dict[str, str]:
        return dict(self.parsing.get("selectors") or {})

    @property
    def pauses(self) -> dict[str, list[float]]:
        return dict(self.parsing.get("pauses") or {})

    def pause(self, name: str) -> list[float]:
        return list(self.pauses.get(name) or self.pauses.get("default") or [0.4, 1.0])


# Backward-compatible selector map populated on load.
SEL: dict[str, str] = {}


def load_settings() -> Settings:
    parsing = load_parsing_config()
    scoring = load_scoring_config()
    runtime = load_runtime_config()

    level = int(_env("LINKEDIN_LEVEL", "2"))
    if level not in {1, 2, 3}:
        raise ValueError("LINKEDIN_LEVEL must be 1, 2, or 3")

    cfg_interests = scoring.get("interest_keywords") or []
    default_interests = ",".join(cfg_interests) if cfg_interests else (
        "engineering,architecture,product,leadership,ai,career"
    )
    interests = tuple(
        p.strip().lower()
        for p in _env("LINKEDIN_INTERESTS", default_interests).split(",")
        if p.strip()
    )

    engagement = runtime.get("engagement") or {}
    like_target = int(_env("LINKEDIN_LIKE_TARGET", str(engagement.get("like_target", 10))))
    comment_pick = int(
        _env("LINKEDIN_COMMENT_PICK", str(engagement.get("comment_pick", 3)))
    )

    settings = Settings(
        email=_env("LINKEDIN_EMAIL"),
        password=_env("LINKEDIN_PASSWORD"),
        storage_state=Path(_env("LINKEDIN_STORAGE_STATE", "./.linkedin_storage.json")),
        level=level,
        headless=_env("LINKEDIN_HEADLESS", "false").lower() in {"1", "true", "yes"},
        base_url=_env("LINKEDIN_BASE_URL", "https://www.linkedin.com"),
        interests=interests,
        ollama_url=_env("OLLAMA_CHAT_URL", "http://localhost:11434/api/chat"),
        ollama_model=_env("OLLAMA_MODEL", "llama3.2"),
        like_target=like_target,
        comment_pick=comment_pick,
        parsing=parsing,
        scoring=scoring,
        runtime=runtime,
    )

    SEL.clear()
    SEL.update(settings.selectors)
    return settings
