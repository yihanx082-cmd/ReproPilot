# ReproPilot Product Case Foundation Design

## 1. Purpose

This phase turns the existing engineering MVP into an evidence-backed AI product manager case study without weakening its technical credibility. The result must explain the user problem, show how the agent remains understandable and controllable, measure user value separately from engineering performance, and provide a clickable product prototype grounded in a real ReproPilot run.

The target audience is graduate students, researchers, and ML engineers who have a paper, a repository, and a dataset but cannot quickly determine whether the repository can run or whether its output genuinely reproduces the paper.

## 2. Current Foundation

The existing CLI remains the source of truth. It already supports PDF evidence extraction, paper-code alignment, Docker execution, diagnosis, bounded patching, high-risk approval, multi-seed experiments, metric comparison, deterministic credibility scoring, and an HTML evidence report.

This phase does not replace that engine. It adds a product-facing layer over its artifacts and creates the research and measurement evidence needed for a portfolio case.

## 3. Product Positioning

ReproPilot is not a paper chatbot and does not promise that every paper can be reproduced. Its promise is narrower and verifiable:

> ReproPilot turns an opaque paper-reproduction attempt into a traceable execution process and produces an evidence-backed judgment about how trustworthy the reproduction is.

The primary value is reducing uncertainty and manual debugging effort while preserving user control over semantic or high-risk changes.

## 4. Scope

### Included

- An asynchronous two-round interview kit for five real participants.
- A structured, anonymous research-record format using participant IDs P01-P05.
- A competitor-analysis framework based on primary-source evidence.
- A concise PRD with problem statement, user journey, requirements, non-goals, risks, and acceptance criteria.
- A clickable desktop Web prototype using the selected execution-timeline direction.
- Realistic demo data derived from the completed ResNet-20/CIFAR-10 run, clearly labeled as demonstration data.
- A usability-test script and observation sheet.
- A manual-versus-ReproPilot comparison protocol.
- A product-metrics dictionary separating product outcomes from engineering-agent metrics.
- A portfolio case-study outline and demo-video script.

### Excluded

- Multi-user collaboration, billing, cloud GPU scheduling, Kubernetes, and a general-purpose chatbot.
- Fabricated interview responses, fabricated satisfaction scores, or statistically representative claims from five participants.
- A production backend that duplicates the Python orchestration engine.
- Automatic approval of data, metric, model, or pretrained-weight changes.
- Treating a credibility score as model accuracy or as proof of scientific correctness.
- Embedding SQL training exercises into the ReproPilot product. SQL remains a separate learning track so the portfolio repository stays focused.

## 5. End-to-End User Journey

1. **Create a task.** The user supplies the paper PDF, GitHub or local repository, dataset location, environment, and initial command. Each technical field includes plain-language help and a safe default where possible.
2. **Review the scope.** ReproPilot shows extracted paper claims, detected repository configuration, unresolved fields, experiment scope, and estimated execution constraints before any run starts.
3. **Follow the execution timeline.** The user sees each state, its status, and the associated evidence while the existing agent performs audit, build, smoke run, repair, formal experiment, comparison, and scoring.
4. **Resolve exceptional decisions.** Low-risk repairs continue through the bounded repair loop. High-risk semantic changes pause the run and show the cause, exact diff, expected impact, targeted test, and approve or reject actions.
5. **Interpret the result.** The final view explains the overall credibility score, dimension-level evidence, metric differences, unresolved risks, and the distinction among `REPRODUCED`, `PARTIAL`, `PROVISIONAL_SMOKE_RUN`, and `NOT_REPRODUCED`.

## 6. Interface Architecture

### 6.1 Task Creation

The screen contains a guided form for paper, repository, dataset, Python/device environment, smoke command, and optional formal experiment. Validation errors appear next to the relevant field and explain how to fix the input. A validation failure prevents execution.

### 6.2 Scope Review

Before starting, the user sees:

- paper claims with page evidence;
- repository facts with source file and line;
- matched, mismatched, and unknown fields;
- unresolved assumptions;
- selected comparison scope;
- time and resource limits.

The primary action explicitly starts the run. The screen never implies that a successful configuration check is a successful reproduction.

### 6.3 Execution Timeline

The selected layout is a three-region desktop workspace:

- **Left:** ordered stages and their state: pending, running, verified, warning, failed, or waiting for approval;
- **Center:** the selected event, human-readable explanation, and current outcome;
- **Right:** evidence such as command argv, logs, source citations, Git diff, test result, image digest, and artifact identifiers.

The timeline is the main product screen because it translates the existing state machine into a user-comprehensible workflow. It must answer three questions at a glance: what is happening, why it is happening, and what evidence supports it.

### 6.4 Approval State

Approval is a state inside the timeline rather than a separate product area. The approval panel contains:

- diagnosed root cause and evidence;
- why the patch is classified as high risk;
- exact Git diff and affected files;
- predicted semantic impact;
- targeted verification command;
- approve and reject actions.

Approval remains bound to the patch SHA-256. If the diff changes, the earlier decision is invalid.

### 6.5 Credibility Report

The report view contains the total score, result label, seven dimension scores, paper-versus-run metrics, seed-level results, repaired issues, unresolved risks, and links to evidence. Copy must state that `80/100 PARTIAL` describes evidence completeness and consistency, not an 80% accurate model.

## 7. Data and Control Flow

The Web layer reads artifacts produced by the existing engine, including `run.json`, `events.jsonl`, paper specifications, alignment findings, command results, patch and approval records, formal experiment evidence, and score data. It does not recalculate scientific conclusions with separate UI-only rules.

For the clickable portfolio prototype, a frozen fixture based on the real ResNet run drives all screens and states. The fixture may omit sensitive paths and credentials but must preserve the real workflow, score, metric comparison, and repair evidence. It is labeled `Demo evidence from the ResNet-20/CIFAR-10 reproduction run`.

The only user-originated control events in the prototype are creating a draft task, validating inputs, starting the demonstrated run, selecting timeline events, approving or rejecting the demonstrated high-risk patch, and navigating to the report. Production integration is deferred; its eventual API must call the same orchestration and approval services already used by the CLI.

## 8. Error and Safety Behavior

- Missing or invalid inputs block task start and provide field-specific recovery guidance.
- Build and command failures retain stdout, stderr, exit code, duration, and environment evidence.
- A recoverable low-risk failure enters the existing bounded diagnosis-patch-test loop.
- A high-risk semantic patch pauses in `WAITING_APPROVAL` and cannot be bypassed by the UI.
- A rejected patch, timeout, exhausted attempt limit, or failed verification produces a terminal evidence report.
- The product never converts an incomplete or failed run into a successful visual state.
- API keys, credentials, private dataset paths, and unsanitized secrets never appear in fixtures, screenshots, or committed files.

## 9. User Research Design

Five participants with recent paper-reproduction experience complete two asynchronous text rounds.

Round one asks about the most recent real attempt: objective, workflow, time spent, blocking points, tools used, help requested, abandonment conditions, and personal definition of success. It avoids asking participants to design features.

Round two uses follow-up questions grounded in each participant's first-round account. It tests interpretations, identifies hidden manual steps, and distinguishes a recurring problem from a one-off incident.

Records use IDs P01-P05 and contain only consented, non-sensitive content. Findings are coded as:

- recurring evidence: mentioned by at least three participants;
- severe evidence: caused abandonment, invalid results, or substantial rework;
- isolated evidence: important but reported by fewer than three participants;
- hypothesis: plausible but not yet supported by the interviews.

No interview result is written before the user supplies the participant's actual text response.

## 10. Measurement Plan

### Engineering metrics already available

- error-localization rate;
- repair-success rate;
- post-repair probe pass rate;
- unrelated-code-change rate;
- model calls, token use, tool calls, wall time, and estimated cost;
- paper-versus-run metric delta and multi-seed variation.

