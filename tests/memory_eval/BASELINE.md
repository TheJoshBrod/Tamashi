# Phase 2 Baseline — Memory Eval

Snapshot of retrieval and extractor behavior **before** Phase 3 (hybrid
auto-recall, bidirectional traversal, token budget, 2-hop) and Phase 5a/5b
(embedding migration, rewriter confidence floor, domain namespaces). Every
LLM-driven phase after this must re-run the harness and report numerical
deltas against the table below.

## Reproduction

```bash
RUN_EVAL=1 env/bin/python3 -m pytest tests/memory_eval/ -v
```

Reports land in `tests/memory_eval/_reports/{retrieval,extractor}.md`, written
by a `pytest_sessionfinish` hook so partial runs still produce a report for
fixtures that did complete.

## Provenance

- **Date captured:** 2026-04-20
- **Extraction model:** `anthropic/claude-haiku-4-5-20251001` (from `core.config.settings.extraction_model`)
- **Embedding model:** `BAAI/bge-small-en-v1.5` via fastembed (local)
- **Vector store:** in-memory Qdrant (`:memory:`) per test; collection name `tamashi_subjects`
- **SubjectStore:** fresh SQLite file under `tmp_path` per test
- **Fixture counts:** 10 retrieval, 10 extractor
- **Pytest summary:** `20 passed` under `RUN_EVAL=1`; default `pytest tests/` is `70 passed, 20 skipped` (eval gate intact).

## Metric conventions

- **precision@k:** `|top_k ∩ expected| / k`.
  With small fixtures (1–2 expected items) and `k=5`, absolute values are low
  by construction — the signal is *direction of change* vs this baseline,
  not the absolute number.
- **recall@k:** `|top_k ∩ expected| / |expected|`; returns 1.0 when expected
  is empty (degenerate pass — nothing to miss).
- **MRR:** uniform-per-expected-item. Each expected name contributes
  `1/rank` if present in the top-k, else 0; we average across expected. This
  is stricter than classic query-level MRR, but honest for fixtures that
  list multiple expected names.
- **forbidden_hit_rate:** `|top_k ∩ forbidden| / k`. Recorded as a **baseline
  measurement, not an invariant** — with the current tiny seeded-subject
  sets and `k=5`, the fallback path often returns every seed including
  distractors. Phase 3's hybrid auto-recall is expected to drive this toward
  0.
- **subject_match_rate / relation_match_rate:** set-overlap over expected,
  case-insensitive for names.
- **hallucination_rate:** `|extracted \ expected| / max(1, |extracted|)`.
  The `max(1, …)` denominator means a silent-failure extractor returning
  nothing scores 0 hallucination — which is why we also gate this module on
  the presence of `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`, so a missing
  credential does not masquerade as a clean baseline.

## Retrieval baseline

| Fixture | P@k | R@k | MRR | Forbid |
| --- | --- | --- | --- | --- |
| retr_lexical_match_pet | 0.200 | 1.000 | 1.000 | 0.000 |
| retr_graphrag_expand_owner_pet | 0.400 | 1.000 | 0.750 | 0.000 |
| retr_semantic_pet_synonym | 0.200 | 1.000 | 1.000 | 1.000 |
| retr_preference_food | 0.200 | 1.000 | 1.000 | 1.000 |
| retr_location_recall | 0.200 | 1.000 | 1.000 | 0.000 |
| retr_goal_recall | 0.200 | 1.000 | 1.000 | 1.000 |
| retr_inbound_neighbor_baseline | 0.400 | 1.000 | 0.750 | 0.000 |
| retr_chain_person_pet_vet | 0.400 | 1.000 | 0.750 | 0.000 |
| retr_negative_off_topic | 0.000 | 1.000 | 1.000 | 0.000 |
| retr_disambiguate_two_people | 0.200 | 1.000 | 1.000 | 0.000 |

**Aggregate (macro):**
- precision_at_k: 0.240
- recall_at_k: 1.000
- mrr: 0.925
- forbidden_hit_rate: 0.300
- n_fixtures: 10

### Reading notes

- `recall@5` pegged at 1.000 everywhere is a **fallback artifact**, not
  evidence that retrieval is solved. With 2–3 seeded subjects per fixture,
  `retrieve_context` returns every seed before ranking has to do any work.
