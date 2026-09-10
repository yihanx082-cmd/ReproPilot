import { useEffect, useState } from "react";

import run from "../data/demo-run.json";
import {
  approvePatch,
  createInitialState,
  getDemoStartStep,
  getDemoStatusMessage,
  getAppMode,
  getRunStatus,
  getStageStatus,
  rejectPatch,
  selectStage,
  validateTask,
} from "./model.js";

const STEPS = [
  ["create", "1", "Task inputs"],
  ["scope", "2", "Review scope"],
  ["timeline", "3", "Run & repair"],
  ["report", "4", "Credibility"],
];

function ProductHeader({ screen, mode = "demo" }) {
  return (
    <header className="product-header">
      <div className="brand-lockup">
        <span className="brand-initials" aria-hidden="true">RP</span>
        <div>
          <strong>ReproPilot</strong>
          <span>Evidence-backed reproduction</span>
        </div>
      </div>
      <nav className="step-nav" aria-label="Task progress">
        {STEPS.map(([id, number, label]) => {
          const currentIndex = STEPS.findIndex(([step]) => step === screen);
          const index = STEPS.findIndex(([step]) => step === id);
          const state = index < currentIndex ? "complete" : index === currentIndex ? "current" : "next";
          return (
            <div className={`step-item ${state}`} key={id} aria-current={state === "current" ? "step" : undefined}>
              <span className="step-number">{number}</span>
              <span>{label}</span>
            </div>
          );
        })}
      </nav>
      <span className="demo-badge">{mode === "live" ? "Local execution" : "Demo mode"}</span>
    </header>
  );
}

function DemoNotice() {
  return (
    <div className="demo-notice" role="note">
      <strong>Frozen, sanitized evidence</strong>
      <span>{run.meta.notice}</span>
    </div>
  );
}

function TaskForm({ task, errors, onChange, onContinue }) {
  return (
    <section className="form-screen" data-testid="task-form">
      <div className="section-heading">
        <p className="eyebrow">New reproduction</p>
        <h1>Create a scoped reproduction task</h1>
        <p>Provide the four inputs the agent needs. You will review paper–code differences before anything runs.</p>
      </div>
      <DemoNotice />
      <form className="task-form" onSubmit={onContinue} noValidate>
        <label className="field field-wide">
          <span>Paper PDF</span>
          <small>The paper is parsed with page-level evidence.</small>
          <input value={task.paper} onChange={(event) => onChange("paper", event.target.value)} aria-invalid={Boolean(errors.paper)} />
          {errors.paper && <em className="field-error">{errors.paper}</em>}
        </label>
        <label className="field field-wide">
          <span>GitHub or local repository</span>
          <small>The original repository remains read-only.</small>
          <input value={task.repository} onChange={(event) => onChange("repository", event.target.value)} aria-invalid={Boolean(errors.repository)} />
          {errors.repository && <em className="field-error">{errors.repository}</em>}
        </label>
        <label className="field">
          <span>Dataset</span>
          <small>Used to verify scope and run commands.</small>
          <input value={task.dataset} onChange={(event) => onChange("dataset", event.target.value)} aria-invalid={Boolean(errors.dataset)} />
          {errors.dataset && <em className="field-error">{errors.dataset}</em>}
        </label>
        <label className="field">
          <span>Environment</span>
          <small>Runs inside a limited Docker sandbox.</small>
          <select value={`${task.python}-${task.device}`} onChange={() => {}}>
            <option value="3.11-cpu">Python 3.11 · CPU</option>
          </select>
        </label>
        <label className="field field-wide">
          <span>Minimum command</span>
          <small>Stored as an argument list, never as an untrusted shell string.</small>
          <input value={task.command.join(" ")} readOnly />
        </label>
        <div className="form-actions field-wide">
          <span>Your inputs are validated before execution.</span>
          <button className="button primary" type="submit">Review reproduction scope</button>
        </div>
      </form>
    </section>
  );
}

