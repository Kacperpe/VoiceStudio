"""Request cancellation visible to killable sidecars on executor threads.

In-process native calls remain accounted for until they return; only sidecars
can safely terminate early. A scope belongs to one job, never to a pool thread.

A scope also carries the job's progress. Engines that decode incrementally
(faster-whisper yields one segment at a time) report through
:func:`report_progress` and poll :func:`raise_if_cancelled` between steps, so a
cancelled request stops at the next segment instead of running to the end.
"""
from contextlib import contextmanager
import threading
import time

_local = threading.local()


class TranscriptionCancelledError(RuntimeError):
    """The caller cancelled the request while the engine was still working."""


class InferenceCancellation:
    def __init__(self):
        self.cancelled = threading.Event()
        # Fraction 0..1, or None while the engine has not reported any.
        self.progress: float | None = None
        # Monotonic time of the last sign of life: creation, then each report.
        self.last_activity = time.monotonic()

    def cancel(self):
        self.cancelled.set()

    def report(self, fraction: float) -> None:
        self.progress = min(1.0, max(0.0, float(fraction)))
        self.last_activity = time.monotonic()

    @contextmanager
    def activate(self):
        previous = getattr(_local, "scope", None)
        _local.scope = self
        try:
            if self.cancelled.is_set():
                raise RuntimeError("Inference request was cancelled before execution")
            yield
        finally:
            _local.scope = previous


def current_cancellation():
    return getattr(_local, "scope", None)


def report_progress(fraction: float) -> None:
    """Record progress for the job running on this thread, if any."""
    scope = current_cancellation()
    if scope is not None:
        scope.report(fraction)


def raise_if_cancelled() -> None:
    """Stop the job running on this thread once its caller has cancelled it."""
    scope = current_cancellation()
    if scope is not None and scope.cancelled.is_set():
        raise TranscriptionCancelledError("Transcription was cancelled")
