# ReproPilot Product Case Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the existing ReproPilot engineering MVP into an evidence-backed AI product manager case with research materials, product requirements, metrics, a locally runnable clickable prototype, and portfolio presentation assets.

**Architecture:** Keep the Python CLI and artifact model as the scientific source of truth. Add product documents under `docs/product/` and an isolated dependency-light Web prototype under `prototype/`; the prototype reads one sanitized JSON fixture based on the real ResNet-20/CIFAR-10 run and never reimplements scoring or repair policy.

**Tech Stack:** Markdown, Python 3.11 validation tests, semantic HTML, CSS, browser-native JavaScript ES modules, Node.js built-in test runner, existing ReproPilot JSON/domain concepts.

**Spec:** `docs/superpowers/specs/2026-09-08-product-case-foundation-design.md`

## Global Constraints

- Do not fabricate interview responses, usability results, satisfaction ratings, or competitor claims.
- Label the five-person research and comparison as exploratory, not statistically representative.
- Use current primary sources for competitor claims and place citations next to the supported claims.
- Keep API keys, credentials, private paths, and private participant details out of committed files.
- The prototype must consume frozen demo evidence and must not duplicate credibility-scoring or repair-policy logic.
- High-risk patch approval must remain visible and SHA-bound in the demonstrated flow.
- The credibility score describes evidence completeness and consistency; it must never be presented as model accuracy.
- Keep SQL interview practice outside the ReproPilot repository.

---

### Task 1: User Research Kit and Evidence Records

**Files:**
- Create: `docs/product/interview-kit.md`
- Create: `docs/product/research-records/README.md`
- Create: `docs/product/research-findings.md`
- Test: `tests/test_product_docs.py`

**Interfaces:**
- Consumes: the target user and research rules in the product-case design spec.
- Produces: a two-round asynchronous interview protocol, an anonymous P01-P05 record contract, and a findings structure that later portfolio documents can cite.

- [ ] **Step 1: Write the failing documentation-structure test**

```python
from pathlib import Path


PRODUCT_DOCS = Path(__file__).parents[1] / "docs" / "product"


def test_research_kit_has_required_sections() -> None:
    interview = (PRODUCT_DOCS / "interview-kit.md").read_text(encoding="utf-8")
    records = (PRODUCT_DOCS / "research-records" / "README.md").read_text(encoding="utf-8")
    findings = (PRODUCT_DOCS / "research-findings.md").read_text(encoding="utf-8")
    for heading in ["Round One", "Round Two", "Consent", "Anonymization"]:
        assert heading in interview
    for participant in ["P01", "P02", "P03", "P04", "P05"]:
        assert participant in records
    assert "Awaiting real participant responses" in findings
    assert "statistically representative" in findings
```

- [ ] **Step 2: Run the focused test and verify that it fails because the files do not exist**

Run: `pytest tests/test_product_docs.py::test_research_kit_has_required_sections -v`

Expected: FAIL with `FileNotFoundError` for `docs/product/interview-kit.md`.

- [ ] **Step 3: Write the research artifacts**

`interview-kit.md` must include a short outreach message, consent language, nine first-round questions about the participant's most recent reproduction attempt, conditional second-round probes, and instructions telling the interviewer not to lead the participant toward ReproPilot features. `research-records/README.md` must define one Markdown record per participant using only P01-P05, raw answer preservation, optional paraphrase fields, and a prohibited-data list. `research-findings.md` must contain empty evidence tables labeled `Awaiting real participant responses`, the recurring/severe/isolated/hypothesis coding rules, and the exploratory-sample disclaimer.

- [ ] **Step 4: Run the focused test**

Run: `pytest tests/test_product_docs.py::test_research_kit_has_required_sections -v`

Expected: PASS.

- [ ] **Step 5: Commit the research kit**

```bash
git add docs/product/interview-kit.md docs/product/research-records/README.md docs/product/research-findings.md tests/test_product_docs.py
git commit -m "docs: add evidence-safe user research kit"
```

### Task 2: Product Metrics and Usability Protocol

