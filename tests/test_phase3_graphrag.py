"""Phase 3: Qdrant vector store, GraphRAG retrieval path, Subject walkers.

Vector operations use QdrantClient(":memory:") — no disk writes, no server.
Embedding calls use a deterministic stub — no model downloads.
Run with: python -m pytest tests/test_phase3_graphrag.py -v
"""
from __future__ import annotations

import asyncio
import hashlib
import random

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
        "description_delta": "User works as a civil engineer in Ann Arbor",
        "subject_type": "person",
    },
    {
        "name": "5K race",
        "summary": "A 5-kilometer running race",
        "description_delta": "User's goal is to run a 5K by June",
        "subject_type": "goal",
    },
]

_EMBED_DIM = 16  # small fixed size — no real model needed


def _det_embed(text: str) -> list[float]:
    """Deterministic 16-dim unit vector keyed off text content.

    Same text → same vector (cosine similarity 1.0 with itself).
    Different texts → different vectors (low similarity).
    """
    seed = int(hashlib.md5(text.encode()).hexdigest(), 16)
    rng = random.Random(seed)
    vec = [rng.gauss(0, 1) for _ in range(_EMBED_DIM)]
    norm = sum(x * x for x in vec) ** 0.5
    return [x / norm for x in vec]


@pytest.fixture
def qdrant_store():
    """Fresh QdrantMemoryStore backed by an in-memory Qdrant client."""
    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, VectorParams
    from memory.vector import QdrantMemoryStore
    from core.config import settings

    store = QdrantMemoryStore()
    client = QdrantClient(":memory:")
    client.create_collection(
        collection_name=settings.subject_collection,
        vectors_config=VectorParams(size=_EMBED_DIM, distance=Distance.COSINE),
    )
    store._client = client
    store._embed = _det_embed  # bypass fastembed entirely
    return store


@pytest.fixture
def isolated_store(tmp_path, monkeypatch):
    """Fresh SubjectStore + cleared _loaded_users for Jac graph isolation."""
    import memory.store as store_mod
    import memory.bridge as bridge_mod

    fresh_ss = store_mod.SubjectStore(db_path=str(tmp_path / "mem.db"))
    monkeypatch.setattr(store_mod, "subject_store", fresh_ss)
    monkeypatch.setattr(bridge_mod, "subject_store", fresh_ss)
    monkeypatch.setattr(bridge_mod, "_loaded_users", set())
    yield fresh_ss


# ---------------------------------------------------------------------------
# Tests 1-3 — QdrantMemoryStore (memory/vector.py)
# ---------------------------------------------------------------------------

def test_vector_upsert_and_search_roundtrip(qdrant_store):
    user_a = _uid("vec_rt")
    qdrant_store.upsert("jid-1", user_a, "subject", "Koda", "User's golden retriever dog")
    qdrant_store.upsert("jid-2", user_a, "subject", "User", "Civil engineer in Ann Arbor")
    qdrant_store.upsert("jid-3", user_a, "subject", "5K race", "A 5-kilometer running race")

    results = qdrant_store.search(user_a, "Koda\nUser's golden retriever dog", k=1)
    assert results == ["jid-1"], f"Expected ['jid-1'], got {results}"


def test_vector_search_user_isolation(qdrant_store):
    user_a = _uid("vec_iso_a")
    user_b = _uid("vec_iso_b")

    qdrant_store.upsert("a-1", user_a, "subject", "Subject A1", "User A subject one")
    qdrant_store.upsert("a-2", user_a, "subject", "Subject A2", "User A subject two")
    qdrant_store.upsert("b-1", user_b, "subject", "Subject B1", "User B subject one")
    qdrant_store.upsert("b-2", user_b, "subject", "Subject B2", "User B subject two")

    results_a = qdrant_store.search(user_a, "User A subject one", k=5)
    results_b = qdrant_store.search(user_b, "User B subject one", k=5)

    assert all(r.startswith("a-") for r in results_a), (
        f"User A search returned User B results: {results_a}"
    )
    assert all(r.startswith("b-") for r in results_b), (
        f"User B search returned User A results: {results_b}"
    )


def test_vector_upsert_is_idempotent(qdrant_store):
    user_a = _uid("vec_idem")
    node_id = "stable-node-id"

    qdrant_store.upsert(node_id, user_a, "subject", "TestSubject", "Idempotent content")
    qdrant_store.upsert(node_id, user_a, "subject", "TestSubject", "Idempotent content")

    count = qdrant_store.count(user_a)
    assert count == 1, f"Expected 1 point after two identical upserts, got {count}"


# ---------------------------------------------------------------------------
# Tests 4-6 — bridge.retrieve_context (memory/bridge.py)
# ---------------------------------------------------------------------------

def test_retrieve_context_uses_graphrag_path(isolated_store, monkeypatch):
    import memory.bridge as bridge_mod
    import memory.vector as vector_mod

    user_a = _uid("graphrag_path")
    result = bridge_mod.ingest_subjects(user_a, SAMPLE_SUBJECTS, [])
    koda_jid = result["new_jids"].get("Koda")
    assert koda_jid, "Expected Koda to be a new subject"

    monkeypatch.setattr(
        vector_mod.vector_store, "search",
        lambda user_id, query, k: [koda_jid],
    )

    ctx = bridge_mod.retrieve_context(user_a, query="dog")
    assert ctx.startswith("Relevant memory:"), f"Unexpected context prefix: {ctx!r}"
    assert "Koda" in ctx, f"Expected Koda in context, got: {ctx!r}"


