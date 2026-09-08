# ReproPilot Prototype Design QA

## Comparison target

- Source: the user-selected **Execution Timeline** wireframe from `repropilot-layout-directions.html`.
- Implementation: `http://127.0.0.1:4173/?screen=timeline` at 1440×900 and 1024×768.
- Combined visual evidence: `C:/Users/10575/Documents/ChatGPT/agent/logs/repropilot-design-comparison.png`.
- Implementation captures: `docs/product/assets/prototype-timeline.png` and `C:/Users/10575/Documents/ChatGPT/agent/logs/repropilot-timeline-1024.png`.

## Findings and fixes

### Resolved P1 — status message contradicted the deep-linked state

The first implementation opened the approval timeline while the live message still said to review task inputs. This weakened state clarity. `getDemoStatusMessage()` now derives the message from the initial screen, and an automated test covers create, timeline, and report states. The revised capture says the demonstrated run is paused for a high-risk semantic decision.

### Accepted expansion — center panel contains decision detail

The wireframe establishes a three-column composition with navigation/stages, timeline content, and evidence. The implementation preserves those proportions and semantic regions, then expands the center panel to show the approved product requirement: root cause, semantic impact, diff, and explicit approval controls. This is intentional product detail, not visual drift.

## Required fidelity surfaces

- **Fonts and typography:** Both source and implementation use a neutral sans-serif hierarchy with a dark navy title, compact metadata, and monospace evidence. The implementation keeps body text readable at 1440×900 and 1024×768; long stage names truncate instead of colliding with status metadata.
- **Spacing and layout rhythm:** The selected three-region workspace is preserved. Borders, modest radii, compact stage rows, and a quiet outer canvas match the wireframe. At 1024×768 the primary approval action remains visible; the full page can scroll to supporting evidence.
- **Colors and visual tokens:** Navy text, blue active state, green verified state, amber warning/approval state, white content surfaces, and cool-gray panels match the selected direction. Red is reserved for explicit rejection or terminal failure.
- **Image quality and asset fidelity:** The source contains no raster imagery, logo asset, illustration, or decorative image. The implementation therefore uses no placeholder imagery or recreated visual asset. The `RP` brand initials are editable product text, not a substitute for a source image.
- **Copy and content:** The implementation retains the ResNet-20/CIFAR-10 task, live reproduction timeline, staged progress, and evidence panel. Added copy explains evidence boundaries and avoids equating credibility with model accuracy.
- **Interaction and accessibility:** The complete create → scope → timeline → approval → report path passed in a real browser. All core actions use buttons or labeled form controls, focus indicators are visible, the state message uses `aria-live="polite"`, and the browser console contained no errors.
- **Responsiveness:** 1440×900 preserves the full three-column workspace. At 1024×768 the layout remains three columns with compact navigation; below 860 px it becomes a single-column reading order rather than shrinking evidence into unreadable panels.

## Verification evidence

- Browser flow: create, scope review, approval timeline, SHA-bound approval, and credibility report all completed.
- Browser console: zero error entries.
- Automated interaction model: 12 tests passed.
- Static app contract: 2 tests passed.
- Sites worker contract: 4 tests passed.
- Production build: passed.

## Remaining P3 notes

- At 1024 px the stepper intentionally hides text labels and retains numbered progress only.
- A later usability round should test whether first-time users recognize the compact evidence file names without opening help text.

## Final result

final result: passed
