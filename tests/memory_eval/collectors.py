"""Session-scoped score collectors for the Phase 2 eval harness.

Lives in its own module (not conftest.py) because pytest loads conftest as
a plugin in a separate module namespace — importing `from ...conftest import x`
inside a test creates a second copy of the module state, so collectors placed
there would not be visible to the session-finish hook.
"""
from __future__ import annotations

_retrieval_scores: list[dict] = []
_extractor_scores: list[dict] = []


def record_retrieval_score(score: dict) -> None:
    _retrieval_scores.append(score)


def record_extractor_score(score: dict) -> None:
    _extractor_scores.append(score)


def get_retrieval_scores() -> list[dict]:
    return _retrieval_scores


def get_extractor_scores() -> list[dict]:
    return _extractor_scores