function ScopeReview({ onBack, onStart }) {
  return (
    <section className="scope-screen" data-testid="scope-review">
      <div className="section-heading split-heading">
        <div>
          <p className="eyebrow">Before execution</p>
          <h1>Review what can actually be compared</h1>
          <p>ReproPilot found two matches, one warning, and two unresolved limits.</p>
        </div>
        <div className="scope-summary">
          <span>Comparison scope</span>
          <strong>Paper-level evaluation</strong>
          <small>Limit: {run.scope.estimated_limit}</small>
        </div>
      </div>
      <div className="claim-table" role="table" aria-label="Paper and code alignment">
        <div className="claim-row claim-header" role="row">
          <span>Field</span><span>Paper</span><span>Repository</span><span>Status</span><span>Evidence</span>
        </div>
        {run.scope.claims.map((claim) => (
          <div className="claim-row" role="row" key={claim.field}>
            <strong>{claim.field}</strong><span>{claim.paper}</span><span>{claim.code}</span>
            <span><b className={`status-tag ${claim.status}`}>{claim.status}</b></span>
            <small>{claim.evidence}</small>
          </div>
        ))}
      </div>
      <div className="risk-block">
        <p className="eyebrow">Unresolved before run</p>
        <h2>Evidence boundaries</h2>
        <ul>{run.scope.unresolved.map((item) => <li key={item}>{item}</li>)}</ul>
      </div>
      <div className="page-actions">
        <button className="button secondary" type="button" onClick={onBack}>Back to inputs</button>
        <button className="button primary" type="button" onClick={onStart}>Start demonstrated run</button>
      </div>
    </section>
  );
}

function StageList({ stages, selectedId, decision, onSelect }) {
  return (
    <aside className="stage-list" aria-label="Execution stages">
      <div className="panel-heading">
        <p className="eyebrow">Run RP-240903</p>
        <h2>Execution</h2>
      </div>
      {stages.map((stage, index) => {
        const effectiveStatus = getStageStatus(stage, decision);
        return (
          <button className={`stage-button ${selectedId === stage.id ? "selected" : ""}`} type="button" onClick={() => onSelect(stage.id)} key={stage.id}>
            <span className={`stage-index ${effectiveStatus}`}>{String(index + 1).padStart(2, "0")}</span>
            <span className="stage-copy"><strong>{stage.title}</strong><small>{effectiveStatus}</small></span>
          </button>
        );
      })}
    </aside>
  );
}

function ApprovalPanel({ decision, rejectOpen, rejectionReason, onApprove, onRejectOpen, onReasonChange, onReject }) {
  if (decision) {
    return (
      <div className={`decision-result ${decision.approved ? "approved" : "rejected"}`}>
        <strong>{decision.approved ? "Patch approved" : "Patch rejected"}</strong>
        <p>{decision.approved ? "The SHA-bound decision is recorded. Verification can continue." : decision.reason}</p>
      </div>
    );
  }
  return (
    <div className="approval-actions">
      <button className="button secondary" type="button" onClick={onRejectOpen}>Reject</button>
      <button className="button primary" type="button" onClick={onApprove}>Approve and continue</button>
      {rejectOpen && (
        <div className="reject-form">
          <label htmlFor="rejection-reason">Reason for rejection</label>
          <textarea id="rejection-reason" value={rejectionReason} onChange={(event) => onReasonChange(event.target.value)} placeholder="Explain which evidence makes this change unacceptable." />
          <button className="button danger" type="button" onClick={onReject}>Confirm rejection</button>
        </div>
      )}
    </div>
  );
}

