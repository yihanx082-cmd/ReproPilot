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

## Evidence boundary

The UI reads `data/demo-run.json`, a frozen and sanitized fixture based on the documented ResNet-20/CIFAR-10 reproduction. **No paper parsing, Docker command, patch, test, or experiment actually runs in this prototype.** The high-risk metric approval is explicitly marked as an illustrative interaction state.

A production Web layer would read the same run artifacts used by the CLI (`run.json`, `events.jsonl`, alignment findings, command results, approval records, formal experiment evidence, and score output). It must call the existing orchestrator and approval services instead of duplicating scoring or policy in the browser.

## Verify

```powershell
npm test
npm run build
npm run test:sites
```

The visual comparison and browser-flow evidence are recorded in [design-qa.md](design-qa.md).
