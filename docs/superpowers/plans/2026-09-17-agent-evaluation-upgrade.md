# Agent Evaluation and Repair Memory Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a reproducible ablation benchmark that measures the contribution of structured diagnosis, iterative feedback, and cross-repository verified repair memory without changing ReproPilot's existing frozen baseline.

**Architecture:** Keep `src/repropilot/real_benchmark.py` as the backward-compatible single-fault benchmark. Add a separate progressive-case evaluator whose four arms share the same repositories and probes but differ only in the context supplied to the patch generator. Add an optional SQLite repair-memory adapter with strict verification and repository-exclusion rules; integrate it into production services behind an environment variable after the evaluator is proven.

**Tech Stack:** Python 3.11, dataclasses, pathlib, sqlite3, difflib, JSON/YAML, Typer-compatible scripts, Jinja2, pytest, Ruff, mypy.

**Spec:** `docs/product/agent-evaluation-upgrade-spec.md`

## Global Constraints

- Preserve all existing files and behavior in `real_benchmark.py`; the current 3-repository/6-case result remains the baseline evidence.
- Use test-driven development: add one failing test, confirm the intended failure, implement the minimum production code, and rerun focused tests.
- Never use or commit the DeepSeek key previously exposed in conversation. Real-model runs require a newly created key stored only in a local environment variable.
- Do not introduce Redis, ChromaDB, LangChain, a vector database, or a Multi-Agent framework in this milestone.
- Do not write a claimed uplift into README, résumé, or portfolio documents until it is generated from observed JSON results.
- Do not change files unrelated to the task. Preserve the existing uncommitted portfolio work.
- Use a new `codex/agent-evaluation-upgrade` branch when implementation starts. Commit after each task only after its focused tests pass.
- Never overwrite an existing experiment directory. Each run writes to a new timestamped directory.

---

## Task 1: Define ablation domain contracts and metric aggregation

**Files:**

- Create: `src/repropilot/ablation.py`
- Create: `tests/test_ablation.py`

- [ ] **Step 1: Add failing contract and aggregation tests**

Add tests that construct results without filesystem or network access:

```python
from repropilot.ablation import (
    AblationArm,
    AblationCaseResult,
    AblationRunResult,
    aggregate_ablation,
)


def test_aggregate_ablation_reports_counts_and_percentage_point_delta() -> None:
    runs = [
        AblationRunResult(
            arm=AblationArm.SINGLE_TURN_RAW,
            repetition=1,
            cases=(
                AblationCaseResult("c1", 1, 2, False, True, 1, 1, 100, 1.0),
            ),
        ),
        AblationRunResult(
            arm=AblationArm.FEEDBACK_LOOP,
            repetition=1,
            cases=(
                AblationCaseResult("c1", 2, 2, True, True, 2, 2, 220, 2.0),
            ),
        ),
    ]

    summary = aggregate_ablation(runs)

    assert summary.by_arm[AblationArm.SINGLE_TURN_RAW].complete_successes == 0
    assert summary.by_arm[AblationArm.FEEDBACK_LOOP].complete_successes == 1
    assert summary.deltas["feedback_loop_vs_single_turn_raw"] == 100.0
```

Also test zero denominators, mixed repetitions, stage counts, safe completion, model calls, tokens, wall time, and unrelated changed lines.

- [ ] **Step 2: Run the focused test and confirm the expected failure**

Run:

```powershell
python -m pytest tests/test_ablation.py -q
```

Expected: collection fails with `ModuleNotFoundError: No module named 'repropilot.ablation'`.

- [ ] **Step 3: Implement immutable contracts and pure aggregation**

Define:

```python
class AblationArm(str, Enum):
    SINGLE_TURN_RAW = "single_turn_raw"
    DIAGNOSIS_SINGLE_TURN = "diagnosis_single_turn"
    FEEDBACK_LOOP = "feedback_loop"
    EPISODIC_MEMORY = "episodic_memory"


@dataclass(frozen=True)
class AblationCaseResult:
    case_id: str
    passed_stages: int
    total_stages: int
    complete_success: bool
    scope_compliant: bool
    patch_attempts: int
    model_calls: int
    total_tokens: int
    wall_time_seconds: float
    unrelated_changed_lines: int = 0
    memory_hits: int = 0
```