function ExecutionTimeline({ state, onSelect, onApprove, onReject, onReport }) {
  const [rejectOpen, setRejectOpen] = useState(false);
  const [rejectionReason, setRejectionReason] = useState("");
  const selected = run.timeline.find((stage) => stage.id === state.selectedStageId);
  const isApproval = selected.id === "approval";
  const selectedStatus = getStageStatus(selected, state.decision);

  return (
    <section className="timeline-screen" data-testid="execution-timeline">
      <div className="timeline-titlebar">
        <div><p className="eyebrow">Live reproduction timeline</p><h1>{run.task.name}</h1></div>
        <div className={`run-status ${state.decision?.approved === false ? "rejected" : ""}`}><span>Current state</span><strong>{getRunStatus(state)}</strong></div>
      </div>
      <div className="timeline-workspace">
        <StageList stages={run.timeline} selectedId={selected.id} decision={state.decision} onSelect={onSelect} />
        <article className="event-detail">
          <div className="event-topline"><span className={`status-tag ${selectedStatus.replace(" ", "-")}`}>{selectedStatus}</span><code>{selected.state}</code></div>
          <h2>{selected.title}</h2>
          <p className="event-summary">{selected.summary}</p>
          {isApproval ? (
            <div className="approval-card" data-testid="approval-panel">
              <div className="approval-warning"><strong>Why the agent paused · 为什么需要你决定</strong><p>{run.approval.root_cause}</p><p>{run.approval.plain_language}</p></div>
              <dl className="impact-grid">
                <div><dt>Risk level</dt><dd>{run.approval.risk}</dd></div>
                <div><dt>Semantic impact · 语义影响</dt><dd><strong>{run.approval.impact}</strong></dd></div>
                <div><dt>Numeric example · 数值示例</dt><dd>{run.approval.example}</dd></div>
                <div><dt>Paper evidence · 论文证据</dt><dd>{run.approval.paper_evidence}</dd></div>
              </dl>
              <div className="diff-block"><div><span>Proposed Git diff</span><small>`-` 删除原行，`+` 添加新行 · illustrative evidence</small></div><pre>{run.approval.diff}</pre></div>
              <div className="test-result">
                <div><span>Test exit code</span><strong>{run.approval.targeted_test_result.exit_code}</strong></div>
                <div><span>Key assertion · 关键断言</span><code>{run.approval.targeted_test_result.assertion}</code></div>
                <div><span>Test log · 测试日志</span><code>{run.approval.targeted_test_result.log_excerpt}</code></div>
              </div>
              <ApprovalPanel
                decision={state.decision}
                rejectOpen={rejectOpen}
                rejectionReason={rejectionReason}
                onApprove={onApprove}
                onRejectOpen={() => setRejectOpen(true)}
                onReasonChange={setRejectionReason}
                onReject={() => onReject(rejectionReason)}
              />
            </div>
          ) : (
            <div className="event-proof"><p>Outcome</p><strong>{selected.status === "verified" ? "Evidence verified" : "Review required"}</strong><span>{selected.evidence.length} artifacts attached to this state.</span></div>
          )}
        </article>
        <aside className="evidence-panel">
          <div className="panel-heading"><p className="eyebrow">Traceable evidence</p><h2>Evidence</h2></div>
          <div className="evidence-list">
            {selected.evidence.map((item, index) => <div className="evidence-item" key={item}><span>{String(index + 1).padStart(2, "0")}</span><code>{item}</code></div>)}
          </div>
          {isApproval && <div className="sha-block"><span>Patch SHA-256 · 补丁唯一指纹</span><code>{run.approval.patch_sha256}</code><span>Targeted test · 针对性测试</span><code>{run.approval.targeted_test.join(" ")}</code></div>}
          <div className="score-clarifier"><strong>Evidence credibility · 复现证据可信度</strong><span>Not model accuracy · 不是模型准确率</span></div>
          <button className="button report-button" type="button" disabled={!state.decision} onClick={onReport}>Open credibility report</button>
        </aside>
      </div>
    </section>
  );
}

function CredibilityReport({ decision, onBack }) {
  const rejected = decision?.approved === false;
  return (
    <section className="report-screen" data-testid="credibility-report">
      <div className="report-hero">
        <div>
          <p className="eyebrow">Final evidence report</p>
          <h1>{run.task.name}</h1>
          <p>{rejected ? "The run stopped because the semantic patch was rejected. No downstream experiment was verified." : "Public pretrained-weight evaluation with three independently recorded seeds."}</p>
        </div>
        {rejected ? (
          <div className="score-card rejected"><span>Terminal evidence report · 终止证据报告</span><strong>STOPPED</strong><b>PATCH REJECTED</b><p>No credibility score was issued after rejection.</p></div>
        ) : (
          <div className="score-card"><span>Evidence credibility · 复现证据可信度</span><strong>{run.report.score}<small>/100</small></strong><b>{run.report.label}</b><p>This is not model accuracy. 这不是模型准确率。</p></div>
        )}
      </div>
      {rejected ? (
        <div className="terminal-report"><h2>Why the run stopped · 为什么停止</h2><p>{decision.reason}</p><p>The rejected patch SHA remains recorded, while formal experiment and scoring stages are marked stopped.</p></div>
      ) : (
      <div className="report-grid">
        <article className="report-card comparison-card">
          <div className="card-heading"><p className="eyebrow">Primary comparison</p><h2>Error rate</h2></div>
          <div className="metric-pair"><div><span>Paper</span><strong>{run.report.comparison.paper_value}%</strong></div><div><span>Observed mean</span><strong>{run.report.comparison.observed_mean}%</strong></div></div>
          <p className="delta-note">Delta {run.report.comparison.delta_percentage_points} percentage points · seeds 11, 22, 33</p>
        </article>
        <article className="report-card dimension-card">
          <div className="card-heading"><p className="eyebrow">Seven dimensions</p><h2>Evidence breakdown</h2></div>
          {run.report.dimensions.map((dimension) => (
            <div className="dimension-row" key={dimension.name}><span>{dimension.name}</span><div className="meter"><i style={{ width: `${(dimension.earned / dimension.weight) * 100}%` }} /></div><strong>{dimension.earned}/{dimension.weight}</strong></div>
          ))}
        </article>
        <article className="report-card risks-card">
          <div className="card-heading"><p className="eyebrow">Why this is PARTIAL</p><h2>Unresolved risks</h2></div>
          <ol>{run.report.unresolved_risks.map((risk) => <li key={risk}>{risk}</li>)}</ol>
        </article>
      </div>
      )}
      <div className="page-actions"><button className="button secondary" type="button" onClick={onBack}>Back to evidence timeline</button><span>Report evidence remains available even when a run fails or stops.</span></div>
    </section>
  );
}

