from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

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
    like_target: int = 10
    comment_pick: int = 3

    @property
    def login_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/login"

    @property
    def feed_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/feed/"


SEL = {
    "email": "input#username",
    "password": "input#password",
    "submit": 'button[type="submit"]',
    "nav": '[data-testid="primary-nav"], nav.global-nav, #global-nav',
    "post": '[data-view-name="feed-full-update"], [data-testid="mainFeed"] [role="listitem"], div.feed-shared-update-v2[data-urn], article[data-urn]',
    "text": '[data-view-name="feed-commentary"], .update-components-text, .feed-shared-update-v2__description',
    "author": (
        '.update-components-actor__title span[aria-hidden="true"], '
        '.update-components-actor__name span[aria-hidden="true"], '
        '[data-view-name="feed-actor"], [data-view-name="feed-header-text"]'
    ),
    "author_link": 'a[href*="/in/"], a[href*="/company/"]',
    "like": 'button[aria-label*="Reaction button state"], [data-view-name="reaction-button"], button[aria-label*="Like"][aria-pressed="false"]',
    "liked": 'button[aria-label*="Reaction button state"]:not([aria-label*="no reaction"]), button[aria-label*="Like"][aria-pressed="true"]',
    "headline": "div.text-body-medium.break-words",
    "about": "#about ~ div .inline-show-more-text",
}


def load_settings() -> Settings:
    level = int(_env("LINKEDIN_LEVEL", "2"))
    if level not in {1, 2, 3}:
        raise ValueError("LINKEDIN_LEVEL must be 1, 2, or 3")

    interests = tuple(
        p.strip().lower()
        for p in _env(
            "LINKEDIN_INTERESTS",
            "engineering,architecture,product,leadership,ai,career",
        ).split(",")
        if p.strip()
    )

    return Settings(
        email=_env("LINKEDIN_EMAIL"),
        password=_env("LINKEDIN_PASSWORD"),
        storage_state=Path(_env("LINKEDIN_STORAGE_STATE", "./.linkedin_storage.json")),
        level=level,
        headless=_env("LINKEDIN_HEADLESS", "false").lower() in {"1", "true", "yes"},
        base_url=_env("LINKEDIN_BASE_URL", "https://www.linkedin.com"),
        interests=interests,
        ollama_url=_env("OLLAMA_CHAT_URL", "http://localhost:11434/api/chat"),
        ollama_model=_env("OLLAMA_MODEL", "llama3.2"),
    )
