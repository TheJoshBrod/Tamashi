# Memory Eval Harness (Phase 2 Baseline)

The eval harness is a measurement-first layer over the memory system. It runs
each retrieval and extraction path against hand-authored fixtures, scores the
result, and writes a markdown report. Every LLM-driven phase after this must
re-run the harness and report numerical deltas against the baseline.

The harness exists because Phase 3 (hybrid auto-recall, bidirectional
traversal, token budget, 2-hop expansion) and Phase 5b (rewriter/extractor
tuning) would otherwise be vibe-based. Numbers shift-left of tuning.

| Location | Role |
|----------|------|
| `tests/memory_eval/fixtures/cases.py` | Hand-authored `(input, expected)` cases |
| `tests/memory_eval/scoring.py` | Precision/recall/MRR/hallucination primitives |
| `tests/memory_eval/parsing.py` | Turns a `retrieve_context` block into a ranked name list |
| `tests/memory_eval/collectors.py` | Session-scoped score accumulators |
| `tests/memory_eval/conftest.py` | Marker gating, fixtures, `pytest_sessionfinish` report hook |
| `tests/memory_eval/test_retrieval.py` | Retrieval baseline driver (marker `eval`) |
| `tests/memory_eval/test_extractor.py` | Extractor baseline driver (marker `eval`, credential-gated) |
| `tests/memory_eval/test_scoring.py` | Deterministic self-tests for the scoring primitives (default suite) |
| `tests/memory_eval/test_parsing.py` | Deterministic self-tests for the parser (default suite) |
| `tests/memory_eval/BASELINE.md` | Snapshot of the Phase 2 numbers + acceptance bars |
| `tests/memory_eval/_reports/` | Generated markdown (overwritten each run) |

## Running

```bash
# Full baseline — requires ANTHROPIC_API_KEY for the extractor suite.
RUN_EVAL=1 env/bin/python3 -m pytest tests/memory_eval/ -v

# Default suite: the scoring + parsing self-tests run, the eval fixtures skip.
env/bin/python3 -m pytest tests/ -v
```

The `eval` pytest marker is added in `conftest.py::pytest_configure` and gated
by `RUN_EVAL=1` in `pytest_collection_modifyitems`. Only tests decorated
`@pytest.mark.eval` are skipped — the deterministic self-tests in
`test_scoring.py` and `test_parsing.py` keep running. A prior implementation
gated by path substring had to be removed because the directory name `eval`
collided with unmarked tests that happened to share the path.

## Gating and silent-failure defenses

Two defenses prevent a missing credential or empty response from masquerading
as a clean baseline:

1. **Credential pre-flight on `test_extractor.py`.** The module carries a
   `pytestmark = pytest.mark.skipif(...)` that skips the whole extractor
   suite when neither `ANTHROPIC_API_KEY` nor `OPENAI_API_KEY` is set. Without
   this, the extractor's broad `except Exception` returns
   `{"subjects": [], "relations": []}` on auth failure and every fixture
   scores 0.0 — test output says "10 passed" with no subject matches.

2. **Hallucination denominator `max(1, |extracted|)`.** In
   `scoring.score_extraction`, a silent-empty extractor scores
   `hallucination_rate = 0.0` by construction, so the credentials gate is
   what actually catches the silent-empty mode. The denominator is there to
   keep the metric well-defined on correct negative fixtures.

## Report rendering (sessionfinish hook)

`conftest.py::pytest_sessionfinish` reads the session collectors and writes
`_reports/{retrieval,extractor}.md` via `scoring.render_markdown_table`. The
hook fires even when the run is interrupted or partial: fixtures that reached
`record_*_score` appear in the table; the rest simply do not.

Collectors live in `tests/memory_eval/collectors.py`, **not in `conftest.py`.**
Pytest loads `conftest.py` as a plugin in a separate module namespace; tests
that `import from tests.memory_eval.conftest` create a second copy of the
module state, so collectors held in conftest would be invisible to the
session-finish hook. Keeping them in a plain module avoids the dual-load.

## Fixture schemas

Retrieval fixtures (`RETRIEVAL_FIXTURES`):

```python
{
  "id": str,
  "description": str,
  "seeded_subjects": [{"name", "summary", "description_delta", "subject_type"}],
  "seeded_relations": [{"source", "kind", "target"}],
  "query": str,
  "expected_top_k_names": [str],   # names that should appear in top-k
  "forbidden_names": [str],         # names that should not appear
  "k": int,
}
```

