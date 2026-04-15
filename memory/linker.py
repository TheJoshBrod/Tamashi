"""Nightly background linker: draw RelatesTo(kind="similar") edges between Facts
that are semantically close according to the Qdrant vector index.

Registered as an APScheduler cron job in app.py (runs at 3 AM by default).
Safe to call manually for testing: await run_linker()
"""
from __future__ import annotations

import asyncio
import logging

from core.config import settings

log = logging.getLogger(__name__)

# Minimum cosine similarity to draw a "similar" edge
_SIMILARITY_THRESHOLD = 0.8


async def run_linker() -> None:
    """For every user with stored facts, find semantically similar Fact pairs
    and draw RelatesTo(kind="similar", weight=score) edges between them.

    Steps per user:
      1. Load all facts from SQLite (source of truth for node_ids)
      2. For each fact, vector-search for nearest neighbors (score > threshold)
      3. Call LinkFacts walker to draw/update edges in the Jac graph
    """
    if not settings.long_term_memory_enabled:
        return

    try:
        from memory.store import fact_store
        from memory.vector import vector_store
        from memory import bridge
        from jaclang.lib import spawn
        from memory.walkers import LinkFacts

        users = fact_store.list_users()
        log.info("linker: processing %d users", len(users))

        for user_id in users:
            try:
                await _link_user(user_id, fact_store, vector_store, bridge, spawn, LinkFacts)
            except Exception:
                log.exception("linker: failed for user %s", user_id)

    except Exception:
        log.exception("linker: startup failed")


async def _link_user(user_id, fact_store, vector_store, bridge, spawn, LinkFacts) -> None:
    facts = fact_store.get_facts(user_id, limit=5000)
    if not facts:
        return

    # Ensure user's facts are loaded into the Jac graph
    bridge._ensure_loaded(user_id)
    user_node = bridge._get_user_node(user_id)

    linked_count = 0
    for fact in facts:
        node_id = fact.get("jid")
        content = fact.get("content", "")
        if not node_id or not content:
            continue

        # Vector-search for neighbors of this fact
        neighbors = await asyncio.to_thread(
            vector_store.search_with_scores,
            user_id,
            content,
            5,  # k
        )
        # Filter out self and below-threshold matches
        targets = [
            {"jid": n["node_id"], "weight": n["score"]}
            for n in neighbors
            if n["node_id"] != node_id and n["score"] >= _SIMILARITY_THRESHOLD
        ]
        if not targets:
            continue

        await asyncio.to_thread(
            spawn,
            LinkFacts(src_jid=node_id, target_jids=targets),
            user_node,
        )
        linked_count += len(targets)

    if linked_count:
        log.info("linker: drew %d edges for user %s", linked_count, user_id)
