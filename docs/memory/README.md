# Memory Architecture

Tamashi uses a three-layer hybrid memory system focused on entity-centric **Subjects** and their **Relationships**.

| Layer | Technology | Role |
|-------|-----------|------|
| Working memory | SQLite `messages` table (FIFO) | Last N turns sent to every LLM call |
| Long-term graph | Jac in-process graph + SQLite `memory_subjects` | Entities (Subjects) and semantic Relations |
| Vector index | Qdrant embedded (fastembed) | Semantic search seeds for GraphRAG |

## Memory Sub-systems

The memory system's intricacies are documented in the following guides:
- [Graph Schema Topology](schema.md) — Details the Jac graph nodes, edges, and allowed relation kinds.
- [Persistence Layer](persistence.md) — SQLite tables, rehydration, and the `subject_events` WAL's atomic snapshot-id drain.
- [Consolidation & Maintenance](consolidation.md) — Explains how the event-driven WAL rewrites subjects without nightly batches.
- [GraphRAG Retrieval](retrieval.md) — Covers how the agent retrieves memory context via vector searches and graph traversals.
- [Eval Harness (Phase 2 Baseline)](eval_harness.md) — Measurement-first fixture harness that every downstream LLM-tuning phase must diff against.

---

## Working Memory

`sessions/sqlite_store.py::get_history(session_id, limit=N)` returns the most-recent `N` messages after the last `/clear` marker. `N` is controlled by `settings.working_memory_size` (default 10).

The orchestrator's `_build_history` uses this limit:

```python
history = self._store.get_history(session_id, limit=settings.working_memory_size)
```

Messages older than the window fall out of every LLM prompt but are never deleted from the database.

---

## Persistence

Jac library mode is **in-memory only** — graph state does not survive process restart. `memory/store.py` provides a SQLite write-through across three tables:

- `memory_subjects` — durable Subject identity.
- `memory_relations` — durable `Relates` edges.
- `subject_events` — append-only per-subject WAL of pending facts; drained atomically by the rewriter using a snapshot of autoincrement ids.

On first access for a user after restart, `bridge._ensure_loaded()` replays both subjects and their `Relates` edges into the Jac graph via the `LoadSubjects` walker.

Full details — including the WAL atomicity contract and the legacy `recent_events` column migration — live in the [Persistence Layer](persistence.md) doc.

---

## Configuration

All settings live in `core/config.py` (overridable via `.env`):

| Setting | Default | Effect |
|---------|---------|--------|
| `working_memory_size` | `10` | FIFO cap for tokens sent to every LLM call |
| `long_term_memory_enabled` | `True` | Master switch for extraction + retrieval |
| `extraction_model` | `anthropic/claude-haiku-4-5-20251001` | Model for subject extraction |
| `memory_context_token_budget` | `1500` | Max tokens injected from memory |
| `vector_db_path` | `memory/qdrant/` | Local Qdrant storage directory |
| `subject_collection` | `tamashi_subjects` | Qdrant collection name |
| `subject_wal_threshold` | `5` | WAL depth that triggers a Subject Rewriter run |
| `subject_vocabulary_k` | `10` | Subjects returned by vocabulary injection vector search |
| `allowed_relation_kinds` | `[...]` | List of valid strings for `Relates.kind` |
| `rewriter_model` | `anthropic/claude-haiku-4-5-20251001` | Model used by the Subject Rewriter |
| `rewriter_neighbor_k` | `5` | Semantic neighbor candidates surfaced to the rewriter |
| `rewriter_max_concurrent` | `3` | Max parallel rewrite LLM calls (global semaphore) |
| `reflection_enabled` | `True` | Master switch for the macro-pattern reflection loop |
| `reflection_interval_seconds` | `3600` | How often the background reflection loop wakes up |
| `reflection_window_days` | `7` | Trailing days window to query for historically active subjects |
| `reflection_subject_limit` | `20` | Max count of active subjects to analyze per reflection cycle |

---

[← Back to Documentation Hub](../README.md)
