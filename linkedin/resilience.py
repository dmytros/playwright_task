from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from functools import wraps
from typing import ParamSpec, TypeVar

P = ParamSpec("P")
T = TypeVar("T")

_LOG = logging.getLogger("linkedin")


def setup_logging(level: str = "INFO") -> None:
    if _LOG.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("[%(levelname)s] %(name)s: %(message)s")
    )
    _LOG.addHandler(handler)
    _LOG.setLevel(getattr(logging, level.upper(), logging.INFO))
    _LOG.propagate = False


def get_logger(name: str | None = None) -> logging.Logger:
    if name:
        return _LOG.getChild(name)
    return _LOG


def pause(a: float = 0.4, b: float = 1.0) -> None:
    time.sleep(random.uniform(a, b))


def pause_range(bounds: list[float] | tuple[float, float]) -> None:
    lo, hi = float(bounds[0]), float(bounds[1])
    pause(lo, hi)


def retry(
    *,
    attempts: int = 3,
    backoff_base: float = 0.4,
    jitter: float = 0.3,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
    on_failure: Callable[[BaseException, int], None] | None = None,
) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """Retry unstable external calls (DOM drift, timeouts)."""

    def decorator(fn: Callable[P, T]) -> Callable[P, T]:
        @wraps(fn)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            last: BaseException | None = None
            for attempt in range(1, attempts + 1):
                try:
                    return fn(*args, **kwargs)
                except exceptions as exc:
                    last = exc
                    if on_failure:
                        on_failure(exc, attempt)
                    else:
                        get_logger("retry").warning(
                            "%s failed attempt %s/%s: %s",
                            fn.__name__,
                            attempt,
                            attempts,
                            exc,
                        )
                    if attempt < attempts:
                        pause(backoff_base, backoff_base + jitter)
            assert last is not None
            raise last

        return wrapper

    return decorator
