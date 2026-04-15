"""Phase 2: FIFO working-buffer, consolidation bookkeeping, async pipeline.

No network calls — extractor and vector store are mocked.
Run with: python -m pytest tests/test_phase2_working_memory.py -v
"""
from __future__ import annotations

import asyncio

import pytest

from conftest import _uid
from core.schemas import Message

SAMPLE_FACTS_EXTRACTED = [
    {"content": "User likes hiking", "topic": "personal", "source_msg_id": 20},
    {"content": "User's goal is to run a marathon", "topic": "goals", "source_msg_id": 20},
]


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
    # Last 10 of 50 start at the 21st pair (0-indexed: "user msg 20")
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

    # Nothing consolidated yet — should return messages outside the working window
    batch = store.get_unconsolidated(sid, working_size)
    assert len(batch) > 0, "Expected unconsolidated messages before any mark"

    # Mark the entire outside-window portion consolidated
    max_id = store.get_max_message_id(sid)
    cutoff = max_id - working_size
    store.mark_consolidated(sid, cutoff)

    batch_after = store.get_unconsolidated(sid, working_size)
    assert batch_after == [], f"Expected [] after marking, got {len(batch_after)} messages"


# ---------------------------------------------------------------------------
# Test 4 — mark_consolidated is monotonic (lower value must not regress mark)
# ---------------------------------------------------------------------------

def test_mark_consolidated_is_monotonic(tmp_path):
    from sessions.sqlite_store import SQLiteSessionStore
    store = SQLiteSessionStore(str(tmp_path / "sess.db"))
    sid = _uid("mono")
    _append_pairs(store, sid, 20)  # 40 messages

    store.mark_consolidated(sid, 10)
    store.mark_consolidated(sid, 5)  # lower value — must not overwrite the higher mark

    # With working_size=5: cutoff = max_id - 5 ≈ 35.
    # Messages 11..35 are still unconsolidated (mark stayed at 10, not regressed to 5).
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

    fresh_fs = store_mod.FactStore(db_path=str(tmp_path / "mem.db"))
    monkeypatch.setattr(store_mod, "fact_store", fresh_fs)
    monkeypatch.setattr(bridge_mod, "fact_store", fresh_fs)
    monkeypatch.setattr(bridge_mod, "_loaded_users", set())

    monkeypatch.setattr(extractor_mod, "extract_facts",
                        lambda *a, **kw: SAMPLE_FACTS_EXTRACTED)

    upsert_calls: list[dict] = []
    monkeypatch.setattr(
        vector_mod.vector_store, "upsert",
        lambda node_id, user_id, kind, text: upsert_calls.append(
            {"node_id": node_id, "user_id": user_id, "text": text}
        ),
    )

    sid = _uid("consolidate")
    _append_pairs(store, sid, 25)  # 50 messages, 40 outside FIFO window

    asyncio.run(consolidate_if_needed(sid, store))

    # Both facts are present in the Jac graph + SQLite
    facts = bridge_mod.list_user_facts(sid)
    contents = {f["content"] for f in facts}
    assert "User likes hiking" in contents
    assert "User's goal is to run a marathon" in contents

    # Qdrant upsert called once per extracted fact
    assert len(upsert_calls) == 2, f"Expected 2 upsert calls, got {len(upsert_calls)}"

    # Window is marked — a second pass returns nothing unconsolidated
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

    fresh_fs = store_mod.FactStore(db_path=str(tmp_path / "mem.db"))
    monkeypatch.setattr(store_mod, "fact_store", fresh_fs)
    monkeypatch.setattr(bridge_mod, "fact_store", fresh_fs)
    monkeypatch.setattr(bridge_mod, "_loaded_users", set())

    call_count = [0]

    def counting_extractor(*a, **kw):
        call_count[0] += 1
        return SAMPLE_FACTS_EXTRACTED

    monkeypatch.setattr(extractor_mod, "extract_facts", counting_extractor)
    monkeypatch.setattr(vector_mod.vector_store, "upsert", lambda *a, **kw: None)

    sid = _uid("idempotent")
    _append_pairs(store, sid, 25)

    asyncio.run(consolidate_if_needed(sid, store))
    asyncio.run(consolidate_if_needed(sid, store))

    assert call_count[0] == 1, f"extract_facts called {call_count[0]}×, expected 1"


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
        return []

    monkeypatch.setattr(extractor_mod, "extract_facts", tracking_extractor)

    class _NeverUsedStore:
        def get_unconsolidated(self, *a, **kw):
            raise AssertionError("store should not be touched when disabled")

    asyncio.run(consolidate_if_needed("any_user", _NeverUsedStore()))
    assert call_count[0] == 0, "extract_facts should not be called when feature is disabled"


# ---------------------------------------------------------------------------
# Test 8 — _build_history injects recall + respects FIFO limit
# ---------------------------------------------------------------------------

def test_build_history_includes_recall_and_respects_limit(tmp_path, monkeypatch):
    from sessions.sqlite_store import SQLiteSessionStore
    from core.orchestrator import Orchestrator
    from core.config import settings
    import memory.bridge as bridge_mod

    store = SQLiteSessionStore(str(tmp_path / "hist.db"))
    sid = _uid("build_hist")
    _append_pairs(store, sid, 20)  # 40 messages total

    monkeypatch.setattr(
        bridge_mod, "retrieve_context",
        lambda *a, **kw: "Relevant memory:\n- [goals] Run a 5K",
    )

    orch = Orchestrator(provider=None, store=store)
    history = orch._build_history(sid, "hello")

    system_msgs = [m for m in history if m.role == "system"]
    assert len(system_msgs) == 2, (
        f"Expected 2 system messages (prompt + recall), got {len(system_msgs)}"
    )
    assert any("Relevant memory" in (m.content or "") for m in system_msgs), (
        "Expected recall block in system messages"
    )

    # Non-system messages = working_memory_size history entries + 1 new user message
    non_system = [m for m in history if m.role != "system"]
    assert len(non_system) == settings.working_memory_size + 1, (
        f"Expected {settings.working_memory_size + 1} non-system messages, "
        f"got {len(non_system)}"
    )
    assert history[-1].role == "user"
    assert history[-1].content == "hello"
