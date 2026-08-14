"""Backward-compatible scoring API. Prefer linkedin.scoring. """

from linkedin.config import load_scoring_config
from linkedin.models import Post
from linkedin.scoring import score_post as _score_post
from linkedin.scoring import top_posts as _top_posts


def score_post(post: Post, interests: tuple[str, ...]) -> Post:
    return _score_post(post, interests, scoring_cfg=load_scoring_config())


def top_posts(posts: list[Post], interests: tuple[str, ...], n: int) -> list[Post]:
    return _top_posts(posts, interests, n, scoring_cfg=load_scoring_config())


__all__ = ["Post", "score_post", "top_posts"]
