"""Qt utility helpers."""

from __future__ import annotations

import contextlib
import os


@contextlib.contextmanager
def silence_stderr():
    """Suppress noisy C-level stderr from driver probes."""
    devnull = open(os.devnull, "w")
    old_fd = os.dup(2)
    try:
        os.dup2(devnull.fileno(), 2)
        yield
    finally:
        os.dup2(old_fd, 2)
        os.close(old_fd)
        devnull.close()

