"""Phase 4: Optimized GraphRAG read path.

Tests cover bridge.retrieve_context end-to-end:
  - GraphRAG path: vector seeds expand to 1-hop neighbors
  - max_subjects cap applied after deduplication
  - User isolation: subjects from another user never leak
  - Fallback: no query / empty seeds → naive RetrieveSubjects
  - Disabled flag: long_term_memory_enabled=False → ""
  - Empty graph → ""
  - Graceful degradation: vector search exception → fallback, not crash
"""
from __future__ import annotations

import hashlib
import random

import pytest

from conftest import _uid

_EMBED_DIM = 16


def _det_embed(text: str) -> list[float]:
    seed = int(hashlib.md5(text.encode()).hexdigest(), 16)
    rng = random.Random(seed)
    vec = [rng.gauss(0, 1) for _ in range(_EMBED_DIM)]
    norm = sum(x * x for x in vec) ** 0.5
    return [x / norm for x in vec]


@pytest.fixture
def qdrant_store():
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
    store._embed = _det_embed
    return store


@pytest.fixture
def isolated_store(tmp_path, monkeypatch):
    import memory.store as store_mod
    import memory.bridge as bridge_mod

    fresh_ss = store_mod.SubjectStore(db_path=str(tmp_path / "mem.db"))
    monkeypatch.setattr(store_mod, "subject_store", fresh_ss)
    monkeypatch.setattr(bridge_mod, "subject_store", fresh_ss)
    monkeypatch.setattr(bridge_mod, "_loaded_users", set())
    yield fresh_ss


# ---------------------------------------------------------------------------
# 1. Empty graph → ""
# ---------------------------------------------------------------------------

def test_retrieve_context_empty_graph_returns_empty(isolated_store, qdrant_store, monkeypatch):
    import memory.bridge as bridge_mod
    import memory.vector as vector_mod

    monkeypatch.setattr(vector_mod, "vector_store", qdrant_store)

    user_a = _uid("empty")
    result = bridge_mod.retrieve_context(user_a, query="anything")
    assert result == "", f"Expected '' for empty graph, got {result!r}"


# ---------------------------------------------------------------------------
# 2. long_term_memory_enabled=False → ""
# ---------------------------------------------------------------------------

def test_retrieve_context_disabled_returns_empty(isolated_store, qdrant_store, monkeypatch):
    import memory.bridge as bridge_mod
    import memory.vector as vector_mod
    from core.config import settings

    monkeypatch.setattr(vector_mod, "vector_store", qdrant_store)
    monkeypatch.setattr(settings, "long_term_memory_enabled", False)

    user_a = _uid("disabled")
    bridge_mod.ingest_subjects(user_a, [
        {"name": "Alice", "summary": "A person", "description_delta": "details", "subject_type": "person"},
    ], [])

    result = bridge_mod.retrieve_context(user_a, query="Alice")
    assert result == "", f"Expected '' when memory disabled, got {result!r}"


# ---------------------------------------------------------------------------
# 3. GraphRAG path: seed expands to 1-hop neighbor
# ---------------------------------------------------------------------------

def test_retrieve_context_graphrag_expands_neighbors(isolated_store, qdrant_store, monkeypatch):
    import memory.bridge as bridge_mod
    import memory.vector as vector_mod

    monkeypatch.setattr(vector_mod, "vector_store", qdrant_store)

    user_a = _uid("graphrag_expand")
    result = bridge_mod.ingest_subjects(user_a, [
        {"name": "Alice", "summary": "A software engineer", "description_delta": "Alice works at ACME", "subject_type": "person"},
        {"name": "Koda", "summary": "Alice's golden retriever", "description_delta": "Koda is Alice's dog", "subject_type": "object"},
    ], [{"source": "Alice", "kind": "has_a", "target": "Koda"}])

    alice_jid = result["new_jids"]["Alice"]
    qdrant_store.upsert(alice_jid, user_a, "subject", "Alice", "A software engineer")

    # Seed on Alice — Koda is a 1-hop neighbor via has_a edge
    monkeypatch.setattr(vector_mod.vector_store, "search", lambda uid, q, k: [alice_jid])

    ctx = bridge_mod.retrieve_context(user_a, query="Alice")
    assert "Alice" in ctx, f"Seed 'Alice' missing from context: {ctx!r}"
    assert "Koda" in ctx, f"1-hop neighbor 'Koda' missing from context: {ctx!r}"


