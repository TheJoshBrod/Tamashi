"""Shared parsing helpers for the retrieval harness."""
from __future__ import annotations

import re


_LINE_RE = re.compile(r"^- (?P<name>[^:\n]+?)(?:\s*:\s*.*)?$")


def parse_retrieved_names(block: str) -> list[str]:
    """Extract ranked Subject names from a 'Relevant memory:' block.

    bridge.retrieve_context emits lines of the form:
        Relevant memory:
        - NAME: SUMMARY
        - NAME2

    Returns names in document order (already rank-ordered by the bridge).
    """
    if not block or not block.strip():
        return []
    names: list[str] = []
    for line in block.splitlines():
        match = _LINE_RE.match(line.strip())
        if match:
            names.append(match.group("name").strip())
    return names