**Files:**
- Create: `docs/product/metrics-plan.md`
- Create: `docs/product/usability-test.md`
- Modify: `tests/test_product_docs.py`

**Interfaces:**
- Consumes: existing benchmark metrics and the five-task usability journey from the spec.
- Produces: precise formulas and observation fields used later by `case-study.md`.

- [ ] **Step 1: Add failing tests for metric definitions and usability thresholds**

```python
def test_metrics_and_usability_are_measurable() -> None:
    metrics = (PRODUCT_DOCS / "metrics-plan.md").read_text(encoding="utf-8")
    usability = (PRODUCT_DOCS / "usability-test.md").read_text(encoding="utf-8")
    for metric in [
        "Task completion rate",
        "Time to interpret",
        "Manual steps reduced",
        "Decision correctness",
        "Report comprehension",
        "Satisfaction",
    ]:
        assert metric in metrics
    assert "4 of 5" in usability
    assert "credibility score" in usability
    assert "model accuracy" in usability
```

- [ ] **Step 2: Run the new test and verify that it fails on missing documents**

Run: `pytest tests/test_product_docs.py::test_metrics_and_usability_are_measurable -v`

Expected: FAIL with `FileNotFoundError` for `docs/product/metrics-plan.md`.

- [ ] **Step 3: Write exact measurement and test procedures**

Define every product metric with numerator, denominator or start/end timestamp, data source, interpretation, and limitation. Keep engineering metrics in a separate table. The usability protocol must include moderator setup, the five participant tasks, no-help and intervention rules, observation fields, the `4 of 5` thresholds, and a comprehension check that distinguishes credibility score from model accuracy.

- [ ] **Step 4: Run the focused product-document tests**

Run: `pytest tests/test_product_docs.py -v`

Expected: PASS.

- [ ] **Step 5: Commit the metrics and usability protocol**

```bash
git add docs/product/metrics-plan.md docs/product/usability-test.md tests/test_product_docs.py
git commit -m "docs: define product metrics and usability protocol"
```

### Task 3: Sourced Competitive Analysis and MVP PRD

**Files:**
- Create: `docs/product/competitor-analysis.md`
- Create: `docs/product/prd.md`
- Modify: `tests/test_product_docs.py`

**Interfaces:**
- Consumes: current official documentation for selected alternatives and the approved product positioning.
- Produces: a source-backed market frame and explicit product requirements for the prototype.

- [ ] **Step 1: Add failing tests for source discipline and PRD scope**

```python
def test_competitor_analysis_and_prd_are_bounded() -> None:
    competitors = (PRODUCT_DOCS / "competitor-analysis.md").read_text(encoding="utf-8")
    prd = (PRODUCT_DOCS / "prd.md").read_text(encoding="utf-8")
    assert "Primary sources" in competitors
    assert "Manual workflow" in competitors
    assert "Coding agents" in competitors
    for heading in ["Problem", "Target User", "Requirements", "Non-goals", "Risks", "Acceptance Criteria"]:
        assert heading in prd
    assert "cloud GPU scheduling" in prd
```

- [ ] **Step 2: Run the focused test and verify the missing-file failure**

Run: `pytest tests/test_product_docs.py::test_competitor_analysis_and_prd_are_bounded -v`

Expected: FAIL with `FileNotFoundError` for `docs/product/competitor-analysis.md`.

- [ ] **Step 3: Research current alternatives from primary sources**

Browse the official product pages and documentation of one paper-code discovery product, one reproducible-computation platform, and one general coding agent. Record page title, direct URL, access date `2026-09-08`, supported workflow claims, and visible limitations. Include the manual terminal/notebook workflow as a non-product baseline. Do not infer unavailable features from marketing omissions.

- [ ] **Step 4: Write the competitor matrix and PRD**

Compare target user, job, paper understanding, environment execution, code repair, evidence chain, approval control, result comparison, and credibility judgment. Write the PRD requirements for task creation, scope review, timeline, approval state, and report; include the explicitly excluded multi-user, billing, chat, Kubernetes, and cloud GPU features.

- [ ] **Step 5: Run documentation tests and manually verify every external claim has an adjacent primary-source citation**

