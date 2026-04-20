"""Deterministic unit tests for the retrieve_context output parser."""
from __future__ import annotations

from tests.memory_eval.parsing import parse_retrieved_names


def test_parse_empty_block_returns_empty():
    assert parse_retrieved_names("") == []
    assert parse_retrieved_names("   ") == []


def test_parse_header_only_returns_empty():
    assert parse_retrieved_names("Relevant memory:") == []


def test_parse_name_with_summary():
    block = "Relevant memory:\n- Alice: software engineer\n- Koda: golden retriever"
    assert parse_retrieved_names(block) == ["Alice", "Koda"]


def test_parse_name_without_summary():
    block = "Relevant memory:\n- Alice\n- Koda"
    assert parse_retrieved_names(block) == ["Alice", "Koda"]


def test_parse_mixed_rows():
    block = "Relevant memory:\n- Alice: engineer\n- Koda\n- Seattle: city"
    assert parse_retrieved_names(block) == ["Alice", "Koda", "Seattle"]


def test_parse_ignores_non_bullet_lines():
    # Header + blank line + bullet; parser must only pick the bullet.
    block = "Relevant memory:\n\n- Alice: engineer\nnote: something"
    assert parse_retrieved_names(block) == ["Alice"]


def test_parse_preserves_order():
    block = "Relevant memory:\n- Third\n- First\n- Second"
    assert parse_retrieved_names(block) == ["Third", "First", "Second"]


def test_parse_strips_whitespace_in_names():
    block = "Relevant memory:\n-  Alice  : engineer"
    assert parse_retrieved_names(block) == ["Alice"]
