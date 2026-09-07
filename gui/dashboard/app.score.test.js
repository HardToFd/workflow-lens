"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const scoring = require("./scoring.js");
const app = require("./app.js");

const metricsFixture = `# Test-only scoring fixture

## 综合效率评分依据
- 公式版本：efficiency-v1
- 基准版本：test-v1
- 基准分组：test-small-change
- 基准耗时秒数：200
- 基准Token：1000
- 验收项数：4
- 基准冻结时间：2026-09-07T08:00:00+08:00
- 基准依据：fixture baseline approved before implementation
- 记录核对：COMPLETE
- 返工核对：COMPLETE
- 核对依据：fixture has two stages and no rework event
- 核对记录数：2
- 核对事件数：0

## S3 · 尝试 1
- 结果：PASS
- 开始：2026-09-07T09:00:00+08:00
- 结束：2026-09-07T09:03:20+08:00
- 用时：200 秒
- 等待秒数：30
- Token：input=1000, output=100, total=1100
- Token 来源：fixture-source

## S4 · 尝试 1
- 结果：PASS
- 开始：2026-09-07T09:04:00+08:00
- 结束：2026-09-07T09:05:40+08:00
- 用时：100 秒
- Token：input=350, output=50, total=400
- Token 来源：fixture-source
`;

function taskFixture(content = metricsFixture) {
  return {
    id: "fixture-scored", title: "Fixture scored task", phase: "S6",
    lifecycle: { source: "explicit", state: "ARCHIVED", acceptance: "PASS", issues: [] },
    records: app.parseMetrics(content), rework: app.parseReworkEvents(content),
    scoreBasis: scoring.parseScoreBasis(content),
  };
}

test("actual artifact loading parses the score basis for the pure scoring module", async () => {
  const priorFetch = globalThis.fetch;
  const priorScoring = globalThis.WorkflowEfficiency;
  const fixture = taskFixture();
  const calls = [];
  globalThis.WorkflowEfficiency = scoring;
  globalThis.fetch = async (url) => {
    calls.push(url);
    const payload = url.endsWith("/artifacts/metrics.md") ? { content: metricsFixture } : {
      lifecycle: fixture.lifecycle, artifacts: [{ name: "metrics.md", exists: true, readable: true }],
    };
    return { ok: true, json: async () => payload };
  };
  try {
    const enriched = await app.enrichTask({ id: fixture.id, title: fixture.title, phase: "S6" });
    assert.equal(enriched.scoreBasis.valid, true);
    assert.equal(enriched.scoreBasis.baselineTime, 200);
    assert.equal(enriched.scoreBasis.acceptanceItems, 4);
    assert.equal(enriched.records.length, 2);
    assert.equal(scoring.scoreTask(enriched).status, "SCORED");
    assert.deepEqual(calls, ["/api/tasks/fixture-scored", "/api/tasks/fixture-scored/artifacts/metrics.md"]);
  } finally {
    globalThis.fetch = priorFetch;
    if (priorScoring === undefined) delete globalThis.WorkflowEfficiency;
    else globalThis.WorkflowEfficiency = priorScoring;
  }
});

test("scored detail renders engine output, three raw factors and distinct waiting guidance", () => {
  const task = taskFixture();
  const result = scoring.scoreTask(task);
  assert.equal(result.status, "SCORED");
  const html = app.efficiencyDetailMarkup(task, result);
  assert.ok(html.includes(`<strong>${result.score.toFixed(1)}</strong>`));
  assert.ok(html.includes(`${(result.factors.time * 100).toFixed(1)}%`));
  assert.ok(html.includes(`${(result.factors.token * 100).toFixed(1)}%`));
  assert.ok(html.includes(`${(result.factors.quality * 100).toFixed(1)}%`));
  assert.match(html, /时间系数 · 35%/);
  assert.match(html, /Token 系数 · 25%/);
  assert.match(html, /质量系数 · 40%/);
  assert.match(html, /T₀ 200 秒 \/ T 300 秒/);
  assert.match(html, /显式等待不再次相加/);
  assert.match(html, /test-v1 \/ test-small-change/);
  assert.doesNotMatch(html, /暂不可评分/);
});

test("missing historical basis stays N/A and preserves every exclusion reason", () => {
  const task = taskFixture(metricsFixture.slice(metricsFixture.indexOf("## S3")));
  const result = scoring.scoreTask(task);
  assert.equal(result.status, "NOT_AVAILABLE");
  const html = app.efficiencyDetailMarkup(task, result);
  assert.match(html, /<strong>N\/A<\/strong>/);
  assert.match(html, /未纳入综合分/);
  assert.match(html, /历史缺失基准保持 N\/A/);
  for (const reason of result.reasons) assert.ok(html.includes(reason), reason);
  assert.doesNotMatch(html, /<strong>0(?:\.0)?<\/strong>/);
});

test("overview scope includes scored and excluded tasks rather than hiding ineligible rows", () => {
  const scored = taskFixture();
  const active = { ...taskFixture(), id: "fixture-active", title: "Still active", lifecycle: { source: "explicit", state: "ACTIVE", acceptance: "PASS", issues: [] } };
  const missing = { ...taskFixture(), id: "fixture-missing", title: "Missing baseline", scoreBasis: scoring.parseScoreBasis("") };
  const tasks = [scored, active, missing];
  const overview = scoring.scoreOverview(tasks);
  const html = app.efficiencyScopeMarkup(tasks, overview);
  assert.equal(overview.scoredCount, 1);
  assert.equal(overview.acceptedCount, 2);
  assert.equal(overview.totalCount, 3);
  assert.match(html, /fixture-scored · 已纳入/);
  assert.match(html, /fixture-active · 未纳入 · N\/A/);
  assert.match(html, /fixture-missing · 未纳入 · N\/A/);
  for (const reason of overview.results[1].reasons) assert.ok(html.includes(reason));
  for (const reason of overview.results[2].reasons) assert.ok(html.includes(reason));
});

test("artifact-provided titles, evidence and reasons are escaped in scoring markup", () => {
  const task = taskFixture();
  task.title = '<img src=x onerror="alert(1)">';
  task.scoreBasis.evidence = "<script>unsafe()</script>";
  const result = { status: "NOT_AVAILABLE", score: null, reasons: ["<script>reason()</script>"] };
  for (const html of [app.efficiencyDetailMarkup(task, result), app.efficiencyScopeMarkup([task], { results: [result] })]) {
    assert.doesNotMatch(html, /<script>|<img /);
    assert.match(html, /&lt;script&gt;reason\(\)&lt;\/script&gt;/);
  }
});

test("empty score and missing scoring module are explicit N/A states", () => {
  assert.equal(app.scoreValue(null), "N/A");
  assert.equal(app.scoreValue(undefined), "N/A");
  assert.equal(app.scoreValue(0), "0.0");
  assert.match(app.efficiencyScopeMarkup([], { results: [] }), /评分覆盖为 N\/A/);
  assert.match(app.efficiencyScopeMarkup([taskFixture()], { results: [] }), /评分模块未加载/);
});

test("browser loads scoring before app and keeps the existing process ledger", () => {
  const html = fs.readFileSync(path.join(__dirname, "index.html"), "utf8");
  assert.ok(html.indexOf('src="/scoring.js"') < html.indexOf('src="/app.js"'));
  assert.match(html, /id="efficiency-overview-value"/);
  assert.match(html, /id="efficiency-detail-body"/);
  assert.match(html, /id="metric-rework"/);
  assert.match(html, /id="metric-token-range"/);
});