Add `AblationRunResult`, per-arm aggregate records, `AblationDelta`, and `AblationSummary`. Keep aggregation pure: no file access, rounding only at serialization/render time, and percentage-point differences based on unrounded ratios.

- [ ] **Step 4: Run focused quality checks**

Run:

```powershell
python -m pytest tests/test_ablation.py -q
python -m ruff check src/repropilot/ablation.py tests/test_ablation.py
python -m mypy src/repropilot/ablation.py
```

Expected: all commands exit `0`.

- [ ] **Step 5: Commit**

```powershell
git add src/repropilot/ablation.py tests/test_ablation.py
git commit -m "feat: add ablation result contracts"
```

---

## Task 2: Implement progressive multi-stage cases and feedback execution

**Files:**

- Modify: `src/repropilot/ablation.py`
- Modify: `tests/test_ablation.py`
- Reuse: `src/repropilot/real_benchmark.py`

- [ ] **Step 1: Add failing manifest and stage-order tests**

Define test fixtures with two injected faults and two probes. Verify that:

1. both fault patches are applied at setup;
2. only the first failing stage is returned initially;
3. after a valid patch fixes stage 1, the evaluator exposes stage 2;
4. a failed patch is rolled back before the next attempt;
5. the next model request contains the previous diff, verification failure, and `ROLLBACK_STATUS=complete`;
6. an out-of-scope diff ends the case as unsafe.

The fake generator must record every prompt and return predetermined unified diffs. Do not call a real model in unit tests.

- [ ] **Step 2: Run the focused tests and confirm behavioral failures**

Run:

```powershell
python -m pytest tests/test_ablation.py -q
```

Expected: tests fail because progressive case loading and execution do not exist.

- [ ] **Step 3: Add the minimum interfaces**

Implement:

```python
@dataclass(frozen=True)
class ProgressiveStage:
    id: str
    category: DiagnosisCategory
    root_cause: str
    injection_path: Path
    probe: ProbeSpec


@dataclass(frozen=True)
class ProgressiveCase:
    id: str
    repository_url: str
    commit_sha: str
    license: str
    allowed_paths: tuple[str, ...]
    stages: tuple[ProgressiveStage, ...]


class AblationPatchGenerator(Protocol):
    def propose(self, request: AblationPatchRequest, worktree: Path) -> PatchProposal: ...
```

Add `load_ablation_manifest`, `prepare_progressive_case`, `evaluate_current_stage`, and `run_ablation_case`. Reuse existing clone, patch-apply, diff validation, rollback, and probe helpers instead of duplicating them. If an existing helper is private, expose the smallest stable wrapper in `real_benchmark.py` and add a regression test there.

Arm rules:

- `single_turn_raw`: one call, raw current failure, no structured diagnosis, no history.
- `diagnosis_single_turn`: one call with deterministic structured diagnosis.
- `feedback_loop`: at most three calls; every call receives the latest stage failure and prior verification evidence.
- `episodic_memory`: identical to feedback loop plus retrieved verified experiences.

- [ ] **Step 4: Verify rollback and call budgets**

Run:

```powershell
python -m pytest tests/test_ablation.py tests/test_real_benchmark.py -q
```

Expected: all tests pass; existing real benchmark behavior remains unchanged.

- [ ] **Step 5: Commit**

```powershell
git add src/repropilot/ablation.py src/repropilot/real_benchmark.py tests/test_ablation.py tests/test_real_benchmark.py
git commit -m "feat: add progressive repair evaluation loop"
```

---

## Task 3: Freeze the three hard cases and validate their probes

**Files:**

- Create: `benchmark/real-ablation.yaml`
- Modify: `tests/test_ablation.py`
- Reuse: `benchmark/real-injections/*.patch`

- [ ] **Step 1: Add a failing frozen-manifest test**

The test must load `benchmark/real-ablation.yaml` and assert exact IDs, repository URLs, full 40-character commits, stage order, two stages per case, and expected allowed paths.

Expected case mapping:

```yaml
cases:
  - id: convmixer-progressive
    stages: [convmixer-missing-dependency, convmixer-incorrect-dataset-path]
  - id: resnet-progressive
    stages: [resnet-learning-rate-mismatch, resnet-top1-metric-mismatch]
  - id: lightning-progressive
    stages: [lightning-cuda-fallback, lightning-validation-shuffle]
```

- [ ] **Step 2: Confirm the missing-file failure**

Run:

```powershell
python -m pytest tests/test_ablation.py -q
```

Expected: failure naming the absent `benchmark/real-ablation.yaml`.

- [ ] **Step 3: Create the complete manifest**

Copy repository identities, licenses, root-cause text, injection paths, probe definitions, and allowed paths from `benchmark/real-projects-2026-09-03.yaml`. Do not shorten commit SHAs in the file. Add a top-level `schema_version: 1`.

- [ ] **Step 4: Validate real injection composition in temporary worktrees**

Run the repository acquisition and preparation tests. Each case must prove:

- both patches apply cleanly to the pinned commit;
- stage 1 fails before repair;
- after applying the known stage-1 reversal, stage 2 fails;
- after applying both known reversals, all probes pass;
- the final diff touches only the manifest's allowed paths.

Run:

```powershell
python -m pytest tests/test_ablation.py -q -m "not live"
```

Expected: exit `0`. Network-dependent acquisition tests must be explicitly marked `live`; deterministic patch/probe tests use cached fixtures or local temporary repositories.

- [ ] **Step 5: Commit**

```powershell
git add benchmark/real-ablation.yaml tests/test_ablation.py
git commit -m "test: freeze progressive repair cases"
```

---

## Task 4: Add JSON, Markdown, and HTML ablation reports

**Files:**

- Modify: `src/repropilot/ablation.py`
- Create: `scripts/run_ablation.py`
- Modify: `tests/test_ablation.py`

- [ ] **Step 1: Add failing serialization and rendering tests**

Use a fixed in-memory summary and assert:

- JSON contains schema version, git commit, manifest SHA-256, model, repetitions, raw case results, and unrounded counts;
- Markdown shows `7/9 (77.8%)`, never a bare percentage;
- deltas use `percentage points` / `个百分点`, not relative percent;
- HTML labels the metric as task success, not model accuracy;
- rerunning against an existing output directory fails without deleting it.

- [ ] **Step 2: Run focused tests and observe missing renderer failures**

```powershell
python -m pytest tests/test_ablation.py -q
```

- [ ] **Step 3: Implement deterministic renderers and CLI**

The runner interface is:

```powershell
python scripts/run_ablation.py `
  --manifest benchmark/real-ablation.yaml `
  --output artifacts/ablation/<timestamp> `
  --arms single_turn_raw,diagnosis_single_turn,feedback_loop,episodic_memory `
  --repetitions 3
```

Required outputs:

```text
ablation-results.json
ablation-summary.md
ablation-report.html
cases/<arm>/<repetition>/<case-id>/...
```

The script must print the output path and return nonzero if configuration is incomplete. It must not silently fall back to a mock model in a real run.

- [ ] **Step 4: Verify reports with a fake generator**

Add `--fixture-mode tests/fixtures/ablation-responses.json` for deterministic CI use. This mode must be visibly labeled `fixture_mode: true` in every output so it cannot be cited as real-model evidence.

Run:

```powershell
python scripts/run_ablation.py --manifest benchmark/real-ablation.yaml --output tmp/ablation-fixture --fixture-mode tests/fixtures/ablation-responses.json
python -m pytest tests/test_ablation.py -q
```

Expected: three report files exist and all tests pass. Remove only the explicitly created `tmp/ablation-fixture` after inspection.

- [ ] **Step 5: Commit**

```powershell
git add src/repropilot/ablation.py scripts/run_ablation.py tests/test_ablation.py tests/fixtures/ablation-responses.json
git commit -m "feat: add ablation evidence reports"
```

---

## Task 5: Add verified episodic repair memory with leakage guards

**Files:**

- Create: `src/repropilot/repair_memory.py`
- Create: `tests/test_repair_memory.py`

- [ ] **Step 1: Add failing persistence and retrieval tests**

Tests must prove:

- a verified experience round-trips through a temporary SQLite database;
- unverified and scope-violating attempts cannot be stored;
- retrieval filters by category;
- current `repository_url + commit_sha` is excluded;
- ranking prefers matching error-signature and stack-tag terms;
- ties are deterministic by `created_at` then `id`;
- no API-key-shaped string can be stored in text fields;
- `NullRepairMemory` returns an empty tuple and performs no writes.

- [ ] **Step 2: Confirm expected import failure**

```powershell
python -m pytest tests/test_repair_memory.py -q
```

Expected: `ModuleNotFoundError` for `repropilot.repair_memory`.

- [ ] **Step 3: Implement the standard-library store**

Define:

```python
class RepairMemory(Protocol):
    def retrieve(
        self,
        diagnosis: Diagnosis,
        *,
        repository_url: str,
        commit_sha: str,
        top_k: int = 2,
    ) -> tuple[RepairExperience, ...]: ...

    def record_verified(self, experience: RepairExperience) -> None: ...
```

Use `sqlite3` with parameterized statements and an explicit schema version table. Normalize tokens with lowercase alphanumeric splitting; rank by category match, error-signature token overlap, and stack-tag overlap. This is intentionally simple and inspectable.

Reject text matching common secret prefixes such as `sk-`, `gho_`, `github_pat_`, and `Bearer `. The verified recording API must require `probe_passed=True` and `scope_compliant=True` in its input record instead of relying on the caller's name.

- [ ] **Step 4: Run focused checks**

```powershell
python -m pytest tests/test_repair_memory.py -q
python -m ruff check src/repropilot/repair_memory.py tests/test_repair_memory.py
python -m mypy src/repropilot/repair_memory.py
```

Expected: all commands exit `0`.

- [ ] **Step 5: Commit**

```powershell
git add src/repropilot/repair_memory.py tests/test_repair_memory.py
git commit -m "feat: store verified repair experiences"
```

---

## Task 6: Integrate memory into the ablation arm and enforce leave-one-repository-out

**Files:**

- Modify: `src/repropilot/ablation.py`
- Modify: `scripts/run_ablation.py`
- Modify: `tests/test_ablation.py`
- Modify: `tests/test_repair_memory.py`

- [ ] **Step 1: Add failing memory-arm tests**

Test a three-repository experiment where the current repository's experiences would be the highest lexical match. Assert they are excluded, at most two other-repository experiences enter the prompt, and only successful case results are recorded after all probes pass.

Also verify experiment ordering:

1. prepare the memory training pool from other repositories;
2. freeze the store for the current held-out repository;
3. evaluate the held-out case;
4. rotate the held-out repository.

- [ ] **Step 2: Run focused tests and confirm missing integration failures**

```powershell
python -m pytest tests/test_ablation.py tests/test_repair_memory.py -q
```

- [ ] **Step 3: Add bounded context rendering**

Add a pure helper:

```python
def build_repair_context(
    *,
    current_failure: str,
    diagnosis: Diagnosis | None,
    allowed_paths: tuple[str, ...],
    previous_patch: str | None,
    verification_failure: str | None,
    rollback_complete: bool,
    experiences: tuple[RepairExperience, ...],
) -> str: ...
```

Use explicit section headers. Bound current failure to 12,000 characters, previous patch to 12,000, verification failure to 8,000, and each experience to 4,000. Truncation must keep the beginning and end with a visible marker.

- [ ] **Step 4: Verify isolation and budgets**

```powershell
python -m pytest tests/test_ablation.py tests/test_repair_memory.py -q
```

Expected: memory-arm prompts contain no same-repository experience, model calls remain at most three per case, and other arms receive no memory content.

- [ ] **Step 5: Commit**

```powershell
git add src/repropilot/ablation.py src/repropilot/repair_memory.py scripts/run_ablation.py tests/test_ablation.py tests/test_repair_memory.py
git commit -m "feat: evaluate cross-repository repair memory"
```

---

## Task 7: Add optional production memory without changing default behavior

**Files:**