Run: `pytest tests/test_product_docs.py -v`

Expected: PASS. Manual check: every named-product capability statement has a direct official link in the same paragraph or table row.

- [ ] **Step 6: Commit the analysis and PRD**

```bash
git add docs/product/competitor-analysis.md docs/product/prd.md tests/test_product_docs.py
git commit -m "docs: add sourced market analysis and product requirements"
```

### Task 4: Sanitized Demo Evidence Fixture

**Files:**
- Create: `prototype/data/demo-run.json`
- Create: `tests/test_prototype_fixture.py`

**Interfaces:**
- Consumes: documented evidence from `docs/formal-demo-result.md`, the seven scoring dimensions, and existing domain values.
- Produces: a static JSON object with `meta`, `task`, `scope`, `timeline`, `approval`, and `report` fields for the Web prototype.

- [ ] **Step 1: Write the failing fixture-contract test**

```python
import json
from pathlib import Path


FIXTURE = Path(__file__).parents[1] / "prototype" / "data" / "demo-run.json"


def test_demo_fixture_is_realistic_and_sanitized() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert payload["meta"]["demo"] is True
    assert "ResNet-20" in payload["meta"]["source_label"]
    assert payload["report"]["score"] == 80
    assert payload["report"]["label"] == "PARTIAL"
    assert payload["report"]["comparison"]["paper_value"] == 8.75
    assert payload["report"]["comparison"]["observed_mean"] == 8.27
    assert len(payload["report"]["dimensions"]) == 7
    assert payload["approval"]["risk"] == "high"
    serialized = json.dumps(payload).lower()
    for forbidden in ["openai_api_key", "sk-", "c:\\\\users", "d:\\\\"]:
        assert forbidden not in serialized
```

- [ ] **Step 2: Run the focused test and verify the missing-fixture failure**

Run: `pytest tests/test_prototype_fixture.py -v`

Expected: FAIL with `FileNotFoundError` for `prototype/data/demo-run.json`.

- [ ] **Step 3: Create the sanitized fixture**

Use only facts already documented in the repository: paper error `8.75`, observed error `8.27 ± 0.00`, delta `-0.48` percentage points, score `80`, label `PARTIAL`, public pretrained-weight limitation, and the real state sequence. Include a high-risk approval example with a non-secret illustrative SHA-256 and a bounded diff excerpt. Set `meta.demo` to `true` and write the source label verbatim.

- [ ] **Step 4: Run the fixture test**

Run: `pytest tests/test_prototype_fixture.py -v`

Expected: PASS.

- [ ] **Step 5: Commit the fixture**

```bash
git add prototype/data/demo-run.json tests/test_prototype_fixture.py
git commit -m "test: add sanitized real-run prototype fixture"
```

### Task 5: Prototype State Model

**Files:**
- Create: `prototype/package.json`
- Create: `prototype/src/model.js`
- Create: `prototype/tests/model.test.js`

**Interfaces:**
- Consumes: the JSON fixture contract from Task 4.
- Produces: `createInitialState(run)`, `validateTask(task)`, `selectStage(state, stageId)`, `approvePatch(state)`, `rejectPatch(state)`, and `getVisibleScreen(state)`.

- [ ] **Step 1: Create the package manifest and failing model tests**

```json
{
  "name": "repropilot-prototype",
  "private": true,
  "type": "module",
  "scripts": {"test": "node --test"}
}
```

```javascript
import assert from "node:assert/strict";
import test from "node:test";
import { approvePatch, createInitialState, getVisibleScreen, validateTask } from "../src/model.js";

const run = { task: { paper: "paper.pdf", repository: "https://github.com/example/repo", dataset: "CIFAR-10" } };

test("valid task advances from create to scope review", () => {
  const state = createInitialState(run);
  assert.deepEqual(validateTask(state.run.task), {});
  assert.equal(getVisibleScreen({ ...state, step: "scope" }), "scope");
});

test("approval is explicit and SHA-bound", () => {
  const state = { ...createInitialState(run), step: "timeline", decision: null };
  const approved = approvePatch(state, "a".repeat(64));
  assert.deepEqual(approved.decision, { approved: true, patchSha256: "a".repeat(64) });
});
```

