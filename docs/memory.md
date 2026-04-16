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

On first access for a user after restart, `bridge._ensure_loaded()` reloads their subjects and relations from SQLite back into the Jac graph.

---

## Consolidation Pipeline

After every agent reply, a fire-and-forget `asyncio.Task` runs `consolidate_if_needed`.

```
agent reply sent  ← Orchestrator.handle_stream
    └── asyncio.create_task(consolidate_if_needed(session_id, store))
            ├── store.get_unconsolidated(...)
            ├── bridge.lookup_vocabulary(...)          # Vector search for existing subjects
            ├── extractor.extract_subjects(messages, vocab) # LiteLLM JSON mode
            ├── bridge.ingest_subjects(session_id, facts)   # Jac + SQLite
            ├── vector_store.upsert(node_id, ...)           # Qdrant (NEW subjects only)
            └── store.mark_consolidated(session_id, cutoff_id)
```

### Extraction model

Configured via `settings.extraction_model` (default `anthropic/claude-haiku-4-5-20251001`). The prompt uses **Vocabulary Injection**: it searches for existing subjects via vector search and provides them as hints to the model to prevent duplicate entity creation with slightly different names.

---

## GraphRAG Retrieval

`bridge.retrieve_context(user_id, query)` runs on every LLM call:

1.  **Vector Search**: Search Qdrant for the top 5 `node_id`s (JIDs) matching the query.
2.  **Walker Expansion**: Spawn the `RetrieveBySubjectJids` walker. It retrieves the seed subjects AND their 1-hop neighbors via `Relates` edges.
3.  **Fallback**: If no vector matches are found, it falls back to `RetrieveSubjects` (naive most-recent-first).
4.  **Injection**: Formats results as `Relevant memory:\n- Subject: Summary` and injects them into the system prompt.

---

## Nightly Linker

`memory/linker.py::run_linker()` is currently a **no-op stub** in Phase 3. Semantic linking between subjects based on cosine similarity is planned for **Phase 5** as part of a larger memory rewriter/summarizer task.

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
| `subject_wal_threshold` | `5` | Turns before a subject's description is summarized |
| `allowed_relation_kinds` | `[...]` | List of valid strings for `Relates.kind` |

---

## Phase Decision Log

### Phase 1 & 2 (Complete)
Established basic Jac graph interop and FastAPI integration.

### Phase 3 — GraphRAG + Qdrant (Complete)
Moved to entity-centric **Subjects**. Implemented vector-seeded GraphRAG and vocabulary-injected extraction.

### Phase 4 — Optimized Read Path (In Progress)
Refining semantic search and multi-hop traversal limits.

### Phase 5 — Subject Rewriter (Planned)
Implementation of the nightly linker and a description summarizer that triggers when the `recent_events` WAL hits the `subject_wal_threshold`.

