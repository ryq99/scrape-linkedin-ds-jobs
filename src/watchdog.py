"""Wall-clock guards so a wedged browser can never hang the whole run.

Playwright's own timeouts are enforced *by the node driver*; if that driver's
pipe wedges (browser crash / OOM), a sync call like `page.evaluate` — which has
no timeout at all — blocks forever at 0% CPU. That is the failure that froze a
run at 100/300 for 8.5h. `time_limit` uses SIGALRM, which interrupts the blocked
syscall regardless of the driver's state; `Deadline` caps total runtime so a
long tail of slow-but-not-hung operations can't drain the battery either.

SIGALRM is delivered on the main thread only — both guards must run there (the
scrape orchestration does).
"""

import signal
import time
from contextlib import contextmanager


class OperationTimeout(Exception):
    """A single browser operation blew its per-call budget (retryable)."""


class RunAborted(Exception):
    """The whole run exceeded its wall-clock budget — stop and clean up."""


@contextmanager
def time_limit(seconds: float, label: str = "operation"):
    """Raise OperationTimeout if the wrapped block runs past `seconds`.

    Works even when blocked in a C-level syscall (the wedged-pipe case), unlike
    Playwright's driver-enforced timeouts.
    """
    def _fire(signum, frame):
        raise OperationTimeout(f"{label} exceeded {seconds:g}s")

    previous = signal.signal(signal.SIGALRM, _fire)
    signal.setitimer(signal.ITIMER_REAL, max(0.001, seconds))
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)  # always disarm
        signal.signal(signal.SIGALRM, previous)


class Deadline:
    """Whole-run wall-clock budget; call check() at safe points between ops."""

    def __init__(self, seconds: float):
        self.seconds = seconds
        self._end = time.monotonic() + seconds

    def check(self, label: str = "") -> None:
        if time.monotonic() > self._end:
            where = f" at {label}" if label else ""
            raise RunAborted(f"run exceeded {self.seconds:g}s budget{where}")

    def remaining(self) -> float:
        return max(0.0, self._end - time.monotonic())
