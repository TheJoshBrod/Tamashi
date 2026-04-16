"""Phase 1-3: verify SQLite-backed subject store, Jac graph operations,
and user isolation.

Run with:
    cd /home/jodab/personal_projects/ai/tamashi
    python -m pytest tests/test_memory_spike.py -v

No running server or LLM API keys needed.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from conftest import _uid


SAMPLE_SUBJECTS = [
    {
        "name": "Koda",
        "summary": "User's golden retriever dog",
        "description_delta": "User's dog is named Koda, a golden retriever",
        "subject_type": "object",
    },
    {
        "name": "User",
        "summary": "The person using this assistant",
        "description_delta": "User works as a civil engineer",
        "subject_type": "person",
    },
    {
        "name": "5K race",
        "summary": "A 5-kilometer running race goal",
        "description_delta": "User's goal is to run a 5K by June",
        "subject_type": "goal",
    },
]

SAMPLE_RELATIONS = [
    {"source": "User", "kind": "wants", "target": "5K race"},
    {"source": "Koda", "kind": "is_a", "target": "User"},
]


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    """Each test gets its own SQLite db and a fresh bridge cache."""
    db_file = str(tmp_path / "test_memory.db")

    import memory.store as store_mod
    fresh_store = store_mod.SubjectStore(db_path=db_file)
    monkeypatch.setattr(store_mod, "subject_store", fresh_store)

    import memory.bridge as bridge_mod
    monkeypatch.setattr(bridge_mod, "subject_store", fresh_store)
    monkeypatch.setattr(bridge_mod, "_loaded_users", set())

    yield


def test_ingest_and_retrieve():
    """Subjects ingested for a user are retrievable within the same process."""
    from memory import bridge

    user_a = _uid("user_a")
    result = bridge.ingest_subjects(user_a, SAMPLE_SUBJECTS, SAMPLE_RELATIONS)
    new_jids = result["new_jids"]
    assert len(new_jids) == 3, f"Expected 3 new subjects, got {new_jids}"

    subjects = bridge.list_user_subjects(user_a)
    names = {s["name"] for s in subjects}
    assert "Koda" in names
    assert "User" in names
    assert "5K race" in names


def test_user_isolation():
    """User B sees no subjects after only user A has been seeded."""
    from memory import bridge

    user_a, user_b = _uid("user_a"), _uid("user_b")
    bridge.ingest_subjects(user_a, SAMPLE_SUBJECTS, [])

    subjects_b = bridge.list_user_subjects(user_b)
    assert subjects_b == [], f"User B should have no subjects, got: {subjects_b}"


def test_retrieve_context_empty_then_populated():
    """retrieve_context returns empty string before any subjects, non-empty after."""
    from memory import bridge

    user_a = _uid("user_a")
    ctx = bridge.retrieve_context(user_a)
    assert ctx == "", f"Expected empty before ingestion, got: {ctx!r}"

    bridge.ingest_subjects(user_a, SAMPLE_SUBJECTS[:1], [])
    ctx = bridge.retrieve_context(user_a)
    assert ctx.startswith("Relevant memory:"), ctx
    assert "Koda" in ctx


def test_sqlite_persistence_via_reload(tmp_path, monkeypatch):
    """Subjects survive Jac graph cache clear (simulates process restart via _ensure_loaded)."""
    import memory.store as store_mod
    import memory.bridge as bridge_mod

    db_file = str(tmp_path / "persist_test.db")
    fresh_store = store_mod.SubjectStore(db_path=db_file)
    monkeypatch.setattr(store_mod, "subject_store", fresh_store)
    monkeypatch.setattr(bridge_mod, "subject_store", fresh_store)
    monkeypatch.setattr(bridge_mod, "_loaded_users", set())

    user_a = _uid("persist_user")

    bridge_mod.ingest_subjects(user_a, SAMPLE_SUBJECTS, [])

    # Simulate restart: clear the in-process cache.
    # The Jac graph still has the nodes (same process), but _ensure_loaded
    # will probe the graph and find them, marking the user as loaded.
    bridge_mod._loaded_users.clear()

    subjects = bridge_mod.list_user_subjects(user_a)
    names = {s["name"] for s in subjects}
    assert "Koda" in names, f"After reload: {subjects}"
    assert len(subjects) == len(SAMPLE_SUBJECTS), f"Expected {len(SAMPLE_SUBJECTS)}, got {len(subjects)}"


def test_max_subjects_cap():
    """RetrieveSubjects respects the max_subjects cap."""
    from memory import bridge
    from jaclang.lib import spawn, root
    from memory.walkers import GetOrCreateUser, RetrieveSubjects

    user_a = _uid("user_cap")
    many_subjects = [
        {
            "name": f"Subject_{i}",
            "summary": f"Summary {i}",
            "description_delta": f"Description {i}",
            "subject_type": "other",
        }
        for i in range(20)
    ]
    bridge.ingest_subjects(user_a, many_subjects, [])

    user_node = spawn(GetOrCreateUser(user_id=user_a), root()).reports[0]
    result = spawn(RetrieveSubjects(max_subjects=5), user_node)
    assert len(result.reports) <= 5, f"Got {len(result.reports)}, expected ≤5"


def test_intra_batch_dedup():
    """Two subjects with the same name in one batch merge description_deltas."""
    from memory import bridge
    from memory.store import subject_store
    import memory.bridge as bridge_mod

    user_a = _uid("dedup")
    batch = [
        {
            "name": "Ann Arbor",
            "summary": "City in Michigan",
            "description_delta": "User lives in Ann Arbor",
            "subject_type": "place",
        },
        {
            "name": "Ann Arbor",
            "summary": "City in Michigan",
            "description_delta": "Ann Arbor is near Detroit",
            "subject_type": "place",
        },
    ]
    result = bridge_mod.ingest_subjects(user_a, batch, [])
    # Only ONE subject created, not two
    assert len(result["new_jids"]) == 1, f"Expected 1 new subject, got {result['new_jids']}"

    subjects = bridge_mod.list_user_subjects(user_a)
    names = [s["name"] for s in subjects]
    assert names.count("Ann Arbor") == 1, f"Duplicate subjects found: {names}"


def test_sqlite_subject_store_upsert_and_list():
    """SubjectStore: insert, retrieve, and unique constraint on (user_id, name)."""
    from memory.store import SubjectStore

    import tempfile, os
    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "test.db")
        store = SubjectStore(db_path=db)

        user = _uid("ss_test")
        store.upsert_subject(user, "Koda", "Dog summary", "Koda is a dog", "object", ["event1"])
        store.upsert_subject(user, "Koda", "Updated summary", "Koda is a golden retriever", "object", ["event1", "event2"])

        rows = store.get_subjects(user)
        assert len(rows) == 1, f"Expected 1 subject (upsert should merge), got {len(rows)}"
        assert rows[0]["summary"] == "Updated summary"
        assert len(rows[0]["recent_events"]) == 2


def test_sqlite_relation_store():
    """SubjectStore: relation upsert and retrieval."""
    from memory.store import SubjectStore

    import tempfile, os
    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "test.db")
        store = SubjectStore(db_path=db)

        user = _uid("rel_test")
        store.upsert_relation(user, "Koda", "is_a", "dog", weight=1.0)
        store.upsert_relation(user, "User", "knows", "Koda", weight=1.0)
        # Re-upsert — should not create duplicates
        store.upsert_relation(user, "Koda", "is_a", "dog", weight=0.9)

        relations = store.get_relations(user)
        assert len(relations) == 2, f"Expected 2 relations, got {len(relations)}"
        koda_is_a = next(r for r in relations if r["src_name"] == "Koda" and r["kind"] == "is_a")
        assert koda_is_a["weight"] == 0.9, "Updated weight not reflected"
