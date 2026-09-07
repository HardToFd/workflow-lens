"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const scoring = require("./scoring.js");

function metadata(overrides = {}) {
  const fields = {
    "公式版本": "efficiency-v1", "基准版本": "php-small-v1", "基准分组": "PHP 单项目局部需求 / 固定模型 / S1-S6",
    "基准耗时秒数": 28800, "基准Token": 1000000, "验收项数": 10,
    "基准冻结时间": "2026-09-06T09:00:00+08:00", "基准依据": "plan.md#审批摘要和验收清单",
    "记录核对": "COMPLETE", "返工核对": "COMPLETE", "核对记录数": 1, "核对事件数": 0,
    "核对依据": "verify.md#全流程记录及返工核对",
    ...overrides,
  };
  return "## 综合效率评分依据\n\n" + Object.entries(fields).map(([key, value]) => `- ${key}：${value}`).join("\n") + "\n";
}

function record(duration = 36000, tokenTotal = 1250000, overrides = {}) {
  const start = "2026-09-06T10:00:00+08:00";
  return { stage: "S3", attempt: 1, result: "PASS", start, end: new Date(Date.parse(start) + duration * 1000).toISOString(),
    duration, tokenTotal, tokenSource: "verified exact usage", waitDuration: null, ...overrides };
}

function event(id = "RW-1", overrides = {}) {
  return { id, type: "defect", loop: "L1", project: "php", fromStage: "S4", toStage: "S3", time: "NOT_AVAILABLE",
    reason: "验收断言失败", acceptance: "AC-1", evidence: "verify.md#首次验证", ...overrides };
}

function task(overrides = {}, basis = {}) {
  return { lifecycle: { source: "explicit", state: "ARCHIVED", acceptance: "PASS", issues: [] },
    records: [record()], rework: { events: [], conflicts: [], invalid: [] }, scoreBasis: scoring.parseScoreBasis(metadata(basis)), ...overrides };
}

function close(actual, expected) { assert.ok(Math.abs(actual - expected) < 1e-10, `${actual} != ${expected}`); }
function unavailable(value, reason) {
  const result = scoring.scoreTask(value);
  assert.equal(result.status, "NOT_AVAILABLE");
  assert.equal(result.score, null);
  assert.ok(result.reasons.some((item) => item.includes(reason)), result.reasons.join("; "));
}

test("browser global and CommonJS expose the same three pure operations", () => {
  const context = { window: {} };
  vm.runInNewContext(fs.readFileSync(require.resolve("./scoring.js"), "utf8"), context);
  assert.deepEqual(Object.keys(context.window.WorkflowEfficiency), ["parseScoreBasis", "scoreTask", "scoreOverview"]);
});

test("user example is 81.3 and returns raw unweighted factors", () => {
  const value = task({ rework: { events: [event(), event("RW-2", { loop: "L2", fromStage: "S5" })], conflicts: [], invalid: [] } }, { "核对事件数": 2 });
  const result = scoring.scoreTask(value);
  assert.equal(result.status, "SCORED", result.reasons.join("; "));
  close(result.score, 100 * 0.8 ** 0.35 * 0.8 ** 0.25 * (10 / 12) ** 0.4);
  assert.equal(result.score.toFixed(1), "81.3");
  assert.deepEqual(result.factors, { time: 0.8, token: 0.8, quality: 10 / 12 });
  assert.deepEqual(result.totals, { time: 36000, tokens: 1250000, defects: 2, acceptanceItems: 10 });
});

test("resource factors cap at one and zero is allowed when recorded explicitly", () => {
  for (const row of [record(100, 100), record(0, 0)]) close(scoring.scoreTask(task({ records: [row] })).score, 100);
});

test("more time, tokens or unique defects cannot increase the score", () => {
  const base = scoring.scoreTask(task()).score;
  for (const value of [task({ records: [record(72000)] }), task({ records: [record(36000, 2500000)] }),
    task({ rework: { events: [event()], conflicts: [], invalid: [] } }, { "核对事件数": 1 })]) assert.ok(scoring.scoreTask(value).score < base);
});

test("waiting, old efficiency and old units do not alter the new score", () => {
  const before = scoring.scoreTask(task()).score;
  for (const waitDuration of [null, 0, 12000, 36000]) {
    close(scoring.scoreTask(task({ records: [record(36000, 1250000, { waitDuration, efficiency: 0, acceptedUnits: 9999, reworkUnits: 0 })] })).score, before);
  }
});