### Product metrics to collect

- **Task completion rate:** participants who complete the assigned prototype flow divided by participants who start it.
- **Time to interpret:** elapsed time from opening the execution view to correctly explaining the current state and required action.
- **Manual steps reduced:** manual baseline steps minus assisted-flow steps under the same task definition.
- **Decision correctness:** whether the participant can correctly identify why a run is paused and whether the change is high risk.
- **Report comprehension:** whether the participant correctly explains `PARTIAL` and the meaning of the credibility score.
- **Satisfaction:** a post-task 1-5 rating plus a required free-text reason.

The five-person comparison is exploratory. Results are reported as observed counts, medians, ranges, and individual comments, never as statistically representative market evidence.

## 11. Usability Evaluation

Each participant is asked to:

1. create a reproduction task from supplied inputs;
2. identify the current execution stage;
3. explain why the run paused;
4. inspect the evidence and approve or reject the patch;
5. explain the final `80/100 PARTIAL` result.

The prototype is ready for portfolio use when at least four of five participants complete the core flow without moderator intervention, at least four correctly explain `PARTIAL`, and no participant interprets the credibility score as model accuracy. Failed criteria trigger copy or interaction changes followed by a documented second iteration.

## 12. Competitor Analysis

The analysis compares four alternatives rather than forcing every tool into one category:

- manual reproduction with terminals, notebooks, and issue trackers;
- paper discovery or paper-code linking tools;
- reproducible execution and computational capsule platforms;
- general coding agents.

Each comparison records target user, job to be done, paper understanding, environment execution, repair behavior, evidence chain, approval control, result comparison, and reproducibility judgment. Claims must cite current primary sources such as official product pages and documentation. The conclusion must identify ReproPilot's narrow differentiation without claiming capabilities that the MVP does not implement.

## 13. Deliverables and Repository Boundaries

Product artifacts live under `docs/product/`:

- `interview-kit.md` — outreach text, two-round questions, consent and anonymization guidance;
- `research-records/README.md` — schema and rules for adding P01-P05 responses;
- `research-findings.md` — evidence coding template, initially marked as awaiting responses;
- `competitor-analysis.md` — sourced comparison and positioning;
- `prd.md` — MVP product requirements and acceptance criteria;
- `metrics-plan.md` — metric definitions and collection procedure;
- `usability-test.md` — test script, observation form, and success thresholds;
- `case-study.md` — portfolio narrative with evidence and iteration slots;
- `demo-video-script.md` — a concise recording plan.

The interactive prototype lives under `prototype/` as an isolated, locally runnable frontend with a README and sanitized fixtures. It must not change the CLI or scoring logic.

SQL interview practice is maintained outside this repository as a separate learning track. It is not a prerequisite for completing the ReproPilot product case.

## 14. Implementation Order

1. Create the research kit, evidence-record templates, PRD, and metric definitions.
2. Research current competitors from primary sources and complete the comparison.
3. Build the clickable prototype from the selected timeline direction and the sanitized ResNet fixture.
4. Verify the main prototype flow and accessibility-critical interactions locally.
5. Prepare the usability protocol, product case, and demo script.
6. Ask the user only to distribute the interview questions and paste real responses.
7. After responses arrive, code findings, update the PRD and case study, and record measured usability results.

## 15. Acceptance Criteria

- Every product claim is either backed by an existing artifact, a cited primary source, or explicitly labeled as a hypothesis.
- The prototype supports the complete demonstrated journey from task creation through report interpretation.
- The execution timeline exposes the existing state machine and evidence rather than inventing a parallel agent.
- High-risk approval cannot be visually or logically bypassed.
- Demo fixtures contain no API keys, credentials, or private paths.
- Research templates never imply that interviews have already occurred.
- Product and engineering metrics are defined separately and use reproducible formulas.
- The current Python test suite remains unchanged and passing because the first prototype iteration is isolated from the engine.
