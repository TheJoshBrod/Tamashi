"""Phase 1 spike: verify SQLite-backed fact store, Jac graph operations,
and user isolation.

Run with:
    cd /home/jodab/personal_projects/ai/tamashi
    python -m pytest tests/test_memory_spike.py -v

No running server or LLM API keys needed.
"""
import sys
import os
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


def _uid(base: str) -> str:
    """Unique user ID per test run to avoid Jac in-process graph bleed."""
    return f"{base}_{uuid.uuid4().hex[:8]}"


SAMPLE_FACTS = [
    {"content": "User's dog is named Koda", "topic": "personal", "source_msg_id": 1},
    {"content": "User works as a civil engineer", "topic": "personal", "source_msg_id": 2},
    {"content": "User's goal is to run a 5K by June", "topic": "goals", "source_msg_id": 3},
]


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    """Each test gets its own SQLite db and a fresh bridge cache."""
    db_file = str(tmp_path / "test_memory.db")

    import memory.store as store_mod
    fresh_store = store_mod.FactStore(db_path=db_file)
    monkeypatch.setattr(store_mod, "fact_store", fresh_store)

    import memory.bridge as bridge_mod
    monkeypatch.setattr(bridge_mod, "fact_store", fresh_store)
    # Clear the loaded-user cache so _ensure_loaded queries the fresh db
    monkeypatch.setattr(bridge_mod, "_loaded_users", set())

    yield


def test_ingest_and_retrieve():
    """Facts ingested for a user are retrievable within the same process."""
    from memory import bridge

    user_a = _uid("user_a")
    jids = bridge.ingest_facts(user_a, SAMPLE_FACTS)
    assert len(jids) == 3, f"Expected 3 jids, got {len(jids)}: {jids}"

    facts = bridge.list_user_facts(user_a)
    contents = [f["content"] for f in facts]
    assert "User's dog is named Koda" in contents
    assert "User works as a civil engineer" in contents
    assert "User's goal is to run a 5K by June" in contents


def test_user_isolation():
    """User B sees no facts after only user A has been seeded."""
    from memory import bridge

    user_a, user_b = _uid("user_a"), _uid("user_b")
    bridge.ingest_facts(user_a, SAMPLE_FACTS)

    facts_b = bridge.list_user_facts(user_b)
    assert facts_b == [], f"User B should have no facts, got: {facts_b}"


def test_retrieve_context_empty_then_populated():
    """retrieve_context returns empty string before any facts, formatted string after."""
    from memory import bridge

    user_a = _uid("user_a")
    ctx = bridge.retrieve_context(user_a)
    assert ctx == "", f"Expected empty before ingestion, got: {ctx!r}"

    bridge.ingest_facts(user_a, SAMPLE_FACTS[:1])
    ctx = bridge.retrieve_context(user_a)
    assert ctx.startswith("Relevant memory:"), ctx
    assert "Koda" in ctx


def test_sqlite_persistence_via_reload(tmp_path, monkeypatch):
    """Facts survive Jac graph cache clear (simulates process restart via _ensure_loaded)."""
    import memory.store as store_mod
    import memory.bridge as bridge_mod

    db_file = str(tmp_path / "persist_test.db")
    fresh_store = store_mod.FactStore(db_path=db_file)
    monkeypatch.setattr(store_mod, "fact_store", fresh_store)
    monkeypatch.setattr(bridge_mod, "fact_store", fresh_store)
    monkeypatch.setattr(bridge_mod, "_loaded_users", set())

    user_a = _uid("persist_user")

    # Write facts
    bridge_mod.ingest_facts(user_a, SAMPLE_FACTS)

    # Simulate restart: clear the in-process cache (Jac graph nodes persist in-process
    # but _loaded_users is cleared, forcing a reload from SQLite next access)
    bridge_mod._loaded_users.clear()

    facts = bridge_mod.list_user_facts(user_a)
    contents = [f["content"] for f in facts]
    assert "User's dog is named Koda" in contents, f"After reload: {facts}"
    assert len(facts) == len(SAMPLE_FACTS), f"Expected {len(SAMPLE_FACTS)}, got {len(facts)}"


def test_max_facts_cap():
    """RetrieveFacts respects the max_facts cap."""
    from memory import bridge
    from jaclang.lib import spawn, root
    from memory.walkers import GetOrCreateUser, RetrieveFacts

    user_a = _uid("user_cap")
    many_facts = [
        {"content": f"Fact number {i}", "topic": "other", "source_msg_id": i}
        for i in range(20)
    ]
    bridge.ingest_facts(user_a, many_facts)

    user_node = spawn(GetOrCreateUser(user_id=user_a), root()).reports[0]
    result = spawn(RetrieveFacts(max_facts=5), user_node)
    assert len(result.reports) <= 5, f"Got {len(result.reports)}, expected ≤5"
