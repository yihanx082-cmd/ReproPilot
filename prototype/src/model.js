const SCREENS = new Set(["create", "scope", "timeline", "report"]);

export function createInitialState(run) {
  return {
    run,
    step: "create",
    selectedStageId: run.timeline?.[0]?.id ?? null,
    decision: null,
  };
}

export function validateTask(task) {
  const errors = {};
  if (!task?.paper?.trim()) errors.paper = "请选择论文 PDF。";
  if (!task?.repository?.trim()) errors.repository = "请输入 GitHub 或本地仓库。";
  if (!task?.dataset?.trim()) errors.dataset = "请选择目标数据集。";
  return errors;
}

export function selectStage(state, stageId) {
  if (!state.run.timeline.some((stage) => stage.id === stageId)) {
    throw new Error(`Unknown timeline stage: ${stageId}`);
  }
  return { ...state, selectedStageId: stageId };
}

function assertCurrentPatch(state, patchSha256) {
  if (patchSha256 !== state.run.approval.patch_sha256) {
    throw new Error("Patch evidence changed; review the new diff.");
  }
}

export function approvePatch(state, patchSha256) {
  assertCurrentPatch(state, patchSha256);
  return {
    ...state,
    decision: { approved: true, patchSha256, reason: null },
  };
}

export function rejectPatch(state, patchSha256, reason) {
  assertCurrentPatch(state, patchSha256);
  if (!reason?.trim()) throw new Error("Rejection reason is required.");
  return {
    ...state,
    decision: { approved: false, patchSha256, reason: reason.trim() },
  };
}

export function getVisibleScreen(state) {
  if (!SCREENS.has(state.step)) throw new Error(`Unknown screen: ${state.step}`);
  return state.step;
}
