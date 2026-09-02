# Real-Project Agent Benchmark Design

## Goal

Measure whether ReproPilot can localize and repair injected faults in pinned,
third-party PyTorch image-classification repositories without using the known
inverse patch as its repair policy.

## Scope

The first public benchmark uses three small repositories and six independent
single-fault cases. Every case starts from a fresh checkout of an exact 40-digit
commit. The evaluator knows the injection patch and expected invariant; the
repair agent receives only the failing probe output and the implicated source
file.

| Repository | License | Pinned commit | Cases |
|---|---|---|---|
| `locuslab/convmixer-cifar10` | MIT | `2d3d9b73d3caa6112ecdcea866f1d2805f37cc8e` | dependency, path |
| `akamaster/pytorch_resnet_cifar10` | BSD-2-Clause | `d5489e8995e81e91ce6b1d69dcc98ad579b0b153` | configuration, metric |
| `karasawatakumi/pytorch-image-classification` | MIT | `4dd18700e9c2eb1787e652326d188e8ecdbac2aa` | CUDA, data |

## Execution boundary

Repository acquisition happens outside the untrusted checkout and validates the
requested commit. A case workspace is disposable. A project-specific semantic
probe is run before injection, after injection, and after repair. The probe uses
Python AST/text inspection and does not import or execute the untrusted training
program, download datasets, or require a GPU.

The model does not see the injection patch or the expected repaired text. It sees
the failure log, diagnosis, and up to three allowed related files. Generated
patches still pass the existing path, diff, and risk policies.

## Outcome states

- `completed`: acquisition, injection, diagnosis, and repair evaluation ran.
- `acquisition_failed`: the pinned repository could not be obtained after bounded retries.
- `injection_failed`: the fault patch no longer applies or does not break its probe.
- `model_failed`: the model did not return a valid patch within the allowed attempts.

Infrastructure failures are reported but excluded from the repair-rate
denominator. This prevents a transient GitHub outage from being counted as an
agent reasoning failure.

## Evidence and metrics

Each case writes its pinned source identity, injection result, failure log,
diagnosis, proposed Git diff, approval decision, post-fix probe output, elapsed
time, tool calls, model calls, and token usage when the API provides it.

The summary reports acquisition success, category-and-file localization,
repair success, post-fix probe pass rate, unrelated changed-line rate, mean patch
attempts, tool/model calls, wall time, and token totals. Cost remains unknown
rather than invented when a compatible provider does not return price data.

## Non-claims

Passing semantic probes is evidence of bounded repair behavior, not evidence that
the repositories reproduce their papers or that full training succeeds. The
existing deterministic reference harness remains a plumbing upper bound and is
reported separately.
