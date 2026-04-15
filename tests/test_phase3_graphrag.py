"""Phase 3: Qdrant vector store, GraphRAG retrieval path, nightly linker.

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

SAMPLE_FACTS = [
    {"content": "User's dog is named Koda", "topic": "personal", "source_msg_id": 1},
    {"content": "User works as a civil engineer", "topic": "personal", "source_msg_id": 2},
    {"content": "User's goal is to run a 5K by June", "topic": "goals", "source_msg_id": 3},
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

    store = QdrantMemoryStore()
    client = QdrantClient(":memory:")
    client.create_collection(
        collection_name="tamashi_memory",
        vectors_config=VectorParams(size=_EMBED_DIM, distance=Distance.COSINE),
    )
    store._client = client
    store._embed = _det_embed  # bypass fastembed entirely
    return store


@pytest.fixture
def isolated_store(tmp_path, monkeypatch):
    """Fresh FactStore + cleared _loaded_users for Jac graph isolation."""
    import memory.store as store_mod
    import memory.bridge as bridge_mod

    fresh_fs = store_mod.FactStore(db_path=str(tmp_path / "mem.db"))
    monkeypatch.setattr(store_mod, "fact_store", fresh_fs)
    monkeypatch.setattr(bridge_mod, "fact_store", fresh_fs)
    monkeypatch.setattr(bridge_mod, "_loaded_users", set())
    yield fresh_fs


# ---------------------------------------------------------------------------
# Tests 1-3 — QdrantMemoryStore (memory/vector.py)
# ---------------------------------------------------------------------------

def test_vector_upsert_and_search_roundtrip(qdrant_store):
    user_a = _uid("vec_rt")
    qdrant_store.upsert("jid-1", user_a, "fact", "User's dog is named Koda")
    qdrant_store.upsert("jid-2", user_a, "fact", "User works as a civil engineer")
    qdrant_store.upsert("jid-3", user_a, "fact", "User's goal is to run a 5K")

    # Exact-text query → same vector → cosine similarity 1.0 → top result
    results = qdrant_store.search(user_a, "User's dog is named Koda", k=1)
    assert results == ["jid-1"], f"Expected ['jid-1'], got {results}"


def test_vector_search_user_isolation(qdrant_store):
    user_a = _uid("vec_iso_a")
    user_b = _uid("vec_iso_b")

    qdrant_store.upsert("a-1", user_a, "fact", "User A fact one")
    qdrant_store.upsert("a-2", user_a, "fact", "User A fact two")
    qdrant_store.upsert("b-1", user_b, "fact", "User B fact one")
    qdrant_store.upsert("b-2", user_b, "fact", "User B fact two")

    results_a = qdrant_store.search(user_a, "User A fact one", k=5)
    results_b = qdrant_store.search(user_b, "User B fact one", k=5)

    assert all(r.startswith("a-") for r in results_a), (
        f"User A search returned User B results: {results_a}"
    )
    assert all(r.startswith("b-") for r in results_b), (
        f"User B search returned User A results: {results_b}"
    )


def test_vector_upsert_is_idempotent(qdrant_store):
    user_a = _uid("vec_idem")
    node_id = "stable-node-id"

    qdrant_store.upsert(node_id, user_a, "fact", "Idempotent fact content")
    qdrant_store.upsert(node_id, user_a, "fact", "Idempotent fact content")

    count = qdrant_store.count(user_a)
    assert count == 1, f"Expected 1 point after two identical upserts, got {count}"


# ---------------------------------------------------------------------------
# Tests 4-6 — bridge.retrieve_context (memory/bridge.py)
# ---------------------------------------------------------------------------

def test_retrieve_context_uses_graphrag_path(isolated_store, monkeypatch):
    import memory.bridge as bridge_mod
    import memory.vector as vector_mod

    user_a = _uid("graphrag_path")
    jids = bridge_mod.ingest_facts(user_a, SAMPLE_FACTS)
    seed_jid = jids[0]  # first fact — "User's dog is named Koda"

    monkeypatch.setattr(
        vector_mod.vector_store, "search",
        lambda user_id, query, k: [seed_jid],
    )

    ctx = bridge_mod.retrieve_context(user_a, query="dog")
    assert ctx.startswith("Relevant memory:"), f"Unexpected context prefix: {ctx!r}"
    assert "Koda" in ctx, f"Expected first fact in context, got: {ctx!r}"


def test_retrieve_context_falls_back_when_no_seeds(isolated_store, monkeypatch):
    import memory.bridge as bridge_mod
    import memory.vector as vector_mod

    user_a = _uid("fallback")
    bridge_mod.ingest_facts(user_a, SAMPLE_FACTS)

    # Empty vector results → should fall back to naive RetrieveFacts walker
    monkeypatch.setattr(
        vector_mod.vector_store, "search",
        lambda user_id, query, k: [],
    )

    ctx = bridge_mod.retrieve_context(user_a, query="")
    assert ctx != "", "Expected non-empty context from fallback retrieval"
    assert ctx.startswith("Relevant memory:"), f"Unexpected format: {ctx!r}"


def test_retrieve_context_deduplicates_and_caps(isolated_store, monkeypatch):
    """fact[2] is a 1-hop neighbor of both seeds; dedup+cap must fire."""
    import memory.bridge as bridge_mod
    import memory.vector as vector_mod
    from memory.walkers import LinkFacts, GetOrCreateUser
    from jaclang.lib import spawn, root

    user_a = _uid("dedup_cap")
    jids = bridge_mod.ingest_facts(user_a, SAMPLE_FACTS)

    user_node = spawn(GetOrCreateUser(user_id=user_a), root()).reports[0]
    # Draw fact[0]→fact[2] and fact[1]→fact[2] so fact[2] appears as neighbor of both seeds
    spawn(LinkFacts(src_jid=jids[0], target_jids=[{"jid": jids[2], "weight": 0.9}]), user_node)
    spawn(LinkFacts(src_jid=jids[1], target_jids=[{"jid": jids[2], "weight": 0.9}]), user_node)

    # Both fact[0] and fact[1] are seeds → fact[2] would be reported twice without dedup
    monkeypatch.setattr(
        vector_mod.vector_store, "search",
        lambda user_id, query, k: [jids[0], jids[1]],
    )

    ctx = bridge_mod.retrieve_context(user_a, query="test", max_facts=2)
    lines = [ln for ln in ctx.split("\n") if ln.startswith("- ")]
    assert len(lines) == 2, f"Expected exactly 2 lines with max_facts=2, got {len(lines)}: {lines}"
    assert len(set(lines)) == len(lines), f"Duplicate lines found: {lines}"


# ---------------------------------------------------------------------------
# Tests 7-8 — Jac walkers: RetrieveByJids, LinkFacts (memory/walkers.jac)
# ---------------------------------------------------------------------------

def test_retrieve_by_jids_walker_expands_neighbors(isolated_store):
    import memory.bridge as bridge_mod
    from memory.walkers import RetrieveByJids, LinkFacts, GetOrCreateUser
    from jaclang.lib import spawn, root

    user_a = _uid("jids_expand")
    jids = bridge_mod.ingest_facts(user_a, SAMPLE_FACTS)

    user_node = spawn(GetOrCreateUser(user_id=user_a), root()).reports[0]
    # Draw fact[0] → fact[1] edge
    spawn(LinkFacts(src_jid=jids[0], target_jids=[{"jid": jids[1], "weight": 0.95}]), user_node)

    # Seed only fact[0]; walker must expand to fact[1] via the edge
    result = spawn(RetrieveByJids(seed_jids=[jids[0]]), user_node)
    returned = {str(r["jid"]) for r in result.reports}

    assert jids[0] in returned, f"Seed fact[0] missing from results: {returned}"
    assert jids[1] in returned, f"Neighbor fact[1] not expanded: {returned}"
    assert jids[2] not in returned, f"Unlinked fact[2] should not appear: {returned}"


def test_link_facts_walker_draws_edge(isolated_store):
    import memory.bridge as bridge_mod
    from memory.walkers import RetrieveByJids, LinkFacts, GetOrCreateUser
    from jaclang.lib import spawn, root

    user_a = _uid("link_edge")
    jids = bridge_mod.ingest_facts(user_a, SAMPLE_FACTS[:2])
    jid_1, jid_2 = jids[0], jids[1]

    user_node = spawn(GetOrCreateUser(user_id=user_a), root()).reports[0]

    # Before edge: only the seed should appear
    before = {str(r["jid"]) for r in spawn(RetrieveByJids(seed_jids=[jid_1]), user_node).reports}
    assert jid_2 not in before, f"fact[1] must not appear before edge is drawn: {before}"

    # Draw the edge
    spawn(LinkFacts(src_jid=jid_1, target_jids=[{"jid": jid_2, "weight": 0.95}]), user_node)

    # After edge: seed + neighbor
    after = {str(r["jid"]) for r in spawn(RetrieveByJids(seed_jids=[jid_1]), user_node).reports}
    assert jid_2 in after, f"fact[1] must appear after edge drawn; got {after}"


# ---------------------------------------------------------------------------
# Tests 9-10 — Nightly linker (memory/linker.py)
# ---------------------------------------------------------------------------

def test_linker_connects_similar_facts(isolated_store, monkeypatch):
    import memory.bridge as bridge_mod
    import memory.vector as vector_mod
    from memory.walkers import RetrieveByJids, GetOrCreateUser
    from memory.linker import run_linker
    from jaclang.lib import spawn, root

    user_a = _uid("linker_sim")
    jids = bridge_mod.ingest_facts(user_a, SAMPLE_FACTS)

    # Every fact's nearest neighbor (besides itself) is fact[1] with score 0.92
    monkeypatch.setattr(
        vector_mod.vector_store, "search_with_scores",
        lambda user_id, query, k: [{"node_id": jids[1], "score": 0.92}],
    )

    asyncio.run(run_linker())

    # fact[0] → fact[1] edge should now exist
    user_node = spawn(GetOrCreateUser(user_id=user_a), root()).reports[0]
    result = spawn(RetrieveByJids(seed_jids=[jids[0]]), user_node)
    returned = {str(r["jid"]) for r in result.reports}

    assert jids[1] in returned, (
        f"Expected linker to draw edge {jids[0]}→{jids[1]}; got {returned}"
    )


def test_linker_respects_similarity_threshold(isolated_store, monkeypatch):
    import memory.bridge as bridge_mod
    import memory.vector as vector_mod
    from memory.walkers import RetrieveByJids, GetOrCreateUser
    from memory.linker import run_linker
    from jaclang.lib import spawn, root

    user_a = _uid("linker_thresh")
    jids = bridge_mod.ingest_facts(user_a, SAMPLE_FACTS[:2])

    # Score below the 0.8 threshold — linker must not draw any edges
    monkeypatch.setattr(
        vector_mod.vector_store, "search_with_scores",
        lambda user_id, query, k: [{"node_id": jids[1], "score": 0.5}],
    )

    asyncio.run(run_linker())

    user_node = spawn(GetOrCreateUser(user_id=user_a), root()).reports[0]
    result = spawn(RetrieveByJids(seed_jids=[jids[0]]), user_node)
    returned = {str(r["jid"]) for r in result.reports}

    assert jids[0] in returned, "Seed must always appear in results"
    assert jids[1] not in returned, (
        f"Below-threshold neighbor must not be linked; got {returned}"
    )


# ---------------------------------------------------------------------------
# Test 11 — FactStore.list_users (memory/store.py)
# ---------------------------------------------------------------------------

def test_fact_store_list_users(isolated_store):
    import memory.bridge as bridge_mod

    user_a = _uid("lu_a")
    user_b = _uid("lu_b")

    bridge_mod.ingest_facts(user_a, SAMPLE_FACTS[:2])
    bridge_mod.ingest_facts(user_b, SAMPLE_FACTS[2:])

    users = set(isolated_store.list_users())
    assert user_a in users, f"user_a missing from list_users: {users}"
    assert user_b in users, f"user_b missing from list_users: {users}"
