# Memory Architecture

Tamashi uses a three-layer hybrid memory system focused on entity-centric **Subjects** and their **Relationships**.

| Layer | Technology | Role |
|-------|-----------|------|
| Working memory | SQLite `messages` table (FIFO) | Last N turns sent to every LLM call |
| Long-term graph | Jac in-process graph + SQLite `memory_subjects` | Entities (Subjects) and semantic Relations |
| Vector index | Qdrant embedded (fastembed) | Semantic search seeds for GraphRAG |

---

## Working Memory

`sessions/sqlite_store.py::get_history(session_id, limit=N)` returns the most-recent `N` messages after the last `/clear` marker. `N` is controlled by `settings.working_memory_size` (default 10).

The orchestrator's `_build_history` uses this limit:

```python
history = self._store.get_history(session_id, limit=settings.working_memory_size)
```

Messages older than the window fall out of every LLM prompt but are never deleted from the database.

---

## Long-Term Memory (Jac Graph)

### Graph topology (`memory/graph.jac`)

```
User ──++>── Subject ──+>:Relates:+>── Subject
```

Node types:

| Node | Key fields | Purpose |
|------|-----------|---------|
| `User` | `user_id` | Per-user scope node (child of global `root()`) |
| `Subject` | `name`, `summary`, `description`, `subject_type` | An entity-centric memory item (person, place, concept, etc.) |

**Subject Properties**:
- `name`: Unique identifier for the entity (e.g., "Koda").
- `summary`: A short, stable identity blurb (~200 chars).
- `description`: A growing log of detailed information about the subject.
- `subject_type`: one of `person`, `concept`, `goal`, `event`, `object`, `place`, `other`.
- `recent_events`: A WAL (Write-Ahead Log) of new information learned before it's merged into the main description.

Edge types:

| Edge | Fields | Meaning |
|------|--------|---------|
| `Relates` | `kind: str`, `weight: float` | Semantic relationship (e.g., "wants", "works_at", "enjoys") |

---

## Persistence

Jac library mode is **in-memory only** — graph state does not survive process restart. `memory/store.py` provides a SQLite write-through:

- **Subjects**: Stored in `memory_subjects` table.
- **Relations**: Stored in `memory_relations` table.

On first access for a user after restart, `bridge._ensure_loaded()` reloads their subjects from SQLite back into the Jac graph via the `LoadSubjects` walker. **`Relates` edges are not reloaded** — they are read directly from SQLite when needed (graph UI, rewriter context). The Jac graph only rebuilds edges as new facts are consolidated during active use.

---

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

## GraphRAG Retrieval

`bridge.retrieve_context(user_id, query)` is exposed as the `search_memory` **agent tool** (`tools/memory_search.py`). The LLM invokes it on demand when it needs context — it is **not** called automatically on every turn.

When called with a query:

1.  **Vector Search**: Search Qdrant for the top 5 `node_id`s (JIDs) matching the query (including similarity scores).
2.  **Walker Expansion**: Spawn the `RetrieveBySubjectJids` walker. It retrieves the seed subjects AND their 1-hop neighbors via `Relates` edges. Edge weights are multiplied by semantic similarity scores to naturally promote highly reinforced connections over hallucinated facts.
3.  **Fallback**: If no vector matches are found (or no query provided), fall back to `RetrieveSubjects` (naive most-recent-first, up to `max_subjects`).
4.  **Return value**: Formatted as `Relevant memory:\n- Name: summary` — the tool returns this string directly to the agent.

---

## Subject Rewriter (Memory Maintainer)

The system uses an event-driven, WAL-threshold architecture instead of a nightly batch job. When `bridge.ingest_subjects` reports that a Subject's `recent_events` log has reached the `subject_wal_threshold`, an async `rewrite_subject` task is launched.

1. **Context Assembly**: The `GetSubjectContext` walker retrieves 1-hop inbound/outbound relations, and Qdrant spots unlinked semantic neighbors.
2. **LLM Synthesis**: The rewriter model (`settings.rewriter_model`) receives the current summary/description, pending WAL facts, and neighbor relationships. It produces a JSON blueprint of updated descriptions and edge mutations, including a **Confidence/Resonance Score (0.0 to 1.0)** for each proposed edge to represent certainty that the relation is accurate and lasting.
3. **Graph Update**: `ClearSubjectWAL`, `DeleteRelates`/`IngestSubjects` modify the Jac Graph & SQLite layer (saving the confidence score as the edge `weight`), followed by a Qdrant idempotent upsert re-embedding the graph subject.

---

## Macroscopic Pattern Synthesis (Reflection Loop)

Instead of only triggering reactive updates to single Subjects, Tamashi runs a scheduled background "Reflection" loop designed to look across the entire working dataset (comparable to "Dreaming" or REM Sleep).

1. **Temporal Querying**: Periodically (`reflection_interval_seconds`) queries the SQLite store for the top 20 most actively modified Subjects within a trailing 7-day window.
2. **Cross-Pollination Agent**: Dispatches an LLM payload containing the summaries of these disparate active subjects, alongside the existing vocabulary of concepts.
3. **Concept Spawning**: The analyzer LLM identifies broad macro-themes or goals emerging across the active nodes. It natively spawns new `Concept` or `Goal` Subjects that explicitly tie these local nodes together via new `Relates` edges.

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

## Memory Graph UI

A visual editor for browsing and editing the graph is available at `localhost:8000/display/memory`. See [Display & Dashboard](display.md) for full usage documentation.

---

## Phase Decision Log

### Phase 1 & 2 (Complete)
Established basic Jac graph interop and FastAPI integration.

### Phase 3 — GraphRAG + Qdrant (Complete)
Moved to entity-centric **Subjects**. Implemented vector-seeded GraphRAG and vocabulary-injected extraction.

### Phase 4 — Optimized Read Path (Complete)
Refining semantic search and multi-hop traversal limits.

### Phase 5 — Subject Rewriter (Complete)
Implemented an asynchronous "Memory Maintainer" that automatically summarizes descriptions and recalculates graph ties when a subject's `recent_events` WAL hits `subject_wal_threshold`, fully removing the legacy scheduled nightly job.

