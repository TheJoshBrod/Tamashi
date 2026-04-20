"""Self-tests for the Phase 2 scoring primitives.

These are deterministic unit tests — they do NOT carry the `eval` marker, so
they run in the default `pytest tests/` suite and act as a regression gate on
the metrics themselves.
"""
from __future__ import annotations

from tests.memory_eval.scoring import (
    aggregate,
    forbidden_hit_rate,
    mrr,
    precision_at_k,
    recall_at_k,
    render_markdown_table,
    score_extraction,
    score_retrieval,
)


# ---------------------------------------------------------------------------
# precision / recall / mrr core
# ---------------------------------------------------------------------------

def test_precision_at_k_case_insensitive():
    assert precision_at_k(["Alice", "Bob", "Carol"], ["alice", "carol"], k=3) == 2 / 3


def test_precision_at_k_respects_cutoff():
    # Only "Alice" is in top-2; Carol at rank 3 is cut off
    assert precision_at_k(["Alice", "Bob", "Carol"], ["Alice", "Carol"], k=2) == 0.5


def test_precision_at_k_zero_k_returns_zero():
    assert precision_at_k(["Alice"], ["Alice"], k=0) == 0.0


def test_recall_at_k_basic():
    assert recall_at_k(["Alice", "Bob"], ["Alice", "Carol"], k=5) == 0.5


def test_recall_at_k_empty_expected_returns_one():
    # Nothing to recall → cannot miss. Harness treats as degenerate pass.
    assert recall_at_k(["Anything"], [], k=5) == 1.0


def test_mrr_first_rank():
    # Alice at rank 1, Bob at rank 2 → (1/1 + 1/2) / 2 = 0.75
    assert mrr(["Alice", "Bob"], ["Alice", "Bob"], k=5) == 0.75


def test_mrr_miss_contributes_zero():
    # Alice at rank 1, Bob missing → (1/1 + 0) / 2 = 0.5
    assert mrr(["Alice"], ["Alice", "Bob"], k=5) == 0.5


def test_mrr_empty_expected_returns_one():
    assert mrr(["Alice"], [], k=5) == 1.0


def test_mrr_respects_k():
    # Bob at rank 3 is cut off when k=2
    assert mrr(["Alice", "Carol", "Bob"], ["Bob"], k=2) == 0.0


def test_forbidden_hit_rate_counts_leaks():
    assert forbidden_hit_rate(["Alice", "Evil"], ["Evil"], k=5) == 1.0
    assert forbidden_hit_rate(["Alice"], ["Evil"], k=5) == 0.0


# ---------------------------------------------------------------------------
# score_retrieval wraps a fixture
# ---------------------------------------------------------------------------

def test_score_retrieval_perfect():
    fixture = {
        "id": "perfect",
        "expected_top_k_names": ["Alice", "Koda"],
        "forbidden_names": [],
        "k": 5,
    }
    result = score_retrieval(["Alice", "Koda", "Bob"], fixture)
    assert result["id"] == "perfect"
    assert result["recall_at_k"] == 1.0
    assert result["mrr"] == (1.0 + 0.5) / 2  # ranks 1 and 2
    assert result["forbidden_hit_rate"] == 0.0


def test_score_retrieval_negative_no_expected():
    # Off-topic fixture: no expected names → recall=1.0 degenerate, MRR=1.0
    fixture = {"id": "neg", "expected_top_k_names": [], "forbidden_names": [], "k": 5}
    result = score_retrieval(["Random", "Noise"], fixture)
    assert result["recall_at_k"] == 1.0
    assert result["mrr"] == 1.0


# ---------------------------------------------------------------------------
# score_extraction: subject / relation / hallucination
# ---------------------------------------------------------------------------

def test_score_extraction_perfect():
    fixture = {
        "id": "perfect",
        "expected_subjects": ["Alice", "Koda"],
        "expected_relations": [("Alice", "has_a", "Koda")],
        "is_negative": False,
    }
    result = score_extraction(
        extracted_subjects=["alice", "Koda"],
        extracted_relations=[("Alice", "has_a", "Koda")],
        fixture=fixture,
    )
    assert result["subject_match_rate"] == 1.0
    assert result["relation_match_rate"] == 1.0
    assert result["hallucination_rate"] == 0.0


def test_score_extraction_hallucination_on_negative():
    # Extractor on a negative fixture must return empty to stay at 0.0
    fixture = {
        "id": "neg",
        "expected_subjects": [],
        "expected_relations": [],
        "is_negative": True,
    }
    good = score_extraction([], [], fixture)
    assert good["hallucination_rate"] == 0.0  # max(1, 0) denominator protects us

    bad = score_extraction(["Weather"], [], fixture)
    assert bad["hallucination_rate"] == 1.0


def test_score_extraction_partial_match():
    fixture = {
        "id": "partial",
        "expected_subjects": ["Alice", "Koda"],
        "expected_relations": [],
        "is_negative": False,
    }
    result = score_extraction(["Alice", "Stranger"], [], fixture)
    assert result["subject_match_rate"] == 0.5   # 1 of 2 expected found
    assert result["hallucination_rate"] == 0.5   # 1 of 2 extracted is hallucinated


# ---------------------------------------------------------------------------
# aggregate + markdown
# ---------------------------------------------------------------------------

def test_aggregate_macro_averages():
    scores = [
        {"precision_at_k": 1.0, "recall_at_k": 0.5},
        {"precision_at_k": 0.0, "recall_at_k": 1.0},
    ]
    agg = aggregate(scores, ["precision_at_k", "recall_at_k"])
    assert agg["precision_at_k"] == 0.5
    assert agg["recall_at_k"] == 0.75


def test_render_markdown_table_shape():
    scores = [{"id": "a", "precision_at_k": 1.0, "recall_at_k": 0.5}]
    out = render_markdown_table(
        "Test",
        scores,
        columns=[("id", "Fixture"), ("precision_at_k", "P@k"), ("recall_at_k", "R@k")],
        summary_keys=["precision_at_k", "recall_at_k"],
    )
    assert "## Test" in out
    assert "| Fixture | P@k | R@k |" in out
    assert "| a | 1.000 | 0.500 |" in out
    assert "precision_at_k: 1.000" in out  # aggregate line
    assert "n_fixtures: 1" in out
