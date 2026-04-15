"""Python facade for the Jac memory graph.

Architecture:
  - Jac graph (in-process, via jaclang.lib): fast traversal, walker-based GraphRAG
  - SQLite FactStore (memory/store.py): durable persistence across restarts

Write path: ingest_facts → Jac graph (in-process) + SQLite (durable)
Read path:  retrieve_context → Jac graph if warm; reload from SQLite on cache miss

Swapping the graph backend only requires changing this module.
"""
from __future__ import annotations

import logging

from jaclang.lib import spawn, root

from memory.walkers import GetOrCreateUser, IngestFacts, RetrieveFacts
from memory.store import fact_store

log = logging.getLogger(__name__)

# Track which user_ids have been loaded into the in-process Jac graph.
# If a user_id is not in this set on retrieve, we reload from SQLite first.
_loaded_users: set[str] = set()


def _get_user_node(user_id: str):
    """Get-or-create the User node for this user_id under global root()."""
    result = spawn(GetOrCreateUser(user_id=user_id), root())
    return result.reports[0]


def _ensure_loaded(user_id: str) -> None:
    """If this user's facts aren't in the Jac graph yet, load them from SQLite."""
    if user_id in _loaded_users:
        return
    # Check whether the Jac graph already has nodes for this user (same process,
    # cache was invalidated but graph was not cleared — avoids duplicate ingestion).
    user_node = _get_user_node(user_id)
    probe = spawn(RetrieveFacts(max_facts=1), user_node)
    if probe.reports:
        _loaded_users.add(user_id)
        return
    # Graph is empty for this user — reload from SQLite (covers process restart).
    persisted = fact_store.get_facts(user_id, limit=1000)
    if not persisted:
        _loaded_users.add(user_id)
        return
    facts_for_jac = [
        {"content": f["content"], "topic": f["topic"], "source_msg_id": 0}
        for f in persisted
    ]
    spawn(IngestFacts(facts=facts_for_jac), user_node)
    _loaded_users.add(user_id)


def ingest_facts(user_id: str, facts: list[dict]) -> list[str]:
    """Write extracted facts into the Jac graph and persist to SQLite.

    Returns a list of jid strings (one per Fact node) for Phase 3 Qdrant mirroring.
    """
    if not facts:
        return []
    _ensure_loaded(user_id)
    user_node = _get_user_node(user_id)
    result = spawn(IngestFacts(facts=facts), user_node)
    jids: list[str] = result.reports
    # Persist to SQLite so facts survive process restart.
    fact_store.insert(user_id, facts, jids)
    _loaded_users.add(user_id)
    return jids


def retrieve_context(user_id: str, query: str = "", max_facts: int = 10) -> str:
    """Return a formatted memory block to prepend to the LLM prompt.

    Returns an empty string if there are no stored facts.
    Phase 3 will replace the naive walker with vector-seeded GraphRAG.
    """
    _ensure_loaded(user_id)
    user_node = _get_user_node(user_id)
    result = spawn(RetrieveFacts(max_facts=max_facts), user_node)
    if not result.reports:
        return ""
    lines = [f"- [{r['topic']}] {r['content']}" for r in result.reports]
    return "Relevant memory:\n" + "\n".join(lines)


def list_user_facts(user_id: str) -> list[dict]:
    """Return all facts for a user. Used by tests and debug endpoints."""
    _ensure_loaded(user_id)
    user_node = _get_user_node(user_id)
    result = spawn(RetrieveFacts(max_facts=1000), user_node)
    return result.reports
