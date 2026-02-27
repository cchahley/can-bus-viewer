"""
Utility helpers shared across the can_viewer package.

Currently provides a single context manager used to silence noisy C-level
stderr output from hardware-driver probe calls (e.g. PCAN API).
"""
import contextlib
import os


@contextlib.contextmanager
def _silence_stderr():
    """Suppress C-level stderr (e.g. noisy PCAN API probe messages)."""
    devnull = open(os.devnull, "w")
    old_fd = os.dup(2)
    try:
        os.dup2(devnull.fileno(), 2)
        yield
    finally:
        os.dup2(old_fd, 2)
        os.close(old_fd)
        devnull.close()
