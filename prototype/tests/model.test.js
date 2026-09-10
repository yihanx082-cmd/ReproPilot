import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  approvePatch,
  createInitialState,
  getDemoStartStep,
  getDemoStatusMessage,
  getAppMode,
  getRunStatus,
  getStageStatus,
  getVisibleScreen,
  rejectPatch,
  selectStage,
  validateTask,
} from "../src/model.js";

const fixtureUrl = new URL("../data/demo-run.json", import.meta.url);
const run = JSON.parse(await readFile(fixtureUrl, "utf8"));

test("initial state opens the task-creation screen", () => {
  const state = createInitialState(run);

  assert.equal(getVisibleScreen(state), "create");
  assert.equal(state.selectedStageId, "ingest");
  assert.equal(state.decision, null);
});

test("valid task has no validation errors", () => {
  assert.deepEqual(validateTask(run.task), {});
});

test("empty required fields return field-specific errors", () => {
  assert.deepEqual(validateTask({ paper: " ", repository: "", dataset: null }), {
    paper: "请选择论文 PDF。",
    repository: "请输入 GitHub 或本地仓库。",
    dataset: "请选择目标数据集。",
  });
});

test("selecting a stage preserves other state", () => {
  const state = createInitialState(run);
  const selected = selectStage(state, "approval");

  assert.equal(selected.selectedStageId, "approval");
  assert.equal(selected.run, run);
  assert.notEqual(selected, state);
});

test("unknown stage cannot be selected", () => {
  assert.throws(
    () => selectStage(createInitialState(run), "missing"),
    /Unknown timeline stage/,
  );
});

test("approval is explicit and SHA-bound", () => {
  const state = { ...createInitialState(run), step: "timeline" };
  const approved = approvePatch(state, run.approval.patch_sha256);

  assert.deepEqual(approved.decision, {
    approved: true,
    patchSha256: run.approval.patch_sha256,
    reason: null,
  });
});

test("changed patch evidence invalidates approval", () => {
  const state = { ...createInitialState(run), step: "timeline" };

  assert.throws(
    () => approvePatch(state, "b".repeat(64)),
    /Patch evidence changed; review the new diff\./,
  );
});

test("rejection records a required reason", () => {
  const state = { ...createInitialState(run), step: "timeline" };
  const rejected = rejectPatch(state, run.approval.patch_sha256, "指标语义不应自动改变");

  assert.equal(rejected.decision.approved, false);
  assert.equal(rejected.decision.reason, "指标语义不应自动改变");
  assert.throws(
    () => rejectPatch(state, run.approval.patch_sha256, " "),
    /Rejection reason is required/,
  );
  assert.equal(getRunStatus(rejected), "STOPPED — PATCH REJECTED");
  assert.equal(getStageStatus(run.timeline[5], rejected.decision), "rejected");
  assert.equal(getStageStatus(run.timeline[6], rejected.decision), "stopped");
  assert.equal(getStageStatus(run.timeline[7], rejected.decision), "stopped");
});

test("approval marks the decision stage verified and completes the run", () => {
  const approved = approvePatch(createInitialState(run), run.approval.patch_sha256);

  assert.equal(getRunStatus(approved), "VERIFIED");
  assert.equal(getStageStatus(run.timeline[5], approved.decision), "verified");
});

test("visible screens are limited to the product journey", () => {
  const state = createInitialState(run);
  for (const screen of ["create", "scope", "timeline", "report"]) {
    assert.equal(getVisibleScreen({ ...state, step: screen }), screen);
  }
  assert.throws(() => getVisibleScreen({ ...state, step: "settings" }), /Unknown screen/);
});

test("demo deep links only open supported review screens", () => {
  assert.equal(getDemoStartStep("?screen=timeline"), "timeline");
  assert.equal(getDemoStartStep("?screen=report"), "report");
  assert.equal(getDemoStartStep("?screen=settings"), "create");
  assert.equal(getDemoStartStep(""), "create");
});

test("demo status message matches the deep-linked screen", () => {
  assert.match(getDemoStatusMessage("timeline"), /paused for a high-risk/);
  assert.match(getDemoStatusMessage("report"), /credibility report/);
  assert.match(getDemoStatusMessage("create"), /Review inputs/);
});

test("live mode requires an explicit local query flag", () => {
  assert.equal(getAppMode("?live=1"), "live");
  assert.equal(getAppMode("?live=0"), "demo");
  assert.equal(getAppMode(""), "demo");
});
