"""Phase 1 regression tests — three P0 fixes pinned as invariants.

  - P0 #1: relations rehydrate from SQLite on cache-empty LoadSubjects
  - P0 #2: subject_events WAL survives concurrent appends during a rewrite
  - P0 #3: IngestSubjects deduplicates (src, kind, tgt) edges

Run with:
    env/bin/python3 -m pytest tests/test_phase1_fixes.py -v
"""
import pytest

from conftest import _uid


@pytest.fixture(autouse=True)
def _autouse_isolation(isolated_store):
    yield isolated_store


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


# --- Phase 1.5: get_subject_context rehydrates recent_events from subject_events ---

def test_get_subject_context_wal_join_preserves_ui_contract():
    """`recent_events` in the context response is sourced from subject_events.

    The UI (display/memory.js) reads `subject.recent_events` to render the WAL
    badge. After Phase 1.5 the Jac node no longer carries the list, so bridge
    must rehydrate from the WAL table. Order must match insertion order.
    """
    from memory import bridge

    u = _uid("wal_join")
    subjects = [
        {"name": "Koda", "summary": "a dog", "description_delta": "Koda is a dog",
         "subject_type": "object"},
    ]
    bridge.ingest_subjects(u, subjects, [])
    # Second ingest appends a delta to the existing subject — becomes a WAL row.
    bridge.ingest_subjects(
        u,
        [{"name": "Koda", "summary": "a dog", "description_delta": "Koda loves walks",
          "subject_type": "object"}],
        [],
    )
    bridge.ingest_subjects(
        u,
        [{"name": "Koda", "summary": "a dog", "description_delta": "Koda is three",
          "subject_type": "object"}],
        [],
    )

    ctx = bridge.get_subject_context(u, "Koda")
    assert ctx is not None
    assert ctx["subject"]["recent_events"] == ["Koda loves walks", "Koda is three"]


def test_get_subject_context_wal_empty_returns_list():
    """Empty WAL returns `[]`, not None or missing key — UI must not crash."""
    from memory import bridge

    u = _uid("wal_empty")
    bridge.ingest_subjects(
        u,
        [{"name": "Koda", "summary": "a dog", "description_delta": "Koda is a dog",
          "subject_type": "object"}],
        [],
    )
    ctx = bridge.get_subject_context(u, "Koda")
    assert ctx is not None
    assert ctx["subject"]["recent_events"] == []


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

def test_load_subjects_twice_does_not_duplicate_edges():
    """LoadSubjects must be idempotent: re-running against the same User node
    with the same SQLite rows must not re-add Relates edges. The walker header
    promises this; this test pins it in place.
    """
    from jaclang.lib import spawn, root
    from memory.walkers import GetOrCreateUser, LoadSubjects

    from memory import bridge
    import memory.bridge as bridge_mod

    u = _uid("loadtwice")
    subjects = [
        {"name": "User", "summary": "the user", "description_delta": "the user",
         "subject_type": "person"},
        {"name": "Koda", "summary": "the dog", "description_delta": "Koda is a dog",
         "subject_type": "object"},
    ]
    relations = [{"source": "User", "kind": "has_pet", "target": "Koda"}]
    bridge.ingest_subjects(u, subjects, relations)

    persisted = bridge_mod.subject_store.get_subjects(u, limit=1000)
    persisted_rel = bridge_mod.subject_store.get_relations(u)
    user_node = spawn(GetOrCreateUser(user_id=u), root()).reports[0]

    spawn(LoadSubjects(subjects=persisted, relations=persisted_rel), user_node)
    spawn(LoadSubjects(subjects=persisted, relations=persisted_rel), user_node)

    edges = [e for e in bridge.get_full_graph(u)["edges"] if e["kind"] == "has_pet"]
    assert len(edges) == 1, f"Expected 1 has_pet edge, got {edges}"


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
            "INSERT INTO memory_subjects (user_id, name, summary, description, subject_type, node_jid) "
            "SELECT ?, name, summary, description, subject_type, node_jid FROM memory_subjects WHERE user_id = ?",
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


# --- Phase 1.5 Commit 2: recent_events column migration + drop ---

def test_legacy_recent_events_column_is_migrated_and_dropped(tmp_path):
    """Old databases with a `recent_events` JSON column must:

    1. Copy pending events into `subject_events` (migration)
    2. Drop the legacy column so the new schema is free of it (capstone)

    Both steps must be idempotent — re-constructing SubjectStore a second time
    against the post-drop DB is a no-op.
    """
    import sqlite3
    from memory.store import SubjectStore

    db = tmp_path / "legacy.db"

    con = sqlite3.connect(db)
    try:
        con.execute(
            """
            CREATE TABLE memory_subjects (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id      TEXT    NOT NULL,
                name         TEXT    NOT NULL,
                summary      TEXT    NOT NULL DEFAULT '',
                description  TEXT    NOT NULL DEFAULT '',
                subject_type TEXT    NOT NULL DEFAULT 'other',
                recent_events TEXT   NOT NULL DEFAULT '[]',
                node_jid     TEXT,
                created_at   TEXT    DEFAULT (datetime('now')),
                updated_at   TEXT    DEFAULT (datetime('now'))
            )
            """
        )
        con.execute(
            """
            INSERT INTO memory_subjects
                (user_id, name, summary, description, subject_type, recent_events)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("u-legacy", "Koda", "a dog", "Koda is a dog", "object",
             '["Koda loves walks", "Koda is three"]'),
        )
        con.commit()
    finally:
        con.close()

    store = SubjectStore(db_path=str(db))

    events = store.get_events("u-legacy", "Koda")
    assert [e["payload"] for e in events] == ["Koda loves walks", "Koda is three"]

    con = sqlite3.connect(db)
    try:
        cols = {r[1] for r in con.execute("PRAGMA table_info(memory_subjects)").fetchall()}
    finally:
        con.close()

    if sqlite3.sqlite_version_info >= (3, 35, 0):
        assert "recent_events" not in cols, (
            f"Expected recent_events column dropped on sqlite {sqlite3.sqlite_version}, got {cols}"
        )
    else:
        assert "recent_events" in cols

    # Second construction must be a no-op: no duplicate events, no crash on the
    # now-missing column.
    SubjectStore(db_path=str(db))
    events_again = store.get_events("u-legacy", "Koda")
    assert [e["payload"] for e in events_again] == ["Koda loves walks", "Koda is three"]
