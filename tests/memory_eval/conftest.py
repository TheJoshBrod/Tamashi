"""Pytest fixtures + marker gating for the Phase 2 baseline eval harness.

These tests are opt-in: they exercise real LLM calls and real embeddings, so
they are skipped by default. To run locally:

    RUN_EVAL=1 env/bin/python3 -m pytest tests/memory_eval/ -v

Markdown reports (precision/recall/MRR tables for retrieval and extraction)
are written to tests/memory_eval/_reports/<suite>.md at session end via a
pytest_sessionfinish hook — so partial runs still produce a report for the
fixtures that did complete.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

_REPORT_DIR = Path(__file__).parent / "_reports"


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "eval: Phase 2 baseline eval (real LLM / real embeddings). "
        "Skipped unless RUN_EVAL=1.",
    )


def pytest_collection_modifyitems(config, items):
    if os.environ.get("RUN_EVAL") == "1":
        return
    skip = pytest.mark.skip(reason="eval suite gated; set RUN_EVAL=1 to run")
    for item in items:
        # Only explicit @pytest.mark.eval — path-based keyword matches (the
        # directory is named "eval") must not skip the deterministic scoring
        # self-tests that share this directory.
        if any(m.name == "eval" for m in item.iter_markers()):
            item.add_marker(skip)


def pytest_sessionfinish(session, exitstatus):
    """Render markdown reports from whatever fixtures did score.

    Survives mid-run failures: any fixture that reached its assert gets its
    row in the table. Absent collectors → no report, no error.
    """
    from tests.memory_eval.collectors import (
        get_retrieval_scores,
        get_extractor_scores,
    )
    _retrieval_scores = get_retrieval_scores()
    _extractor_scores = get_extractor_scores()
    if not _retrieval_scores and not _extractor_scores:
        return
    from tests.memory_eval.scoring import render_markdown_table
    _REPORT_DIR.mkdir(parents=True, exist_ok=True)

    if _retrieval_scores:
        md = render_markdown_table(
            title="Retrieval Baseline (Phase 2)",
            scores=_retrieval_scores,
            columns=[
                ("id", "Fixture"),
                ("precision_at_k", "P@k"),
                ("recall_at_k", "R@k"),
                ("mrr", "MRR"),
                ("forbidden_hit_rate", "Forbid"),
            ],
            summary_keys=["precision_at_k", "recall_at_k", "mrr", "forbidden_hit_rate"],
        )
        (_REPORT_DIR / "retrieval.md").write_text(md)

    if _extractor_scores:
        md = render_markdown_table(
            title="Extractor Baseline (Phase 2)",
            scores=_extractor_scores,
            columns=[
                ("id", "Fixture"),
                ("subject_match_rate", "Subjects"),
                ("relation_match_rate", "Relations"),
                ("hallucination_rate", "Halluc"),
                ("is_negative", "Neg?"),
            ],
            summary_keys=["subject_match_rate", "relation_match_rate", "hallucination_rate"],
        )
        (_REPORT_DIR / "extractor.md").write_text(md)


@pytest.fixture
def qdrant_store(monkeypatch):
    """In-memory Qdrant with the real fastembed model.

    Points at :memory: so the eval harness does not touch the on-disk qdrant
    directory. Uses the production embedding model (BAAI/bge-small-en-v1.5)
    so retrieval numbers reflect the real stack.
    """
    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, VectorParams
    from memory.vector import QdrantMemoryStore
    import memory.vector as vector_mod
    from core.config import settings

    store = QdrantMemoryStore()
    embed_model = store._get_embed_model()
    sample_dim = len(list(embed_model.embed(["probe"]))[0])

    client = QdrantClient(":memory:")
    client.create_collection(
        collection_name=settings.subject_collection,
        vectors_config=VectorParams(size=sample_dim, distance=Distance.COSINE),
    )
    store._client = client
    store._embed_model = embed_model

    monkeypatch.setattr(vector_mod, "vector_store", store)
    import memory.bridge as bridge_mod
    monkeypatch.setattr(bridge_mod, "vector_store", store)
    return store


@pytest.fixture(scope="session")
def eval_report_dir():
    _REPORT_DIR.mkdir(parents=True, exist_ok=True)
    return _REPORT_DIR