function LiveRunPanel() {
  const [configPath, setConfigPath] = useState("examples/cifar10-smoke.yaml");
  const [connection, setConnection] = useState("checking");
  const [jobId, setJobId] = useState(null);
  const [job, setJob] = useState(null);
  const [activeRun, setActiveRun] = useState(null);
  const [events, setEvents] = useState([]);
  const [message, setMessage] = useState("Checking the loopback API…");

  useEffect(() => {
    fetch("/api/health")
      .then((response) => {
        if (!response.ok) throw new Error("Local API is unavailable");
        return response.json();
      })
      .then(() => {
        setConnection("ready");
        setMessage("Local API connected. Choose a YAML configuration to start a real run.");
      })
      .catch(() => {
        setConnection("offline");
        setMessage("Local API unavailable. Start it with: repropilot serve");
      });
  }, []);

  useEffect(() => {
    if (!jobId) return undefined;
    let cancelled = false;
    async function refresh() {
      const response = await fetch(`/api/jobs/${jobId}`);
      const nextJob = await response.json();
      if (cancelled) return;
      setJob(nextJob);
      if (["QUEUED", "RUNNING"].includes(nextJob.status)) {
        window.setTimeout(refresh, 750);
        return;
      }
      if (!nextJob.run_id) {
        setMessage(nextJob.error || "The local run failed before artifacts were created.");
        return;
      }
      const [runResponse, eventResponse] = await Promise.all([
        fetch(`/api/runs/${nextJob.run_id}`),
        fetch(`/api/runs/${nextJob.run_id}/events`),
      ]);
      const [runPayload, eventPayload] = await Promise.all([
        runResponse.json(), eventResponse.json(),
      ]);
      if (cancelled) return;
      setActiveRun(runPayload);
      setEvents(eventPayload.events || []);
      setMessage(`Run ${nextJob.run_id} reached ${nextJob.status}.`);
    }
    refresh().catch((error) => setMessage(error.message));
    return () => { cancelled = true; };
  }, [jobId]);

  async function startRun(event) {
    event.preventDefault();
    setActiveRun(null);
    setEvents([]);
    setMessage("Submitting configuration to the local agent…");
    const response = await fetch("/api/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ config_path: configPath }),
    });
    const payload = await response.json();
    if (!response.ok) {
      setMessage(payload.detail || payload.error || "Run could not be created.");
      return;
    }
    setJob(payload);
    setJobId(payload.job_id);
  }

  async function decide(approved) {
    const reason = approved ? null : "Rejected from the local evidence review.";
    const response = await fetch(`/api/runs/${activeRun.run_id}/decision`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ approved, reason }),
    });
    const payload = await response.json();
    if (!response.ok) {
      setMessage(payload.detail || payload.error || "Decision could not be recorded.");
      return;
    }
    setJob(payload);
    setJobId(payload.job_id);
    setMessage("SHA-bound decision recorded. The local agent is resuming.");
  }

  return (
    <section className="live-run-screen" data-testid="live-run-panel">
      <div className="section-heading split-heading">
        <div>
          <p className="eyebrow">Local agent bridge</p>
          <h1>Run the real ReproPilot pipeline</h1>
          <p>This mode reads actual CLI artifacts. It is available only from the loopback server on your own computer.</p>
        </div>
        <div className={`connection-card ${connection}`}><span>Connection</span><strong>{connection}</strong></div>
      </div>
      <form className="live-run-form" onSubmit={startRun}>
        <label className="field"><span>Run configuration YAML</span><small>Path is resolved by the local Python process.</small><input value={configPath} onChange={(event) => setConfigPath(event.target.value)} /></label>
        <button className="button primary" type="submit" disabled={connection !== "ready"}>Start real run</button>
      </form>
      <div className="live-message" aria-live="polite">{message}</div>
      <div className="live-grid">
        <article className="report-card">
          <p className="eyebrow">Job</p>
          <h2>{job?.status || "Not started"}</h2>
          <dl className="live-facts"><div><dt>Job ID</dt><dd>{jobId || "—"}</dd></div><div><dt>Run ID</dt><dd>{activeRun?.run_id || job?.run_id || "—"}</dd></div><div><dt>Evidence events</dt><dd>{events.length}</dd></div></dl>
          {activeRun?.status === "WAITING_APPROVAL" && <div className="approval-actions"><button className="button secondary" type="button" onClick={() => decide(false)}>Reject patch</button><button className="button primary" type="button" onClick={() => decide(true)}>Approve SHA-bound patch</button></div>}
          {activeRun?.report_url && <a className="button report-button" href={activeRun.report_url} target="_blank" rel="noreferrer">Open generated HTML report</a>}
        </article>
        <article className="report-card live-events">
          <p className="eyebrow">Actual artifact timeline</p>
          <h2>Events</h2>
          {events.length === 0 ? <p>No events recorded yet.</p> : <ol>{events.map((event, index) => <li key={`${event.timestamp}-${index}`}><span>{event.kind}</span><strong>{event.message}</strong><small>{event.timestamp}</small></li>)}</ol>}
        </article>
      </div>
    </section>
  );
}

