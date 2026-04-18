"""Phase 2: FIFO working-buffer, consolidation bookkeeping, async pipeline.

No network calls — extractor and vector store are mocked.
Run with: python -m pytest tests/test_phase2_working_memory.py -v
"""
from __future__ import annotations

import asyncio

import pytest

from conftest import _uid
from core.schemas import Message

SAMPLE_SUBJECTS_EXTRACTED = {
    "subjects": [
        {
            "name": "User",
            "summary": "The person using this assistant",
            "description_delta": "User likes hiking",
            "subject_type": "person",
        },
        {
            "name": "Marathon",
            "summary": "A 26.2 mile running race",
            "description_delta": "User's goal is to run a marathon",
            "subject_type": "goal",
        },
    ],
    "relations": [{"source": "User", "kind": "wants", "target": "Marathon"}],
}


def _append_pairs(store, session_id: str, n: int) -> None:
    """Append n user+assistant message pairs (2*n messages total)."""
    for i in range(n):
        store.append(session_id, Message(role="user", content=f"user msg {i}"))
        store.append(session_id, Message(role="assistant", content=f"assistant reply {i}"))


# ---------------------------------------------------------------------------
# Test 1 — get_history limit
# ---------------------------------------------------------------------------

def test_get_history_respects_limit(tmp_path):
    from sessions.sqlite_store import SQLiteSessionStore
    store = SQLiteSessionStore(str(tmp_path / "sess.db"))
    sid = _uid("hist_limit")
    _append_pairs(store, sid, 25)  # 50 messages total

    limited = store.get_history(sid, limit=10)
    assert len(limited) == 10, f"Expected 10, got {len(limited)}"
    assert limited[0].content == "user msg 20", (
        f"Expected first of last-10 to be 'user msg 20', got {limited[0].content!r}"
    )

    all_msgs = store.get_history(sid, limit=None)
    assert len(all_msgs) == 50, f"Expected 50, got {len(all_msgs)}"


# ---------------------------------------------------------------------------
# Test 2 — get_history reset marker
# ---------------------------------------------------------------------------

def test_get_history_respects_reset_marker(tmp_path):
    from sessions.sqlite_store import SQLiteSessionStore
    store = SQLiteSessionStore(str(tmp_path / "sess.db"))
    sid = _uid("hist_reset")
    _append_pairs(store, sid, 5)   # 10 messages before reset
    store.reset(sid)
    _append_pairs(store, sid, 3)   # 6 messages post-reset

    history = store.get_history(sid, limit=20)
    assert len(history) == 6, f"Expected 6 post-reset messages, got {len(history)}"
    assert history[0].content == "user msg 0", (
        f"Expected first post-reset message to be 'user msg 0', got {history[0].content!r}"
    )


# ---------------------------------------------------------------------------
# Test 3 — get_unconsolidated window math
# ---------------------------------------------------------------------------

def test_get_unconsolidated_window_math(tmp_path):
    from sessions.sqlite_store import SQLiteSessionStore
    store = SQLiteSessionStore(str(tmp_path / "sess.db"))
    sid = _uid("unconsolidated")
    _append_pairs(store, sid, 25)  # 50 messages
    working_size = 10

    batch = store.get_unconsolidated(sid, working_size)
    assert len(batch) > 0, "Expected unconsolidated messages before any mark"

    max_id = store.get_max_message_id(sid)
    cutoff = max_id - working_size
    store.mark_consolidated(sid, cutoff)

    batch_after = store.get_unconsolidated(sid, working_size)
    assert batch_after == [], f"Expected [] after marking, got {len(batch_after)} messages"


# ---------------------------------------------------------------------------
# Test 4 — mark_consolidated is monotonic
# ---------------------------------------------------------------------------

def test_mark_consolidated_is_monotonic(tmp_path):
    from sessions.sqlite_store import SQLiteSessionStore
    store = SQLiteSessionStore(str(tmp_path / "sess.db"))
    sid = _uid("mono")
    _append_pairs(store, sid, 20)  # 40 messages

    store.mark_consolidated(sid, 10)
    store.mark_consolidated(sid, 5)  # lower value — must not overwrite the higher mark

    batch = store.get_unconsolidated(sid, 5)
    assert len(batch) > 0, (
        "Expected messages between mark=10 and cutoff — second mark must not regress to 5"
    )


# ---------------------------------------------------------------------------
# Test 5 — consolidator extracts, ingests, and mirrors to Qdrant
# ---------------------------------------------------------------------------

