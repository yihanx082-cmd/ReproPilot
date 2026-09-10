import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const appUrl = new URL("../src/App.jsx", import.meta.url);
const indexUrl = new URL("../index.html", import.meta.url);

test("app exposes the complete evidence-led journey", async () => {
  const source = await readFile(appUrl, "utf8");

  for (const landmark of [
    "task-form",
    "scope-review",
    "execution-timeline",
    "approval-panel",
    "credibility-report",
  ]) {
    assert.match(source, new RegExp(`data-testid=[\"']${landmark}[\"']`));
  }
  assert.match(source, /aria-live=["']polite["']/);
  assert.match(source, /Frozen, sanitized evidence/);
  assert.match(source, /This is not model accuracy/);
  assert.match(source, /不是模型准确率/);
  assert.match(source, /为什么需要你决定/);
  assert.match(source, /getRunStatus\(state\)/);
  assert.match(source, /Test exit code/);
});

test("document suppresses an unnecessary favicon request", async () => {
  const source = await readFile(indexUrl, "utf8");
  assert.match(source, /rel="icon" href="data:,"/);
});