test("non-defect events do not penalize quality; repeated identical IDs count once", () => {
  const events = [event("RW-scope", { type: "scope_change", loop: "L3" }), event(), event()];
  const result = scoring.scoreTask(task({ rework: { events, conflicts: [], invalid: [] } }, { "核对事件数": 2 }));
  assert.equal(result.status, "SCORED", result.reasons.join("; "));
  assert.equal(result.totals.defects, 1);
  assert.equal(result.factors.quality, 10 / 11);
});

test("a baseline section and each field must occur exactly once", () => {
  for (const text of ["", metadata() + metadata(), metadata() + "- 基准Token：12\n", metadata().replace("- 核对依据：verify.md#全流程记录及返工核对\n", "")]) {
    assert.equal(scoring.parseScoreBasis(text).valid, false);
  }
  assert.equal(scoring.parseScoreBasis(null).valid, false);
  assert.equal(scoring.parseScoreBasis(metadata().replaceAll("：", ": ").replaceAll("\n", "\r\n")).valid, true);
});

test("invalid, pending, placeholder and unsafe basis values are rejected", () => {
  for (const fields of [{ "基准耗时秒数": 0 }, { "基准Token": 1.5 }, { "验收项数": -1 }, { "核对事件数": "UNKNOWN" },
    { "基准Token": Number.MAX_SAFE_INTEGER + 1 }, { "记录核对": "PENDING" }, { "返工核对": "PENDING" },
    { "基准依据": "<待填>" }, { "核对依据": "`NOT_AVAILABLE`" }, { "公式版本": "efficiency-v2" }, { "旧返工映射": "PENDING" }]) {
    assert.equal(scoring.parseScoreBasis(metadata(fields)).valid, false, JSON.stringify(fields));
  }
});

test("timezones are mandatory, calendar dates valid and frozen baseline predates implementation", () => {
  for (const stamp of ["2026-09-06T09:00:00", "2026-02-30T09:00:00+08:00", "2026-09-06T25:00:00+08:00"]) {
    assert.equal(scoring.parseScoreBasis(metadata({ "基准冻结时间": stamp })).valid, false);
  }
  unavailable(task({}, { "基准冻结时间": "2026-09-06T11:00:00+08:00" }), "实施前冻结");
  assert.equal(scoring.scoreTask(task({}, { "基准冻结时间": "2026-09-06T01:00:00Z" })).status, "SCORED");
  unavailable(task({ records: [record(36000, 1250000, { stage: "S4" })] }), "S3 实施时间");
});

test("explicit accepted archival with no lifecycle conflict is mandatory", () => {
  for (const lifecycle of [undefined, { source: "legacy", state: "ARCHIVED", acceptance: "PASS", issues: [] },
    { source: "explicit", state: "ACTIVE", acceptance: "PASS", issues: [] },
    { source: "explicit", state: "ARCHIVED", acceptance: "UNKNOWN", issues: [] },
    { source: "explicit", state: "ARCHIVED", acceptance: "PASS", issues: ["conflict"] }]) unavailable(task({ lifecycle }), "验收归档");
  unavailable(task({ detail: { delivery: { status: "STALE" } } }), "交付材料已失效");
  assert.equal(scoring.scoreTask(task({ detail: { delivery: { status: "UNVERIFIED" } } })).status, "SCORED");
});

test("unknown zero, unfinished review and new records or events invalidate old review counts", () => {
  unavailable(task({ rework: undefined }), "事件账本");
  unavailable(task({}, { "核对事件数": "NOT_AVAILABLE" }), "核对事件数");
  unavailable(task({ records: [record(), record(1, 1, { stage: "S4" })] }), "核对记录数");
  unavailable(task({ rework: { events: [event()], conflicts: [], invalid: [] } }), "核对事件数");
  unavailable(task({ records: [record(36000, 1250000, { hasLegacyRework: true, legacyReworkCount: 2 })] }), "旧返工数字");
  assert.equal(scoring.scoreTask(task({ records: [record(36000, 1250000, { hasLegacyRework: true })] }, { "旧返工映射": "COMPLETE" })).status, "SCORED");
});