- The interesting knob is `forbidden_hit_rate = 0.300`: three fixtures
  (`retr_semantic_pet_synonym`, `retr_preference_food`, `retr_goal_recall`)
  returned the distractor alongside the target. Phase 3 hybrid auto-recall
  should push this toward 0 without regressing recall.
- `retr_inbound_neighbor_baseline` currently relies on outbound-only
  traversal; Phase 3 bidirectional traversal (P0 #4) should improve its
  MRR once reverse edges are considered at seed-expansion time.

## Extractor baseline

| Fixture | Subjects | Relations | Halluc | Neg? |
| --- | --- | --- | --- | --- |
| extr_single_subject_pet | 1.000 | 1.000 | 0.000 | False |
| extr_multi_subject_relation | 1.000 | 1.000 | 0.000 | False |
| extr_preference_enjoys | 0.000 | 1.000 | 0.000 | False |
| extr_location_located_in | 0.000 | 1.000 | 1.000 | False |
| extr_goal_subject | 0.000 | 1.000 | 0.000 | False |
| extr_vocabulary_reuse | 1.000 | 1.000 | 0.000 | False |
| extr_works_at | 1.000 | 1.000 | 0.000 | False |
| extr_multiturn_pet_vet | 1.000 | 1.000 | 0.000 | False |
| extr_negative_small_talk | 1.000 | 1.000 | 0.000 | True |
| extr_negative_ephemeral | 1.000 | 1.000 | 0.000 | True |

**Aggregate (macro):**
- subject_match_rate: 0.700
- relation_match_rate: 1.000
- hallucination_rate: 0.100
- n_fixtures: 10

### Reading notes

- **Three subject misses** (`extr_preference_enjoys`, `extr_location_located_in`,
  `extr_goal_subject`) are early targets for Phase 5b rewriter/extractor
  tuning — they share the shape "user states an abstract preference / goal
  / location" where the extractor is declining to name a subject.
- **`relation_match_rate = 1.000` aggregate is inflated** by degenerate
  `0 / max(1, 0)` passes on fixtures with empty expected relations. Treat
  only fixtures with a non-empty expected-relation list as Phase 5b signal.
- **`is_negative = True` fixtures should stay at `hallucination_rate = 0`.**
  They currently do. Regressions here are the loudest Phase 5b signal.

## Bugs found while standing up the baseline

1. **Extractor silently swallowed every response** (`memory/extractor.py`).
   `litellm.completion(model=anthropic/..., response_format={"type":"json_object"})`
   returned Markdown-fenced JSON (```` ```json\n{...}\n``` ````), so
   `json.loads` raised, was caught by the broad `except`, and the extractor
   returned `{"subjects": [], "relations": []}`. Fixed inline via
   `_strip_json_fences` before parse. Before the fix, every positive
   fixture reported `subject_match_rate = 0.0` but the suite reported "10
   passed" — exactly the silent-failure mode the gating rule was designed
   to prevent. The credentials pre-flight (`ANTHROPIC_API_KEY` /
   `OPENAI_API_KEY` module skip) catches the missing-key variant; the
   parse-path fix catches the bad-response variant.

2. **conftest collector dual-load.** Collectors initially lived in
   `conftest.py`; importing `from tests.memory_eval.conftest import ...`
   inside tests created a second module instance, so the
   `pytest_sessionfinish` hook saw an empty list. Moved collectors to
   `tests/memory_eval/collectors.py`; conftest imports from there.

## Phase 3 / 5 acceptance bar

- **Phase 3 (hybrid auto-recall + bidirectional + token budget + 2-hop):**
  forbidden_hit_rate ↓ from 0.300 with no recall regression. MRR on
  `retr_inbound_neighbor_baseline` ↑ from 0.750 (target 1.0 once reverse
  edges count).
- **Phase 5a (embedding migration to name+summary):** aggregate P@k and MRR
  must match or beat this baseline on `subjects_v2` **before** the old
  collection is dropped.
- **Phase 5b (rewriter/extractor tuning):** subject_match_rate ↑ from 0.700
  with hallucination_rate ≤ 0.100. The three subject-miss fixtures
  (`extr_preference_enjoys`, `extr_location_located_in`, `extr_goal_subject`)
  should flip to ≥ 0.5 without regressing `is_negative` cases.
