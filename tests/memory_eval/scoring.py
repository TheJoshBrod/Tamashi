"""Scoring primitives for the Phase 2 baseline eval harness.

All comparisons are case-insensitive on stripped names. The scoring functions
return small dataclass-like dicts so the harness tests can both assert
behaviour and render a summary markdown table.

Definitions:
    precision@k = |retrieved[:k] ∩ expected| / k
    recall@k    = |retrieved[:k] ∩ expected| / |expected|   (0 if expected is empty)
    MRR         = mean over expected items of (1/rank if found within top-k else 0)
    subject_match_rate    = |extracted ∩ expected| / |expected|
    relation_match_rate   = |extracted_triples ∩ expected_triples| / |expected_triples|
    hallucination_rate    = |extracted \\ expected| / max(1, |extracted|)
"""
from __future__ import annotations


def _norm(name: str) -> str:
    return (name or "").strip().lower()


def _norm_set(names) -> set[str]:
    return {_norm(n) for n in names if _norm(n)}


def _norm_triple(triple) -> tuple[str, str, str]:
    src, kind, tgt = triple
    return (_norm(src), _norm(kind), _norm(tgt))


def _norm_triples(triples) -> set[tuple[str, str, str]]:
    return {_norm_triple(t) for t in triples}


def precision_at_k(retrieved: list[str], expected: list[str], k: int) -> float:
    """|retrieved[:k] ∩ expected| / k. Returns 0.0 if k <= 0."""
    if k <= 0:
        return 0.0
    top = _norm_set(retrieved[:k])
    exp = _norm_set(expected)
    return len(top & exp) / k


def recall_at_k(retrieved: list[str], expected: list[str], k: int) -> float:
    """|retrieved[:k] ∩ expected| / |expected|. Returns 1.0 if expected is empty
    (nothing to recall, nothing missed)."""
    exp = _norm_set(expected)
    if not exp:
        return 1.0
    top = _norm_set(retrieved[:k])
    return len(top & exp) / len(exp)


def mrr(retrieved: list[str], expected: list[str], k: int) -> float:
    """Mean reciprocal rank across expected items within top-k.

    For each expected name, find its first occurrence in retrieved[:k] (1-indexed
    rank) and contribute 1/rank; miss contributes 0. Average across expected.
    Returns 1.0 if expected is empty (degenerate — nothing to rank).
    """
    exp = list(dict.fromkeys(_norm(e) for e in expected if _norm(e)))
    if not exp:
        return 1.0
    top = [_norm(r) for r in retrieved[:k]]
    total = 0.0
    for name in exp:
        try:
            rank = top.index(name) + 1
            total += 1.0 / rank
        except ValueError:
            pass
    return total / len(exp)


def forbidden_hit_rate(retrieved: list[str], forbidden: list[str], k: int) -> float:
    """Share of forbidden names that leaked into top-k. Lower is better."""
    forb = _norm_set(forbidden)
    if not forb:
        return 0.0
    top = _norm_set(retrieved[:k])
    return len(top & forb) / len(forb)


def score_retrieval(retrieved: list[str], fixture: dict) -> dict:
    """Run all retrieval metrics for one fixture."""
    k = fixture.get("k", 5)
    expected = fixture.get("expected_top_k_names", [])
    forbidden = fixture.get("forbidden_names", [])
    return {
        "id": fixture["id"],
        "precision_at_k": precision_at_k(retrieved, expected, k),
        "recall_at_k": recall_at_k(retrieved, expected, k),
        "mrr": mrr(retrieved, expected, k),
        "forbidden_hit_rate": forbidden_hit_rate(retrieved, forbidden, k),
        "retrieved": retrieved[:k],
        "expected": list(expected),
        "k": k,
    }


def score_extraction(
    extracted_subjects: list[str],
    extracted_relations: list[tuple[str, str, str]],
    fixture: dict,
) -> dict:
    """Run all extractor metrics for one fixture.

    Hallucination denominator is max(1, |extracted|) to avoid divide-by-zero
    when the extractor correctly returns nothing on a negative fixture.
    """
    exp_subjects = _norm_set(fixture.get("expected_subjects", []))
    exp_relations = _norm_triples(fixture.get("expected_relations", []))
    got_subjects = _norm_set(extracted_subjects)
    got_relations = _norm_triples(extracted_relations)

    if exp_subjects:
        subject_match = len(got_subjects & exp_subjects) / len(exp_subjects)
    else:
        subject_match = 1.0  # nothing to match

    if exp_relations:
        relation_match = len(got_relations & exp_relations) / len(exp_relations)
    else:
        relation_match = 1.0

    hallucinated = got_subjects - exp_subjects
    hallucination = len(hallucinated) / max(1, len(got_subjects))

    return {
        "id": fixture["id"],
        "subject_match_rate": subject_match,
        "relation_match_rate": relation_match,
        "hallucination_rate": hallucination,
        "is_negative": bool(fixture.get("is_negative", False)),
        "extracted_subjects": sorted(got_subjects),
        "expected_subjects": sorted(exp_subjects),
    }


def aggregate(scores: list[dict], keys: list[str]) -> dict:
    """Macro-average requested numeric keys across per-fixture scores."""
    if not scores:
        return {k: 0.0 for k in keys}
    return {
        k: sum(s.get(k, 0.0) for s in scores) / len(scores)
        for k in keys
    }


def render_markdown_table(
    title: str,
    scores: list[dict],
    columns: list[tuple[str, str]],
    summary_keys: list[str],
) -> str:
    """Render one fixture-per-row markdown table with an aggregate footer.

    columns: list of (key, header) tuples; numeric values are formatted to 3 dp.
    summary_keys: subset of numeric keys to macro-average into the footer row.
    """
    headers = " | ".join(h for _, h in columns)
    sep = " | ".join("---" for _ in columns)
    lines = [f"## {title}", "", f"| {headers} |", f"| {sep} |"]
    for row in scores:
        cells = []
        for key, _ in columns:
            val = row.get(key, "")
            cells.append(f"{val:.3f}" if isinstance(val, float) else str(val))
        lines.append("| " + " | ".join(cells) + " |")

    agg = aggregate(scores, summary_keys)
    lines.append("")
    lines.append("**Aggregate (macro):**")
    for k in summary_keys:
        lines.append(f"- {k}: {agg[k]:.3f}")
    lines.append(f"- n_fixtures: {len(scores)}")
    return "\n".join(lines)
