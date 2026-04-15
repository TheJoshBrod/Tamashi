"""Async consolidation: extract facts from messages that fell out of the FIFO
working window and ingest them into the long-term Jac graph + SQLite store +
Qdrant vector index.

Called as a fire-and-forget asyncio task after each agent reply.
"""
from __future__ import annotations

import asyncio
import logging

from core.config import settings
from core.events import event_bus

log = logging.getLogger(__name__)


async def consolidate_if_needed(session_id: str, store) -> None:
    """Extract facts from unconsolidated messages and write to long-term memory.

    Args:
        session_id: the user's session / phone number
        store:      the SessionStore singleton (from app.py)
    """
    if not settings.long_term_memory_enabled:
        return

    try:
        batch = store.get_unconsolidated(session_id, settings.working_memory_size)
        if not batch:
            return

        max_id = store.get_max_message_id(session_id)
        raw = [{"role": m.role, "content": m.content} for m in batch if m.content]

        # Extraction is a blocking LiteLLM call — run in a thread so we don't
        # block the event loop.
        from memory import extractor, bridge
        facts = await asyncio.to_thread(
            extractor.extract_facts, raw, source_msg_id=max_id
        )

        vector_ok = True
        if facts:
            jids = await asyncio.to_thread(bridge.ingest_facts, session_id, facts)

            # Phase 3: mirror each new Fact to the Qdrant vector index.
            # If this fails we do NOT mark the batch consolidated — the next
            # turn will retry rather than silently drop the vectors.
            if jids:
                try:
                    from memory.vector import vector_store
                    for fact, node_id in zip(facts, jids):
                        await asyncio.to_thread(
                            vector_store.upsert,
                            node_id,
                            session_id,
                            "fact",
                            fact["content"],
                        )
                except Exception:
                    vector_ok = False
                    log.warning(
                        "vector upsert failed for %s — will retry on next turn",
                        session_id,
                    )

            if vector_ok:
                event_bus.emit({
                    "event": "MEMORY_CONSOLIDATED",
                    "session_id": session_id,
                    "fact_count": len(facts),
                    "jids": jids,
                })
                log.info("consolidated %d facts for %s", len(facts), session_id)

        # Only advance the consolidation mark when all writes (SQLite + Qdrant)
        # succeeded. If Qdrant failed, leave the mark where it is so the next
        # turn re-processes the same batch.
        if vector_ok:
            cutoff = max_id - settings.working_memory_size
            if cutoff > 0:
                store.mark_consolidated(session_id, cutoff)

    except Exception:
        event_bus.emit({"event": "MEMORY_FAILED", "session_id": session_id})
        log.exception("consolidation failed for %s", session_id)
