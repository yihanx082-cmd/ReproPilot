# ReproPilot Real-Project Agent Baseline

Recorded on 2026-09-03 with the OpenAI-compatible `deepseek-v4-pro` model.

> This benchmark measures bounded fault localization and repair on pinned real
> PyTorch repositories. Passing a semantic probe does not show that a full
> training run reproduces a paper result.

## Method

The evaluator acquired three repositories at exact commits and created six
disposable workspaces. Each workspace received one hidden fault. The Agent saw
the failure message and allowed source file, but not the injection patch or
expected repaired text. Every generated diff passed the local path, size, risk,
transaction, and post-fix probe checks.

The case definitions and pinned source identities are in
[`real-projects.yaml`](real-projects.yaml). The runner is
[`run_real_benchmark.py`](../scripts/run_real_benchmark.py).

## Aggregate result

| Metric | Result |
|---|---:|
| Repositories | 3 |
| Evaluated cases | 6 |
| Infrastructure failures | 0 |
| Error localization rate | 100% (6/6) |
| Repair success rate | 100% (6/6) |
| Post-fix probe pass rate | 100% (6/6) |
| Unrelated changed-line rate | 0% |
| Mean patch attempts | 1.0 |
| Model calls | 6 |
| Tool calls | 54 |
| Input / output tokens | 17,778 / 1,056 |
| Measured Agent wall time | 70.80 seconds |
| Model cost | Unknown; the provider response did not include price data |
| Safety invariants | Passed |

## Case evidence

| Case | Category | Attempts | Changed lines | Approval gate | Result |
|---|---|---:|---:|---|---|
| `convmixer-missing-dependency` | dependency | 1 | 1 | not required | passed |
| `convmixer-incorrect-dataset-path` | path | 1 | 2 | not required | passed |
| `resnet-learning-rate-mismatch` | configuration | 1 | 1 | not required | passed |
| `resnet-top1-metric-mismatch` | metric | 1 | 1 | required and honored | passed |
| `lightning-cuda-fallback` | CUDA/runtime | 1 | 1 | not required | passed |
| `lightning-validation-shuffle` | data | 1 | 1 | required and honored | passed |

Raw JSON, per-case diffs, and the HTML report were retained outside Git to
avoid publishing generated third-party workspaces. The SHA-256 digest of the
aggregate `benchmark-results.json` is
`f6eded36a763d7592ed0a51b81e87e3be731d98b25bfe98f7ac722d98dbe48eb`.

## Reproduce the benchmark

Set the three API environment variables described in the project README, then
run:

```powershell
python scripts/run_real_benchmark.py `
  --cases benchmark/real-projects.yaml `
  --output artifacts/real-agent-benchmark `
  --source-cache artifacts/pinned-sources `
  --approve-high-risk
```

`--approve-high-risk` is suitable here only because the runner works on
disposable benchmark copies and still records every approval decision. Real
reproduction runs should pause for user review of metric, data, model, and
weight changes.
