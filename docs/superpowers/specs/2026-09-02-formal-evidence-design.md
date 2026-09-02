# Formal Evidence and Multi-Seed Design

## Goal

Extend the existing ReproPilot run after its repaired smoke test so it can execute a declared paper-comparable command for at least three explicit random seeds, aggregate the observed metrics, and award reproducibility points only from persisted evidence.

## Scope

This phase changes the existing state machine rather than replacing it. Paper ingestion, repository audit, Docker build, smoke execution, diagnosis, patching, approval, and rollback keep their current behavior. A new formal experiment is optional, so every existing YAML file and API caller remains valid.

## Request contract

`RunRequest` gains an optional `formal_experiment` object:

- `command`: an argv template containing the exact token `{seed}` once or more.
- `seeds`: 3–10 unique integers.
- `comparison_scope`: `paper` or `reduced`.
- `scope_evidence`: non-empty artifact citations when the scope is `paper`.

`comparison_scope: paper` is an auditable declaration, not hidden inference. The generated report must show the declaration and its citations. `reduced` remains the default-safe interpretation and cannot receive result-proximity points.

## State and execution flow

After a successful smoke run, the orchestrator enters `FORMAL_EXPERIMENT` when the optional configuration exists. The service substitutes each seed into argv, executes seeds sequentially in the already-built sandbox and repaired run worktree, and writes one `formal-seed-<seed>.json` command result plus its stdout/stderr logs. It also writes `experiment_manifest.json` containing the declared scope, citations, rendered commands, exit status, duration, and image evidence.

Any failed or timed-out seed stops the run with a terminal report. Successful formal runs continue through the existing `COMPARE → SCORE → REPORT` states. Runs without a formal experiment retain the old path.

## Paper–code configuration evidence

Repository auditing also records execution-request facts from the dataset name and common argv flags (`--arch`, `--epochs`, `--batch-size`, `--lr`, `--learning-rate`, `--momentum`, `--weight-decay`, and `--seed`). These facts use the same canonical fields as paper claims and are persisted in `repo_facts.json`, allowing the existing deterministic aligner to compare the command actually executed rather than only repository defaults.

The paper extractor receives a focused second pass only when the first response yields no claims. That pass requests claims only, never duplicate result tables. Its output still passes the existing exact page/quote validator; unsupported claims remain unresolved.

## Metric aggregation and scoring

Metric comparison prefers successful formal-seed logs and falls back to the successful smoke log for backward compatibility. Each comparison stores all seed values, their mean, population standard deviation, delta from the paper, and every source log.

Evidence rules are deterministic:

- `random_seeds` is verified only when at least three unique configured seeds all have successful command artifacts.
- `result_proximity` is unknown for reduced scope or missing comparisons; verified when every comparable metric is within 1.0 percentage point of the paper; partial within 5.0; failed otherwise.
- `data` remains partial unless dataset identity has a matching paper–execution alignment finding.
- `configuration` uses existing alignment findings and never receives points when none exist.
- A paper-scoped formal experiment clears the smoke-only reduction flag, while its declaration and citations remain visible as evidence and in unresolved risks.

The score is a consequence of these artifacts. No special case targets the number 70.

## Reporting

The single-file HTML report adds a Formal Experiment section with seed, command, exit status and duration. It shows comparison scope and scope evidence, and the metric table displays mean ± standard deviation plus individual values.

## Error handling and compatibility

Invalid seed templates, duplicate seeds, too few seeds, or paper scope without citations fail configuration validation before run artifacts are created. Formal seed failures do not enter the repair loop: the repair loop is deliberately bounded to the smoke command, while formal failures produce evidence and a clear terminal reason.

Existing configs, reports and tests remain valid because `formal_experiment` is optional and old artifacts are still readable.

## Verification

- Unit tests cover request validation, seed substitution, aggregation and score thresholds.
- Orchestrator tests cover the optional formal state, failure and timeout behavior, and legacy flow.
- An end-to-end fixture verifies three seed artifacts and an HTML report.
- The full suite, Ruff, Mypy and Docker integration tests must pass.
- The real ResNet/CIFAR-10 demo must run three seeds, preserve every artifact, and produce a score derived from the documented rules.