function DemoApp() {
  const initialStep = getDemoStartStep(window.location.search);
  const [state, setState] = useState(() => {
    const initial = createInitialState(run);
    return {
      ...initial,
      step: initialStep,
      selectedStageId: initialStep === "timeline" ? "approval" : initial.selectedStageId,
    };
  });
  const [task, setTask] = useState(run.task);
  const [errors, setErrors] = useState({});
  const [message, setMessage] = useState(() => getDemoStatusMessage(initialStep));

  function continueToScope(event) {
    event.preventDefault();
    const nextErrors = validateTask(task);
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length === 0) {
      setState((current) => ({ ...current, step: "scope", run: { ...current.run, task } }));
      setMessage("Inputs validated. Review the evidence boundary before execution.");
    }
  }

  function startRun() {
    setState((current) => ({ ...selectStage(current, "approval"), step: "timeline" }));
    setMessage("The demonstrated run is paused for a high-risk semantic decision.");
  }

  function approve() {
    setState((current) => approvePatch(current, run.approval.patch_sha256));
    setMessage("Approval recorded against the current patch SHA. Verification may continue.");
  }

  function reject(reason) {
    try {
      setState((current) => rejectPatch(current, run.approval.patch_sha256, reason));
      setMessage("Rejection recorded. A terminal evidence report can still be generated.");
    } catch (error) {
      setMessage(error.message);
    }
  }

  return (
    <main className="app-shell">
      <ProductHeader screen={state.step} />
      <div className="live-message" aria-live="polite">{message}</div>
      {state.step === "create" && <TaskForm task={task} errors={errors} onChange={(field, value) => setTask((current) => ({ ...current, [field]: value }))} onContinue={continueToScope} />}
      {state.step === "scope" && <ScopeReview onBack={() => setState((current) => ({ ...current, step: "create" }))} onStart={startRun} />}
      {state.step === "timeline" && <ExecutionTimeline state={state} onSelect={(id) => setState((current) => selectStage(current, id))} onApprove={approve} onReject={reject} onReport={() => setState((current) => ({ ...current, step: "report" }))} />}
      {state.step === "report" && <CredibilityReport decision={state.decision} onBack={() => setState((current) => ({ ...current, step: "timeline" }))} />}
    </main>
  );
}

export function App() {
  const mode = getAppMode(window.location.search);
  if (mode === "live") {
    return <main className="app-shell"><ProductHeader screen="timeline" mode="live" /><LiveRunPanel /></main>;
  }
  return <DemoApp />;
}