Extractor fixtures (`EXTRACTOR_FIXTURES`):

```python
{
  "id": str,
  "description": str,
  "messages": [{"role", "content"}],
  "vocabulary": [{"name", "summary", "subject_type"}],
  "expected_subjects": [str],
  "expected_relations": [(src, kind, tgt)],
  "is_negative": bool,
}
```

Relation `kind` values are constrained to `settings.allowed_relation_kinds`.

## Metrics

All name comparisons are case-insensitive on stripped strings.

- **precision@k** — `|retrieved[:k] ∩ expected| / k`. With 1–2 expected items
  and `k=5`, absolute values are low by construction. The signal is
  *direction of change vs baseline*, not the absolute number.
- **recall@k** — `|retrieved[:k] ∩ expected| / |expected|`; returns `1.0`
  when expected is empty (degenerate pass).
- **MRR** — uniform-per-expected-item. Each expected name contributes
  `1/rank` if present in the top-k, else `0`; averaged across expected.
  Stricter than classic query-level MRR, but honest for fixtures that list
  multiple expected names.
- **forbidden_hit_rate** — `|retrieved[:k] ∩ forbidden| / |forbidden|`.
  Recorded as a **baseline measurement, not an invariant.** With the
  current tiny seeded-subject sets and `k=5`, the fallback path often
  returns every seed including distractors. Phase 3's hybrid auto-recall is
  expected to drive this toward 0.
- **subject_match_rate / relation_match_rate** — set-overlap over expected.
- **hallucination_rate** — `|extracted \ expected| / max(1, |extracted|)`.

Aggregates in the report footer are macro-averaged across fixtures via
`scoring.aggregate`.

## Retrieval baseline (2026-04-20)

```
precision_at_k     0.240
recall_at_k        1.000  (fallback artifact — see BASELINE.md)
mrr                0.925
forbidden_hit_rate 0.300
n_fixtures         10
```

## Extractor baseline (2026-04-20)

```
subject_match_rate   0.700
relation_match_rate  1.000
hallucination_rate   0.100
n_fixtures           10
```

## Bugs caught while standing up the baseline

1. **Silent-empty extractor.**
   `litellm.completion(model="anthropic/claude-haiku-4-5-20251001",
   response_format={"type": "json_object"})` returned markdown-fenced JSON
   (```` ```json\n{…}\n``` ````). `json.loads` raised and the broad
   `except` in `memory/extractor.py::extract_subjects` returned
   `{"subjects": [], "relations": []}`. Before the fix, every positive
   fixture reported `subject_match_rate = 0.0` but the suite reported "10
   passed" — exactly the silent-failure mode the gating rule is designed
   to prevent. **Fix:** `memory/extractor.py::_strip_json_fences` strips
   the fences before `json.loads`.
   **Regression gate:** `tests/test_extractor_parsing.py` runs in the
   default suite so a future edit that silently drops fence stripping
   fails loud without needing `RUN_EVAL=1`.

2. **conftest dual-load.**
   Collectors initially lived in `conftest.py`; importing
   `from tests.memory_eval.conftest import ...` inside tests created a
   second module instance, so the `pytest_sessionfinish` hook saw an empty
   list. Moved collectors to `collectors.py`; conftest imports from there.

## Acceptance bars for downstream phases

- **Phase 3 (hybrid auto-recall + bidirectional + token budget + 2-hop).**
  `forbidden_hit_rate ↓` from `0.300` with no recall regression. MRR on
  `retr_inbound_neighbor_baseline` ↑ from `0.750` (target `1.0` once
  reverse edges count).
- **Phase 5a (embedding migration to `name + summary`).** Aggregate P@k and
  MRR must match or beat this baseline on `subjects_v2` **before** the old
  collection is dropped.
- **Phase 5b (rewriter/extractor tuning).** `subject_match_rate ↑` from
  `0.700` with `hallucination_rate ≤ 0.100`. The three subject-miss
  fixtures (`extr_preference_enjoys`, `extr_location_located_in`,
  `extr_goal_subject`) should flip to `≥ 0.5` without regressing
  `is_negative` cases.

---

[← Back to Memory Architecture](README.md)