def test_consolidator_extracts_and_ingests(tmp_path, monkeypatch):
    import memory.extractor as extractor_mod
    import memory.store as store_mod
    import memory.bridge as bridge_mod
    import memory.vector as vector_mod
    from memory.consolidator import consolidate_if_needed
    from sessions.sqlite_store import SQLiteSessionStore

    store = SQLiteSessionStore(str(tmp_path / "sess.db"))

    fresh_ss = store_mod.SubjectStore(db_path=str(tmp_path / "mem.db"))
    monkeypatch.setattr(store_mod, "subject_store", fresh_ss)
    monkeypatch.setattr(bridge_mod, "subject_store", fresh_ss)
    monkeypatch.setattr(bridge_mod, "_loaded_users", set())

    monkeypatch.setattr(extractor_mod, "extract_subjects",
                        lambda *a, **kw: SAMPLE_SUBJECTS_EXTRACTED)
    monkeypatch.setattr(vector_mod.vector_store, "search_with_payload",
                        lambda *a, **kw: [])

    upsert_calls: list[dict] = []

    def capture_upsert(node_id, user_id, kind, name, text, subject_type="other"):
        upsert_calls.append({"node_id": node_id, "name": name})

    monkeypatch.setattr(vector_mod.vector_store, "upsert", capture_upsert)

    sid = _uid("consolidate")
    _append_pairs(store, sid, 25)  # 50 messages, 40 outside FIFO window

    asyncio.run(consolidate_if_needed(sid, store))

    subjects = bridge_mod.get_full_graph(sid)["nodes"]
    names = {s["name"] for s in subjects}
    assert "User" in names, f"Expected 'User' in subjects, got {names}"
    assert "Marathon" in names, f"Expected 'Marathon' in subjects, got {names}"

    assert len(upsert_calls) == 2, f"Expected 2 upsert calls (one per new subject), got {len(upsert_calls)}"

    remaining = store.get_unconsolidated(sid, 10)
    assert remaining == [], f"Expected [] after consolidation, got {len(remaining)}"


# ---------------------------------------------------------------------------
# Test 6 — consolidator is idempotent (second call is a no-op)
# ---------------------------------------------------------------------------

def test_consolidator_is_idempotent(tmp_path, monkeypatch):
    import memory.extractor as extractor_mod
    import memory.store as store_mod
    import memory.bridge as bridge_mod
    import memory.vector as vector_mod
    from memory.consolidator import consolidate_if_needed
    from sessions.sqlite_store import SQLiteSessionStore

    store = SQLiteSessionStore(str(tmp_path / "sess.db"))

    fresh_ss = store_mod.SubjectStore(db_path=str(tmp_path / "mem.db"))
    monkeypatch.setattr(store_mod, "subject_store", fresh_ss)
    monkeypatch.setattr(bridge_mod, "subject_store", fresh_ss)
    monkeypatch.setattr(bridge_mod, "_loaded_users", set())

    call_count = [0]

    def counting_extractor(*a, **kw):
        call_count[0] += 1
        return SAMPLE_SUBJECTS_EXTRACTED

    monkeypatch.setattr(extractor_mod, "extract_subjects", counting_extractor)
    monkeypatch.setattr(vector_mod.vector_store, "search_with_payload",
                        lambda *a, **kw: [])
    monkeypatch.setattr(vector_mod.vector_store, "upsert", lambda *a, **kw: None)

    sid = _uid("idempotent")
    _append_pairs(store, sid, 25)

    asyncio.run(consolidate_if_needed(sid, store))
    asyncio.run(consolidate_if_needed(sid, store))

    assert call_count[0] == 1, f"extract_subjects called {call_count[0]}×, expected 1"


# ---------------------------------------------------------------------------
# Test 7 — consolidator disabled by long_term_memory_enabled=False
# ---------------------------------------------------------------------------

def test_consolidator_disabled_by_flag(monkeypatch):
    from core.config import settings
    from memory.consolidator import consolidate_if_needed
    import memory.extractor as extractor_mod

    monkeypatch.setattr(settings, "long_term_memory_enabled", False)

    call_count = [0]

    def tracking_extractor(*a, **kw):
        call_count[0] += 1
        return {"subjects": [], "relations": []}

    monkeypatch.setattr(extractor_mod, "extract_subjects", tracking_extractor)

    class _NeverUsedStore:
        def get_unconsolidated(self, *a, **kw):
            raise AssertionError("store should not be touched when disabled")

    asyncio.run(consolidate_if_needed("any_user", _NeverUsedStore()))
    assert call_count[0] == 0, "extract_subjects should not be called when feature is disabled"


# ---------------------------------------------------------------------------
# Test 8 — _build_history respects FIFO limit (no passive recall injection)
# ---------------------------------------------------------------------------

def test_build_history_respects_limit(tmp_path):
    from sessions.sqlite_store import SQLiteSessionStore
    from core.orchestrator import Orchestrator
    from core.config import settings

    store = SQLiteSessionStore(str(tmp_path / "hist.db"))
    sid = _uid("build_hist")
    _append_pairs(store, sid, 20)  # 40 messages total

    orch = Orchestrator(provider=None, store=store)
    history = orch._build_history(sid, "hello")

    system_msgs = [m for m in history if m.role == "system"]
    assert len(system_msgs) == 1, (
        f"Expected 1 system message (prompt only — no passive recall), got {len(system_msgs)}"
    )

    # Non-system messages = working_memory_size history entries + 1 new user message
    non_system = [m for m in history if m.role != "system"]
    assert len(non_system) == settings.working_memory_size + 1, (
        f"Expected {settings.working_memory_size + 1} non-system messages, "
        f"got {len(non_system)}"
    )
    assert history[-1].role == "user"
    assert history[-1].content == "hello"
