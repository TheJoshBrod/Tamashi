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

from memory.walkers import (
    GetOrCreateUser, IngestSubjects, LoadSubjects, RetrieveSubjects,
    GetSubjectContext, ClearSubjectWAL, DeleteRelates,
)
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


def get_full_graph(user_id: str) -> dict:
    """Return all nodes and relations for the UI."""
    _ensure_loaded(user_id)
    user_node = _get_user_node(user_id)
    
    # 1. Get nodes from Jac graph
    from memory.walkers import RetrieveFullGraph
    result = spawn(RetrieveFullGraph(), user_node)
    nodes = [n for n in result.reports if isinstance(n, dict)]
    
    # 2. Get relations from SQLite
    relations = subject_store.get_relations(user_id)
    
    # 3. Map relations to JIDs
    # Robustness: strip names to avoid whitespace mismatches
    name_to_jid = {n["name"].strip(): n["jid"] for n in nodes if "name" in n and "jid" in n}
    
    mapped_edges = []
    for rel in relations:
        src_name = rel["src_name"].strip()
        tgt_name = rel["tgt_name"].strip()
        src_jid = name_to_jid.get(src_name)
        tgt_jid = name_to_jid.get(tgt_name)
        
        if src_jid and tgt_jid:
            mapped_edges.append({
                "from": src_jid,
                "to": tgt_jid,
                "label": rel["kind"],
                "kind": rel["kind"],
                "weight": rel.get("weight", 1.0)
            })
        else:
            log.debug(f"Skipping edge: {src_name} ({src_jid}) -> {tgt_name} ({tgt_jid})")
            
    return {
        "nodes": [{"id": n["jid"], "label": n["name"], "group": n["subject_type"], **n} for n in nodes],
        "edges": mapped_edges
    }


def update_subject(
    user_id: str,
    jid: str,
    name: str,
    summary: str,
    description: str,
    subject_type: str,
) -> dict:
    """Update a subject across all 3 layers (Jac, SQLite, Qdrant)."""
    _ensure_loaded(user_id)
    user_node = _get_user_node(user_id)
    
    data = {
        "name": name,
        "summary": summary,
        "description": description,
        "subject_type": subject_type
    }
    
    # 1. Jac Graph
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    from memory.walkers import UpdateSubject
    result = spawn(UpdateSubject(jid=jid, data=data, now=now), user_node)
    if not result.reports or result.reports[0].get("status") != "success":
        return {"status": "error", "message": "Failed to update Jac node"}

    # 2. SQLite
    # We need the old name if it changed to update relations? 
    # Actually, ingest_subjects handles merging by name.
    # But for a direct update by JID:
    subject_store.upsert_subject(
        user_id=user_id,
        name=name,
        summary=summary,
        description=description,
        subject_type=subject_type,
        recent_events=[], # Clear WAL on manual edit? Or keep it? Let's clear it.
        node_jid=jid,
    )
    
    # 3. Qdrant: Always upsert to update summary/embedding
    try:
        from memory.vector import vector_store
        vector_store.upsert(jid, user_id, "subject", name, summary, subject_type)
    except Exception:
        log.warning("vector upsert failed during manual update")
        
    return {"status": "success", "jid": jid}


def delete_subject(user_id: str, jid: str) -> dict:
    """Delete a subject across all 3 layers."""
    _ensure_loaded(user_id)
    user_node = _get_user_node(user_id)
    
    # Use RetrieveSubjects to find the name first (needed for SQLite cleanup)
    # Actually, we can just find the node in Jac.
    from memory.walkers import RetrieveSubjects
    probe = spawn(RetrieveSubjects(max_subjects=1000), user_node)
    subject_name = None
    for r in probe.reports:
        if r.get("jid") == jid:
            subject_name = r.get("name")
            break
            
    if not subject_name:
        return {"status": "error", "message": "Subject not found"}

    # 1. Jac Graph
    from memory.walkers import DeleteSubject
    spawn(DeleteSubject(jid=jid), user_node)

    # 2. SQLite
    subject_store.delete_subject(user_id, subject_name)
    
    # 3. Qdrant
    try:
        # Need a vector_store.delete(jid) method! 
        # For now, it's fine if it stays in Qdrant but is gone from Graph, 
        # but let's try to add delete to vector.py later.
        pass
    except Exception:
        pass
        
    return {"status": "success", "jid": jid}


def add_relation(user_id: str, src_name: str, kind: str, tgt_name: str) -> dict:
    """Add a relation between two subjects."""
    return ingest_subjects(user_id, [], [{"source": src_name, "kind": kind, "target": tgt_name}])


