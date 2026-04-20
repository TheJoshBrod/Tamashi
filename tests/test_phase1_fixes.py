"""Phase 1 regression tests — the three P0 fixes from merged-pan.md.

These tests pin the correctness guarantees of the Phase 1 bug fixes so future
refactors cannot silently reintroduce the bugs:
  - P0 #1: relations rehydrate from SQLite on cache-empty LoadSubjects
  - P0 #2: subject_events WAL survives concurrent appends during a rewrite
  - P0 #3: IngestSubjects deduplicates (src, kind, tgt) edges

Run with:
    env/bin/python3 -m pytest tests/test_phase1_fixes.py -v
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from conftest import _uid


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

    yield fresh_store


# --- P0 #2: WAL race fix ---

def test_subject_events_race_survives_concurrent_append(isolated_store):
    """The rewriter snapshots ids → LLM runs → atomic delete-by-id.

    Simulates the race: an event that appends *during* the LLM call must have a
    new id and survive the DELETE WHERE id IN (<snapshot>) step.
    """
    store = isolated_store
    u = _uid("race")

    id_a = store.append_event(u, "Koda", "fact a")
    id_b = store.append_event(u, "Koda", "fact b")
    id_c = store.append_event(u, "Koda", "fact c")

    # Rewriter snapshot before the (slow) LLM call
    snapshot = [e["id"] for e in store.get_events(u, "Koda")]
    assert snapshot == [id_a, id_b, id_c]

    # Concurrent append lands while the LLM is running
    id_d = store.append_event(u, "Koda", "fact d")
    assert id_d not in snapshot

    # Rewriter commits: atomic delete of exactly the snapshot ids
    store.delete_events_by_ids(snapshot)

    remaining = store.get_events(u, "Koda")
    assert len(remaining) == 1
    assert remaining[0]["id"] == id_d
    assert remaining[0]["payload"] == "fact d"


def test_delete_events_by_ids_empty_is_noop(isolated_store):
    """Rewriter guards against empty snapshot; an empty id list must not wipe the table."""
    store = isolated_store
    u = _uid("race_empty")
    store.append_event(u, "Koda", "fact a")
    store.delete_events_by_ids([])
    assert store.get_event_count(u, "Koda") == 1


# --- P0 #3: edge dedup ---

def test_ingest_deduplicates_identical_edge():
    """Ingesting the same (src, kind, tgt) twice must produce exactly one Jac edge."""
    from memory import bridge

    u = _uid("edgededup")
    subjects = [
        {"name": "Koda", "summary": "a dog", "description_delta": "Koda is a dog",
         "subject_type": "object"},
        {"name": "User", "summary": "the user", "description_delta": "the user",
         "subject_type": "person"},
    ]
    relation = [{"source": "User", "kind": "has_pet", "target": "Koda"}]

    bridge.ingest_subjects(u, subjects, relation)
    bridge.ingest_subjects(u, [], relation)  # second pass with same edge

    graph = bridge.get_full_graph(u)
    edges = [
        e for e in graph["edges"]
        if e["kind"] == "has_pet" and e["label"] == "has_pet"
    ]
    assert len(edges) == 1, f"Expected exactly one has_pet edge, got {edges}"


# --- P0 #1: relations rehydrate on cache-empty load ---

def test_relations_rehydrate_after_cache_flush():
    """Simulates process restart: clear the in-process Jac cache and verify that
    LoadSubjects restores relations alongside subjects.
    """
    from memory import bridge
    import memory.bridge as bridge_mod

    u = _uid("rehydrate")
    subjects = [
        {"name": "User", "summary": "the user", "description_delta": "the user",
         "subject_type": "person"},
        {"name": "5K race", "summary": "a running goal",
         "description_delta": "wants to run a 5K", "subject_type": "goal"},
    ]
    relations = [{"source": "User", "kind": "wants", "target": "5K race"}]

    bridge.ingest_subjects(u, subjects, relations)

    # Simulate restart: drop the Jac cache so _ensure_loaded re-runs LoadSubjects.
    # Subjects + relations live in SQLite; the in-process Jac graph is empty for
    # this user until LoadSubjects fires.
    bridge_mod._loaded_users.discard(u)

    # Force a fresh Jac subgraph for this user so probe() returns empty and
    # LoadSubjects has to rehydrate from SQLite.
    fresh_uid = _uid("rehydrate_fresh")
    # Copy rows over to the new user_id (the existing Jac subtree for `u` is
    # already populated, which would short-circuit rehydration).
    import sqlite3
    con = sqlite3.connect(bridge_mod.subject_store._db_path)
    try:
        con.execute(
            "INSERT INTO memory_subjects (user_id, name, summary, description, subject_type, recent_events, node_jid) "
            "SELECT ?, name, summary, description, subject_type, recent_events, node_jid FROM memory_subjects WHERE user_id = ?",
            (fresh_uid, u),
        )
        con.execute(
            "INSERT INTO memory_relations (user_id, src_name, kind, tgt_name, weight) "
            "SELECT ?, src_name, kind, tgt_name, weight FROM memory_relations WHERE user_id = ?",
            (fresh_uid, u),
        )
        con.commit()
    finally:
        con.close()

    # First access for fresh_uid: Jac is empty, SQLite has the rows — LoadSubjects
    # must restore both subjects AND relations.
    graph = bridge.get_full_graph(fresh_uid)
    node_names = {n["label"] for n in graph["nodes"]}
    assert "User" in node_names
    assert "5K race" in node_names

    edges = [e for e in graph["edges"] if e["kind"] == "wants"]
    assert len(edges) == 1, f"Expected 'wants' edge to rehydrate, got {graph['edges']}"