test("all attempts contribute; partial values, bad windows and duplicate attempts refuse a score", () => {
  const value = task({ records: [record(18000, 625000), record(18000, 625000, { attempt: 2 })] }, { "核对记录数": 2 });
  close(scoring.scoreTask(value).score, scoring.scoreTask(task()).score);
  for (const row of [record(36000, null), record(36000, 1.5), record(36000, -1), record(36000, Number.MAX_SAFE_INTEGER + 1),
    record(36000, 1250000, { duration: null }), record(36000, 1250000, { duration: 0.5 }),
    record(36000, 1250000, { tokenSource: "NOT_AVAILABLE" })]) unavailable(task({ records: [row] }), "阶段");
  unavailable(task({ records: [record(), record()] }, { "核对记录数": 2 }), "重复");
  unavailable(task({ records: [record(36000, 1250000, { start: "bad" })] }), "时间窗口");
  unavailable(task({ records: [record(36000, 1250000, { duration: 35000 })] }), "窗口不一致");
  unavailable(task({ records: [record(1, Number.MAX_SAFE_INTEGER), record(1, 1, { attempt: 2 })] }, { "核对记录数": 2 }), "有效范围");
});

test("invalid or conflicting ledger entries cannot silently become zero defects", () => {
  unavailable(task({ rework: { events: [], conflicts: ["RW-1"], invalid: [] } }), "冲突");
  unavailable(task({ rework: { events: [], conflicts: [], invalid: ["RW-1"] } }), "无效");
  unavailable(task({ rework: { events: [event(), event("RW-1", { reason: "different" })], conflicts: [], invalid: [] } }, { "核对事件数": 1 }), "内容冲突");
  unavailable(task({ rework: { events: [event("RW-1", { evidence: "" })], conflicts: [], invalid: [] } }, { "核对事件数": 1 }), "字段无效");
});

test("overview weights unrounded scores by T0 and reports accepted versus all-task coverage", () => {
  const first = task({ records: [record(100, 100)] }, { "基准耗时秒数": 100, "基准Token": 100 });
  const second = task({ records: [record(300, 1600)] }, { "基准耗时秒数": 300, "基准Token": 100 });
  const missing = task({ scoreBasis: scoring.parseScoreBasis("") });
  const active = task({ lifecycle: { source: "explicit", state: "ACTIVE", acceptance: "UNKNOWN", issues: [] } });
  const result = scoring.scoreOverview([first, second, missing, active]);
  close(result.score, 62.5);
  assert.equal(result.scoredCount, 2);
  assert.equal(result.acceptedCount, 3);
  assert.equal(result.totalCount, 4);
  assert.equal(result.coverage, 2 / 3);
  assert.equal(result.allCoverage, 0.5);
  const precise = scoring.scoreOverview([task(), first]);
  close(precise.score, (scoring.scoreTask(task()).score * 28800 + 100 * 100) / 28900);
  assert.notEqual(precise.score, (Number(scoring.scoreTask(task()).score.toFixed(1)) * 28800 + 100 * 100) / 28900);
  assert.equal(scoring.scoreOverview([missing, active]).score, null);
  assert.equal(scoring.scoreOverview([]).coverage, null);
});

test("the dashboard parsers and a real-format metrics section feed the score without special adapters", () => {
  const dashboard = require("./app.js");
  const content = "## S3 · 尝试 1\n\n- 结果：`PASS`\n- 开始：`2026-09-06T10:00:00+08:00`\n"
    + "- 结束：`2026-09-06T20:00:00+08:00`\n- 用时：`36000` 秒\n- 等待秒数：`NOT_AVAILABLE`\n"
    + "- Token 来源：`Codex exact usage`\n- Token：`input=1200000, cached_input=1000000, output=50000, reasoning=10000, total=1250000`\n\n"
    + metadata();
  const value = task({ records: dashboard.parseMetrics(content), rework: dashboard.parseReworkEvents(content), scoreBasis: scoring.parseScoreBasis(content) });
  assert.equal(value.records.length, 1);
  close(scoring.scoreTask(value).score, scoring.scoreTask(task()).score);
});

test("missing metadata reports the prerequisite without cascading dependent errors", () => {
  const result = scoring.scoreTask(task({ records: [], scoreBasis: scoring.parseScoreBasis("") }));
  assert.deepEqual(result.reasons, ["缺少综合效率评分依据", "没有完整阶段记录"]);
  const independent = scoring.scoreTask(task({ scoreBasis: null, records: [record(1, null)] }));
  assert.ok(independent.reasons.includes("阶段记录存在缺失或无效的耗时/Token"));
  assert.ok(!independent.reasons.some((reason) => /冻结|核对记录数|核对事件数/.test(reason)));
});
