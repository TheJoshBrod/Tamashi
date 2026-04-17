"""Async consolidation: extract subjects from messages that fell out of the FIFO
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
    """Extract subjects from unconsolidated messages and write to long-term memory.

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

        # Build vocabulary: vector-search existing subjects relevant to this batch.
        conversation_text = " ".join(
            m["content"] for m in raw if m.get("content") and m["role"] == "user"
        )
        vocabulary: list[dict] = []
        if conversation_text:
            from memory import bridge
            vocabulary = await asyncio.to_thread(
                bridge.lookup_vocabulary, session_id, conversation_text
            )

        # Extraction is a blocking LiteLLM call — run in a thread.
        from memory import extractor, bridge
        extracted = await asyncio.to_thread(
            extractor.extract_subjects, raw, vocabulary
        )

        subjects = extracted.get("subjects", [])
        relations = extracted.get("relations", [])

        vector_ok = True
        if subjects or relations:
            ingest_result = await asyncio.to_thread(
                bridge.ingest_subjects, session_id, subjects, relations
            )
            new_jids: dict = ingest_result.get("new_jids", {})
            needs_rewrite: list = ingest_result.get("needs_rewrite", [])

            # Build lookup for subject data from the extraction results.
            subject_data_by_name = {s["name"]: s for s in subjects}

            # Mirror only NEW subjects to Qdrant (existing summaries are unchanged).
            if new_jids:
                try:
                    from memory.vector import vector_store
                    for name, node_id in new_jids.items():
                        s_data = subject_data_by_name.get(name, {})
                        await asyncio.to_thread(
                            vector_store.upsert,
                            node_id,
                            session_id,
                            "subject",
                            name,
                            s_data.get("summary", ""),
                            s_data.get("subject_type", "other"),
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
                    "subject_count": len(subjects),
                    "relation_count": len(relations),
                    "rewrites_queued": len(needs_rewrite),
                })
                log.info(
                    "consolidated %d subjects, %d relations for %s",
                    len(subjects), len(relations), session_id,
                )

            # Dispatch WAL rewrites for subjects that crossed the threshold.
            if needs_rewrite:
                from memory.rewriter import rewrite_subject
                for subject_name in needs_rewrite:
                    asyncio.create_task(rewrite_subject(session_id, subject_name))

        # Only advance the consolidation mark when all writes succeeded.
        if vector_ok:
            cutoff = max_id - settings.working_memory_size
            if cutoff > 0:
                store.mark_consolidated(session_id, cutoff)

    except Exception:
        event_bus.emit({"event": "MEMORY_FAILED", "session_id": session_id})
        log.exception("consolidation failed for %s", session_id)
