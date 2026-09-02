# Real-Project Agent Benchmark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a repeatable six-case benchmark over three pinned real PyTorch repositories and publish evidence-backed Agent repair metrics.

**Architecture:** Keep the existing deterministic fixture benchmark unchanged. Add a focused real-project module that loads a pinned manifest, obtains a disposable checkout, applies one hidden injection, runs a non-executing semantic probe, asks the existing patch generator for a minimal repair, verifies the repair, and writes JSON/Markdown evidence.

**Tech Stack:** Python 3.11+, Pydantic, PyYAML, Git CLI, OpenAI-compatible API, pytest, Ruff, Mypy.

**Spec:** `docs/superpowers/specs/2026-09-02-real-agent-benchmark-design.md`

## Global Constraints

- Never execute untrusted training code on the host.
- Pin every upstream repository to an exact 40-digit commit.
- Never expose API credentials in artifacts, logs, diffs, or Git history.
- Do not give the repair model the injection patch or expected repaired text.
- Preserve the deterministic reference benchmark and its published claims.

---

### Task 1: Manifest and acquisition contract

**Files:**
- Create: `benchmark/real-projects.yaml`
- Create: `src/repropilot/real_benchmark.py`
- Create: `tests/test_real_benchmark.py`

**Interfaces:**
- Produces: `RealBenchmarkCase`, `load_real_cases(path, root=None)`, and `acquire_repository(case, destination, retries=3)`.

- [ ] Write tests that reject floating refs, resolve injection paths, validate three unique repositories/six cases, and distinguish acquisition failure.
- [ ] Run `python -m pytest tests/test_real_benchmark.py -v` and confirm missing imports fail.
- [ ] Implement the minimum validated models and bounded Git acquisition.
- [ ] Run the same test file and confirm it passes.
- [ ] Commit with `feat: define pinned real benchmark cases`.

### Task 2: Semantic probe and injected-case lifecycle

**Files:**
- Create: `src/repropilot/benchmark_probe.py`
- Create: `benchmark/real-injections/*.patch`
- Modify: `src/repropilot/real_benchmark.py`
- Modify: `tests/test_real_benchmark.py`

**Interfaces:**
- Produces: `run_probe(case, workspace)` and `prepare_injected_case(case, workspace)`.

- [ ] Write tests proving each probe passes on its baseline source, fails after its injection, and emits category/file evidence.
- [ ] Run focused tests and confirm probe/injection behavior is absent.
- [ ] Implement AST/text probes and Git patch application without importing target code.
- [ ] Run focused tests and confirm red-to-green behavior.
- [ ] Commit with `feat: add hidden real-project fault probes`.

### Task 3: Model repair evaluation and evidence

**Files:**
- Modify: `src/repropilot/real_benchmark.py`
- Modify: `src/repropilot/services.py`
- Modify: `tests/test_real_benchmark.py`
- Modify: `tests/test_llm_compatibility.py`

**Interfaces:**
- Produces: `run_agent_case(case, workspace, patch_generator)` and model usage counters on `OpenAICompatiblePatchGenerator`.

- [ ] Write failing tests for category-and-file localization, patch transaction safety, post-fix probe verification, and model/token counters.
- [ ] Confirm tests fail for the missing lifecycle and counters.
- [ ] Implement one bounded proposal/apply/probe loop using existing diagnosis, risk, and diff policy.
- [ ] Confirm focused and existing patch-generator tests pass.
- [ ] Commit with `feat: evaluate model repairs on real projects`.

### Task 4: CLI and reports

**Files:**
- Create: `scripts/run_real_benchmark.py`
- Modify: `src/repropilot/real_benchmark.py`
- Modify: `tests/test_real_benchmark.py`

**Interfaces:**
- Produces: per-case JSON, `benchmark-results.json`, and `benchmark-summary.md`.

- [ ] Write failing tests for infrastructure-aware denominators and report content.
- [ ] Implement JSON/Markdown reporting and non-zero exit only for unsafe invariants or total infrastructure failure.
- [ ] Run script tests and focused benchmark tests.
- [ ] Commit with `feat: report real agent benchmark evidence`.

### Task 5: Real execution and public documentation

**Files:**
- Create: `benchmark/real-baseline-summary.md`
- Modify: `README.md`
- Modify: `docs/architecture.md`

**Interfaces:**
- Consumes: `scripts/run_real_benchmark.py` and the six-case manifest.
- Produces: an honest, dated benchmark result with links to machine-readable evidence.

- [ ] Run all six cases with the configured OpenAI-compatible model and retain raw artifacts outside Git.
- [ ] Copy only sanitized aggregate evidence into `benchmark/real-baseline-summary.md`.
- [ ] Document the distinction between reference-harness and real-Agent results.
- [ ] Run `ruff check src tests scripts`, `mypy src`, and `pytest -q`.
- [ ] Review `git diff --check`, inspect the full diff, commit, push, create PR, wait for CI, and merge after checks pass.
