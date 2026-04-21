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

Both `memory/extractor.py` and `memory/rewriter.py` go through the shared `_call_json_llm` helper (defined in `rewriter.py`). It requests `response_format={"type": "json_object"}` but strips ```` ```json … ``` ```` fences before `json.loads` — Anthropic via litellm still occasionally wraps JSON payloads in fences even under JSON mode, and without the strip the parse silently raises, the broad `except` returns an empty result, and no subjects are ever written. A regression gate for this path lives in `tests/test_extractor_parsing.py` (default suite) — see the [eval harness doc](eval_harness.md) for how the bug was caught.

---

## Subject Rewriter (Memory Maintainer)

The system uses an event-driven, WAL-threshold architecture instead of a nightly batch job. When `bridge.ingest_subjects` appends a new fact and the `subject_events` count for that Subject reaches `settings.subject_wal_threshold`, an async `rewrite_subject` task is launched. See the [Persistence Layer](persistence.md) doc for the WAL table layout and its atomicity contract.

1. **Context Assembly**: The rewriter first **snapshots** the pending WAL ids from `subject_events` — this is what makes the subsequent LLM call safe to run without a lock (concurrent appends get new ids and survive the drain). In parallel, `GetSubjectContext` retrieves 1-hop inbound/outbound relations, and Qdrant surfaces unlinked semantic neighbors. A `NODE_ACTIVE` event is dispatched over WebSockets to visually isolate the working node in the UI.
2. **LLM Synthesis**: The rewriter model (`settings.rewriter_model`) receives the current summary/description, the snapshotted WAL payloads, and neighbor relationships. It produces a JSON blueprint of updated description, edge mutations, a confidence score (0.0 to 1.0), and a **`dream_snippet`** — an internal whimsical observation reflecting on the facts it synthesized.
3. **Graph Update** (`bridge.apply_rewrite`):
   - `ClearSubjectWAL` writes the new summary/description onto the in-memory Jac Subject. *(The walker no longer clears the WAL — the name is legacy.)*
   - `subject_store.delete_events_by_ids(consumed_event_ids)` atomically drains exactly the events the rewriter saw.
   - `memory_subjects` is upserted with the new summary/description.
   - `DeleteRelates` / `IngestSubjects` apply edge mutations, saving confidence as `Relates.weight`.
   - A Qdrant idempotent upsert re-embeds the subject.

   The pipeline terminates by dispatching `NODE_INACTIVE` and broadcasting the `dream_snippet` via a `MEMORY_DREAM` WebSocket event.

---

## Macroscopic Pattern Synthesis (Reflection Loop)

Instead of only triggering reactive updates to single Subjects, Tamashi runs a scheduled background "Reflection" loop designed to look across the entire working dataset (comparable to "Dreaming" or REM Sleep).

1. **Temporal Querying**: Periodically (`reflection_interval_seconds`) queries the SQLite store for the top 20 most actively modified Subjects within a trailing 7-day window.
2. **Cross-Pollination Agent**: Dispatches an LLM payload containing the summaries of these disparate active subjects, alongside the existing vocabulary of concepts.
3. **Concept Spawning**: The analyzer LLM identifies broad macro-themes or goals emerging across the active nodes. It natively spawns new `Concept` or `Goal` Subjects that explicitly tie these local nodes together via new `Relates` edges.

---

Related: [Graph Schema Topology](schema.md) · [Persistence Layer](persistence.md) · [GraphRAG Retrieval](retrieval.md) · [Eval Harness](eval_harness.md)

[← Back to Documentation Hub](../README.md)
