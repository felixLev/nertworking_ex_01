##### DO NOT MODIFY THIS FILE #####

"""Shared helpers for the select()-based bank server: simulated clock and
non-blocking operator console input.
"""
from __future__ import annotations

import select
import sys
import time
from datetime import date, datetime
from typing import Callable, Optional


class SimTime:
    """Simulated bank clock.

    Wall-clock time still flows for history timestamps, but the operator can jump
    the calendar forward by one day at a time. Standing orders and loan due dates
    use ``today()`` / ``advance_day()``. Transaction stamps use ``now()``.
    """

    def __init__(self, start_date: date):
        """Start the simulated clock on ``start_date``, keeping the current time of day."""
        wall_now = time.time()
        local = time.localtime(wall_now)
        # Build a local timestamp for start_date at "now"'s hour/minute/second.
        self._origin_sim = time.mktime((
            start_date.year, start_date.month, start_date.day,
            local.tm_hour, local.tm_min, local.tm_sec,
            local.tm_wday, local.tm_yday, local.tm_isdst,
        ))
        self._origin_wall = wall_now
        self._jump_sec = 0.0  # extra seconds added by advance_day()

    def now(self) -> float:
        """Current simulated Unix timestamp (seconds since epoch)."""
        return self._origin_sim + (time.time() - self._origin_wall) + self._jump_sec

    def today(self) -> date:
        """Current simulated calendar date."""
        return datetime.fromtimestamp(self.now()).date()

    def advance_day(self) -> date:
        """Jump the simulated clock forward by 24 hours. Returns the new date."""
        self._jump_sec += 24 * 3600.0
        return self.today()

    def format(self, fmt: str = "%Y-%m-%d %H:%M:%S", when: Optional[float] = None) -> str:
        """Format a simulated timestamp (default: now) with ``time.strftime`` rules."""
        return time.strftime(fmt, time.localtime(self.now() if when is None else when))


class Console:
    """Non-blocking console line reader for the server's select() loop.

    Call ``poll()`` once per loop iteration. When the operator presses Enter,
    ``on_line`` is invoked with the typed line (without the trailing newline).

    On Unix, stdin is checked with a zero-timeout ``select()``. On Windows,
    where ``select()`` cannot watch stdin, keypresses are polled via ``msvcrt``.
    If stdin is not a TTY, ``poll()`` is a no-op.
    """

    def __init__(self):
        self._stdin_buf = ""
        self._watch_stdin = sys.stdin.isatty() and sys.platform != "win32"
        self._poll_stdin = sys.stdin.isatty() and sys.platform == "win32"

    def poll(self, on_line: Callable[[str], None]) -> None:
        if self._watch_stdin:
            self._poll_unix(on_line)
        elif self._poll_stdin:
            self._poll_windows(on_line)

    def _poll_unix(self, on_line: Callable[[str], None]) -> None:
        readable, _, _ = select.select([sys.stdin], [], [], 0)
        if sys.stdin not in readable:
            return
        try:
            line = sys.stdin.readline()
        except EOFError:
            self._watch_stdin = False
            return
        if line == "":
            # EOF (stdin closed): stop watching the console.
            self._watch_stdin = False
            return
        on_line(line.rstrip("\r\n"))

    def _poll_windows(self, on_line: Callable[[str], None]) -> None:
        try:
            import msvcrt
        except ImportError:
            self._poll_stdin = False
            return
        while msvcrt.kbhit():
            ch = msvcrt.getwch()
            if ch in ("\x00", "\xe0"):
                msvcrt.getwch()  # discard the extended key code
                continue
            if ch in ("\r", "\n"):
                print(flush=True)  # getwch does not echo Enter
                on_line(self._stdin_buf)
                self._stdin_buf = ""
            elif ch == "\x08":  # backspace
                if self._stdin_buf:
                    self._stdin_buf = self._stdin_buf[:-1]
                    print("\b \b", end="", flush=True)
            elif ch == "\x03":  # Ctrl+C
                raise KeyboardInterrupt
            else:
                self._stdin_buf += ch
                print(ch, end="", flush=True)
