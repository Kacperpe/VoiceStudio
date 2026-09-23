"""A resumed book keeps its own cached chapters when it outgrows the cache cap.

The chapter cache is capped (2 GB by default) and was pruned at the START of
every render, oldest mtime first. A full-length book easily passes the cap, so
resuming it evicted its own earliest chapters (untouched since they rendered)
and synthesized them again. The prune now runs when the job ends and spares
every file touched since the oldest live job began; hits refresh mtimes so
reused chapters count as touched.

No models / GPU: the synth boundary is stubbed, as in test_audiobook_cancel.
"""
from __future__ import annotations

import asyncio
import json
import os
import time

import torch

from services.longform_render import SEGMENT_SUBDIR, prune_cache_dir


def _resolve(_voice_id):
    return {"ref_audio": None, "ref_text": None, "instruct": None, "seed": None}


def _stub_build_synth(calls):
    def _factory(default_voice=None, language=None, opts=None, voice_map=None):
        def synth(text, voice_id, speed=None):
            calls.append(text)
            return torch.zeros(2400)
        return {"mode": "generic", "resolve": _resolve, "engine_id": "stub",
                "synth": synth, "sample_rate": 24000}
    return _factory


def _plan():
    from services.audiobook import AudiobookPlan, Chapter, Span
    return AudiobookPlan(chapters=[
        Chapter(title=t, spans=[Span(voice_id=None, text=b)])
        for t, b in (("One", "alpha"), ("Two", "beta"), ("Three", "gamma"))
    ])


def _stop_after(n_ok):
    state = {"i": 0}

    async def check():
        state["i"] += 1
        return state["i"] > n_ok

    return check


def _render(monkeypatch, outputs, calls, n_ok):
    from api.routers import audiobook
    monkeypatch.setattr(audiobook, "_build_synth", _stub_build_synth(calls))
    monkeypatch.setattr("core.config.OUTPUTS_DIR", str(outputs))
    monkeypatch.setattr("services.ffmpeg_utils.find_ffmpeg", lambda: "/usr/bin/true")
    # A cap far below one chapter: the book always "outgrows" the cache.
    monkeypatch.setattr(audiobook, "prune_cache_dir",
                        lambda d, **kw: prune_cache_dir(d, max_bytes=1, **kw))

    async def run():
        return [json.loads(f[len("data:"):].strip())
                async for f in audiobook._render_longform_sse(
                    _plan(), default_voice=None, is_disconnected=_stop_after(n_ok))]

    return asyncio.run(run())


def _age_cache(cache_dir, seconds):
    t = time.time() - seconds
    for root, _dirs, names in os.walk(cache_dir):
        for name in names:
            os.utime(os.path.join(root, name), (t, t))


def test_resume_reuses_chapters_of_a_book_bigger_than_the_cap(tmp_path, monkeypatch):
    from api.routers import audiobook
    from services.longform_render import LONGFORM_CACHE_SUBDIR

    out = tmp_path / "outputs"
    out.mkdir()
    cache_dir = out / LONGFORM_CACHE_SUBDIR
    calls: list[str] = []

    first = _render(monkeypatch, out, calls, n_ok=2)
    assert [e["type"] for e in first].count("chapter") == 2
    assert calls == ["alpha", "beta"]
    # The interrupted job's own end-of-run prune kept its chapters.
    assert any(cache_dir.glob("*.wav"))

    _age_cache(cache_dir, 3600)  # the user resumes an hour later
    calls.clear()
    second = _render(monkeypatch, out, calls, n_ok=3)
    chapters = [e for e in second if e["type"] == "chapter"]
    assert [c["cached"] for c in chapters] == [True, True, False]
    assert calls == ["gamma"]  # only the unrendered chapter synthesized
    assert audiobook._live_render_starts == {}


def test_prune_spares_files_touched_since_keep_since(tmp_path):
    old = tmp_path / "old.wav"
    reused = tmp_path / "reused.wav"
    seg = tmp_path / SEGMENT_SUBDIR / "fresh.wav"
    seg.parent.mkdir()
    for p in (old, reused, seg):
        p.write_bytes(b"\0" * 600)
    hour_ago = time.time() - 3600
    os.utime(old, (hour_ago - 60, hour_ago - 60))
    os.utime(reused, (hour_ago, hour_ago))
    started = time.time() - 10
    os.utime(reused, None)  # a cache hit during the job

    remaining, removed = prune_cache_dir(str(tmp_path), max_bytes=1, keep_since=started)
    assert removed == 1 and not old.exists()
    assert reused.exists() and seg.exists()
    assert remaining == 1200  # over the cap until a later job, by design


def test_a_finishing_job_spares_a_concurrent_jobs_files(tmp_path, monkeypatch):
    from api.routers import audiobook
    calls: list[str] = []
    out = tmp_path / "outputs"
    out.mkdir()
    # Another render began before this one and is still in flight.
    monkeypatch.setitem(audiobook._live_render_starts, "other", time.time() - 600)
    from services.longform_render import LONGFORM_CACHE_SUBDIR
    cache_dir = out / LONGFORM_CACHE_SUBDIR
    cache_dir.mkdir()
    theirs = cache_dir / "theirs.wav"
    theirs.write_bytes(b"\0" * 600)
    t = time.time() - 300  # written by the other job after it started
    os.utime(theirs, (t, t))

    _render(monkeypatch, out, calls, n_ok=1)
    assert theirs.exists()
