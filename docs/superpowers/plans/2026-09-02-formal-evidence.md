# Formal Evidence and Multi-Seed Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add evidence-backed three-seed formal experiments and honest paper-comparable scoring to the existing ReproPilot workflow.

**Architecture:** An optional formal experiment request extends the current run contract. The orchestrator executes it only after the smoke/repair loop succeeds; services persist one command artifact per seed, aggregate metrics, and build score dimensions from those artifacts. Existing smoke-only requests follow their current path unchanged.

**Tech Stack:** Python 3.11+, Pydantic 2, Typer, Docker, Jinja2, Pytest, Ruff, Mypy.

**Spec:** `docs/superpowers/specs/2026-09-02-formal-evidence-design.md`

## Global Constraints

- Existing YAML files and callers remain valid because `formal_experiment` is optional.
- Formal experiments use 3–10 unique integer seeds and an argv template containing `{seed}`.
- Paper comparison requires non-empty `scope_evidence`; reduced scope never earns result-proximity points.
- Every earned score dimension cites persisted artifacts.
- Formal failures terminate with evidence and do not enter the bounded smoke repair loop.
- No production behavior is added before a failing test demonstrates it.

---

### Task 1: Formal experiment request contract

**Files:**
- Modify: `src/repropilot/domain.py`
- Modify: `tests/test_artifacts.py`

**Interfaces:**
- Produces: `FormalExperimentRequest(command: list[str], seeds: list[int], comparison_scope: Literal["paper", "reduced"], scope_evidence: list[str])`.
- Produces: optional `RunRequest.formal_experiment: FormalExperimentRequest | None`.

- [ ] **Step 1: Write failing validation tests**

Add tests that accept three unique seeds with `{seed}`, reject two seeds, reject duplicates, reject a command without `{seed}`, and reject `comparison_scope: paper` without citations.

- [ ] **Step 2: Verify RED**

Run: `.venv\Scripts\python.exe -m pytest tests/test_artifacts.py -q`

Expected: failure because `formal_experiment` is not validated.

- [ ] **Step 3: Implement the minimal Pydantic model**

Use a model-level validator:

```python
class FormalExperimentRequest(BaseModel):
    command: list[str] = Field(min_length=1)
    seeds: list[int] = Field(min_length=3, max_length=10)
    comparison_scope: Literal["paper", "reduced"] = "reduced"
    scope_evidence: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_evidence_contract(self) -> FormalExperimentRequest:
        if len(set(self.seeds)) != len(self.seeds):
            raise ValueError("formal experiment seeds must be unique")
        if not any("{seed}" in token for token in self.command):
            raise ValueError("formal experiment command must contain {seed}")
        if self.comparison_scope == "paper" and not self.scope_evidence:
            raise ValueError("paper comparison scope requires evidence citations")
        return self
```

- [ ] **Step 4: Verify GREEN and commit**

Run: `.venv\Scripts\python.exe -m pytest tests/test_artifacts.py -q`

Commit: `feat: define formal experiment request contract`

### Task 2: Formal experiment state and execution

**Files:**
- Modify: `src/repropilot/domain.py`
- Modify: `src/repropilot/orchestrator.py`
- Modify: `src/repropilot/services.py`
- Modify: `tests/test_orchestrator.py`
- Modify: `tests/test_end_to_end.py`

**Interfaces:**
- Produces: `RunState.FORMAL_EXPERIMENT`.
- Produces: `RunServices.formal_experiment(request, store, timeout) -> list[CommandResult]`.
- Produces artifacts: `formal-seed-<seed>.json` and `experiment_manifest.json`.

- [ ] **Step 1: Write failing orchestrator tests**

Cover the state order `SMOKE_RUN → FORMAL_EXPERIMENT → COMPARE`, absence of the state for legacy requests, and terminal failure/timeout when one seed fails.

- [ ] **Step 2: Verify RED**

Run: `.venv\Scripts\python.exe -m pytest tests/test_orchestrator.py -q`

