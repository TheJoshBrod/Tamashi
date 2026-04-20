"""Phase 2 baseline extractor eval harness.

For each fixture:
  1. Call extractor.extract_subjects(messages, vocabulary)
  2. Score the returned subjects and relations against the fixture

Scores are streamed into the conftest collector; the markdown report is
rendered once at session finish.
"""
from __future__ import annotations

import os

import pytest

from tests.memory_eval.collectors import record_extractor_score
from tests.memory_eval.fixtures.cases import EXTRACTOR_FIXTURES
from tests.memory_eval.scoring import score_extraction

# The extractor silently returns {} on LLM failure (including auth errors),
# which would let a missing API key masquerade as a valid 0.0 baseline. Skip
# the whole module if no credential is present so we fail loud instead.
_HAS_LLM_CRED = bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("OPENAI_API_KEY"))
pytestmark = pytest.mark.skipif(
    not _HAS_LLM_CRED,
    reason="extractor eval requires ANTHROPIC_API_KEY or OPENAI_API_KEY",
)


@pytest.mark.eval
@pytest.mark.parametrize("fixture", EXTRACTOR_FIXTURES, ids=lambda f: f["id"])
def test_extractor_baseline(fixture):
    """Run the real extractor LLM call and score the structured result."""
    from memory import extractor

    result = extractor.extract_subjects(
        messages=fixture["messages"],
        vocabulary=fixture["vocabulary"],
    )

    extracted_subject_names = [s.get("name", "") for s in result.get("subjects", [])]
    extracted_relations = [
        (r.get("source", ""), r.get("kind", ""), r.get("target", ""))
        for r in result.get("relations", [])
    ]

    score = score_extraction(extracted_subject_names, extracted_relations, fixture)
    record_extractor_score(score)

    # Baseline harness does not hard-assert on thresholds. Invariants only:
    # - the call did not crash (we got a dict back)
    # - on negative fixtures, hallucination rate is baseline-only, not enforced
    assert isinstance(result, dict)
    assert "subjects" in result and "relations" in result