- Modify: `src/repropilot/services.py`
- Modify: `src/repropilot/cli.py`
- Modify: `.env.example`
- Create: `tests/test_services.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Add failing compatibility tests**

Tests must prove:

- without `REPROPILOT_MEMORY_DB`, services use `NullRepairMemory` and existing patch prompts remain byte-for-byte unchanged;
- with a temporary database path, verified experiences are retrieved and appended under `RETRIEVED_VERIFIED_EXPERIENCES`;
- a failed target test is never recorded as verified memory;
- a passed probe with an out-of-scope diff is never recorded;
- a fully verified repair is recorded once;
- local/non-Git inputs receive a stable source identity and do not crash.

- [ ] **Step 2: Run tests and confirm the configuration is unsupported**

```powershell
python -m pytest tests/test_services.py tests/test_cli.py -q
```

- [ ] **Step 3: Inject the memory dependency surgically**

Extend `DefaultRunServices.__init__` with `repair_memory: RepairMemory | None = None` and replace `None` with `NullRepairMemory`. In `_default_services()`, instantiate `SQLiteRepairMemory` only when `REPROPILOT_MEMORY_DB` is set. Do not add a new required CLI argument.

In `propose_patch`, keep the existing prompt construction unchanged when no memories are returned. When memories exist, append the bounded section produced by `build_repair_context`. Record an experience only at the point where target tests and semantic probes have both passed and scope validation is already complete.

Add to `.env.example`:

```text
# Optional local SQLite file. Leave unset to disable cross-run repair memory.
REPROPILOT_MEMORY_DB=
```

- [ ] **Step 4: Run regression tests**

```powershell
python -m pytest tests/test_services.py tests/test_cli.py tests/test_orchestrator.py -q
python -m ruff check src/repropilot/services.py src/repropilot/cli.py tests/test_services.py tests/test_cli.py
python -m mypy src/repropilot
```

Expected: all existing no-memory tests still pass and the new opt-in tests pass.

- [ ] **Step 5: Commit**

```powershell
git add src/repropilot/services.py src/repropilot/cli.py .env.example tests/test_services.py tests/test_cli.py
git commit -m "feat: add opt-in repair memory to run services"
```

---

## Task 8: Run deterministic verification, document usage, and protect claims

**Files:**

- Modify: `README.md`
- Create: `docs/product/agent-ablation-method.md`
- Modify: `docs/product/agent-testing-resume-entry.md`
- Modify: `tests/test_product_docs.py`
- Modify: `.gitignore`

- [ ] **Step 1: Add failing documentation guard tests**

Tests must assert that:

- README links to the methodology and shows both fixture and real commands;
- fixture output is explicitly described as non-evidence;
- résumé text contains placeholders generated from results, not a hard-coded `12.9` claim;
- `.gitignore` excludes local memory databases and timestamped ablation artifacts while allowing committed small fixtures.

- [ ] **Step 2: Run the doc test and observe the missing content**

```powershell
python -m pytest tests/test_product_docs.py -q
```

- [ ] **Step 3: Write the operating guide**

Document:

1. why the original 6/6 suite has a ceiling effect;
2. the four experimental arms;
3. progressive-fault semantics;
4. leave-one-repository-out memory evaluation;
5. fixture run versus real run;
6. how to inspect raw evidence;
7. how résumé bullets are generated only after real results exist.

Do not include a live API key or an example that resembles one.

- [ ] **Step 4: Execute the deterministic end-to-end run**

```powershell
python scripts/run_ablation.py --manifest benchmark/real-ablation.yaml --output tmp/ablation-final-fixture --fixture-mode tests/fixtures/ablation-responses.json
python -m pytest -q
python -m ruff check .
python -m mypy src/repropilot
git diff --check
```

Expected: all commands exit `0`; reports label themselves as fixture data; `git status --short` shows only intended source, test, manifest, and documentation changes.

- [ ] **Step 5: Inspect the evidence manually**

Open `tmp/ablation-final-fixture/ablation-report.html` and verify:

- the four arms are distinguishable;
- every percentage includes a numerator and denominator;
- deltas are labeled as percentage points;
- model accuracy is never confused with task success;
- fixture mode is visible above the fold;
- failed stages link to their diff, test output, and probe evidence.

- [ ] **Step 6: Commit**

```powershell
git add README.md docs/product/agent-ablation-method.md docs/product/agent-testing-resume-entry.md tests/test_product_docs.py .gitignore
git commit -m "docs: explain agent ablation methodology"
```

---

## Task 9: Run the real-model experiment and publish only observed results

**Prerequisite:** A newly created API key is configured locally. The previously exposed key is not permitted.

**Files:**

- Generate locally: `artifacts/ablation/<timestamp>/...`
- Modify after review: `README.md`
- Modify after review: `docs/product/agent-testing-resume-entry.md`
- Modify after review: `docs/product/portfolio-attachment.md`

- [ ] **Step 1: Capture the exact experiment identity**

Record current Git commit, dirty-state flag, manifest SHA-256, model, provider base URL without credentials, repetition count, Python version, Docker version, and start time. Refuse to run if the source tree contains uncommitted code changes that affect `src/`, `scripts/`, `benchmark/`, or `tests/`.

- [ ] **Step 2: Run one paid smoke repetition**

```powershell
python scripts/run_ablation.py --manifest benchmark/real-ablation.yaml --output artifacts/ablation/<timestamp>-smoke --arms single_turn_raw,diagnosis_single_turn,feedback_loop,episodic_memory --repetitions 1
```

Expected: 12 case-arm executions finish, raw evidence is present, and no case exceeds its model-call budget. Stop and fix evaluator defects before spending on three repetitions.

- [ ] **Step 3: Run the frozen three-repetition experiment**

```powershell
python scripts/run_ablation.py --manifest benchmark/real-ablation.yaml --output artifacts/ablation/<timestamp>-final --arms single_turn_raw,diagnosis_single_turn,feedback_loop,episodic_memory --repetitions 3
```

Expected: 36 case-arm executions with complete raw evidence. Do not rerun individual failed cases selectively; any full rerun receives a new output directory and is reported separately.

- [ ] **Step 4: Verify all published numbers against raw JSON**

Add a test that loads the chosen final `ablation-results.json` and regenerates the summary. Confirm counts, denominators, percentage-point deltas, calls, tokens, wall time, and unrelated-change rates match the Markdown and HTML reports.

- [ ] **Step 5: Update portfolio wording with observed results**

Use this template and replace variables only through the report generator:

```text
构建单轮生成、结构化诊断、反馈循环与跨任务记忆四组消融评测；
在 3 个冻结真实仓库的 {runs} 次多阶段修复实验中，反馈循环将完整任务成功率
从 {baseline_successes}/{baseline_total} 提升至 {loop_successes}/{loop_total}
（+{delta_pp:.1f} 个百分点），无关修改行比例为 {unrelated_rate:.1f}%。
```

If the observed delta is zero or negative, report that fact and retain the cost/quality analysis. Do not substitute the desired `12.9` value.

- [ ] **Step 6: Final verification and commit**

```powershell
python -m pytest -q
python -m ruff check .
python -m mypy src/repropilot
git diff --check
git status --short
```

Review the diff to ensure no key, local database, downloaded repository, or raw secret-bearing log is staged. Then commit only the selected small report summary and updated product documents:

```powershell
git add README.md docs/product/agent-testing-resume-entry.md docs/product/portfolio-attachment.md
git commit -m "docs: publish measured agent ablation results"
```

---

## Final Review Checklist

- [ ] The original 3-repository/6-case benchmark still passes unchanged.
- [ ] Every new public class and function has one consistent name across source, tests, scripts, and docs.
- [ ] Four arms differ only in their defined context and call budget.
- [ ] Progressive stages are exposed in deterministic order.
- [ ] Failed patches are rolled back before another attempt.
- [ ] Same-repository memories cannot enter held-out evaluation prompts.
- [ ] Only verified, scope-compliant repairs enter SQLite memory.
- [ ] All percentages include counts; all improvements are percentage-point differences.
- [ ] Fixture-mode outputs cannot be mistaken for real evidence.
- [ ] No performance claim exists without a reproducible JSON source.
- [ ] `pytest`, Ruff, mypy, and `git diff --check` pass.
- [ ] Git status contains no key, local database, benchmark clone, or unintended artifact.
