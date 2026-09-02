# ReproPilot Reference Harness Baseline

Recorded on 2026-08-17 with six deterministic, single-fault fixtures.

> This is a reference harness baseline that reverses the known injected patch. It validates isolation, diagnosis categories, risk gates, metrics, and report generation. It is not evidence that an LLM repair policy generalizes to unseen repositories.

| Metric | Result |
|---|---:|
| Cases | 6 |
| Error localization rate | 100% |
| Repair success rate | 100% |
| Post-fix test pass rate | 100% |
| Unrelated changed-line rate | 0% |
| Mean patch attempts | 1.0 |
| Tool calls | 42 |
| Model calls | 0 |
| Model cost | $0.00 |
| Safety invariants | Passed |

Observed wall time was approximately 25 seconds on the development machine and is expected to vary by host.
