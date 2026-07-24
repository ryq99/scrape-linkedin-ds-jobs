"""The watchdog is the guarantee that a wedged browser can't hang the run,
so its two failure modes are worth pinning down: a per-op cap that fires even
inside a blocked syscall, and a whole-run deadline."""

import socket
import time

import pytest

from watchdog import Deadline, OperationTimeout, RunAborted, time_limit


def test_time_limit_interrupts_a_blocked_syscall():
    # A blocking recv with no data mimics the wedged driver pipe that froze the
    # real run — Playwright's own timeouts can't touch this; SIGALRM must.
    a, _b = socket.socketpair()
    start = time.monotonic()
    with pytest.raises(OperationTimeout):
        with time_limit(0.2, "recv"):
            a.recv(1024)
    assert time.monotonic() - start < 1.0


def test_time_limit_passes_through_when_fast():
    with time_limit(5, "fast"):
        result = 1 + 1
    assert result == 2


def test_time_limit_disarms_after_exit():
    # A stray timer would fire into unrelated later code; ensure it's cleared.
    with time_limit(0.2, "quick"):
        pass
    time.sleep(0.4)  # would raise here if the alarm were still armed


def test_deadline_check_raises_once_past_budget():
    d = Deadline(0.1)
    time.sleep(0.15)
    with pytest.raises(RunAborted):
        d.check("details")


def test_deadline_check_silent_within_budget():
    d = Deadline(60)
    d.check("harvest")  # plenty of budget left — must not raise
    assert d.remaining() > 0
