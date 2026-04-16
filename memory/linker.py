"""Nightly background linker: temporarily disabled pending Phase 5 rewrite.

The old fact-based linker (drawing RelatesTo edges between similar Facts) has
been removed along with the Fact node. A subject-based linker that draws
Relates edges between semantically similar Subjects will be implemented in
Phase 5 as part of the WAL rewriter.
"""
from __future__ import annotations

import logging

from core.config import settings

log = logging.getLogger(__name__)


async def run_linker() -> None:
    """No-op until Phase 5 implements subject-aware linking."""
    log.info("linker: disabled in Phase 3 — will be rewritten for subjects in Phase 5")
