"""
File transcription reports progress, survives long files, and can be cancelled.

A 40-minute recording used to fail every time: ``run_transcribe_guarded``
abandoned any transcribe after a fixed 300 s wall clock even while faster-whisper
was steadily decoding it, and nothing stopped the native job when the client
gave up, so the GPU kept working on results nobody could read. The timeout now
measures inactivity, engines report progress per segment, and a request id lets
the UI poll progress and cancel.
"""
import asyncio
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

os.environ.setdefault("OMNIVOICE_MODEL", "test")
os.environ.setdefault("OMNIVOICE_DISABLE_FILE_LOG", "1")


# ── faster-whisper reports and honours cancellation per segment ────────────


class _FakeWhisperModel:
    def __init__(self, ends, duration, on_segment=None):
        self._ends = ends
        self._duration = duration
        self._on_segment = on_segment

    def transcribe(self, _path, **_kw):
        def _segments():
            start = 0.0
            for end in self._ends:
                if self._on_segment:
                    self._on_segment(end)
                yield SimpleNamespace(text=f"to {end}", start=start, end=end, words=[])
                start = end

        info = SimpleNamespace(language="pl", language_probability=1.0, duration=self._duration)
        return _segments(), info


def _faster_whisper(model):
    from services.asr_backend import FasterWhisperBackend

    backend = FasterWhisperBackend("test-model")
    backend._model = model
    return backend


def test_faster_whisper_reports_progress_per_segment():
    from services.inference_cancellation import InferenceCancellation

    scope = InferenceCancellation()
    seen = []
    backend = _faster_whisper(
        _FakeWhisperModel([2.5, 5.0, 10.0], 10.0, on_segment=lambda _e: seen.append(scope.progress))
    )
    with scope.activate():
        out = backend.transcribe("clip.wav", word_timestamps=False)
    assert len(out["segments"]) == 3
    # Each segment's progress is recorded before the next one is decoded.
    assert seen == [None, 0.25, 0.5]
    assert scope.progress == 1.0


def test_faster_whisper_stops_at_the_next_segment_once_cancelled():
    from services.inference_cancellation import (
        InferenceCancellation,
        TranscriptionCancelledError,
    )

    scope = InferenceCancellation()
    decoded = []

    def _on_segment(end):
        decoded.append(end)
        if end == 2.0:
            scope.cancel()

    backend = _faster_whisper(_FakeWhisperModel([1.0, 2.0, 3.0, 4.0], 4.0, _on_segment))
    with scope.activate(), pytest.raises(TranscriptionCancelledError):
        backend.transcribe("clip.wav", word_timestamps=False)
    assert decoded == [1.0, 2.0]


# ── the guard times out on inactivity, not on total length ────────────────


def _guarded(fn, timeout):
    from services.asr_backend import run_transcribe_guarded

    with ThreadPoolExecutor(max_workers=1) as pool:
        return asyncio.run(run_transcribe_guarded(pool, fn, what="Test", timeout=timeout))


def test_a_long_transcribe_that_keeps_reporting_is_not_abandoned():
    from services.inference_cancellation import report_progress

    def _steady():
        for step in range(8):
            time.sleep(0.05)
            report_progress(step / 8)
        return "done"

    # 0.4 s of work against a 0.2 s bound: only progress keeps it alive.
    assert _guarded(_steady, timeout=0.2) == "done"


def test_a_silent_transcribe_still_times_out():
    from services.asr_backend import ASRTimeoutError

    release = threading.Event()

    def _stuck():
        release.wait(2)
        return "late"

    try:
        with pytest.raises(ASRTimeoutError):
            _guarded(_stuck, timeout=0.2)
    finally:
        release.set()


# ── the endpoint: progress polling and cancel by request id ───────────────


class _SlowBackend:
    """Reports half-way, then waits until cancelled — a long file mid-decode."""

    id = "slow"

    def transcribe(self, _path, **_kw):
        from services.inference_cancellation import raise_if_cancelled, report_progress

        report_progress(0.5)
        for _ in range(500):
            raise_if_cancelled()
            time.sleep(0.01)
        return {"text": "never", "segments": [], "language": "pl"}


@pytest.mark.usefixtures("asr_model_installed")
def test_progress_is_visible_and_cancel_stops_the_request(monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setattr("services.asr_backend.get_capture_asr_backend", lambda **_k: _SlowBackend())
    monkeypatch.setattr("services.asr_backend.get_active_asr_backend", lambda **_k: _SlowBackend())
    monkeypatch.setattr("services.asr_backend.load_active_asr_backend", lambda **_k: _SlowBackend())
    from main import app

    client = TestClient(app, client=("127.0.0.1", 50000))
    response = {}

    def _post():
        response["r"] = client.post(
            "/transcribe",
            files={"audio": ("a.wav", b"\x00" * 32000, "audio/wav")},
            data={"mode": "accurate", "request_id": "job-1"},
        )

    worker = threading.Thread(target=_post)
    worker.start()
    deadline = time.monotonic() + 10
    progress = None
    while time.monotonic() < deadline:
        progress = client.get("/transcribe/progress/job-1").json()
        if progress["active"] and progress["progress"] == 0.5:
            break
        time.sleep(0.02)
    assert progress == {"active": True, "progress": 0.5}

    assert client.post("/transcribe/cancel/job-1").json() == {"cancelled": True}
    worker.join(10)
    assert response["r"].status_code == 499, response["r"].text
    # The registry entry goes away with the request.
    assert client.get("/transcribe/progress/job-1").json() == {"active": False, "progress": None}


def test_unknown_ids_are_inert():
    from fastapi.testclient import TestClient
    from main import app

    client = TestClient(app, client=("127.0.0.1", 50000))
    assert client.get("/transcribe/progress/nope").json() == {"active": False, "progress": None}
    assert client.post("/transcribe/cancel/nope").json() == {"cancelled": False}
