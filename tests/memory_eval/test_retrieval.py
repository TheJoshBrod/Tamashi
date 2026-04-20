"""Phase 2 baseline retrieval eval harness.

For each fixture:
  1. Seed the isolated SubjectStore + in-memory Qdrant via bridge.ingest_subjects
  2. Call bridge.retrieve_context(user_id, query, max_subjects=k)
  3. Parse the returned 'Relevant memory:' block into a ranked name list
  4. Score with precision@k / recall@k / MRR / forbidden_hit_rate

Scores are streamed into the conftest collector; the markdown report is
rendered once at session finish, so partial runs still leave a report.
"""
from __future__ import annotations

import uuid

import pytest

from tests.memory_eval.collectors import record_retrieval_score
from tests.memory_eval.fixtures.cases import RETRIEVAL_FIXTURES
from tests.memory_eval.parsing import parse_retrieved_names
from tests.memory_eval.scoring import score_retrieval


def _uid(base: str) -> str:
    return f"{base}_{uuid.uuid4().hex[:8]}"


@pytest.mark.eval
@pytest.mark.parametrize("fixture", RETRIEVAL_FIXTURES, ids=lambda f: f["id"])
def test_retrieval_baseline(fixture, isolated_store, qdrant_store):
    """Ingest the fixture, run retrieve_context, and score the result."""
    import memory.bridge as bridge_mod

    user_id = _uid(fixture["id"])
    bridge_mod.ingest_subjects(
        user_id,
        fixture["seeded_subjects"],
        fixture["seeded_relations"],
    )

    # Mirror production: Qdrant upsert happens in the consolidator, not
    # ingest_subjects. Replicate it here so the vector seed path engages.
    for subj in fixture["seeded_subjects"]:
        meta = isolated_store.get_subject_by_name(user_id, subj["name"])
        if meta and meta.get("jid"):
            qdrant_store.upsert(
                meta["jid"],
                user_id,
                "subject",
                subj["name"],
                summary=subj.get("summary", ""),
                subject_type=subj.get("subject_type", "other"),
                description=subj.get("description_delta", ""),
            )

    k = fixture.get("k", 5)
    block = bridge_mod.retrieve_context(user_id, query=fixture["query"], max_subjects=k)
    retrieved = parse_retrieved_names(block)

    score = score_retrieval(retrieved, fixture)
    record_retrieval_score(score)

    # Baseline harness does not hard-assert on metric thresholds. Phase 3
    # tuning drives forbidden_hit_rate toward 0 and recall_at_k up;
    # forbidden_hit_rate is reported as a baseline measurement here, not
    # an invariant, because with small seed sets and generous k the
    # distractor is returned by design.
    assert isinstance(retrieved, list)
