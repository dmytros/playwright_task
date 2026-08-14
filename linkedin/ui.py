"""Backward-compatible re-exports. Prefer linkedin.client.LinkedIn. """

from linkedin.client import LinkedIn
from linkedin.resilience import pause

__all__ = ["LinkedIn", "pause"]
