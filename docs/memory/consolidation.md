# Consolidation & Maintenance

## Consolidation Pipeline

After every agent reply, a fire-and-forget `asyncio.Task` runs `consolidate_if_needed`.

```
agent reply sent  ← Orchestrator.handle_stream
    └── asyncio.create_task(consolidate_if_needed(session_id, store))
            ├── store.get_unconsolidated(...)
            ├── bridge.lookup_vocabulary(...)          # Vector search for existing subjects
            ├── extractor.extract_subjects(messages, vocab) # LiteLLM JSON mode
            ├── bridge.ingest_subjects(session_id, facts)   # Jac + SQLite (returns needs_rewrite)
            ├── vector_store.upsert(node_id, ...)           # Qdrant (NEW subjects only)
            ├── for name in needs_rewrite:                  # Async Subject Rewriter trigger
            │     asyncio.create_task(rewrite_subject(user_id, name))
            └── store.mark_consolidated(session_id, cutoff_id)  # only if vector writes succeeded
```

### Extraction model

Configured via `settings.extraction_model` (default `anthropic/claude-haiku-4-5-20251001`). The prompt uses **Vocabulary Injection**: it searches for existing subjects via vector search and provides them as hints to the model to prevent duplicate entity creation with slightly different names.

---

## Subject Rewriter (Memory Maintainer)

The system uses an event-driven, WAL-threshold architecture instead of a nightly batch job. When `bridge.ingest_subjects` reports that a Subject's `recent_events` log has reached the `subject_wal_threshold`, an async `rewrite_subject` task is launched.

1. **Context Assembly**: The `GetSubjectContext` walker retrieves 1-hop inbound/outbound relations, and Qdrant spots unlinked semantic neighbors. An active graph highlight event (`NODE_ACTIVE`) is dispatched over WebSockets to visually isolate the working node in the UI.
2. **LLM Synthesis**: The rewriter model (`settings.rewriter_model`) receives the current summary/description, pending WAL facts, and neighbor relationships. It produces a JSON blueprint of updated descriptions, edge mutations, a confidence score (0.0 to 1.0), and a **`dream_snippet`**—an internal whimsical observation reflecting on the facts it synthesized.
3. **Graph Update**: `ClearSubjectWAL`, `DeleteRelates`/`IngestSubjects` modify the Jac Graph & SQLite layer (saving the confidence score as the edge `weight`), followed by a Qdrant idempotent upsert re-embedding the graph subject. The pipeline terminates by dispatching a `NODE_INACTIVE` event, and broadcasting the `dream_snippet` via a `MEMORY_DREAM` WebSocket event.

---

## Macroscopic Pattern Synthesis (Reflection Loop)

Instead of only triggering reactive updates to single Subjects, Tamashi runs a scheduled background "Reflection" loop designed to look across the entire working dataset (comparable to "Dreaming" or REM Sleep).

1. **Temporal Querying**: Periodically (`reflection_interval_seconds`) queries the SQLite store for the top 20 most actively modified Subjects within a trailing 7-day window.
2. **Cross-Pollination Agent**: Dispatches an LLM payload containing the summaries of these disparate active subjects, alongside the existing vocabulary of concepts.
3. **Concept Spawning**: The analyzer LLM identifies broad macro-themes or goals emerging across the active nodes. It natively spawns new `Concept` or `Goal` Subjects that explicitly tie these local nodes together via new `Relates` edges.

---

[← Back to Documentation Hub](../README.md)
