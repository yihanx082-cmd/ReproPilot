# ResNet-20 / CIFAR-10 Formal Demo Result

## Outcome

ReproPilot completed a paper-scoped, three-seed evaluation on the repaired ResNet/CIFAR-10 repository and produced a `70/100` credibility score with the label `PARTIAL`.

| Item | Evidence-backed value |
|---|---|
| Run status | `SUCCEEDED` |
| Seeds | `11`, `22`, `33` |
| Paper error | `8.75%` |
| Observed errors | `8.27%`, `8.27%`, `8.27%` |
| Mean ± population std | `8.27 ± 0.00%` |
| Delta | `-0.48` percentage points |
| Credibility | `70/100 (PARTIAL)` |

The run generated `experiment_manifest.json`, one `formal-seed-<seed>.json` artifact per seed, four metric evidence citations, `repro_score.json`, `evidence_bundle.json`, and a self-contained `report.html`. Every score dimension that earned points cites at least one artifact.

## What this proves

- The repaired repository can be built and evaluated in the bounded Docker sandbox.
- A formal command template can render and execute three explicit seeds.
- Metrics are aggregated from three independent command logs rather than copied from one smoke run.
- The report can distinguish a comparable partial result from a reduced smoke run.
- The observed error is within the deterministic one-percentage-point proximity threshold.

## What this does not prove

This demo evaluates one published ResNet-20 checkpoint on the full CIFAR-10 test set. It does not train the model from scratch three times. Evaluation is deterministic for this checkpoint, so the three observed values have zero variance even though each process initializes Python, NumPy and PyTorch with a different seed.

The cached paper extraction used for this run contained result-table evidence but no configuration claims, leaving configuration consistency at `unknown` and earning `0/20` for that dimension. The new focused claim-recovery path is covered by automated compatibility tests, but a fresh model-backed extraction is still required to demonstrate it on this paper. For that reason the result is reported as `PARTIAL`, never as a complete paper reproduction.

## Diagnosed real-world failure

The first formal attempt passed the smoke evaluation but failed all formal commands because the legacy repository did not implement the assumed `--manualSeed` flag. The corrected configuration initializes `random`, NumPy and PyTorch in a Python entry wrapper before executing the unmodified `trainer.py`. The next run completed all three seeds successfully.