Expected: failure because the state and service method do not exist.

- [ ] **Step 3: Add the state and orchestration**

After successful smoke execution, call the formal service only when configured. Reject any nonzero/timed-out result before comparison and preserve the existing path otherwise.

- [ ] **Step 4: Write a failing service-level end-to-end test**

Use the local fixture sandbox to return metric-bearing output for seeds 11, 22 and 33. Assert exact argv substitution, three JSON artifacts and a manifest.

- [ ] **Step 5: Verify RED**

Run: `.venv\Scripts\python.exe -m pytest tests/test_end_to_end.py -q`

- [ ] **Step 6: Implement sequential seed execution**

Render each argv token with `token.replace("{seed}", str(seed))`, run it in the existing sandbox, persist the command result through `_record_command`, then write a manifest containing configuration and result summaries.

- [ ] **Step 7: Verify GREEN and commit**

Run: `.venv\Scripts\python.exe -m pytest tests/test_orchestrator.py tests/test_end_to_end.py -q`

Commit: `feat: execute formal experiments across explicit seeds`

### Task 3: Execution facts for paper–code alignment

**Files:**
- Modify: `src/repropilot/repository.py`
- Modify: `src/repropilot/services.py`
- Modify: `tests/test_repository.py`
- Modify: `tests/test_alignment.py`

**Interfaces:**
- Produces: `execution_request_facts(request: RunRequest) -> list[RepoFact]`.
- Consumes: `RunRequest.dataset.name`, smoke argv and formal argv.

- [ ] **Step 1: Write failing fact extraction tests**

Assert canonical facts for dataset name, architecture, epochs, batch size, learning rate, momentum, weight decay and seed, with `run-request` as the source path and stable one-based argv positions.

- [ ] **Step 2: Verify RED**

Run: `.venv\Scripts\python.exe -m pytest tests/test_repository.py -q`

- [ ] **Step 3: Implement exact flag mapping**

Parse only explicit two-token flags; coerce integer/float values; do not infer aliases beyond the declared mapping. Append these facts to scanner facts before `align_claims` and persist the combined list.

- [ ] **Step 4: Verify GREEN and commit**

Run: `.venv\Scripts\python.exe -m pytest tests/test_repository.py tests/test_alignment.py -q`

Commit: `feat: align paper claims with executed configuration`

### Task 4: Focused recovery for missing paper claims

**Files:**
- Modify: `src/repropilot/paper.py`
- Modify: `tests/test_llm_compatibility.py`
- Modify: `tests/test_paper.py`

**Interfaces:**
- Keeps: `OpenAICompatiblePaperLLM.extract(pages) -> PaperExtraction`.
- Adds internal second completion only when the first validated `PaperSpec.claims` list is empty.

- [ ] **Step 1: Write a failing two-response compatibility test**

The first DeepSeek-style JSON response contains results but no claims; the second contains evidence-backed claims and no results. Assert merged claims, original results, unresolved-field de-duplication and summed token usage.

- [ ] **Step 2: Verify RED**

Run: `.venv\Scripts\python.exe -m pytest tests/test_llm_compatibility.py -q`

- [ ] **Step 3: Implement the focused claim pass**

Issue a claims-only prompt, validate it as `PaperSpec`, merge only claims, preserve first-pass results, and combine model usage. Exact page/quote validation remains in `extract_paper_spec`.

- [ ] **Step 4: Verify GREEN and commit**

Run: `.venv\Scripts\python.exe -m pytest tests/test_llm_compatibility.py tests/test_paper.py -q`

Commit: `feat: recover evidence-backed paper claims`

### Task 5: Multi-seed aggregation and evidence scoring

**Files:**
- Modify: `src/repropilot/services.py`
- Modify: `src/repropilot/scoring.py`
- Modify: `tests/test_end_to_end.py`
- Modify: `tests/test_scoring.py`

**Interfaces:**
- Consumes: successful `formal-seed-*.json`, their logs and `experiment_manifest.json`.
- Produces: aggregated `MetricComparison.run_values`, seed evidence and thresholded result-proximity evidence.

