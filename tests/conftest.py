import hashlib
import os
import random
import sys
import uuid

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _uid(base: str) -> str:
    """Unique user ID per test run to avoid Jac in-process graph bleed."""
    return f"{base}_{uuid.uuid4().hex[:8]}"


_EMBED_DIM = 16


def _det_embed(text: str) -> list[float]:
    """Deterministic unit-norm pseudo-embedding keyed by md5(text).

    Same text → same vector (cosine 1.0 with itself); different texts → low
    similarity. Lets fast unit tests bypass fastembed model loads.
    """
    seed = int(hashlib.md5(text.encode()).hexdigest(), 16)
    rng = random.Random(seed)
    vec = [rng.gauss(0, 1) for _ in range(_EMBED_DIM)]
    norm = sum(x * x for x in vec) ** 0.5
    return [x / norm for x in vec]


@pytest.fixture
def isolated_store(tmp_path, monkeypatch):
    """Fresh SubjectStore on a temp SQLite + cleared Jac load cache."""
    import memory.store as store_mod
    import memory.bridge as bridge_mod

    fresh_ss = store_mod.SubjectStore(db_path=str(tmp_path / "mem.db"))
    monkeypatch.setattr(store_mod, "subject_store", fresh_ss)
    monkeypatch.setattr(bridge_mod, "subject_store", fresh_ss)
    monkeypatch.setattr(bridge_mod, "_loaded_users", set())
    yield fresh_ss


@pytest.fixture
def qdrant_store():
    """In-memory Qdrant + deterministic embedding — no fastembed, no disk."""
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