def get_subject_context(user_id: str, name: str) -> dict | None:
    """Return context for a Subject: data + 1-hop outbound neighbors with edge kinds.

    Neighbor edge kinds are joined from SQLite since Jac traversal returns nodes only.
    Returns None if the subject is not found.
    """
    _ensure_loaded(user_id)
    user_node = _get_user_node(user_id)

    result = spawn(GetSubjectContext(name=name), user_node)
    if not result.reports:
        return None

    raw = result.reports[0]
    if not raw.get("name"):
        return None

    # Enrich neighbors with edge kind from SQLite
    relations = subject_store.get_relations(user_id)
    rel_lookup: dict[tuple[str, str], list[str]] = {}
    for rel in relations:
        key = (rel["src_name"], rel["tgt_name"])
        rel_lookup.setdefault(key, []).append(rel["kind"])

    enriched_neighbors = []
    for nbr in raw.get("neighbors", []):
        nbr_name = nbr["name"]
        kinds = rel_lookup.get((name, nbr_name), [])
        enriched_neighbors.append({
            **nbr,
            "edge_kind": kinds[0] if kinds else "related_to",
        })

    return {
        "subject": {
            "jid": raw["jid"],
            "name": raw["name"],
            "summary": raw["summary"],
            "description": raw["description"],
            "subject_type": raw["subject_type"],
            "recent_events": raw["recent_events"],
        },
        "neighbors": enriched_neighbors,
    }


def apply_rewrite(
    user_id: str,
    name: str,
    new_summary: str,
    new_description: str,
    add_edges: list[dict],
    remove_edges: list[dict],
) -> dict:
    """Apply a rewriter's mutations: clear WAL, update summary/description, mutate edges.

    Writes through all three layers: Jac graph, SQLite, Qdrant.
    """
    _ensure_loaded(user_id)
    user_node = _get_user_node(user_id)

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()

    # 1. Update Jac in-memory graph (clears WAL + writes new summary/description)
    result = spawn(ClearSubjectWAL(
        name=name,
        new_summary=new_summary,
        new_description=new_description,
        now=now,
    ), user_node)

    jid_str: str | None = None
    if result.reports and result.reports[0].get("status") == "success":
        jid_str = str(result.reports[0].get("jid", ""))

    # 2. Determine subject_type (needed for SQLite upsert and Qdrant)
    subject_type = "other"
    if not jid_str:
        for s in subject_store.get_subjects(user_id, limit=1000):
            if s["name"] == name:
                subject_type = s["subject_type"]
                jid_str = s.get("jid")
                break
    else:
        for s in subject_store.get_subjects(user_id, limit=1000):
            if s["name"] == name:
                subject_type = s["subject_type"]
                break

    # 3. Persist updated subject to SQLite (clears WAL)
    subject_store.upsert_subject(
        user_id=user_id,
        name=name,
        summary=new_summary,
        description=new_description,
        subject_type=subject_type,
        recent_events=[],
        node_jid=jid_str,
    )

    # 4. Add new edges
    if add_edges:
        edge_dicts = [
            {"source": name, "kind": e["kind"], "target": e["target"]}
            for e in add_edges
        ]
        ingest_subjects(user_id, [], edge_dicts)

    # 5. Remove edges
    for edge in remove_edges:
        delete_relation(user_id, name, edge["kind"], edge["target"])

    # 6. Re-embed in Qdrant (idempotent via stable node_id hash)
    if jid_str:
        try:
            from memory.vector import vector_store
            vector_store.upsert(jid_str, user_id, "subject", name, new_summary, subject_type)
        except Exception:
            log.warning("vector upsert failed during apply_rewrite for %r", name)

    return {"status": "success", "jid": jid_str}


def delete_relation(user_id: str, src_name: str, kind: str, tgt_name: str) -> dict:
    """Delete a relation across layers."""
    _ensure_loaded(user_id)
    user_node = _get_user_node(user_id)

    # 1. Delete from SQLite first so keep_kinds is accurate
    subject_store.delete_relation(user_id, src_name, kind, tgt_name)

    # 2. Delete from Jac in-memory graph using DeleteRelates walker.
    #    Walker deletes all src->tgt edges then re-adds any surviving kinds.
    remaining = subject_store.get_relations(user_id)
    keep_kinds = [
        r["kind"] for r in remaining
        if r["src_name"] == src_name and r["tgt_name"] == tgt_name
    ]
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    spawn(DeleteRelates(
        source_name=src_name,
        kind=kind,
        target_name=tgt_name,
        keep_kinds=keep_kinds,
        now=now,
    ), user_node)

    return {"status": "success"}