- [ ] **Step 1: Write failing aggregation tests**

Assert that three logs produce three run values, the hand-calculated mean/std/delta, and all three log artifact IDs. Assert smoke fallback for legacy runs.

- [ ] **Step 2: Write failing score threshold tests**

For paper scope, assert verified at absolute delta ≤1.0, partial at ≤5.0 and failed above 5.0. Assert reduced scope remains unknown. Assert seed evidence requires three unique successful seed artifacts.

- [ ] **Step 3: Verify RED**

Run: `.venv\Scripts\python.exe -m pytest tests/test_end_to_end.py tests/test_scoring.py -q`

- [ ] **Step 4: Implement aggregation and dimension builders**

Prefer formal results when present. Construct all dimension statuses in `_build_evidence_bundle` from persisted manifest/results/findings and let `score_reproduction` consume them without target-number exceptions.

- [ ] **Step 5: Verify GREEN and commit**

Run: `.venv\Scripts\python.exe -m pytest tests/test_end_to_end.py tests/test_scoring.py -q`

Commit: `feat: score aggregated formal experiment evidence`

### Task 6: Report and user-facing configuration

**Files:**
- Modify: `src/repropilot/templates/report.html.j2`
- Modify: `tests/test_reporting.py`
- Modify: `examples/cifar10-smoke.yaml`
- Create: `examples/cifar10-formal.yaml`
- Modify: `README.md`
- Modify: `docs/architecture.md`

**Interfaces:**
- Consumes: formal experiment fields already present in `EvidenceBundle` and metric comparisons.
- Produces: visible scope citations, seed commands/results and mean ± standard deviation.

- [ ] **Step 1: Write a failing report behavior test**

Render a bundle with three formal runs and assert the semantic headings, seed values, scope citation, individual metric values and mean ± standard deviation appear in HTML.

- [ ] **Step 2: Verify RED**

Run: `.venv\Scripts\python.exe -m pytest tests/test_reporting.py -q`

- [ ] **Step 3: Implement the smallest template/domain additions**

Add formal experiment evidence to the bundle only if the report cannot read it from existing fields. Render no empty section for legacy runs. Add one formal YAML example and document why paper scope requires citations.

- [ ] **Step 4: Verify GREEN and commit**

Run: `.venv\Scripts\python.exe -m pytest tests/test_reporting.py tests/test_cli.py -q`

Commit: `docs: expose formal experiment evidence`

### Task 7: Full verification and real ResNet/CIFAR-10 run

**Files:**
- Modify only if required by a failing regression test or truthful demo configuration.
- Generate outside Git: `<external-demo-root>\resnet-cifar10\runs\<run-id>\*`.

**Interfaces:**
- Consumes: the real paper, repository, full CIFAR-10 data and repaired run command.
- Produces: three formal seed artifacts, aggregated comparison, score and `report.html`.

- [ ] **Step 1: Run complete local quality gates**

```powershell
$env:REPROPILOT_DOCKER_TESTS='1'
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe -m mypy src
```

- [ ] **Step 2: Execute the real formal configuration**

Run the CLI with seeds 11, 22 and 33 and paper scope citations. Do not place the API key in a file, command argument, log or Git.

- [ ] **Step 3: Verify evidence rather than only exit status**

Assert run status is `SUCCEEDED`, all three seed artifacts have exit code 0 and distinct rendered seed argv, metric comparisons contain three values, report exists, and every earned score dimension cites an artifact.

- [ ] **Step 4: Update the demo evidence summary and rerun quality gates**

Record the actual score, mean ± standard deviation, delta, wall time and unresolved risks. Do not claim full paper reproduction if the report remains partial.

- [ ] **Step 5: Commit and push**

Commit: `feat: add evidence-backed formal reproduction runs`

Push `codex/phase-2-evidence` and open a draft PR against `main`; do not merge without explicit user approval.
