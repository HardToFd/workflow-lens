"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const dashboard = require("./app.js");

function stage(fields = {}, phase = "S3", attempt = 1) {
  return `## ${phase} · 尝试 ${attempt}\n` + Object.entries(fields).map(([key, value]) => `- ${key}：\`${value}\``).join("\n") + "\n";
}

function event(id = "RW-20260906-01", overrides = {}) {
  const fields = {
    类型: "defect", 回路: "L1", 项目: "example", 来源阶段: "S4", 目标阶段: "S3",
    事件时间: "2026-09-06T10:00:00+08:00", 原因: "验收断言失败", 关联验收: "AC-1", 证据: "verify.md:12",
    ...overrides,
  };
  return `## 返工事件 ${id}\n` + Object.entries(fields).map(([key, value]) => `- ${key}：${["原因", "关联验收", "证据"].includes(key) ? value : `\`${value}\``}`).join("\n") + "\n";
}

test("stable lifecycle wins over stage and free text", () => {
  assert.equal(dashboard.statusMeta({ phase: "S6", status: "已取消", lifecycle: { state: "ACTIVE" } }).key, "active");
  assert.equal(dashboard.statusMeta({ phase: "S3", status: "完成", lifecycle: { state: "ARCHIVED" } }).key, "archived");
  assert.equal(dashboard.statusMeta({ phase: "S3", detail: { lifecycle: { state: "CANCELLED" } } }).key, "cancelled");
  assert.deepEqual(dashboard.statusMeta({ phase: "S4", lifecycle: { state: "WAITING" } }), { key: "blocked", label: "等待" });
  assert.equal(dashboard.statusMeta({ phase: "S3", lifecycle: { state: "BLOCKED" } }).key, "blocked");
});

test("legacy local completion stays active or blocked until S6 or explicit cancellation", () => {
  assert.equal(dashboard.statusMeta({ phase: "S3", status: "已完成本地实现和定向回归" }).key, "active");
  assert.equal(dashboard.statusMeta({ phase: "S4", status: "本地测试完成，等待外部联测" }).key, "blocked");
  assert.equal(dashboard.statusMeta({ phase: "S6", status: "已完成本地验收" }).key, "archived");
  assert.equal(dashboard.statusMeta({ phase: "S3", status: "已取消（范围调整）" }).key, "cancelled");
  assert.equal(dashboard.statusMeta({ phase: "S3", status: "需求已作废" }).key, "cancelled");
  assert.equal(dashboard.statusMeta({ phase: "S3", status: "未取消，已完成取消按钮" }).key, "active");
  assert.deepEqual(dashboard.statusMeta({ phase: "S6", status: "BLOCKED" }), { key: "blocked", label: "阻塞" });
  assert.deepEqual(dashboard.statusMeta({ phase: "S6", status: "WAITING" }), { key: "blocked", label: "等待" });
  assert.deepEqual(dashboard.statusMeta({ phase: "S6", status: "等待清理授权" }), { key: "blocked", label: "等待" });
  assert.equal(dashboard.statusMeta({ phase: "S6", status: "BLOCKED", lifecycle: { state: "ARCHIVED" } }).key, "archived");
});

test("archived stage does not imply acceptance, merge, deployment or cleanup", () => {
  assert.ok(dashboard.lifecycleEvidence({ phase: "S6" }).every((field) => field.value === "UNKNOWN"));
  const fields = Object.fromEntries(dashboard.lifecycleEvidence({ lifecycle: {
    state: "ARCHIVED", closure_reason: "ACCEPTED_NO_MR", delivery_form: "LOCAL",
    acceptance: "PASS", merge: "NOT_MERGED", deployment: "NOT_RUN", cleanup: "RETAINED",
  } }).map(({ label, value }) => [label, value]));
  assert.equal(fields["验收"], "通过");
  assert.equal(fields["合入"], "未合入");
  assert.equal(fields["部署验证"], "NOT_RUN");
  assert.equal(fields["清理"], "保留");
});

test("numbers preserve missing and explicit zero without extracting digits from prose", () => {
  for (const value of [undefined, "", "NOT_AVAILABLE", "UNKNOWN", "约 12 秒", "12abc", "-2", "1e3", "9007199254740992"]) {
    assert.equal(dashboard.parseMetricNumber(value), null, String(value));
  }
  assert.equal(dashboard.parseMetricNumber("0"), 0);
  assert.equal(dashboard.parseMetricNumber("12.5 秒", "seconds"), 12.5);
  assert.equal(dashboard.parseMetricNumber("12.5 s", "seconds"), 12.5);
  assert.equal(dashboard.parseMetricNumber("`12.5` 秒", "seconds"), 12.5);
  assert.equal(dashboard.parseMetricNumber("12 秒"), null);
  const records = dashboard.parseMetrics(stage({ 用时: "NOT_AVAILABLE", Token: "NOT_AVAILABLE", 等待秒数: "NOT_AVAILABLE", 返工次数: "" }) + stage({ 用时: "0 秒", Token: "input=0, output=0, total=0", 等待秒数: "0" }, "S4"));
  assert.deepEqual(records.map(({ duration, tokenTotal, waitDuration }) => [duration, tokenTotal, waitDuration]), [[null, null, null], [0, 0, 0]]);
  assert.equal(dashboard.parseMetrics("## S3 · 尝试 1\n- 用时：`126` 秒\n")[0].duration, 126);
});

test("blank fields do not consume following lines and CRLF works", () => {
  const text = "- 用时：\r\n- Token：`input=1, total=2`\r\n- 备注：保留原文\r\n";
  assert.equal(dashboard.fieldValue(text, "用时"), "");
  assert.equal(dashboard.fieldValue(text, "Token"), "input=1, total=2");
  assert.equal(dashboard.fieldValue(text, "备注"), "保留原文");
});

test("event sections cannot supply missing stage metrics", () => {
  const text = stage({ 结果: "BLOCKED" }, "S4") + event() + "- 用时：`999 秒`\n- Token：`total=999`\n" + stage({ 用时: "5 秒", Token: "total=100" }, "S3", 2);
  const rows = dashboard.parseMetrics(text);
  assert.equal(rows.length, 2);
  assert.equal(rows[0].duration, null);
  assert.equal(rows[0].tokenTotal, null);
  assert.equal(rows[1].duration, 5);
  assert.equal(rows[1].tokenTotal, 100);
  assert.equal(dashboard.parseReworkEvents(text).events.length, 1);
});

test("identical event IDs are idempotent; distinct IDs count independently", () => {
  const rework = dashboard.parseReworkEvents(event() + event() + event("RW-02"));
  assert.equal(rework.events.length, 2);
  assert.equal(rework.duplicates, 1);
  assert.equal(dashboard.reworkSummary({ rework }).count, 2);
});

test("free text preserves Markdown backticks and remains idempotent", () => {
  for (const value of ["`payload.user_id` was missing", "`foo`"]) {
    const text = event("RW-markdown", { 原因: `  ${value}  `, 关联验收: value, 证据: value });
    const rework = dashboard.parseReworkEvents(text + text);
    assert.equal(rework.events.length, 1);
    assert.equal(rework.events[0].reason, value);
    assert.equal(rework.events[0].acceptance, value);
    assert.equal(rework.events[0].evidence, value);
    assert.equal(rework.duplicates, 1);
    assert.equal(dashboard.reworkSummary({ rework }).count, 1);
    assert.deepEqual(rework.conflicts, []);
  }
});

test("conflicting IDs are excluded and never silently presented as a complete count", () => {
  const rework = dashboard.parseReworkEvents(event() + event("RW-20260906-01", { 原因: "另一条原因" }) + event("RW-valid"));
  const summary = dashboard.reworkSummary({ rework });
  assert.deepEqual(rework.conflicts, ["RW-20260906-01"]);
  assert.equal(rework.events.length, 1);
  assert.equal(summary.count, null);
  assert.equal(summary.l1Count, null);
  assert.equal(summary.knownCount, 1);
  assert.match(dashboard.eventCountLabel(summary), /待核对/);
  assert.match(dashboard.reworkCoverageNote(summary), /冲突 ID：RW-20260906-01/);
});

test("incomplete events are visibly invalid and not counted", () => {
  const rework = dashboard.parseReworkEvents(event("RW-no-evidence", { 证据: "" }) + event("RW-no-time", { 事件时间: "" }));
  const summary = dashboard.reworkSummary({ rework });
  assert.equal(summary.count, null);
  assert.deepEqual(rework.invalid, ["RW-no-evidence", "RW-no-time"]);
  assert.match(dashboard.reworkCoverageNote(summary), /无效事件/);
  assert.equal(dashboard.parseReworkEvents(event("RW-no-timestamp", { 事件时间: "NOT_AVAILABLE" })).events.length, 1);
  assert.deepEqual(dashboard.parseReworkEvents(event("RW-repeated-field") + "- 类型：`scope_change`\n").invalid, ["RW-repeated-field"]);
  assert.deepEqual(dashboard.parseReworkEvents(event("RW-no-zone", { 事件时间: "2026-09-06T10:00:00" })).invalid, ["RW-no-zone"]);
  assert.deepEqual(dashboard.parseReworkEvents(event("RW-not-defect", { 类型: "scope_change" })).invalid, ["RW-not-defect"]);
  assert.deepEqual(dashboard.parseReworkEvents(event("RW-wrong-loop", { 来源阶段: "S2", 目标阶段: "S1" })).invalid, ["RW-wrong-loop"]);
  assert.equal(dashboard.parseReworkEvents(event("R".repeat(64))).events.length, 1);
  assert.deepEqual(dashboard.parseReworkEvents(event("R".repeat(65))).invalid, ["R".repeat(65)]);
  assert.deepEqual(dashboard.parseReworkEvents(event("RW-invalid-date", { 事件时间: "2026-02-30T10:00:00+08:00" })).invalid, ["RW-invalid-date"]);
});

test("L1 quality count requires both defect and L1; stage attribution uses source stage", () => {
  const rework = dashboard.parseReworkEvents(event("RW-L1") + event("RW-L2", { 回路: "L2", 来源阶段: "S2", 目标阶段: "S1" }) + event("RW-scope", { 类型: "scope_change", 回路: "L3" }));
  const summary = dashboard.reworkSummary({ rework });
  assert.equal(summary.count, 3);
  assert.equal(summary.l1Count, 1);
  assert.equal(dashboard.reworkSummary({ rework }, "S4").count, 2);
  assert.equal(dashboard.reworkSummary({ rework }, "S3").count, 0);
  assert.equal(dashboard.reworkSummary({ rework }, "S2").l1Count, 0);
});

test("equivalent timezone representations deduplicate by instant", () => {
  const rework = dashboard.parseReworkEvents(event() + event("RW-20260906-01", { 事件时间: "2026-09-06T02:00:00Z" }));
  assert.equal(rework.events.length, 1);
  assert.equal(rework.duplicates, 1);
  assert.deepEqual(rework.conflicts, []);
});

test("legacy repeated or cumulative rounds and FAIL records do not become independent events", () => {
  const text = [1, 1, 3].map((count, i) => stage({ 返工次数: count, 结果: "FAIL", 有效产出单元: "100", 返工影响单元: "1", 效率比: "99%" }, "S3", i + 1)).join("");
  const records = dashboard.parseMetrics(text);
  const task = { records, rework: dashboard.parseReworkEvents(text) };
  assert.deepEqual(records.map((record) => record.legacyReworkCount), [1, 1, 3]);
  const aggregate = dashboard.aggregateTask(task);
  assert.equal(aggregate.rework.count, null);
  assert.equal(aggregate.rework.legacyRecordCount, 3);
  assert.match(dashboard.reworkCoverageNote(aggregate.rework), /3 条 legacy/);
  assert.equal(dashboard.eventCountLabel(aggregate.rework), "NOT_AVAILABLE");
  assert.equal(dashboard.parseMetrics(stage({ 返工次数: "0" }))[0].hasLegacyRework, false);
  for (const model of [aggregate, dashboard.buildMetricModel(task)]) {
    assert.equal(Object.hasOwn(model, "efficiency"), false);
    assert.equal(Object.hasOwn(model, "reworkCount"), false);
    assert.equal(Object.hasOwn(model, "reworkUnits"), false);
  }
});

test("partial totals include explicit zero while preserving missing coverage and waiting", () => {
  const records = [
    { stage: "S3", duration: 10, tokenTotal: 100, waitDuration: null },
    { stage: "S3", duration: null, tokenTotal: null, waitDuration: null },
    { stage: "S4", duration: 0, tokenTotal: 0, waitDuration: null },
  ];
  const aggregate = dashboard.aggregateTask({ records });
  assert.deepEqual([aggregate.duration, aggregate.durationCoverage, aggregate.tokens, aggregate.tokenCoverage], [10, 2, 100, 2]);
  assert.equal(aggregate.waitDuration, null);
  assert.equal(aggregate.waitCoverage, 0);
  assert.equal(dashboard.waitingLabel(aggregate.waitDuration), "NOT_AVAILABLE");
  assert.match(dashboard.recordedMetricLabel(aggregate.tokens, 2, 3, dashboard.formatTokens), /部分/);
  const model = dashboard.buildMetricModel({ records });
  assert.equal(model.rows.find((row) => row.stage === "S3").tokens, 100);
  assert.equal(model.rows.find((row) => row.stage === "S3").tokenCoverage, 1);
  assert.equal(model.rows.find((row) => row.stage === "S4").tokens, 0);
  assert.equal(model.rows.find((row) => row.stage === "S6").tokens, null);
  records[2].waitDuration = 0;
  assert.equal(dashboard.aggregateTask({ records }).waitDuration, 0);
  assert.equal(dashboard.aggregateTask({ records }).waitCoverage, 1);
});

test("empty and wholly missing metrics never produce zero totals", () => {
  for (const records of [[], [{ stage: "S3", duration: null, tokenTotal: null }]]) {
    const aggregate = dashboard.aggregateTask({ records });
    assert.equal(aggregate.duration, null);
    assert.equal(aggregate.tokens, null);
    assert.equal(aggregate.waitDuration, null);
    assert.equal(aggregate.rework.count, null);
  }
});

test("overview sums recorded intervals across lifecycle states, not completion-text averages", () => {
  const model = dashboard.overviewMetricModel([
    { id: "active", status: "已完成本地实现", records: [{ stage: "S3", duration: 100, tokenTotal: 20 }] },
    { id: "archived", lifecycle: { state: "ARCHIVED" }, records: [{ stage: "S6", duration: 200, tokenTotal: null }] },
  ]);
  assert.equal(model.duration, 300);
  assert.equal(model.tokens, 20);
  assert.equal(model.tokenCoverage, 1);
  assert.equal(model.records.length, 2);
});