- [ ] **Step 2: Run Node tests and verify module-not-found failure**

Run: `npm test --prefix prototype`

Expected: FAIL because `prototype/src/model.js` does not exist.

- [ ] **Step 3: Implement the minimal immutable state model**

Validation returns a field-to-message object for empty paper, repository, or dataset values. Selection returns a copied state with `selectedStageId`. Approval and rejection require the current fixture patch SHA and return copied state with an explicit decision. Visible screens are exactly `create`, `scope`, `timeline`, and `report`.

- [ ] **Step 4: Expand tests for invalid inputs, stage selection, rejection reason, and invalid SHA**

Use Node's built-in assertions to verify every exported function and confirm that approval with a changed SHA throws `Patch evidence changed; review the new diff.`.

- [ ] **Step 5: Run prototype model tests**

Run: `npm test --prefix prototype`

Expected: all tests PASS.

- [ ] **Step 6: Commit the state model**

```bash
git add prototype/package.json prototype/src/model.js prototype/tests/model.test.js
git commit -m "feat: add prototype interaction state model"
```

### Task 6: Clickable Execution-Timeline Prototype

**Files:**
- Create: `prototype/index.html`
- Create: `prototype/styles.css`
- Create: `prototype/src/app.js`
- Create: `prototype/README.md`
- Modify: `prototype/tests/model.test.js`

**Interfaces:**
- Consumes: `prototype/data/demo-run.json` and all state-model functions from Task 5.
- Produces: a locally runnable four-screen prototype with keyboard-operable navigation and the complete demo journey.

- [ ] **Step 1: Add a failing static-contract test**

Add a Node test that reads `index.html` and asserts the presence of one `main` landmark, the demo-data disclosure, a live status region, and named roots for task form, scope review, timeline, approval panel, and report.

- [ ] **Step 2: Run prototype tests and verify failure on missing `index.html`**

Run: `npm test --prefix prototype`

Expected: FAIL with an `ENOENT` error for `prototype/index.html`.

- [ ] **Step 3: Build the semantic HTML shell and visual system**

Create a desktop-first application shell matching the selected timeline direction. Use restrained neutral surfaces, one blue action color, amber for approval warnings, red only for terminal failure, readable 14-16 px body text, visible focus rings, real button elements, and no emoji or handcrafted SVG assets. The execution workspace must present stages on the left, selected event detail in the center, and evidence on the right.

- [ ] **Step 4: Wire the complete demonstrated flow**

Load the fixture with `fetch`, render task creation, validate required fields, show scope review, start the frozen run, select timeline events, open the approval state, approve or reject the demonstrated patch, and navigate to the final report. Render score copy as `Evidence credibility 80/100 — PARTIAL` followed immediately by `This is not model accuracy.`.

- [ ] **Step 5: Document local startup and prototype boundaries**

`prototype/README.md` must use `python -m http.server 4173 -d prototype`, identify the demo fixture, state that no real command executes, and explain that the production integration will consume the same artifacts as the CLI.

- [ ] **Step 6: Run automated checks**

Run: `npm test --prefix prototype`

Expected: all Node tests PASS.

Run: `pytest tests/test_prototype_fixture.py tests/test_product_docs.py -v`

Expected: all focused Python tests PASS.

- [ ] **Step 7: Run local visual and interaction QA**

Start the documented HTTP server, open the prototype in the user's selected in-app browser, and complete this exact path: create task → scope review → timeline → inspect approval evidence → approve → report. Check 1440×900 and 1024×768 viewports for clipped panels, unreadable text, broken focus states, and inactive primary controls. Capture one screenshot of the timeline and one of the report for the case study.

- [ ] **Step 8: Commit the verified prototype**

```bash
git add prototype
git commit -m "feat: build clickable reproduction timeline prototype"
```

### Task 7: Portfolio Case, Figma Handoff, and Demo Script

