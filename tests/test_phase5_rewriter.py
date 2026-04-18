"""Phase 5: WAL-triggered Subject rewriter.

Tests cover:
  - _validate_rewrite: schema enforcement (valid/invalid targets, kinds, missing fields)
  - _build_prompt: section structure
  - Per-subject lock: two concurrent rewrite_subject tasks → at most one LLM call
"""
from __future__ import annotations

import asyncio

import pytest

from conftest import _uid
from memory.rewriter import _validate_rewrite, _build_prompt


# ---------------------------------------------------------------------------
# _validate_rewrite
# ---------------------------------------------------------------------------

VALID_TARGETS = {"Alice", "Koda", "Work"}


def test_validate_rewrite_passes_valid_input():
    raw = {
        "summary": "A person who owns a dog",
        "description": "Alice has a golden retriever named Koda.",
        "add_edges": [{"target": "Koda", "kind": "has_a"}],
        "remove_edges": [],
    }
    result = _validate_rewrite(raw, VALID_TARGETS)
    assert result is not None
    assert result["summary"] == "A person who owns a dog"
    assert result["add_edges"] == [{"target": "Koda", "kind": "has_a"}]
    assert result["remove_edges"] == []


def test_validate_rewrite_rejects_missing_summary():
    raw = {
        "summary": "",
        "description": "Alice has a golden retriever.",
        "add_edges": [],
        "remove_edges": [],
    }
    assert _validate_rewrite(raw, VALID_TARGETS) is None


def test_validate_rewrite_rejects_missing_description():
    raw = {
        "summary": "A person who owns a dog",
        "description": "",
        "add_edges": [],
        "remove_edges": [],
    }
    assert _validate_rewrite(raw, VALID_TARGETS) is None


def test_validate_rewrite_drops_invalid_target():
    raw = {
        "summary": "Someone",
        "description": "Details.",
        "add_edges": [
            {"target": "Koda", "kind": "has_a"},
            {"target": "UnknownEntity", "kind": "knows"},
        ],
        "remove_edges": [],
    }
    result = _validate_rewrite(raw, VALID_TARGETS)
    assert result is not None
    assert len(result["add_edges"]) == 1
    assert result["add_edges"][0]["target"] == "Koda"


def test_validate_rewrite_drops_invalid_kind():
    raw = {
        "summary": "Someone",
        "description": "Details.",
        "add_edges": [
            {"target": "Koda", "kind": "has_a"},
            {"target": "Work", "kind": "INVENTED_KIND"},
        ],
        "remove_edges": [],
    }
    result = _validate_rewrite(raw, VALID_TARGETS)
    assert result is not None
    assert len(result["add_edges"]) == 1
    assert result["add_edges"][0]["kind"] == "has_a"


def test_validate_rewrite_handles_non_dict_edges():
    raw = {
        "summary": "Someone",
        "description": "Details.",
        "add_edges": ["bad", None, {"target": "Koda", "kind": "has_a"}],
        "remove_edges": [],
    }
    result = _validate_rewrite(raw, VALID_TARGETS)
    assert result is not None
    assert len(result["add_edges"]) == 1


# ---------------------------------------------------------------------------
# _build_prompt
# ---------------------------------------------------------------------------

def test_build_prompt_contains_required_sections():
    subject = {
        "name": "Alice",
        "subject_type": "person",
        "summary": "A software engineer",
        "description": "Alice works at ACME.",
        "recent_events": ["Alice got a promotion", "Alice adopted a dog"],
    }
    neighbors = [{"name": "Koda", "edge_kind": "has_a", "summary": "a golden retriever"}]
    semantic_nbrs = [{"name": "Work", "subject_type": "place", "summary": "ACME office"}]

    prompt = _build_prompt(subject, neighbors, semantic_nbrs)

    assert "Alice" in prompt
    assert "Pending facts" in prompt
    assert "Alice got a promotion" in prompt
    assert "Current 1-hop neighbors" in prompt
    assert "Koda" in prompt
    assert "Semantic neighbors" in prompt
    assert "Work" in prompt
    assert "Allowed relation kinds" in prompt
    assert "add_edges" in prompt


# ---------------------------------------------------------------------------
# Per-subject lock: concurrent rewrite_subject → at most one LLM call
# ---------------------------------------------------------------------------

@pytest.fixture
def isolated_store(tmp_path, monkeypatch):
    import memory.store as store_mod
    import memory.bridge as bridge_mod

    fresh_ss = store_mod.SubjectStore(db_path=str(tmp_path / "mem.db"))
    monkeypatch.setattr(store_mod, "subject_store", fresh_ss)
    monkeypatch.setattr(bridge_mod, "subject_store", fresh_ss)
    monkeypatch.setattr(bridge_mod, "_loaded_users", set())
    yield fresh_ss


def test_concurrent_rewrite_calls_llm_at_most_once(isolated_store, monkeypatch):
    """Two concurrent rewrite_subject tasks for the same subject hit the LLM at most once.

    The second task acquires the lock after the first finishes and finds the WAL
    already cleared, so it exits without calling the LLM.
    """
    import memory.bridge as bridge_mod
    import memory.rewriter as rewriter_mod

    user_id = _uid("lock_test")
    name = "Alice"

    # Simulate get_subject_context: first call returns events, subsequent calls return empty WAL
    call_count = {"n": 0}

    def fake_get_context(uid, n):
        call_count["n"] += 1
        events = ["Alice got a promotion"] if call_count["n"] == 1 else []
        return {
            "subject": {
                "jid": "jid-alice",
                "name": name,
                "summary": "A software engineer",
                "description": "Alice works at ACME.",
                "subject_type": "person",
                "recent_events": events,
            },
            "neighbors": [],
        }

    llm_calls = {"n": 0}

    def fake_call_llm(prompt):
        llm_calls["n"] += 1
        return {
            "summary": "Updated summary",
            "description": "Updated description",
            "add_edges": [],
            "remove_edges": [],
        }

    monkeypatch.setattr(bridge_mod, "get_subject_context", fake_get_context)
    monkeypatch.setattr(bridge_mod, "apply_rewrite", lambda *a, **kw: {"status": "success"})
    monkeypatch.setattr(rewriter_mod, "_call_llm", fake_call_llm)

    # Clear any pre-existing locks so this test is isolated
    rewriter_mod._rewrite_locks.clear()

    async def run():
        t1 = asyncio.create_task(rewriter_mod.rewrite_subject(user_id, name))
        t2 = asyncio.create_task(rewriter_mod.rewrite_subject(user_id, name))
        await asyncio.gather(t1, t2)

    asyncio.run(run())

    assert llm_calls["n"] <= 1, (
        f"Expected at most 1 LLM call under lock, got {llm_calls['n']}"
    )
