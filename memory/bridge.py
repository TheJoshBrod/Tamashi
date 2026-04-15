"""Python facade for the Jac memory graph + Qdrant vector store.

Architecture:
  - Jac graph (in-process, via jaclang.lib): fast traversal, walker-based GraphRAG
  - SQLite FactStore (memory/store.py): durable persistence across restarts
  - Qdrant embedded (memory/vector.py): semantic vector search for Phase 3 retrieval

Write path:
  ingest_facts → Jac graph (in-process) + SQLite (durable) + Qdrant (vector index)

Read path (Phase 3 GraphRAG):
  1. Vector search → seed jids
  2. RetrieveByJids walker → 1-hop graph expansion
  3. Fallback to RetrieveFacts if vector store empty
  4. Deduplicate + token-budget cap in Python

Swapping the graph backend only requires changing this module.
"""
from __future__ import annotations

import logging
from core.config import settings

from jaclang.lib import spawn, root

from memory.walkers import GetOrCreateUser, IngestFacts, RetrieveFacts, RetrieveByJids
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
    """Write extracted facts into the Jac graph, SQLite, and Qdrant.

    Returns a list of jid strings (one per Fact node) for Qdrant mirroring.
    The caller (consolidator) handles Qdrant upsert after this returns.
    """
    if not facts:
        return []
    _ensure_loaded(user_id)
    user_node = _get_user_node(user_id)
    result = spawn(IngestFacts(facts=facts), user_node)
    jids: list[str] = [str(j) for j in result.reports]
    # Persist to SQLite so facts survive process restart.
    fact_store.insert(user_id, facts, jids)
    _loaded_users.add(user_id)
    return jids


def retrieve_context(user_id: str, query: str = "", max_facts: int = 10) -> str:
    """Return a formatted memory block to prepend to the LLM prompt.

    Phase 3 two-step GraphRAG:
      1. Vector search → seed jids (returns [] if store empty)
      2. RetrieveByJids walker → 1-hop graph expansion
      3. Fallback to RetrieveFacts if seeds are empty
      4. Deduplicate, cap to max_facts, format as bullet list

    Returns an empty string if there are no stored facts.
    """
    _ensure_loaded(user_id)
    user_node = _get_user_node(user_id)

    # Step 1: vector search for semantically similar facts
    seed_jids: list[str] = []
    if settings.long_term_memory_enabled:
        try:
            from memory.vector import vector_store
            seed_jids = vector_store.search(user_id, query, k=5)
        except Exception:
            log.debug("vector search unavailable, falling back to naive retrieval")

    # Step 2: GraphRAG expansion via Jac walker, or naive fallback
    if seed_jids:
        result = spawn(RetrieveByJids(seed_jids=seed_jids), user_node)
    else:
        result = spawn(RetrieveFacts(max_facts=max_facts), user_node)

    if not result.reports:
        return ""

    # Step 3: deduplicate (RetrieveByJids can report the same neighbor twice)
    seen: set[str] = set()
    deduped = []
    for r in result.reports:
        key = str(r.get("jid", r.get("content", "")))
        if key not in seen:
            seen.add(key)
            deduped.append(r)
        if len(deduped) >= max_facts:
            break

    lines = [f"- [{r['topic']}] {r['content']}" for r in deduped]
    return "Relevant memory:\n" + "\n".join(lines)


def list_user_facts(user_id: str) -> list[dict]:
    """Return all facts for a user. Used by tests and debug endpoints."""
    _ensure_loaded(user_id)
    user_node = _get_user_node(user_id)
    result = spawn(RetrieveFacts(max_facts=1000), user_node)
    return result.reports