**Files:**
- Create: `docs/product/case-study.md`
- Create: `docs/product/figma-handoff.md`
- Create: `docs/product/demo-video-script.md`
- Create: `docs/product/assets/prototype-timeline.png`
- Create: `docs/product/assets/prototype-report.png`
- Modify: `tests/test_product_docs.py`

**Interfaces:**
- Consumes: research status, sourced competitor analysis, PRD, existing benchmark evidence, prototype screenshots, and usability thresholds.
- Produces: a truthful portfolio narrative, a frame-by-frame Figma recreation map, and a recordable demonstration.

- [ ] **Step 1: Add failing portfolio-artifact tests**

```python
def test_case_study_preserves_evidence_boundaries() -> None:
    case_study = (PRODUCT_DOCS / "case-study.md").read_text(encoding="utf-8")
    handoff = (PRODUCT_DOCS / "figma-handoff.md").read_text(encoding="utf-8")
    script = (PRODUCT_DOCS / "demo-video-script.md").read_text(encoding="utf-8")
    assert "Awaiting real participant responses" in case_study
    assert "6/6" in case_study
    assert "80/100" in case_study
    for frame in ["Task Creation", "Scope Review", "Execution Timeline", "Approval", "Credibility Report"]:
        assert frame in handoff
    assert "not model accuracy" in script.lower()
```

- [ ] **Step 2: Run the focused test and verify missing-file failure**

Run: `pytest tests/test_product_docs.py::test_case_study_preserves_evidence_boundaries -v`

Expected: FAIL with `FileNotFoundError` for `docs/product/case-study.md`.

- [ ] **Step 3: Write the evidence-backed case study**

Use the structure: context, user problem, discovery status, alternatives, product decision, system workflow, prototype, engineering evaluation, real reproduction, measurement plan, limitations, and next iteration. Include the verified `6/6` benchmark result and `80/100 PARTIAL` reproduction result. Keep research and usability sections visibly labeled `Awaiting real participant responses` until actual evidence arrives.

- [ ] **Step 4: Write the Figma recreation map and video script**

The handoff defines five named frames, their dimensions, components, shared colors/type/spacing, and clickable transitions. The video script runs for five minutes or less and demonstrates the problem, task setup, paper-code mismatch, repair evidence, high-risk decision, and final credibility interpretation.

- [ ] **Step 5: Add verified screenshots and run document tests**

Copy only the two screenshots captured during Task 6 into `docs/product/assets/`. Run: `pytest tests/test_product_docs.py -v`.

Expected: PASS.

- [ ] **Step 6: Commit portfolio materials**

```bash
git add docs/product/case-study.md docs/product/figma-handoff.md docs/product/demo-video-script.md docs/product/assets tests/test_product_docs.py
git commit -m "docs: package ReproPilot product portfolio case"
```

### Task 8: Repository Integration and Full Verification

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: all deliverables from Tasks 1-7.
- Produces: discoverable links from the project landing page and a fully verified branch.

- [ ] **Step 1: Add a concise Product Case section to the README**

Link the PRD, competitor analysis, research kit, metrics plan, case study, and prototype README. State that interview findings and usability outcomes remain pending until real participants provide data.

- [ ] **Step 2: Run formatting, typing, Python, and prototype tests**

Run: `ruff check src tests scripts`

Expected: PASS with no diagnostics.

Run: `mypy src`

Expected: PASS with no errors.

Run: `pytest -q`

Expected: all tests PASS; Docker integration tests may remain skipped under their existing opt-in rule.

Run: `npm test --prefix prototype`

Expected: all tests PASS.

- [ ] **Step 3: Verify repository hygiene**

Run: `git diff --check` and scan tracked files for `sk-`, `OPENAI_API_KEY=`, `C:\Users\`, and unredacted participant names.

Expected: no whitespace errors, credentials, private paths, or participant identities.

- [ ] **Step 4: Commit the integration**

```bash
git add README.md
git commit -m "docs: link product case from project overview"
```

- [ ] **Step 5: Prepare the branch for review**

Run: `git status --short --branch` and `git log --oneline main..HEAD`.

Expected: clean branch with the design commit followed by focused implementation commits for research, metrics, analysis, fixture, prototype, portfolio, and README integration.
