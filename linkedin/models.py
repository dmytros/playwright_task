from __future__ import annotations

from dataclasses import dataclass, field


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


@dataclass(frozen=True)
class ParsedCard:
    urn: str
    author: str
    author_url: str
    text: str

    def to_post(self) -> Post:
        return Post(
            urn=self.urn,
            author=self.author,
            author_url=self.author_url,
            text=self.text,
        )


@dataclass
class ProfileBits:
    headline: str = ""
    about: str = ""
    friction: str = ""

    def as_dict(self) -> dict[str, str]:
        return {
            "headline": self.headline,
            "about": self.about,
            "friction": self.friction,
        }
