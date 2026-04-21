# Graph Schema Topology

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

Pending facts learned about a Subject are **not** stored on the node. They live in the `subject_events` WAL table in SQLite and are drained by the Subject Rewriter — see the [Persistence Layer](persistence.md) doc.

Edge types:

| Edge | Fields | Meaning |
|------|--------|---------|
| `Relates` | `kind: str`, `weight: float` | Semantic relationship (e.g., "wants", "works_at", "enjoys") |

---

Related: [Persistence Layer](persistence.md) · [Consolidation & Maintenance](consolidation.md) · [GraphRAG Retrieval](retrieval.md)

[← Back to Documentation Hub](../README.md)
