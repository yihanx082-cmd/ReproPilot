# ReproPilot Clickable Product Prototype

Public demo: https://repropilot-evidence-agent.yizhuliang42.chatgpt.site

This desktop prototype demonstrates the complete evidence-led journey: task creation, paper–code scope review, execution timeline, high-risk patch approval, and credibility report.

## Run locally

```powershell
cd prototype
npm install
npm run dev -- --host 127.0.0.1 --port 4173 --strictPort
```

Open `http://127.0.0.1:4173/`. Direct review links are available at `?screen=timeline` and `?screen=report`.

## Run with real local artifacts

Build the frontend and let the Python package serve it together with the loopback-only API:

```powershell
cd prototype
npm run build
cd ..
repropilot serve --host 127.0.0.1 --port 8765
```

Open `http://127.0.0.1:8765/?live=1`. The live screen starts a run from a local YAML path, polls the real job and run artifacts, displays persisted events, and records SHA-bound approval or rejection decisions before resuming. Docker and model credentials are required only when an actual run is started.

## Evidence boundary

The public site and the default local route read `data/demo-run.json`, a frozen and sanitized fixture based on the documented ResNet-20/CIFAR-10 reproduction. **No paper parsing, Docker command, patch, test, or experiment runs in demo mode.** The high-risk metric approval is explicitly marked as an illustrative interaction state.

The explicit local `?live=1` route calls the existing orchestrator and reads the same artifacts used by the CLI (`run.json`, `events.jsonl`, approval records, and `report.html`). It does not duplicate scoring or repair policy in the browser. The server accepts loopback hosts only, validates run identifiers, and requires JSON for mutation requests. The deployed public build has no execution backend and remains a shareable frozen demonstration.

## Verify

```powershell
npm test
npm run build
npm run test:sites
```

The visual comparison and browser-flow evidence are recorded in [design-qa.md](design-qa.md).
