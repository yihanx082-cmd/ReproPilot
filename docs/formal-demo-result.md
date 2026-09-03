# ResNet-20 / CIFAR-10 End-to-End Reproduction Result

## Outcome

ReproPilot completed a fresh, paper-scoped run from the original PDF and legacy repository through Docker repair, three-seed evaluation, metric comparison and HTML reporting. The final evidence-backed credibility score is `80/100` with the label `PARTIAL`.

| Item | Evidence-backed value |
|---|---|
| Run status | `SUCCEEDED` |
| Seeds | `11`, `22`, `33` |
| Paper error | `8.75%` |
| Observed errors | `8.27%`, `8.27%`, `8.27%` |
| Mean ± population std | `8.27 ± 0.00%` |
| Delta | `-0.48` percentage points |
| Credibility | `80/100 (PARTIAL)` |
| Run ID | `20260903T060938477022Z-2d4bfc37` |

The run generated `paper_spec.json`, repository-alignment evidence, two diagnoses and Git diffs, rollback and verification records, `experiment_manifest.json`, one `formal-seed-<seed>.json` artifact per seed, four metric evidence citations, `repro_score.json`, `evidence_bundle.json`, and a self-contained `report.html`. Every score dimension that earned points cites at least one artifact.

## What this proves

- A fresh model-backed extraction can focus on the requested CIFAR-10/ResNet-20 target and cite the paper's exact table row (`ResNet 20 0.27M 8.75`, page 7).
- The legacy repository can be built, minimally repaired and evaluated in the bounded Docker sandbox.
- A failed first patch is rolled back exactly before the next diagnosis and patch attempt.
- A formal command template can render and execute three explicit seeds.
- Metrics are aggregated from three independent command logs rather than copied from one smoke run.
- The report can distinguish a comparable partial result from a reduced smoke run.
- The observed error is within the deterministic one-percentage-point proximity threshold.

## What this does not prove

This demo evaluates one published ResNet-20 checkpoint on the full CIFAR-10 test set. It does not train the model from scratch three times. Evaluation is deterministic for this checkpoint, so the three observed values have zero variance even though each process initializes Python, NumPy and PyTorch with a different seed.

The score remains partial for two evidence reasons. Data consistency earns `10/20` because the full CIFAR-10 directory is available and mounted read-only, but the run does not prove the paper's original split provenance with a published checksum. Configuration consistency earns `10/20` because the PDF extraction and repository audit recover only part of the training recipe. The public checkpoint version and all original training-time choices are not fully established. For that reason the result is reported as `PARTIAL`, never as a complete paper reproduction.

## Diagnosed and repaired real-world failures

The original project assumes CUDA and calls `.cuda()` unconditionally, so its first Docker smoke command fails in the configured CPU environment. ReproPilot generated a low-risk, single-file patch that removed unconditional device transfers and loaded the checkpoint on CPU. Verification then revealed a second real incompatibility: the public pretrained checkpoint has no `epoch` field. The first patch was rolled back, a second complete 21-line patch added a safe epoch fallback together with the CPU changes, and the targeted verification passed before the smoke and formal commands continued.

The formal command wrapper initializes Python, NumPy and PyTorch with seeds `11`, `22` and `33` before executing the repository's `trainer.py`. Because this is deterministic checkpoint evaluation rather than training, the seeds produce the same value; retaining all three commands and logs still proves that the multi-run evidence path executed.

## Score breakdown

| Dimension | Earned | Reason |
|---|---:|---|
| Environment | `15/15` | Docker build evidence verified |
| Data | `10/20` | Dataset present, original split provenance incomplete |
| Configuration | `10/20` | Partial paper/code alignment evidence |
| Metrics | `15/15` | Paper and run error rates are comparable |
| Random seeds | `10/10` | Three explicit successful seed artifacts |
| Result proximity | `15/15` | Absolute difference is `0.48` percentage points |
| External dependencies | `5/5` | Required build dependencies were available |

The SHA-256 digest of the final `repro_score.json` is `8272288fb6c286c98a3948269b566a2aa2061d1afc93a449a1665c5188649a70`.