# ---------------------------------------------------------------------------
# 4. max_subjects cap applied after GraphRAG expansion
# ---------------------------------------------------------------------------

def test_retrieve_context_respects_max_subjects(isolated_store, monkeypatch):
    import memory.bridge as bridge_mod
    import memory.vector as vector_mod

    user_a = _uid("max_cap")
    subjects = [
        {"name": f"Subject{i}", "summary": f"Summary {i}", "description_delta": f"Desc {i}", "subject_type": "concept"}
        for i in range(8)
    ]
    bridge_mod.ingest_subjects(user_a, subjects, [])

    # Force empty seeds → fallback path → all 8 subjects eligible
    monkeypatch.setattr(vector_mod.vector_store, "search", lambda uid, q, k: [])

    ctx = bridge_mod.retrieve_context(user_a, query="something", max_subjects=3)
    lines = [ln for ln in ctx.split("\n") if ln.startswith("- ")]
    assert len(lines) <= 3, f"Expected at most 3 lines, got {len(lines)}: {lines}"


# ---------------------------------------------------------------------------
# 5. User isolation: user_b subjects never appear for user_a
# ---------------------------------------------------------------------------

def test_retrieve_context_user_isolation(isolated_store, qdrant_store, monkeypatch):
    import memory.bridge as bridge_mod
    import memory.vector as vector_mod

    monkeypatch.setattr(vector_mod, "vector_store", qdrant_store)

    user_a = _uid("iso_a")
    user_b = _uid("iso_b")

    bridge_mod.ingest_subjects(user_a, [
        {"name": "AliceA", "summary": "User A subject", "description_delta": "d", "subject_type": "person"},
    ], [])
    bridge_mod.ingest_subjects(user_b, [
        {"name": "AliceB", "summary": "User B subject", "description_delta": "d", "subject_type": "person"},
    ], [])

    # Force fallback (no vector seeds) so all subjects for user_a are candidates
    monkeypatch.setattr(vector_mod.vector_store, "search", lambda uid, q, k: [])

    ctx_a = bridge_mod.retrieve_context(user_a, query="")
    assert "AliceA" in ctx_a, f"user_a subject missing: {ctx_a!r}"
    assert "AliceB" not in ctx_a, f"user_b subject leaked into user_a: {ctx_a!r}"


# ---------------------------------------------------------------------------
# 6. No query → fallback path (RetrieveSubjects, not GraphRAG)
# ---------------------------------------------------------------------------

def test_retrieve_context_no_query_uses_fallback(isolated_store, monkeypatch):
    import memory.bridge as bridge_mod
    import memory.vector as vector_mod
    from memory.walkers import RetrieveBySubjectJids
    from jaclang.lib import spawn as jac_spawn

    user_a = _uid("no_query")
    bridge_mod.ingest_subjects(user_a, [
        {"name": "Bob", "summary": "A person", "description_delta": "details", "subject_type": "person"},
    ], [])

    graphrag_called = {"flag": False}
    real_spawn = jac_spawn

    def tracking_spawn(walker, node):
        if isinstance(walker, RetrieveBySubjectJids):
            graphrag_called["flag"] = True
        return real_spawn(walker, node)

    monkeypatch.setattr("memory.bridge.spawn", tracking_spawn)

    ctx = bridge_mod.retrieve_context(user_a, query="")
    assert not graphrag_called["flag"], "GraphRAG walker should not be called with no query"
    assert "Bob" in ctx, f"Expected Bob in fallback context: {ctx!r}"


# ---------------------------------------------------------------------------
# 7. Vector search exception → fallback, not crash
# ---------------------------------------------------------------------------

def test_retrieve_context_graceful_on_vector_exception(isolated_store, monkeypatch):
    import memory.bridge as bridge_mod
    import memory.vector as vector_mod

    user_a = _uid("graceful")
    bridge_mod.ingest_subjects(user_a, [
        {"name": "Charlie", "summary": "A concept", "description_delta": "d", "subject_type": "concept"},
    ], [])

    def boom(uid, q, k):
        raise RuntimeError("simulated vector failure")

    monkeypatch.setattr(vector_mod.vector_store, "search", boom)

    # Must not raise; falls back to naive retrieval
    ctx = bridge_mod.retrieve_context(user_a, query="Charlie")
    assert ctx != "", f"Expected fallback context, got empty string"
    assert "Charlie" in ctx, f"Expected Charlie in fallback context: {ctx!r}"
