import time
from collections.abc import Callable
from typing import TypeVar

from app.core.logging import get_logger

T = TypeVar("T")
log = get_logger(__name__)


def retry_with_backoff(
    fn: Callable[[], T],
    *,
    attempts: int = 4,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Call `fn`, retrying on any exception with delays base, 2*base, 4*base, ... (capped)."""
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except Exception as exc:
            if attempt == attempts:
                raise
            delay = min(base_delay * 2 ** (attempt - 1), max_delay)
            log.warning(
                "retrying after error",
                extra={"attempt": attempt, "delay": delay, "error": str(exc)},
            )
            sleep(delay)
    raise AssertionError("unreachable")
