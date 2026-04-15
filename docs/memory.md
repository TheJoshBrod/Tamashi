# Memory Architecture

Tamashi uses a three-layer hybrid memory system:

| Layer | Technology | Role |
|-------|-----------|------|
| Working memory | SQLite `messages` table (FIFO) | Last N turns sent to every LLM call |
| Long-term graph | Jac in-process graph + SQLite `memory_facts` | Entities, relations, 1-hop traversal |
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
User ──++>── Fact ──++>── Topic
              │
              └──+>:RelatesTo:+>── Fact   (Phase 3 — similarity edges)
```

Node types:

| Node | Key fields | Purpose |
|------|-----------|---------|
| `User` | `user_id` | Per-user scope node (child of global `root()`) |
| `Fact` | `content`, `topic`, `source_msg_id` | An extracted memory item |
| `Topic` | `label` | Shared topic node (`health`, `goals`, `personal`, `nutrition`, `other`) |
| `Article` | `title`, `url`, `snippet` | Reserved for external article ingestion |

Edge types:

| Edge | Fields | Meaning |
|------|--------|---------|
| `RelatesTo` | `kind: str`, `weight: float` | Semantic similarity (`kind="similar"`) or other relationships |
| `Mentions` | — | Fact → Topic link |

### Multi-tenancy

Library mode (`jaclang.lib`) exposes one global `root()`. Each user gets a `User(user_id=...)` child node under `root()`. All walkers receive or discover the User node and scope their data there. The user's WhatsApp phone number (`From` field from Twilio) is the `user_id`.

### Persistence

Jac library mode is **in-memory only** — graph state does not survive process restart. `memory/store.py` provides a SQLite write-through: every `ingest_facts` call writes to both the Jac graph and `memory_facts` (SQLite). On first access for a user after restart, `bridge._ensure_loaded()` reloads their facts from SQLite back into the Jac graph.

---

## Consolidation Pipeline

After every agent reply, a fire-and-forget `asyncio.Task` runs `consolidate_if_needed`:

```
agent reply sent
    └── asyncio.create_task(consolidate_if_needed(session_id, store))
            ├── store.get_unconsolidated(session_id, working_memory_size)
            │       → messages outside the FIFO window not yet consolidated
            ├── extractor.extract_facts(raw_messages)   # LiteLLM JSON mode
            ├── bridge.ingest_facts(session_id, facts)  # Jac + SQLite
            ├── vector_store.upsert(node_id, ...)       # Qdrant
            └── store.mark_consolidated(session_id, cutoff_id)
```

`consolidated_marks(session_id, max_message_id)` in SQLite tracks the high-water mark so no messages are processed twice.

### Extraction model

Configured via `settings.extraction_model` (default `anthropic/claude-haiku-4-5-20251001`). The prompt asks for 0-5 self-contained facts with a topic tag. Uses `response_format={"type": "json_object"}` — no Jac `by llm()` dependency.

---

## GraphRAG Retrieval

`bridge.retrieve_context(user_id, query)` runs on every LLM call:

```
query string
    │
    ▼
vector_store.search(user_id, query, k=5)
    │  → list of jid strings (nearest facts by cosine similarity)
    │
    ▼
spawn(RetrieveByJids(seed_jids=...), user_node)
    │  → seed facts + their 1-hop Fact neighbors via any outgoing edge
    │
    ▼
Python dedup + cap to max_facts
    │
    ▼
"Relevant memory:\n- [topic] content\n..." injected as second system message
```

**Fallback**: if the vector store is empty (first N turns before any consolidation) or unavailable, falls back to `RetrieveFacts` (naive most-recent-first walker).

**Token budget**: `settings.memory_context_token_budget` (default 1500). Enforced by the `max_facts` cap — each fact is ~20-40 tokens so 10 facts ≈ 200-400 tokens, well within budget.

---

## Nightly Linker

`memory/linker.py::run_linker()` runs as an APScheduler cron job at 3 AM. For each user with stored facts, it:

1. Loads all facts from SQLite
2. For each fact, calls `vector_store.search_with_scores(user_id, fact.content, k=5)`
3. Filters neighbors with cosine similarity ≥ 0.8
4. Calls the `LinkFacts` walker to draw `RelatesTo(kind="similar", weight=score)` edges

After the linker has run, `RetrieveByJids` expands not just direct graph neighbors but also semantically linked facts across the user's history.

APScheduler is started in `app.py::startup_event`. If `apscheduler` is not installed, the linker is silently disabled — retrieval still works (just without pre-computed similarity edges).

---

## Configuration

All settings live in `core/config.py` (overridable via `.env`):

| Setting | Default | Effect |
|---------|---------|--------|
| `working_memory_size` | `10` | FIFO cap — turns sent to every LLM call |
| `long_term_memory_enabled` | `True` | Master switch for extraction + retrieval |
| `extraction_model` | `anthropic/claude-haiku-4-5-20251001` | Model for fact extraction |
| `memory_context_token_budget` | `1500` | Max tokens injected from memory |
| `vector_db_path` | `memory/qdrant/` | Local Qdrant storage directory |

---

## File Map

```
memory/
├── graph.jac           # Node/edge topology (User, Fact, Topic, RelatesTo, Mentions)
├── walkers.jac         # Jac walkers: GetOrCreateUser, IngestFacts, RetrieveFacts,
│                       #              RetrieveByJids, LinkFacts
├── bridge.py           # Python→Jac facade; GraphRAG retrieve_context
├── store.py            # SQLite FactStore — durable persistence for Jac graph
├── extractor.py        # LiteLLM JSON-mode fact extraction
├── consolidator.py     # Async post-reply task: extract → ingest → Qdrant upsert
├── vector.py           # QdrantMemoryStore (fastembed, embedded, no server)
├── linker.py           # APScheduler nightly job: draw similarity edges
└── qdrant/             # Local Qdrant storage (gitignored)
```

---

## Phase Decision Log

### Phase 1 — Jac Spike (complete)
Validated Jac library-mode Python interop, walker semantics (`++>` returns list, `can` vs `def`, `with Root entry`), and multi-tenancy via User child nodes.

**Finding**: Jac library mode has no cross-restart persistence. Mitigated with SQLite write-through (`memory/store.py`) and probe-based lazy reload (`bridge._ensure_loaded`).

### Phase 2 — FastAPI Integration (complete)
Wired FIFO working buffer, retrieval injection into `_build_history`, async consolidation via `BackgroundTasks`, and `consolidated_marks` tracking table.

### Phase 3 — GraphRAG + Qdrant (complete)
Added `memory/vector.py` (Qdrant embedded + fastembed), upgraded `retrieve_context` to two-step GraphRAG (vector seeds → `RetrieveByJids` walker), wired Qdrant upsert into `consolidator.py`, and added nightly `LinkFacts` edge-generation via APScheduler.

**Jac type system notes from Phase 3**:
- Local variables need explicit type annotation (`count: int = 0`) for arithmetic inference
- `float(target["weight"])` required when accessing untyped dict values for typed edge fields
- `list` (ungeneric) used for `seed_jids`/`target_jids` to avoid `jid()` return-type conflicts

### Phase 4 — Full-Stack Jac Evaluation (optional, not started)
Decision pending. Current recommendation: keep Jac boxed in the memory module. FastAPI handles HTTP; Jac handles graph traversal. The seam is `memory/bridge.py`.
