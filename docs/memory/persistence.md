# Persistence Layer

Jac's library mode is process-local — graph state does not survive restart. Tamashi pairs it with a SQLite write-through so Subjects, Relations, and pending facts are durable across restarts.

All memory tables live in `sessions.db` alongside the chat history.

## Tables

| Table | Role | Source of truth for |
|-------|------|---------------------|
| `memory_subjects` | Durable Subject record | Identity (`name`, `summary`, `description`, `subject_type`, `node_jid`) |
| `memory_relations` | Durable `Relates` edges | Subject-to-Subject semantic edges (`kind`, `weight`) |
| `subject_events` | Append-only per-subject WAL | Pending facts awaiting rewriter consolidation |

Column-level detail lives in `memory/store.py::SubjectStore._init_schema`. See [Graph Schema Topology](schema.md) for the matching Jac node and edge types.

## Rehydration

On the first access for a user after process start, `bridge._ensure_loaded(user_id)` replays SQLite state into the in-process Jac graph via the `LoadSubjects` walker. Double-checked locking keeps the fast path lock-free once the user is loaded; contention only occurs on the first post-restart access.

`Relates` edges are idempotently reloaded from `memory_relations` into the graph alongside the Subjects they connect.

---

## The `subject_events` WAL

Every new fact learned for an **existing** Subject is appended as a row in `subject_events`. The row's autoincrement `id` is the load-bearing primitive: it lets the rewriter drain safely across an LLM call without holding a lock.

### Write path

`bridge.ingest_subjects` → `subject_store.append_event`:

1. For each delta about an existing Subject, append `(user_id, subject_name, payload, created_at)`.
2. Check `subject_store.get_event_count(user_id, name)` against `settings.subject_wal_threshold` (default `5`). If met or exceeded, schedule an async `rewrite_subject` task.

### Drain path (atomic consumption)

`memory/rewriter.py::rewrite_subject` → `bridge.apply_rewrite` → `subject_store.delete_events_by_ids`:

1. **Snapshot** `pending = subject_store.get_events(user_id, name)` before the LLM call — captures the exact `id`s the rewriter will consume.
2. **LLM call** (seconds of wall time, no lock held).
3. **Apply** `bridge.apply_rewrite(..., consumed_event_ids=snapshot_ids)` — which delegates to `subject_store.delete_events_by_ids(snapshot_ids)`.

**Atomicity property.** Any fact that lands in `subject_events` during step 2 receives a fresh autoincrement `id` not present in the snapshot, so the delete in step 3 leaves it untouched. The next rewriter run will see it. No fact is ever silently dropped.

`apply_rewrite` requires `consumed_event_ids` as a mandatory argument (no default) so a future caller cannot regress to lossy bulk-delete semantics.

### New Subject versus existing Subject

- **New Subject**: the first delta becomes the initial `description`. It is *not* also written to `subject_events`, because that would immediately count against the WAL threshold on the very first fact.
- **Existing Subject**: every delta is appended to `subject_events`; `description` is only mutated by the rewriter.

---

## Legacy column migration

Prior versions stored the WAL as a JSON `recent_events` column on `memory_subjects`. On startup, `SubjectStore._init_schema` runs two idempotent passes:

1. `_migrate_recent_events_to_subject_events` — copies any un-migrated JSON entries into `subject_events`, guarded per `(user_id, subject_name)` so it is a no-op on already-migrated databases.
2. `_drop_recent_events_column` — drops the column via `ALTER TABLE ... DROP COLUMN`. Requires SQLite ≥ 3.35; on older runtimes the column lingers harmlessly until the host is upgraded, and the drop retries automatically on the next boot.

The drop runs *after* the migration, so a partial upgrade can never lose un-migrated rows.

---

Related: [Graph Schema Topology](schema.md) · [Consolidation & Maintenance](consolidation.md) · [GraphRAG Retrieval](retrieval.md)

[← Back to Documentation Hub](../README.md)