def test_retrieve_context_falls_back_when_no_seeds(isolated_store, monkeypatch):
    import memory.bridge as bridge_mod
    import memory.vector as vector_mod

    user_a = _uid("fallback")
    bridge_mod.ingest_subjects(user_a, SAMPLE_SUBJECTS, [])

    monkeypatch.setattr(
        vector_mod.vector_store, "search",
        lambda user_id, query, k: [],
    )

    ctx = bridge_mod.retrieve_context(user_a, query="")
    assert ctx != "", "Expected non-empty context from fallback retrieval"
    assert ctx.startswith("Relevant memory:"), f"Unexpected format: {ctx!r}"


def test_retrieve_context_deduplicates(isolated_store, monkeypatch):
    """Same subject appearing as both seed and neighbor is deduplicated."""
    import memory.bridge as bridge_mod
    import memory.vector as vector_mod

    user_a = _uid("dedup")
    result = bridge_mod.ingest_subjects(user_a, SAMPLE_SUBJECTS[:2], [])
    jid_koda = result["new_jids"].get("Koda")
    jid_user = result["new_jids"].get("User")

    # Both seeds returned — with max_subjects=2, should get exactly 2 unique lines
    monkeypatch.setattr(
        vector_mod.vector_store, "search",
        lambda user_id, query, k: [jid_koda, jid_user],
    )

    ctx = bridge_mod.retrieve_context(user_a, query="test", max_subjects=2)
    lines = [ln for ln in ctx.split("\n") if ln.startswith("- ")]
    assert len(lines) <= 2, f"Expected at most 2 lines with max_subjects=2, got {len(lines)}: {lines}"
    assert len(set(lines)) == len(lines), f"Duplicate lines found: {lines}"


# ---------------------------------------------------------------------------
# Tests 7-8 — Subject walkers: IngestSubjects, RetrieveBySubjectJids
# ---------------------------------------------------------------------------

def test_ingest_subjects_walker_creates_and_reports(isolated_store):
    """IngestSubjects walker creates Subject nodes and reports jids."""
    import memory.bridge as bridge_mod

    user_a = _uid("walker_create")
    result = bridge_mod.ingest_subjects(user_a, SAMPLE_SUBJECTS[:2], [])

    new_jids = result["new_jids"]
    assert "Koda" in new_jids, f"Expected Koda in new_jids: {new_jids}"
    assert "User" in new_jids, f"Expected User in new_jids: {new_jids}"

    subjects = bridge_mod.list_user_subjects(user_a)
    names = {s["name"] for s in subjects}
    assert names == {"Koda", "User"}, f"Unexpected subjects: {names}"


def test_retrieve_by_subject_jids_expands_neighbors(isolated_store):
    """RetrieveBySubjectJids expands to 1-hop neighbors via Relates edges."""
    import memory.bridge as bridge_mod
    from memory.walkers import RetrieveBySubjectJids, GetOrCreateUser, IngestSubjects
    from jaclang.lib import spawn, root
    from datetime import datetime, timezone

    user_a = _uid("jids_expand")
    result = bridge_mod.ingest_subjects(user_a, SAMPLE_SUBJECTS, [])
    koda_jid = result["new_jids"].get("Koda")
    user_jid = result["new_jids"].get("User")
    race_jid = result["new_jids"].get("5K race")

    # Add a Relates edge: User → 5K race
    user_node = spawn(GetOrCreateUser(user_id=user_a), root()).reports[0]
    now = datetime.now(timezone.utc).isoformat()
    spawn(IngestSubjects(subjects=[], relations=[
        {"source": "User", "kind": "wants", "target": "5K race"}
    ], now=now), user_node)

    # Seed on "User"; walker must expand to "5K race" via the edge
    result = spawn(RetrieveBySubjectJids(seed_jids=[user_jid]), user_node)
    returned_names = {str(r["name"]) for r in result.reports}

    assert "User" in returned_names, f"Seed 'User' missing: {returned_names}"
    assert "5K race" in returned_names, f"Neighbor '5K race' not expanded: {returned_names}"
    assert "Koda" not in returned_names, f"Unlinked 'Koda' should not appear: {returned_names}"


# ---------------------------------------------------------------------------
# Tests 9-10 — Nightly linker (memory/linker.py) — now a no-op
# ---------------------------------------------------------------------------

def test_linker_is_noop(isolated_store):
    """run_linker is a no-op in Phase 3 — completes without error."""
    from memory.linker import run_linker
    import memory.bridge as bridge_mod

    user_a = _uid("linker_noop")
    bridge_mod.ingest_subjects(user_a, SAMPLE_SUBJECTS[:2], [])

    # Should complete without raising
    asyncio.run(run_linker())


def test_linker_disabled_when_long_term_memory_off(monkeypatch):
    """run_linker respects long_term_memory_enabled=False indirectly (no-op either way)."""
    from core.config import settings
    from memory.linker import run_linker

    monkeypatch.setattr(settings, "long_term_memory_enabled", False)
    asyncio.run(run_linker())  # Must not raise


# ---------------------------------------------------------------------------
# Test 11 — SubjectStore.list_users (memory/store.py)
# ---------------------------------------------------------------------------

def test_subject_store_list_users(isolated_store):
    import memory.bridge as bridge_mod

    user_a = _uid("lu_a")
    user_b = _uid("lu_b")

    bridge_mod.ingest_subjects(user_a, SAMPLE_SUBJECTS[:2], [])
    bridge_mod.ingest_subjects(user_b, SAMPLE_SUBJECTS[2:], [])

    users = set(isolated_store.list_users())
    assert user_a in users, f"user_a missing from list_users: {users}"
    assert user_b in users, f"user_b missing from list_users: {users}"
