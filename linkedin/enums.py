from __future__ import annotations

from enum import Enum, IntEnum


class Level(IntEnum):
    LIKE = 1
    DRAFT = 2
    PROFILE_DRAFT = 3


class ParserKind(str, Enum):
    VIEW_NAME = "view_name"
    LISTITEM = "listitem"
    LEGACY = "legacy"


class LikeOutcome(str, Enum):
    LIKED = "liked"
    ALREADY_LIKED = "already_liked"
    FAILED_TIMEOUT = "failed:timeout"
    FAILED_NOT_FOUND = "failed:not_found"
    FAILED_NO_BUTTON = "failed:no_button"

    @classmethod
    def failed(cls, reason: str) -> str:
        return f"failed:{reason}"[:80]

    @property
    def ok(self) -> bool:
        return self in {LikeOutcome.LIKED, LikeOutcome.ALREADY_LIKED}


class DraftProvider(str, Enum):
    OLLAMA = "ollama"
    LOCAL_FALLBACK = "local_fallback"


class ScoringStrategyName(str, Enum):
    SUBSTANCE_INTEREST = "substance_interest"
    LENGTH_ONLY = "length_only"
