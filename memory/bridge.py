"""Python facade for the Jac memory graph + Qdrant vector store.

Architecture:
  - Jac graph (in-process, via jaclang.lib): fast traversal, walker-based GraphRAG
  - SQLite SubjectStore (memory/store.py): durable persistence across restarts
  - Qdrant embedded (memory/vector.py): semantic vector search for retrieval

Write path:
  ingest_subjects → Jac graph (in-process) + SQLite (durable) + Qdrant (vector index)

Read path (Phase 3 stub — full read path in Phase 4):
  retrieve_context returns "" until Phase 4 rewrites the read path.

Swapping the graph backend only requires changing this module.
"""
from __future__ import annotations

import logging

from core.config import settings
from jaclang.lib import spawn, root

from memory.walkers import GetOrCreateUser, IngestSubjects, LoadSubjects, RetrieveSubjects
from memory.store import subject_store

log = logging.getLogger(__name__)

# Track which user_ids have been loaded into the in-process Jac graph.
_loaded_users: set[str] = set()


def _get_user_node(user_id: str):
    """Get-or-create the User node for this user_id under global root()."""
    result = spawn(GetOrCreateUser(user_id=user_id), root())
    return result.reports[0]


def _ensure_loaded(user_id: str) -> None:
    """If this user's subjects aren't in the Jac graph yet, load them from SQLite.

    Preserves recent_events across restarts: the SQLite store persists the WAL,
    and this function rehydrates it into the in-memory Subject nodes.
    """
    if user_id in _loaded_users:
        return
    user_node = _get_user_node(user_id)
    # Probe: if subjects already in graph, just mark loaded and return.
    probe = spawn(RetrieveSubjects(max_subjects=1), user_node)
    if probe.reports:
        _loaded_users.add(user_id)
        return
    # Graph is empty for this user — reload from SQLite (covers process restart).
    persisted = subject_store.get_subjects(user_id, limit=1000)
    if persisted:
        spawn(LoadSubjects(subjects=persisted), user_node)
    _loaded_users.add(user_id)


def ingest_subjects(
    user_id: str,
    subjects: list[dict],
    relations: list[dict],
) -> dict:
    """Ingest extracted subjects and relations into the Jac graph + SQLite.

    Pre-deduplicates same-name subjects by merging their description_deltas
    before calling the walker (walker receives a clean, deduplicated list).

    Args:
        user_id:   the user's session / phone number
        subjects:  list of {name, description_delta, summary?, subject_type?}
        relations: list of {source, kind, target}

    Returns:
        {
          "new_jids": {name: jid_str},   # only newly created subjects
          "needs_rewrite": [name, ...]   # subjects whose WAL hit the threshold
        }
    """
    if not subjects and not relations:
        return {"new_jids": {}, "needs_rewrite": []}

    _ensure_loaded(user_id)
    user_node = _get_user_node(user_id)

    # Intra-batch deduplication: merge description_deltas for same name.
    merged: dict[str, dict] = {}
    for s in subjects:
        name = s["name"]
        if name in merged:
            existing_delta = merged[name]["description_delta"]
            new_delta = s["description_delta"]
            merged[name]["description_delta"] = f"{existing_delta}\n{new_delta}".strip()
        else:
            merged[name] = {
                "name": name,
                "summary": s.get("summary", ""),
                "description_delta": s["description_delta"],
                "subject_type": s.get("subject_type", "other") or "other",
                # recent_events = new deltas to APPEND to the existing node list
                "recent_events": [s["description_delta"]],
            }

    deduped = list(merged.values())
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()

    result = spawn(IngestSubjects(subjects=deduped, relations=relations, now=now), user_node)

    new_jids: dict[str, str] = {}
    needs_rewrite: list[str] = []

    for report in result.reports:
        name = str(report.get("name", ""))
        is_new = bool(report.get("is_new", False))
        jid_val = str(report.get("jid", ""))
        recent_events = list(report.get("recent_events", []))

        if is_new:
            new_jids[name] = jid_val
            s_data = merged[name]
            subject_store.upsert_subject(
                user_id=user_id,
                name=name,
                summary=s_data["summary"],
                description=s_data["description_delta"],
                subject_type=s_data["subject_type"],
                recent_events=recent_events,
                node_jid=jid_val,
            )
        else:
            subject_store.update_subject_wal(user_id, name, recent_events)

        if len(recent_events) >= settings.subject_wal_threshold:
            needs_rewrite.append(name)

    for rel in relations:
        subject_store.upsert_relation(
            user_id=user_id,
            src_name=rel["source"],
            kind=rel["kind"],
            tgt_name=rel["target"],
        )

    _loaded_users.add(user_id)
    return {"new_jids": new_jids, "needs_rewrite": needs_rewrite}


def lookup_vocabulary(
    user_id: str,
    conversation_text: str,
    k: int | None = None,
) -> list[dict]:
    """Return up to k existing subjects relevant to the conversation.

    Used to build the vocabulary injection block in extraction prompts.
    Returns [{name, summary, subject_type}] with ~200-char summaries.
    Returns [] gracefully if vector store is empty or unavailable.
    """
    if not settings.long_term_memory_enabled:
        return []
    if k is None:
        k = settings.subject_vocabulary_k
    try:
        from memory.vector import vector_store
        results = vector_store.search_with_payload(user_id, conversation_text, k=k)
        vocab = []
        for r in results:
            payload = r.get("payload", {})
            vocab.append({
                "name": payload.get("name", ""),
                "summary": payload.get("summary", ""),
                "subject_type": payload.get("subject_type", "other"),
            })
        return [v for v in vocab if v["name"]]
    except Exception:
        log.debug("lookup_vocabulary failed, returning empty vocabulary")
        return []


def retrieve_context(user_id: str, query: str = "", max_subjects: int = 10) -> str:
    """Return a formatted memory block for the LLM prompt.

    Phase 3 stub: returns basic subject summaries via naive graph retrieval.
    Full GraphRAG read path (RetrieveBySubjectJids + markdown formatter) is Phase 4.
    Returns "" if no subjects are stored yet.
    """
    if not settings.long_term_memory_enabled:
        return ""
    try:
        _ensure_loaded(user_id)
        user_node = _get_user_node(user_id)

        # Phase 3: try vector search, fall back to naive graph retrieval.
        seed_jids: list[str] = []
        if query:
            try:
                from memory.vector import vector_store
                seed_jids = vector_store.search(user_id, query, k=5)
            except Exception:
                pass

        if seed_jids:
            from memory.walkers import RetrieveBySubjectJids
            result = spawn(RetrieveBySubjectJids(seed_jids=seed_jids), user_node)
        else:
            result = spawn(RetrieveSubjects(max_subjects=max_subjects), user_node)

        if not result.reports:
            return ""

        seen: set[str] = set()
        lines = []
        for r in result.reports:
            name = str(r.get("name", ""))
            if not name or name in seen:
                continue
            seen.add(name)
            summary = str(r.get("summary", ""))
            lines.append(f"- {name}: {summary}" if summary else f"- {name}")
            if len(lines) >= max_subjects:
                break

        if not lines:
            return ""
        return "Relevant memory:\n" + "\n".join(lines)
    except Exception:
        log.debug("retrieve_context failed gracefully", exc_info=True)
        return ""


def list_user_subjects(user_id: str) -> list[dict]:
    """Return all subjects for a user. Used by tests and debug endpoints."""
    _ensure_loaded(user_id)
    user_node = _get_user_node(user_id)
    result = spawn(RetrieveSubjects(max_subjects=1000), user_node)
    return result.reports
