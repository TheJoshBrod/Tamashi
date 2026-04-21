# GraphRAG Retrieval

`bridge.retrieve_context(user_id, query)` is exposed as the `search_memory` **agent tool** (`tools/memory_search.py`). The LLM invokes it on demand when it needs context — it is **not** called automatically on every turn.

When called with a query:

1.  **Vector Search**: Search Qdrant for the top 5 `node_id`s (JIDs) matching the query (including similarity scores).
2.  **Walker Expansion**: Spawn the `RetrieveBySubjectJids` walker. It retrieves the seed subjects AND their 1-hop neighbors via `Relates` edges. Edge weights are multiplied by semantic similarity scores to naturally promote highly reinforced connections over hallucinated facts.
3.  **Fallback**: If no vector matches are found (or no query provided), fall back to `RetrieveSubjects` (naive most-recent-first, up to `max_subjects`).
4.  **Return value**: Formatted as `Relevant memory:\n- Name: summary` — the tool returns this string directly to the agent.

> The `- Name: summary` line shape is a load-bearing contract: the Phase 2
> [eval harness parser](eval_harness.md) matches `^- NAME(: SUMMARY)?$` to
> reconstruct the ranked name list. Retrieval experiments must preserve that
> line shape or update `tests/memory_eval/parsing.py` in lockstep.

---

Related: [Graph Schema Topology](schema.md) · [Persistence Layer](persistence.md) · [Consolidation & Maintenance](consolidation.md) · [Eval Harness](eval_harness.md)

[← Back to Documentation Hub](../README.md)
