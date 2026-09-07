"use strict";

const STAGES = ["S1", "S2", "S3", "S4", "S5", "S6"];
const STAGE_NAMES = {
  S1: "解析与影响面",
  S2: "技术方案",
  S3: "实现",
  S4: "验证",
  S5: "交付",
  S6: "归档收尾",
};
const ARTIFACT_STAGE = {
  "analysis.md": "S1",
  "plan.md": "S2",
  "impl-log.md": "S3",
  "verify.md": "S4",
  "delivery.md": "S5",
  "state.md": "S6",
};
const STATUS_ORDER = { blocked: 0, active: 1, archived: 2, cancelled: 3 };
const REWORK_TYPES = { defect: "实现缺陷", scope_change: "范围变更", baseline_adaptation: "基线适配", environment: "环境阻塞", workflow_migration: "流程迁移" };
const TIMELINE_MIN_SCALE = 1;
const TIMELINE_MAX_SCALE = 3;
const numberFormat = new Intl.NumberFormat("zh-CN");
const compactNumberFormat = new Intl.NumberFormat("zh-CN", { notation: "compact", maximumFractionDigits: 1 });
const dateFormat = new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit" });
const dateTimeFormat = new Intl.DateTimeFormat("zh-CN", {
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

const state = {
  tasks: [],
  view: "overview",
  selectedTaskId: null,
  selectedEvent: -1,
  timelineCamera: { scale: 1, fitScale: 1, x: 0, y: 0, mode: "fit", drag: null, resizeFrame: 0 },
  drawerOpen: true,
  inspectorTrigger: null,
  inspectorTimer: null,
  metricTaskId: null,
  metricStage: null,
  filters: { search: "", time: "all", status: "all", sort: "updated-desc" },
  commandIndex: 0,
  commandItems: [],
};

const elements = typeof document === "undefined" ? {} : {
  appShell: document.querySelector("#app-shell"),
  sidebar: document.querySelector("#sidebar"),
  sidebarScrim: document.querySelector("#sidebar-scrim"),
  sidebarToggle: document.querySelector("#sidebar-toggle"),
  mobileMenu: document.querySelector("#mobile-menu"),
  sourceState: document.querySelector("#source-state"),
  sourceDetail: document.querySelector("#source-detail"),
  sourcePulse: document.querySelector(".source-pulse"),
  viewContext: document.querySelector("#view-context"),
  contextTitle: document.querySelector("#context-title"),
  overviewView: document.querySelector("#overview-view"),
  analysisView: document.querySelector("#analysis-view"),
  refreshButton: document.querySelector("#refresh-button"),
  errorBanner: document.querySelector("#error-banner"),
  errorMessage: document.querySelector("#error-message"),
  errorRetry: document.querySelector("#error-retry"),
  liveRegion: document.querySelector("#live-region"),
  lastUpdated: document.querySelector("#last-updated"),
  coverageValue: document.querySelector("#coverage-value"),
  coverageCaption: document.querySelector("#coverage-caption"),
  metricTotal: document.querySelector("#metric-total"),
  metricTotalNote: document.querySelector("#metric-total-note"),
  metricDurationAverage: document.querySelector("#metric-duration-average"),
  metricDurationRange: document.querySelector("#metric-duration-range"),
  metricTokenAverage: document.querySelector("#metric-token-average"),
  metricTokenRange: document.querySelector("#metric-token-range"),
  metricEfficiency: document.querySelector("#metric-efficiency"),
  metricRework: document.querySelector("#metric-rework"),
  trendChart: document.querySelector("#trend-chart"),
  trendSummary: document.querySelector("#trend-summary"),
  trendTable: document.querySelector("#trend-table"),
  statusChart: document.querySelector("#status-chart"),
  ganttChart: document.querySelector("#gantt-chart"),
  ganttTable: document.querySelector("#gantt-table"),
  categoryChart: document.querySelector("#category-chart"),
  reworkList: document.querySelector("#rework-list"),
  stageChart: document.querySelector("#stage-chart"),
  analysisCount: document.querySelector("#analysis-count"),
  analysisLayout: document.querySelector("#analysis-layout"),
  demandDrawer: document.querySelector("#demand-drawer"),
  demandDrawerToggle: document.querySelector("#demand-drawer-toggle"),
  demandDrawerClose: document.querySelector("#demand-drawer-close"),
  demandDrawerScrim: document.querySelector("#demand-drawer-scrim"),
  demandSearch: document.querySelector("#demand-search"),
  timeFilter: document.querySelector("#time-filter"),
  statusFilter: document.querySelector("#status-filter"),
  sortFilter: document.querySelector("#sort-filter"),
  demandList: document.querySelector("#demand-list"),
  detailEmpty: document.querySelector("#detail-empty"),
  detailContent: document.querySelector("#detail-content"),
  detailId: document.querySelector("#detail-id"),
  detailTitle: document.querySelector("#detail-title"),
  detailBadges: document.querySelector("#detail-badges"),
  detailDuration: document.querySelector("#detail-duration"),
  detailTokens: document.querySelector("#detail-tokens"),
  detailEfficiency: document.querySelector("#detail-efficiency"),
  timelineCaption: document.querySelector("#timeline-caption"),
  timelineViewport: document.querySelector("#timeline-viewport"),
  timelineScale: document.querySelector("#timeline-scale"),
  timelinePlane: document.querySelector("#timeline-plane"),
  canvasInspector: document.querySelector("#canvas-inspector"),
  inspectorTitle: document.querySelector("#inspector-title"),
  inspectorClose: document.querySelector("#inspector-close"),
  eventDetail: document.querySelector("#event-detail"),
  metricDrilldown: document.querySelector("#metric-drilldown"),
  metricDrilldownCaption: document.querySelector("#metric-drilldown-caption"),
  metricDrilldownSource: document.querySelector("#metric-drilldown-source"),
  metricDrilldownKpis: document.querySelector("#metric-drilldown-kpis"),
  efficiencyOverview: document.querySelector("#efficiency-overview"),
  efficiencyOverviewValue: document.querySelector("#efficiency-overview-value"),
  efficiencyOverviewCoverage: document.querySelector("#efficiency-overview-coverage"),
  efficiencyOverviewNote: document.querySelector("#efficiency-overview-note"),
  efficiencyOverviewScope: document.querySelector("#efficiency-overview-scope"),
  efficiencyDetail: document.querySelector("#efficiency-detail"),
  efficiencyDetailBody: document.querySelector("#efficiency-detail-body"),
  tokenCompositionChart: document.querySelector("#token-composition-chart"),
  durationDistributionChart: document.querySelector("#duration-distribution-chart"),
  metricStageDetailTitle: document.querySelector("#metric-stage-detail-title"),
  metricStageDetailCaption: document.querySelector("#metric-stage-detail-caption"),
  metricStageDetailBody: document.querySelector("#metric-stage-detail-body"),
  metricStageTable: document.querySelector("#metric-stage-table"),
  artifactTabs: document.querySelector("#artifact-tabs"),
  artifactContent: document.querySelector("#artifact-content"),
  commandTrigger: document.querySelector("#command-trigger"),
  commandDialog: document.querySelector("#command-dialog"),
  commandInput: document.querySelector("#command-input"),
  commandResults: document.querySelector("#command-results"),
};

function escapeHtml(value = "") {
  return String(value).replace(/[&<>'"]/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "'": "&#39;",
    '"': "&quot;",
  })[character]);
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function parseDate(value) {
  if (!value) return null;
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function taskDate(task) {
  const match = task.id.match(/(?:PRD-)?(20\d{2})(\d{2})(\d{2})/);
  if (match) {
    const parsed = new Date(`${match[1]}-${match[2]}-${match[3]}T00:00:00+08:00`);
    if (!Number.isNaN(parsed.getTime())) return parsed;
  }
  return parseDate(task.updated_at);
}

function formatDate(value) {
  const parsed = value instanceof Date ? value : parseDate(value);
  return parsed ? dateFormat.format(parsed) : "日期缺失";
}

function formatDateTime(value) {
  const parsed = value instanceof Date ? value : parseDate(value);
  return parsed ? dateTimeFormat.format(parsed) : "—";
}

function formatCanvasStart(value) {
  const parsed = value instanceof Date ? value : parseDate(value);
  return parsed ? dateTimeFormat.format(parsed) : "未记录";
}

function canvasStartMarkup(value, className, prefix) {
  const parsed = parseDate(value);
  const label = formatCanvasStart(parsed);
  if (!parsed) return `<span class="${className}">${escapeHtml(`${prefix} · ${label}`)}</span>`;
  return `<time class="${className}" datetime="${escapeHtml(value)}">${escapeHtml(`${prefix} · ${label}`)}</time>`;
}

function formatDuration(seconds) {
  if (!Number.isFinite(seconds)) return "—";
  if (seconds < 60) return `${Math.round(seconds)} 秒`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} 分`;
  if (seconds < 86400) {
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.round((seconds % 3600) / 60);
    return minutes ? `${hours} 小时 ${minutes} 分` : `${hours} 小时`;
  }
  const days = Math.floor(seconds / 86400);
  const hours = Math.round((seconds % 86400) / 3600);
  return hours ? `${days} 天 ${hours} 小时` : `${days} 天`;
}

function formatTokens(value) {
  return Number.isFinite(value) ? compactNumberFormat.format(value) : "—";
}

function recordedMetricLabel(value, coverage, total, formatter) {
  return formatter(value) + (Number.isFinite(value) && coverage < total ? "（部分）" : "");
}

function waitingLabel(value) {
  return Number.isFinite(value) ? formatDuration(value) : "NOT_AVAILABLE";
}

function formatPercent(value) {
  return Number.isFinite(value) ? `${(value * 100).toFixed(1)}%` : "—";
}

function statusMeta(task) {
  const lifecycle = task.lifecycle || task.detail?.lifecycle;
  const stable = {
    ACTIVE: { key: "active", label: "进行中" },
    BLOCKED: { key: "blocked", label: "阻塞" },
    WAITING: { key: "blocked", label: "等待" },
    ARCHIVED: { key: "archived", label: "已归档" },
    CANCELLED: { key: "cancelled", label: "已作废" },
  };
  if (stable[lifecycle?.state]) return stable[lifecycle.state];
  const value = String(task.status || "").toLowerCase();
  if (/(?:^|[（(；;，,\s])(?:需求)?(?:已)?(?:作废|取消|cancelled|canceled)(?:$|[（(）)；;，,。\s])/.test(value)) return stable.CANCELLED;
  if (/blocked|阻塞/.test(value)) return stable.BLOCKED;
  if (/waiting|等待|^待/.test(value)) return stable.WAITING;
  // 旧记录只能按阶段归档；“本地实现完成”等说明不改变 S3/S4 的生命周期。
  if (task.phase === "S6") return stable.ARCHIVED;
  return { key: "active", label: "进行中" };
}

function lifecycleEvidence(task) {
  const lifecycle = task.lifecycle || task.detail?.lifecycle || {};
  const fields = [
    ["closure_reason", "关闭原因", { ACCEPTED_NO_MR: "无 MR 验收", MERGED: "已合入", CANCELLED: "作废", NONE: "未关闭" }],
    ["delivery_form", "交付", { BRANCH: "分支", PATCH: "补丁", LOCAL: "本地", MIXED: "混合", NONE: "无" }],
    ["acceptance", "验收", { PASS: "通过", NOT_RUN: "NOT_RUN" }],
    ["merge", "合入", { MERGED: "已合入", NOT_MERGED: "未合入" }],
    ["deployment", "部署验证", { VERIFIED: "已验证", NOT_RUN: "NOT_RUN" }],
    ["cleanup", "清理", { COMPLETE: "完成", PENDING: "待处理", RETAINED: "保留" }],
  ];
  return fields.map(([key, label, labels]) => ({ label, value: labels[lifecycle[key]] || "UNKNOWN" }));
}

function classifyCategory(task) {
  const value = `${task.id} ${task.title}`.toLowerCase();
  if (/feature|产品|功能|交互|creative|content/.test(value)) return "产品功能";
  if (/dashboard|report|看板|报表|素材汇总/.test(value)) return "报表与看板";
  if (/queue|队列|click|同步|orgid/.test(value)) return "数据链路";
  if (/alert|预警|监控/.test(value)) return "监控告警";
  if (/download|下载|folder|目录/.test(value)) return "平台工具";
  return "其他需求";
}

async function api(path) {
  const response = await fetch(path, { headers: { Accept: "application/json" }, cache: "no-store" });
  let payload = null;
  try {
    payload = await response.json();
  } catch {
    payload = {};
  }
  if (!response.ok) throw new Error(payload.error || `请求失败：${response.status}`);
  return payload;
}

function fieldValue(block, label) {
  const expression = new RegExp(`^- ${escapeRegExp(label)}[：:][ \\t]*(?:\u0060([^\u0060\\r\\n]*)\u0060|([^\\r\\n]*))[ \\t]*\\r?$`, "m");
  const match = block.match(expression);
  return match ? (match[1] ?? match[2] ?? "").trim() : "";
}

function parseMetricNumber(value, unit = "") {
  let text = String(value ?? "").trim();
  // 兼容 metrics-record 的历史格式：数值在反引号内，秒单位在外。
  if (unit === "seconds") text = text.replace(/^`(\d+(?:\.\d+)?)`\s*(秒|s)$/, "$1 $2");
  const suffix = unit === "seconds" ? "(?:\\s*(?:秒|s))?" : "";
  if (!new RegExp(`^\\d+(?:\\.\\d+)?${suffix}$`).test(text)) return null;
  const number = Number(text.replace(/\s*(?:秒|s)$/, ""));
  return Number.isFinite(number) && number >= 0 && number <= Number.MAX_SAFE_INTEGER ? number : null;
}

function metricsSections(content) {
  const headers = [...String(content || "").matchAll(/^##[ \t]+([^\r\n]+)[ \t]*\r?$/gm)];
  return headers.map((match, index) => ({
    heading: match[1].trim(),
    block: content.slice(match.index + match[0].length, headers[index + 1]?.index ?? content.length),
  }));
}

function parseMetrics(content) {
  return metricsSections(content).flatMap(({ heading, block }) => {
    const match = heading.match(/^(S[1-6])\s+·\s+尝试\s+(\d+)$/);
    if (!match) return [];
    const tokenLine = fieldValue(block, "Token");
    const tokenMatch = tokenLine.match(/(?:^|,\s*)total=(\d+)(?=\s*(?:,|$))/);
    const efficiencyText = fieldValue(block, "效率比");
    const efficiencyValue = /^\d+(?:\.\d+)?%$/.test(efficiencyText) ? parseMetricNumber(efficiencyText.slice(0, -1)) : null;
    const efficiency = Number.isFinite(efficiencyValue) ? efficiencyValue / 100 : null;
    return {
      stage: match[1],
      attempt: Number(match[2]),
      result: fieldValue(block, "结果") || "UNKNOWN",
      start: fieldValue(block, "开始"),
      end: fieldValue(block, "结束"),
      duration: parseMetricNumber(fieldValue(block, "用时"), "seconds"),
      waitDuration: parseMetricNumber(fieldValue(block, "等待秒数")),
      tokenSource: fieldValue(block, "Token 来源"),
      tokenTotal: tokenMatch ? parseMetricNumber(tokenMatch[1]) : null,
      legacyReworkCount: parseMetricNumber(fieldValue(block, "返工次数")),
      hasLegacyRework: parseMetricNumber(fieldValue(block, "返工次数")) > 0,
      acceptedUnits: parseMetricNumber(fieldValue(block, "有效产出单元")),
      reworkUnits: parseMetricNumber(fieldValue(block, "返工影响单元")),
      efficiency: Number.isFinite(efficiency) && efficiency <= 1 ? efficiency : null,
      note: fieldValue(block, "备注"),
      source: "metrics.md",
    };
  });
}

function parseReworkEvents(content) {
  const grouped = new Map();
  const labels = ["类型", "回路", "项目", "来源阶段", "目标阶段", "事件时间", "原因", "关联验收", "证据"];
  metricsSections(content).forEach(({ heading, block }) => {
    const match = heading.match(/^返工事件\s+(.+)$/);
    if (!match) return;
    // 自由文本原样保留 Markdown；只有结构化字段由工具包裹反引号。
    const rawValue = (label) => (block.match(new RegExp(`^- ${escapeRegExp(label)}[：:][ \\t]*([^\\r\\n]*)`, "m"))?.[1] || "").trim();
    const event = {
      id: match[1].trim(), type: fieldValue(block, "类型"), loop: fieldValue(block, "回路"),
      project: fieldValue(block, "项目"), fromStage: fieldValue(block, "来源阶段"), toStage: fieldValue(block, "目标阶段"),
      time: fieldValue(block, "事件时间"), reason: rawValue("原因"),
      acceptance: rawValue("关联验收"), evidence: rawValue("证据"),
    };
    const timestamp = event.time === "NOT_AVAILABLE" ? null : parseDate(event.time);
    const timeParts = event.time.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/);
    // Date 会把 2 月 30 日滚入 3 月；事件账本需拒绝这种非法日期。
    const validCalendar = timeParts && Number(timeParts[1]) >= 1 && Number(timeParts[2]) >= 1 && Number(timeParts[2]) <= 12
      && Number(timeParts[3]) >= 1 && Number(timeParts[3]) <= new Date(Date.UTC(Number(timeParts[1]), Number(timeParts[2]), 0)).getUTCDate()
      && Number(timeParts[4]) < 24 && Number(timeParts[5]) < 60 && Number(timeParts[6]) < 60;
    const valid = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/.test(event.id)
      && labels.every((label) => [...block.matchAll(new RegExp(`^- ${escapeRegExp(label)}[：:]`, "gm"))].length === 1)
      && Object.values(event).every((value) => !/[\u0000-\u001f]/.test(value))
      && Object.hasOwn(REWORK_TYPES, event.type) && ["L1", "L2", "L3", "NONE"].includes(event.loop)
      && STAGES.includes(event.fromStage) && STAGES.includes(event.toStage)
      && (event.loop !== "L1" || (event.type === "defect" && event.fromStage === "S4" && event.toStage === "S3"))
      && event.project && event.reason && event.acceptance && event.evidence
      && (event.time === "NOT_AVAILABLE" || (validCalendar && timestamp));
    // 事件时间按同一时刻比较；不因等价时区写法误报同 ID 冲突。
    if (valid && timestamp) event.time = new Date(timestamp.getTime() + 8 * 3600000).toISOString().replace(/\.\d{3}Z$/, "+08:00");
    const rows = grouped.get(event.id) || [];
    rows.push({ event, valid: Boolean(valid), signature: JSON.stringify(event) });
    grouped.set(event.id, rows);
  });
  const events = [], conflicts = [], invalid = [];
  let duplicates = 0;
  grouped.forEach((rows, id) => {
    if (new Set(rows.map((row) => row.signature)).size > 1) conflicts.push(id);
    else if (rows.some((row) => !row.valid)) invalid.push(id);
    else { events.push(rows[0].event); duplicates += rows.length - 1; }
  });
  return { events, conflicts, invalid, duplicates };
}

function reworkSummary(task, stage = null) {
  const source = task.rework || { events: [], conflicts: [], invalid: [] };
  const events = source.events.filter((event) => !stage || event.fromStage === stage);
  const knownL1 = events.filter((event) => event.type === "defect" && event.loop === "L1").length;
  const uncertain = source.conflicts.length + source.invalid.length;
  const records = (task.records || []).filter((record) => !stage || record.stage === stage);
  return {
    events, conflicts: source.conflicts, invalid: source.invalid, knownCount: events.length, knownL1,
    count: source.events.length && !uncertain ? events.length : null,
    l1Count: source.events.length && !uncertain ? knownL1 : null,
    legacyRecordCount: records.filter((record) => record.hasLegacyRework).length,
  };
}

function eventCountLabel(summary) {
  if (summary.conflicts.length || summary.invalid.length) return `待核对（已知 ${summary.knownCount}）`;
  return Number.isFinite(summary.count) ? numberFormat.format(summary.count) : "NOT_AVAILABLE";
}

function reworkCoverageNote(summary) {
  const notes = [`L1 缺陷 ${Number.isFinite(summary.l1Count) ? summary.l1Count : "NOT_AVAILABLE"}`];
  if (summary.legacyRecordCount) notes.push(`${summary.legacyRecordCount} 条 legacy 阶段未按事件 ID 对齐`);
  if (summary.conflicts.length) notes.push(`冲突 ID：${summary.conflicts.join("、")}`);
  if (summary.invalid.length) notes.push(`无效事件：${summary.invalid.join("、")}`);
  return notes.join(" · ");
}

function aggregateTask(task) {
  const records = task.records || [];
  const durations = sumAvailable(records, "duration"), tokens = sumAvailable(records, "tokenTotal"), waits = sumAvailable(records, "waitDuration");
  return {
    duration: durations.total, durationCoverage: durations.count,
    tokens: tokens.total, tokenCoverage: tokens.count,
    waitDuration: waits.total, waitCoverage: waits.count,
    rework: reworkSummary(task),
  };
}

async function enrichTask(task) {
  try {
    const detail = await api(`/api/tasks/${encodeURIComponent(task.id)}`);
    const metrics = detail.artifacts.find((artifact) => artifact.name === "metrics.md");
    let records = [];
    let rework = parseReworkEvents("");
    let metricsText = "";
    if (metrics?.exists && metrics.readable !== false) {
      const artifact = await api(`/api/tasks/${encodeURIComponent(task.id)}/artifacts/metrics.md`);
      metricsText = artifact.content || "";
      records = parseMetrics(artifact.content);
      rework = parseReworkEvents(artifact.content);
    }
    const scoreBasis = globalThis.WorkflowEfficiency?.parseScoreBasis(metricsText) || null;
    const enriched = { ...task, detail, lifecycle: detail.lifecycle || task.lifecycle, records, rework, scoreBasis };
    enriched.aggregate = aggregateTask(enriched);
    enriched.statusMeta = statusMeta(enriched);
    enriched.category = classifyCategory(enriched);
    enriched.eventDate = taskDate(enriched);
    return enriched;
  } catch (error) {
    const enriched = {
      ...task,
      detail: { id: task.id, title: task.title, top: {}, projects: [], artifacts: [], diagnostic: error.message },
      records: [],
      loadError: error.message,
    };
    enriched.aggregate = aggregateTask(enriched);
    enriched.statusMeta = statusMeta(enriched);
    enriched.category = classifyCategory(enriched);
    enriched.eventDate = taskDate(enriched);
    return enriched;
  }
}

function setConnection(mode, detail) {
  elements.sourcePulse.classList.remove("is-ready", "is-error");
  elements.sourceState.textContent = mode === "ready" ? "本地证据已连接" : mode === "error" ? "本地证据异常" : "连接本地数据";
  elements.sourceDetail.textContent = detail;
  if (mode === "ready") elements.sourcePulse.classList.add("is-ready");
  if (mode === "error") elements.sourcePulse.classList.add("is-error");
}

function setLoading(loading) {
  elements.refreshButton.dataset.state = loading ? "loading" : "default";
  elements.refreshButton.disabled = loading;
  elements.refreshButton.setAttribute("aria-busy", String(loading));
  if (loading) setConnection("loading", "READING STATE + METRICS");
}

function showError(message) {
  elements.errorMessage.textContent = `${message} 请确认 dashboard_server.py 正在运行并指向正确工作区。`;
  elements.errorBanner.hidden = false;
  setConnection("error", "READ FAILED");
}

function clearError() {
  elements.errorBanner.hidden = true;
}

async function loadDashboard() {
  setLoading(true);
  clearError();
  try {
    const payload = await api("/api/tasks");
    state.tasks = await Promise.all((payload.tasks || []).map(enrichTask));
    if (!state.selectedTaskId || !state.tasks.some((task) => task.id === state.selectedTaskId)) {
      state.selectedTaskId = state.tasks.find((task) => task.statusMeta.key === "blocked")?.id || state.tasks[0]?.id || null;
    }
    renderAll();
    const metricCount = state.tasks.filter((task) => task.records.length).length;
    setConnection("ready", `${state.tasks.length} TASKS · ${metricCount} METRICS`);
    const now = new Date();
    elements.lastUpdated.textContent = `更新 ${dateTimeFormat.format(now)}`;
    elements.liveRegion.textContent = `已读取 ${state.tasks.length} 个需求，其中 ${metricCount} 个包含过程度量。`;
  } catch (error) {
    showError(error.message);
  } finally {
    setLoading(false);
  }
}

function overviewMetricModel(tasks) {
  const records = tasks.flatMap((task) => task.records || []);
  const rework = { events: [], conflicts: [], invalid: [] };
  tasks.forEach((task) => {
    rework.events.push(...(task.rework?.events || []));
    rework.conflicts.push(...(task.rework?.conflicts || []).map((id) => `${task.id}/${id}`));
    rework.invalid.push(...(task.rework?.invalid || []).map((id) => `${task.id}/${id}`));
  });
  return { records, ...aggregateTask({ records, rework }) };
}

function scoreValue(value, decimals = 1) {
  return Number.isFinite(value) ? value.toFixed(decimals) : "N/A";
}

function scoreNumber(value) {
  return Number.isFinite(value) ? numberFormat.format(value) : "N/A";
}

function scoreReasonsMarkup(reasons) {
  return `<ul>${reasons.map((reason) => `<li>${escapeHtml(reason)}</li>`).join("")}</ul>`;
}

function efficiencyScopeMarkup(tasks, overview) {
  if (!tasks.length) return '<p class="score-note">当前没有需求，评分覆盖为 N/A。</p>';
  return `<ul>${tasks.map((task, index) => {
    const result = overview.results[index];
    const scored = result?.status === "SCORED" && Number.isFinite(result.score);
    return `<li><strong>${escapeHtml(task.title || task.id)}</strong><span>${escapeHtml(task.id)} · ${scored ? `已纳入 · ${scoreValue(result.score)} 分 · T₀ ${scoreNumber(result.baselineTime)} 秒` : "未纳入 · N/A"}</span>${scored ? "" : scoreReasonsMarkup(result?.reasons || ["评分模块未加载，请刷新页面。"])}</li>`;
  }).join("")}</ul>`;
}

function renderEfficiencyOverview() {
  const overview = globalThis.WorkflowEfficiency?.scoreOverview(state.tasks);
  const scored = overview && Number.isFinite(overview.score);
  elements.efficiencyOverview.dataset.scoreStatus = scored ? "SCORED" : "NOT_AVAILABLE";
  elements.efficiencyOverviewValue.textContent = scoreValue(overview?.score);
  if (!overview) {
    elements.efficiencyOverviewCoverage.textContent = "评分模块未加载";
    elements.efficiencyOverviewNote.textContent = "刷新页面以加载评分模块；现有过程记录可继续查看。";
    elements.efficiencyOverviewScope.innerHTML = efficiencyScopeMarkup(state.tasks, { results: [] });
    return;
  }
  elements.efficiencyOverviewCoverage.textContent = `已验收归档覆盖 ${overview.scoredCount} / ${overview.acceptedCount}（${Number.isFinite(overview.coverage) ? formatPercent(overview.coverage) : "N/A"}）`;
  elements.efficiencyOverviewNote.textContent = `全部需求覆盖 ${overview.scoredCount} / ${overview.totalCount}（${Number.isFinite(overview.allCoverage) ? formatPercent(overview.allCoverage) : "N/A"}） · ${scored ? "仅汇总有效样本，分数上限 100。" : "暂无可评分样本；缺失依据保持 N/A。"}`;
  elements.efficiencyOverviewScope.innerHTML = efficiencyScopeMarkup(state.tasks, overview);
}

function efficiencyDetailMarkup(task, result) {
  const scored = result.status === "SCORED" && Number.isFinite(result.score);
  const basis = task.scoreBasis || {};
  const totals = result.totals || {};
  const factors = result.factors || {};
  const coefficient = (value) => Number.isFinite(value) ? formatPercent(value) : "N/A";
  const components = [
    { name: "时间系数", weight: "35%", value: factors.time, note: `T₀ ${scoreNumber(basis.baselineTime)} 秒 / T ${scoreNumber(totals.time)} 秒` },
    { name: "Token 系数", weight: "25%", value: factors.token, note: `K₀ ${scoreNumber(basis.baselineTokens)} / K ${scoreNumber(totals.tokens)}` },
    { name: "质量系数", weight: "40%", value: factors.quality, note: `冻结验收项 N ${scoreNumber(totals.acceptanceItems ?? basis.acceptanceItems)} · 缺陷事件 R ${scoreNumber(totals.defects)}` },
  ];
  const metadata = [
    ["基准版本 / 分组", [basis.baselineVersion, basis.baselineGroup].filter(Boolean).join(" / ") || "N/A"],
    ["冻结时间", basis.frozenAt || "N/A"],
    ["基准依据", basis.evidence || "N/A"],
    ["完整性核对证据", basis.reviewEvidence || "N/A"],
  ];
  return `<div class="score-summary"><div class="score-readout"><h5>当前需求</h5><div><strong>${scored ? scoreValue(result.score) : "N/A"}</strong><span>/ 100</span></div><p>${scored ? "已纳入综合分" : "未纳入综合分"}</p></div><div class="score-components">${components.map((component) => `<article class="score-component"><h5>${component.name} · ${component.weight}</h5><strong>${coefficient(component.value)}</strong><p>${escapeHtml(component.note)}</p></article>`).join("")}</div></div>${scored ? "" : `<div class="score-reasons"><strong>暂不可评分</strong>${scoreReasonsMarkup(result.reasons || [])}<p>仅按已有证据补齐 metrics.md 中的「综合效率评分依据」；历史缺失基准保持 N/A。</p></div>`}<dl class="score-basis">${metadata.map(([label, value]) => `<div><dt>${label}</dt><dd>${escapeHtml(value)}</dd></div>`).join("")}</dl><div class="score-formula"><code>E = 100 × (T₀ / max(T₀, T))^0.35 × (K₀ / max(K₀, K))^0.25 × (N / (N + R))^0.40</code><p>T 汇总全部尝试的记录区间，包含区间内等待；显式等待不再次相加。K 为全部尝试的 Token。R 按唯一 ID 统计全部回路的 defect 事件，N 为冻结验收项数。</p><p>低于基准不额外加分，最高 100 分；整体按可评分需求的 T₀ 加权。</p></div>`;
}

function renderEfficiencyDetail(task) {
  const result = globalThis.WorkflowEfficiency?.scoreTask(task) || { status: "NOT_AVAILABLE", score: null, reasons: ["评分模块未加载，请刷新页面。"] };
  elements.efficiencyDetail.dataset.scoreStatus = result.status;
  elements.efficiencyDetailBody.innerHTML = efficiencyDetailMarkup(task, result);
}

function renderMetrics() {
  renderEfficiencyOverview();
  const metricTasks = state.tasks.filter((task) => task.records.length);
  const model = overviewMetricModel(state.tasks);
  const archived = state.tasks.filter((task) => task.statusMeta.key === "archived").length;
  elements.metricTotal.textContent = numberFormat.format(state.tasks.length);
  elements.metricTotalNote.textContent = `${archived} 已归档；验收、合入和部署分别记录`;
  elements.metricDurationAverage.textContent = recordedMetricLabel(model.duration, model.durationCoverage, model.records.length, formatDuration);
  elements.metricDurationRange.textContent = `${model.durationCoverage}/${model.records.length} 个区间 · 显式等待 ${Number.isFinite(model.waitDuration) ? formatDuration(model.waitDuration) : "NOT_AVAILABLE"}（${model.waitCoverage}/${model.records.length}）`;
  elements.metricTokenAverage.textContent = recordedMetricLabel(model.tokens, model.tokenCoverage, model.records.length, formatTokens);
  elements.metricTokenRange.textContent = `${model.tokenCoverage}/${model.records.length} 条有数值 · ${model.tokenCoverage === model.records.length && model.records.length ? "已记录值合计" : "部分合计，缺失未补零"}`;
  elements.metricEfficiency.textContent = eventCountLabel(model.rework);
  elements.metricRework.textContent = reworkCoverageNote(model.rework);
  elements.coverageValue.textContent = `${metricTasks.length}/${state.tasks.length || 0}`;
  elements.coverageCaption.textContent = state.tasks.length ? `${((metricTasks.length / state.tasks.length) * 100).toFixed(1)}% 的需求有阶段记录` : "没有需求";
}

function trendPoints() {
  const grouped = new Map();
  state.tasks.forEach((task) => {
    if (!task.eventDate) return;
    const key = task.eventDate.toISOString().slice(0, 10);
    grouped.set(key, (grouped.get(key) || 0) + 1);
  });
  let cumulative = 0;
  return [...grouped.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([date, count]) => {
    cumulative += count;
    return { date, count, cumulative };
  });
}

function renderTrend() {
  const points = trendPoints();
  if (!points.length) {
    elements.trendChart.innerHTML = '<div class="empty-inline"><strong>没有可用日期</strong><span>PRD id 与更新时间均未提供可解析日期。</span></div>';
    elements.trendTable.innerHTML = "";
    return;
  }
  const width = 720;
  const height = 240;
  const left = 48;
  const right = 24;
  const top = 28;
  const bottom = 44;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const max = Math.max(...points.map((point) => point.cumulative), 1);
  const coordinates = points.map((point, index) => ({
    ...point,
    x: left + (points.length === 1 ? plotWidth / 2 : index * (plotWidth / (points.length - 1))),
    y: top + plotHeight - (point.cumulative / max) * plotHeight,
  }));
  const path = coordinates.map((point, index) => `${index ? "L" : "M"}${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(" ");
  const grid = [0, 0.5, 1].map((ratio) => {
    const y = top + plotHeight * ratio;
    const value = Math.round(max * (1 - ratio));
    return `<line class="chart-grid" x1="${left}" y1="${y}" x2="${width - right}" y2="${y}"/><text class="chart-label" x="${left - 10}" y="${y + 4}" text-anchor="end">${value}</text>`;
  }).join("");
  const dots = coordinates.map((point, index) => {
    const showLabel = index === 0 || index === coordinates.length - 1 || index % Math.ceil(coordinates.length / 4) === 0;
    return `<g><circle class="chart-point" cx="${point.x}" cy="${point.y}" r="4"><title>${escapeHtml(point.date)} · 累计 ${point.cumulative}</title></circle>${showLabel ? `<text class="chart-label" x="${point.x}" y="${height - 14}" text-anchor="middle">${escapeHtml(formatDate(point.date))}</text>` : ""}</g>`;
  }).join("");
  elements.trendChart.innerHTML = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-labelledby="trend-svg-title trend-svg-desc"><title id="trend-svg-title">需求累计趋势</title><desc id="trend-svg-desc">从 ${escapeHtml(points[0].date)} 到 ${escapeHtml(points.at(-1).date)}，累计 ${points.at(-1).cumulative} 个需求。</desc>${grid}<path class="chart-line" d="${path}"/>${dots}<text class="chart-value" x="${coordinates.at(-1).x}" y="${coordinates.at(-1).y - 12}" text-anchor="end">${points.at(-1).cumulative}</text></svg>`;
  elements.trendSummary.textContent = `${formatDate(points[0].date)} 至 ${formatDate(points.at(-1).date)}，累计 ${points.at(-1).cumulative} 个需求`;
  elements.trendTable.innerHTML = `<table><thead><tr><th>日期</th><th>新增</th><th>累计</th></tr></thead><tbody>${points.map((point) => `<tr><td>${escapeHtml(point.date)}</td><td>${point.count}</td><td>${point.cumulative}</td></tr>`).join("")}</tbody></table>`;
}

function renderStatus() {
  const counts = { archived: 0, active: 0, blocked: 0, cancelled: 0 };
  state.tasks.forEach((task) => { counts[task.statusMeta.key] += 1; });
  const total = Math.max(state.tasks.length, 1);
  const entries = [
    ["archived", "已归档"],
    ["active", "进行中"],
    ["blocked", "阻塞 / 等待"],
    ["cancelled", "已作废"],
  ];
  elements.statusChart.innerHTML = `<div class="status-track" aria-hidden="true">${entries.map(([key]) => `<span class="status-segment status-segment--${key}" style="width:${(counts[key] / total) * 100}%"></span>`).join("")}</div><div class="status-legend">${entries.map(([key, label]) => `<div><span class="status-symbol status-symbol--${key}" aria-hidden="true"></span><span>${label}</span><strong>${counts[key]}</strong></div>`).join("")}</div>`;
}

function renderBarList(target, entries, emptyMessage) {
  if (!entries.length) {
    target.innerHTML = `<div class="empty-inline"><strong>没有可用数据</strong><span>${escapeHtml(emptyMessage)}</span></div>`;
    return;
  }
  const max = Math.max(...entries.map((entry) => entry.value), 1);
  target.innerHTML = entries.map((entry) => `<div class="bar-row"><div class="bar-row__head"><span>${escapeHtml(entry.label)}</span><strong>${numberFormat.format(entry.value)}</strong></div><div class="bar-track" aria-hidden="true"><div class="bar-fill" style="--bar-scale:${entry.value / max}"></div></div></div>`).join("");
}

function renderCategories() {
  const counts = new Map();
  state.tasks.forEach((task) => counts.set(task.category, (counts.get(task.category) || 0) + 1));
  const entries = [...counts.entries()].map(([label, value]) => ({ label, value })).sort((a, b) => b.value - a.value);
  renderBarList(elements.categoryChart, entries, "没有可分类的需求标题。");
}

function renderStages() {
  const counts = STAGES.map((stage) => ({ label: stage, value: state.tasks.filter((task) => task.phase === stage).length }));
  renderBarList(elements.stageChart, counts, "state.md 未提供当前环节。");
}

function renderRework() {
  const events = state.tasks.flatMap((task) => (task.rework?.events || []).map((event) => ({ task, event })));
  const summary = overviewMetricModel(state.tasks).rework;
  const warning = `<p class="event-note">${escapeHtml(reworkCoverageNote(summary))}。仅展示已登记事件，不估算历史返工总数。</p>`;
  if (!events.length) {
    elements.reworkList.innerHTML = '<div class="empty-inline"><strong>未提供可计数的返工事件</strong><span>NOT_AVAILABLE；旧阶段轮次数与 FAIL 记录不直接计作独立事件。</span></div>' + warning;
    return;
  }
  const grouped = new Map();
  events.forEach(({ task, event }) => {
    const reason = REWORK_TYPES[event.type];
    const group = grouped.get(reason) || { reason, count: 0, samples: [] };
    group.count += 1;
    if (group.samples.length < 2) group.samples.push(`${task.id} · ${event.id} · ${event.loop} · ${event.reason}`);
    grouped.set(reason, group);
  });
  const rows = [...grouped.values()].sort((a, b) => b.count - a.count);
  elements.reworkList.innerHTML = rows.map((row) => `<article class="rework-item"><strong>${escapeHtml(row.reason)} · ${row.count} 个已登记事件</strong>${row.samples.map((sample) => `<span title="${escapeHtml(sample)}">${escapeHtml(sample)}</span>`).join("")}</article>`).join("") + warning;
}

function assignGanttLanes(records, visibleSpan = 0) {
  const laneEnds = [];
  const minimumVisibleDuration = visibleSpan * 0.045;
  return records.map((record) => {
    const recordStart = parseDate(record.start).getTime();
    const recordEnd = parseDate(record.end).getTime();
    let lane = laneEnds.findIndex((laneEnd) => laneEnd <= recordStart);
    if (lane < 0) lane = laneEnds.length;
    laneEnds[lane] = Math.max(recordEnd, recordStart + minimumVisibleDuration);
    return { record, lane };
  });
}

function renderGantt() {
  const rows = state.tasks.map((task) => ({
    task,
    records: task.records
      .filter((record) => parseDate(record.start) && parseDate(record.end))
      .sort((a, b) => parseDate(a.start).getTime() - parseDate(b.start).getTime()),
  })).filter((row) => row.records.length).sort((a, b) => parseDate(a.records[0].start).getTime() - parseDate(b.records[0].start).getTime());
  const allRecords = rows.flatMap((row) => row.records);
  if (!allRecords.length) {
    elements.ganttChart.innerHTML = '<div class="empty-inline"><strong>没有可核验阶段窗口</strong><span>metrics.md 缺少完整的开始与结束时间。</span></div>';
    elements.ganttTable.innerHTML = "";
    return;
  }
  const start = Math.min(...allRecords.map((record) => parseDate(record.start).getTime()));
  const end = Math.max(...allRecords.map((record) => parseDate(record.end).getTime()));
  const span = Math.max(end - start, 1);
  const tickCount = 5;
  const ticks = Array.from({ length: tickCount }, (_, index) => {
    const ratio = index / (tickCount - 1);
    const time = new Date(start + (span * ratio));
    return { left: ratio * 100, label: formatDateTime(time) };
  });
  const tickMarkup = ticks.map((tick, index) => `<span class="gantt-tick gantt-tick--${index === 0 ? "start" : index === tickCount - 1 ? "end" : "middle"}" style="--tick-left:${tick.left}%"><i aria-hidden="true"></i><time>${escapeHtml(tick.label)}</time></span>`).join("");
  const axis = `<div class="gantt-axis"><div class="gantt-axis__meta"><span>需求泳道</span><span>共享时间轴</span></div><div class="gantt-axis__timeline">${tickMarkup}</div></div>`;
  const groups = rows.map(({ task, records }) => {
    const assignedRecords = assignGanttLanes(records, span);
    const laneCount = Math.max(...assignedRecords.map(({ lane }) => lane), 0) + 1;
    const taskStart = records[0].start;
    const taskEnd = records.reduce((latest, record) => parseDate(record.end).getTime() > parseDate(latest).getTime() ? record.end : latest, records[0].end);
    const overviewBars = assignedRecords.map(({ record, lane }) => {
      const recordStart = parseDate(record.start).getTime();
      const recordEnd = parseDate(record.end).getTime();
      const left = ((recordStart - start) / span) * 100;
      const width = Math.max(((recordEnd - recordStart) / span) * 100, 0.05);
      const description = `${record.stage} 尝试 ${record.attempt} · ${record.result} · ${formatDateTime(record.start)} 至 ${formatDateTime(record.end)}`;
      return `<span class="gantt-overview-bar" role="img" aria-label="${escapeHtml(description)}" data-result="${escapeHtml(record.result)}" style="--bar-left:${left}%;--bar-width:${width}%;--bar-lane:${lane}" title="${escapeHtml(description)}"><b>${escapeHtml(record.stage)}</b></span>`;
    }).join("");
    const recordRows = records.map((record) => {
      const recordStart = parseDate(record.start).getTime();
      const recordEnd = parseDate(record.end).getTime();
      const left = ((recordStart - start) / span) * 100;
      const width = Math.max(((recordEnd - recordStart) / span) * 100, 0.05);
      const description = `${record.stage} 尝试 ${record.attempt} · ${record.result} · ${formatDateTime(record.start)} 至 ${formatDateTime(record.end)} · ${formatDuration(record.duration)}`;
      return `<div class="gantt-record"><div class="gantt-record__meta"><strong>${escapeHtml(record.stage)} · 尝试 ${escapeHtml(record.attempt)}</strong><span><b class="gantt-result" data-result="${escapeHtml(record.result)}">${escapeHtml(record.result)}</b><small>${escapeHtml(formatDuration(record.duration))}</small></span></div><div class="gantt-track">${ticks.map((tick) => `<i class="gantt-gridline" aria-hidden="true" style="--tick-left:${tick.left}%"></i>`).join("")}<span class="gantt-bar" role="img" aria-label="${escapeHtml(description)}" data-result="${escapeHtml(record.result)}" style="--bar-left:${left}%;--bar-width:${width}%" title="${escapeHtml(description)}"></span></div></div>`;
    }).join("");
    const open = rows.length === 1 ? " open" : "";
    return `<details class="gantt-group"${open}><summary class="gantt-demand-row" style="--lane-count:${laneCount}"><div class="gantt-demand__meta"><span class="gantt-disclosure" aria-hidden="true">›</span><span><strong title="${escapeHtml(task.title)}">${escapeHtml(task.title)}</strong><small>${escapeHtml(task.id)} · ${escapeHtml(task.statusMeta.label)} · ${numberFormat.format(records.length)} 条记录</small></span></div><div class="gantt-demand-track" aria-label="${escapeHtml(`${formatDateTime(taskStart)} 至 ${formatDateTime(taskEnd)}`)}">${ticks.map((tick) => `<i class="gantt-gridline" aria-hidden="true" style="--tick-left:${tick.left}%"></i>`).join("")}${overviewBars}</div></summary><div class="gantt-records" aria-label="${escapeHtml(task.id)} 阶段明细">${recordRows}</div></details>`;
  }).join("");
  elements.ganttChart.innerHTML = `<div class="gantt-canvas">${axis}${groups}</div>`;
  elements.ganttTable.innerHTML = `<table><thead><tr><th>需求</th><th>阶段</th><th>结果</th><th>开始</th><th>结束</th><th>用时</th></tr></thead><tbody>${rows.flatMap(({ task, records }) => records.map((record) => `<tr><td>${escapeHtml(task.id)}</td><td>${escapeHtml(record.stage)} · ${escapeHtml(record.attempt)}</td><td>${escapeHtml(record.result)}</td><td>${escapeHtml(record.start)}</td><td>${escapeHtml(record.end)}</td><td>${escapeHtml(formatDuration(record.duration))}</td></tr>`)).join("")}</tbody></table>`;
}

function renderOverview() {
  renderMetrics();
  renderTrend();
  renderStatus();
  renderGantt();
  renderCategories();
  renderRework();
  renderStages();
}

function filteredTasks() {
  const now = Date.now();
  const query = state.filters.search.trim().toLowerCase();
  const filtered = state.tasks.filter((task) => {
    if (query && !`${task.id} ${task.title}`.toLowerCase().includes(query)) return false;
    if (state.filters.status !== "all" && task.statusMeta.key !== state.filters.status) return false;
    if (state.filters.time !== "all") {
      if (!task.eventDate) return false;
      const cutoff = now - Number(state.filters.time) * 86400000;
      if (task.eventDate.getTime() < cutoff) return false;
    }
    return true;
  });
  return filtered.sort((a, b) => {
    if (state.filters.sort === "updated-asc") return (a.eventDate?.getTime() || 0) - (b.eventDate?.getTime() || 0);
    if (state.filters.sort === "status") return STATUS_ORDER[a.statusMeta.key] - STATUS_ORDER[b.statusMeta.key] || a.id.localeCompare(b.id);
    if (state.filters.sort === "duration-desc") return (b.aggregate.duration ?? -1) - (a.aggregate.duration ?? -1);
    return (b.eventDate?.getTime() || 0) - (a.eventDate?.getTime() || 0);
  });
}

function renderDemandList() {
  const tasks = filteredTasks();
  elements.analysisCount.textContent = `${tasks.length} / ${state.tasks.length} 个需求`;
  if (!tasks.length) {
    elements.demandList.innerHTML = '<div class="empty-inline"><strong>没有匹配需求</strong><span>调整时间、状态或搜索条件。</span></div>';
    return;
  }
  elements.demandList.innerHTML = tasks.map((task) => `<button class="demand-card${task.id === state.selectedTaskId ? " is-active" : ""}" type="button" data-task-id="${escapeHtml(task.id)}" aria-pressed="${task.id === state.selectedTaskId}"><span class="demand-card__title" title="${escapeHtml(task.title)}">${escapeHtml(task.title)}</span><span class="demand-card__meta"><span>${escapeHtml(task.statusMeta.label)} · ${escapeHtml(task.phase || "未开始")}</span><span>${escapeHtml(formatDate(task.eventDate))}</span></span><span class="demand-card__metrics"><span>${recordedMetricLabel(task.aggregate.duration, task.aggregate.durationCoverage, task.records.length, formatDuration)}</span><span>${recordedMetricLabel(task.aggregate.tokens, task.aggregate.tokenCoverage, task.records.length, formatTokens)} Token</span></span></button>`).join("");
}

function fallbackTimeline(task) {
  const artifacts = task.detail.artifacts || [];
  const records = artifacts.filter((artifact) => artifact.exists && ARTIFACT_STAGE[artifact.name]).map((artifact) => ({
    stage: ARTIFACT_STAGE[artifact.name],
    attempt: 1,
    result: "EVIDENCE",
    start: "",
    end: "",
    duration: null,
    tokenTotal: null,
    efficiency: null,
    waitDuration: null,
    legacyReworkCount: null,
    acceptedUnits: null,
    reworkUnits: null,
    note: `${artifact.label} 已存在；metrics.md 未提供该阶段时间。`,
    source: artifact.name,
  }));
  if (!records.length && task.phase && STAGES.includes(task.phase)) {
    records.push({ stage: task.phase, attempt: 1, result: "CURRENT", duration: null, tokenTotal: null, efficiency: null, note: "仅 state.md 提供当前环节。", source: "state.md" });
  }
  return records.sort((a, b) => STAGES.indexOf(a.stage) - STAGES.indexOf(b.stage));
}

function detailEvents(task) {
  return task.records.length ? task.records : fallbackTimeline(task);
}

function summarizeStage(events, stage) {
  const stageEvents = events.filter((event) => event.stage === stage);
  const latest = stageEvents.at(-1) || null;
  const durations = sumAvailable(stageEvents, "duration"), tokens = sumAvailable(stageEvents, "tokenTotal");
  const earliestStart = stageEvents.reduce((earliest, event) => {
    const parsed = parseDate(event.start);
    if (!parsed) return earliest;
    if (!earliest || parsed.getTime() < earliest.time) return { value: event.start, time: parsed.getTime() };
    return earliest;
  }, null);
  return {
    events: stageEvents,
    latest,
    start: earliestStart?.value || "",
    duration: durations.total, durationCoverage: durations.count,
    tokens: tokens.total, tokenCoverage: tokens.count,
    waitDuration: sumAvailable(stageEvents, "waitDuration").total,
  };
}

function workflowGroupHeight(attemptCount) {
  const rows = Math.max(1, Math.ceil(attemptCount / 2));
  return 92 + 46 + rows * 72 + Math.max(0, rows - 1) * 8 + 16;
}

function workflowTransitionKey(transition) {
  return `${transition.fromSequence}-${transition.toSequence}`;
}

function workflowLayout(events, reworkTransitions) {
  const groupWidth = 286;
  const columnGap = 56;
  const paddingX = 48;
  const returnTrackTop = 52;
  const returnTrackGap = 38;
  const rankedTransitions = [...reworkTransitions].sort((left, right) => {
    const leftSpan = STAGES.indexOf(left.from) - STAGES.indexOf(left.to);
    const rightSpan = STAGES.indexOf(right.from) - STAGES.indexOf(right.to);
    return rightSpan - leftSpan || left.fromSequence - right.fromSequence;
  });
  const returnLanes = new Map(rankedTransitions.map((transition, index) => [workflowTransitionKey(transition), index]));
  const topY = reworkTransitions.length
    ? returnTrackTop + Math.max(0, reworkTransitions.length - 1) * returnTrackGap + 52
    : 52;
  const attemptCounts = Object.fromEntries(STAGES.map((stage) => [stage, events.filter((event) => event.stage === stage).length]));
  const groupHeight = Math.max(...STAGES.map((stage) => workflowGroupHeight(attemptCounts[stage])));
  const width = paddingX * 2 + groupWidth * STAGES.length + columnGap * (STAGES.length - 1);
  const height = topY + groupHeight + 48;
  const positions = new Map(STAGES.map((stage, index) => {
    return [stage, {
      stage,
      column: index,
      x: paddingX + index * (groupWidth + columnGap),
      y: topY,
      width: groupWidth,
      summaryHeight: 92,
    }];
  }));
  return { width, height, positions, returnLanes, returnTrackTop, returnTrackGap, topY };
}

function workflowMainRoute(from, to) {
  return `M${from.x + from.width},${from.y + from.summaryHeight / 2} H${to.x}`;
}

function workflowReworkTransitions(events) {
  return events.slice(1).flatMap((event, index) => {
    const previous = events[index];
    if (STAGES.indexOf(event.stage) >= STAGES.indexOf(previous.stage)) return [];
    return [{
      from: previous.stage,
      to: event.stage,
      fromSequence: index + 1,
      toSequence: index + 2,
      fromResult: previous.result,
      toResult: event.result,
    }];
  });
}

function workflowReworkRoute(transition, layout) {
  const from = layout.positions.get(transition.from);
  const to = layout.positions.get(transition.to);
  const lane = layout.returnLanes.get(workflowTransitionKey(transition)) || 0;
  const fromX = from.x + from.width / 2;
  const targetOffset = (lane - (layout.returnLanes.size - 1) / 2) * 22;
  const toX = to.x + to.width / 2 + targetOffset;
  const channelY = layout.returnTrackTop + lane * layout.returnTrackGap;
  const label = `返工 ${transition.from} ${transition.fromResult} → ${transition.to} · #${String(transition.fromSequence).padStart(2, "0")}→#${String(transition.toSequence).padStart(2, "0")}`;
  const labelWidth = Math.max(188, Math.min(244, label.length * 7.4 + 30));
  const labelX = Math.min((fromX + toX) / 2, toX + 220);
  return {
    path: `M${fromX},${from.y} V${channelY + 12} Q${fromX},${channelY} ${fromX - 12},${channelY} H${toX + 12} Q${toX},${channelY} ${toX},${channelY + 12} V${to.y}`,
    label,
    labelX,
    labelY: channelY,
    labelWidth,
    sourceX: fromX,
    sourceY: from.y,
  };
}

function timelineMetrics() {
  return {
    width: Number(elements.timelinePlane.dataset.width || 0),
    height: Number(elements.timelinePlane.dataset.height || 0),
    viewportWidth: elements.timelineViewport.clientWidth,
    viewportHeight: elements.timelineViewport.clientHeight,
  };
}

function timelineMinimumScale() {
  return TIMELINE_MIN_SCALE;
}

function clampTimelineCamera() {
  const camera = state.timelineCamera;
  const metrics = timelineMetrics();
  if (!metrics.width || !metrics.height || !metrics.viewportWidth || !metrics.viewportHeight) return;
  const scaledWidth = metrics.width * camera.scale;
  const scaledHeight = metrics.height * camera.scale;
  const margin = 32;
  if (scaledWidth <= metrics.viewportWidth) camera.x = (metrics.viewportWidth - scaledWidth) / 2;
  else camera.x = Math.min(margin, Math.max(metrics.viewportWidth - scaledWidth - margin, camera.x));
  if (scaledHeight <= metrics.viewportHeight) camera.y = (metrics.viewportHeight - scaledHeight) / 2;
  else camera.y = Math.min(margin, Math.max(metrics.viewportHeight - scaledHeight - margin, camera.y));
}

function applyTimelineCamera() {
  const camera = state.timelineCamera;
  const metrics = timelineMetrics();
  if (!metrics.width || !metrics.height || !metrics.viewportWidth || !metrics.viewportHeight) return;
  clampTimelineCamera();
  const pixelRatio = window.devicePixelRatio || 1;
  camera.x = Math.round(camera.x * pixelRatio) / pixelRatio;
  camera.y = Math.round(camera.y * pixelRatio) / pixelRatio;
  elements.timelinePlane.style.transform = `translate(${camera.x}px, ${camera.y}px) scale(${camera.scale})`;
  const zoomLabel = document.querySelector('[data-zoom="reset"]');
  const zoomOut = document.querySelector('[data-zoom="out"]');
  const zoomIn = document.querySelector('[data-zoom="in"]');
  if (zoomLabel) zoomLabel.textContent = `${Math.round(camera.scale * 100)}%`;
  if (zoomOut) zoomOut.disabled = camera.scale <= timelineMinimumScale() + 0.001;
  if (zoomIn) zoomIn.disabled = camera.scale >= TIMELINE_MAX_SCALE - 0.001;
  const pannable = metrics.width * camera.scale > metrics.viewportWidth + 1 || metrics.height * camera.scale > metrics.viewportHeight + 1;
  elements.timelineViewport.dataset.cameraMode = camera.mode;
  elements.timelineViewport.dataset.pannable = String(pannable);
}

function fitTimelineToViewport() {
  const metrics = timelineMetrics();
  if (!metrics.width || !metrics.height || !metrics.viewportWidth || !metrics.viewportHeight) return;
  const camera = state.timelineCamera;
  camera.fitScale = TIMELINE_MIN_SCALE;
  camera.scale = TIMELINE_MIN_SCALE;
  camera.x = metrics.width <= metrics.viewportWidth ? (metrics.viewportWidth - metrics.width) / 2 : 24;
  camera.y = metrics.height <= metrics.viewportHeight ? (metrics.viewportHeight - metrics.height) / 2 : 24;
  camera.mode = "fit";
  applyTimelineCamera();
}

function scheduleTimelineCamera(options = {}) {
  cancelAnimationFrame(state.timelineCamera.resizeFrame);
  state.timelineCamera.resizeFrame = requestAnimationFrame(() => {
    state.timelineCamera.resizeFrame = 0;
    if (options.forceFit || state.timelineCamera.mode === "fit") fitTimelineToViewport();
    else applyTimelineCamera();
  });
}

function zoomTimeline(nextScale, clientX, clientY) {
  const camera = state.timelineCamera;
  const rect = elements.timelineViewport.getBoundingClientRect();
  const anchorX = Number.isFinite(clientX) ? clientX - rect.left : rect.width / 2;
  const anchorY = Number.isFinite(clientY) ? clientY - rect.top : rect.height / 2;
  const previousScale = camera.scale;
  const next = Math.max(timelineMinimumScale(), Math.min(TIMELINE_MAX_SCALE, Math.round(nextScale * 20) / 20));
  if (Math.abs(next - previousScale) < 0.001) return;
  const contentX = (anchorX - camera.x) / previousScale;
  const contentY = (anchorY - camera.y) / previousScale;
  camera.scale = next;
  camera.x = anchorX - contentX * next;
  camera.y = anchorY - contentY * next;
  camera.mode = "manual";
  applyTimelineCamera();
}

function endTimelineDrag(event) {
  const camera = state.timelineCamera;
  if (!camera.drag) return;
  const moved = camera.drag.moved;
  camera.drag = null;
  elements.timelineViewport.dataset.panning = "false";
  try { elements.timelineViewport.releasePointerCapture(event.pointerId); } catch (_) {}
  if (moved) {
    elements.timelineViewport.dataset.justPanned = "true";
    setTimeout(() => { delete elements.timelineViewport.dataset.justPanned; }, 100);
  }
}

function bindTimelineCamera() {
  elements.timelineViewport.addEventListener("pointerdown", (event) => {
    if (event.button !== 0 || elements.timelineViewport.dataset.pannable !== "true") return;
    if (event.target.closest("button, a, input, select, textarea, summary, .workflow-stage-group, .canvas-inspector")) return;
    const camera = state.timelineCamera;
    camera.drag = { startX: event.clientX, startY: event.clientY, x: camera.x, y: camera.y, moved: false };
    camera.mode = "manual";
    elements.timelineViewport.dataset.panning = "true";
    try { elements.timelineViewport.setPointerCapture(event.pointerId); } catch (_) {}
  });
  elements.timelineViewport.addEventListener("pointermove", (event) => {
    const camera = state.timelineCamera;
    if (!camera.drag) return;
    const dx = event.clientX - camera.drag.startX;
    const dy = event.clientY - camera.drag.startY;
    if (Math.abs(dx) + Math.abs(dy) > 3) camera.drag.moved = true;
    camera.x = camera.drag.x + dx;
    camera.y = camera.drag.y + dy;
    applyTimelineCamera();
  });
  elements.timelineViewport.addEventListener("pointerup", endTimelineDrag);
  elements.timelineViewport.addEventListener("pointercancel", endTimelineDrag);
  elements.timelineViewport.addEventListener("keydown", (event) => {
    const movement = {
      ArrowLeft: [64, 0],
      ArrowRight: [-64, 0],
      ArrowUp: [0, 64],
      ArrowDown: [0, -64],
    }[event.key];
    if (!movement || elements.timelineViewport.dataset.pannable !== "true") return;
    event.preventDefault();
    state.timelineCamera.x += movement[0];
    state.timelineCamera.y += movement[1];
    state.timelineCamera.mode = "manual";
    applyTimelineCamera();
  });
  elements.timelineViewport.addEventListener("wheel", (event) => {
    if (!event.ctrlKey && !event.metaKey) return;
    event.preventDefault();
    const factor = Math.exp(-event.deltaY * 0.002);
    zoomTimeline(state.timelineCamera.scale * factor, event.clientX, event.clientY);
  }, { passive: false });
  if (typeof ResizeObserver === "function") {
    const observer = new ResizeObserver(() => scheduleTimelineCamera());
    observer.observe(elements.timelineViewport);
    state.timelineCamera.observer = observer;
  } else {
    window.addEventListener("resize", () => scheduleTimelineCamera());
  }
}

function renderTimeline(task) {
  const events = detailEvents(task);
  state.selectedEvent = -1;
  const reworkTransitions = workflowReworkTransitions(events);
  const layout = workflowLayout(events, reworkTransitions);
  const stageGroups = STAGES.map((stage) => {
    const position = layout.positions.get(stage);
    const summary = summarizeStage(events, stage);
    const result = summary.latest?.result || "无记录";
    const meta = summary.events.length ? `${numberFormat.format(summary.events.length)} 次 · ${recordedMetricLabel(summary.duration, summary.durationCoverage, summary.events.length, formatDuration)}` : "暂无阶段证据";
    const stageStartLabel = formatCanvasStart(summary.start);
    const stageStart = canvasStartMarkup(summary.start, "workflow-stage-summary__start", "起始");
    const attemptNodes = summary.events.map((event) => {
      const eventIndex = events.indexOf(event);
      const sequence = String(eventIndex + 1).padStart(2, "0");
      const attemptStartLabel = formatCanvasStart(event.start);
      const attemptStart = canvasStartMarkup(event.start, "workflow-attempt__start", "开始");
      return `<button type="button" class="workflow-attempt" data-event-index="${eventIndex}" data-result="${escapeHtml(event.result)}" aria-pressed="false" aria-controls="canvas-inspector" aria-expanded="false" aria-label="记录 ${sequence}，${escapeHtml(`${event.stage} 尝试 ${event.attempt}，${event.result}，开始时间 ${attemptStartLabel}`)}"><span><em>#${sequence}</em>${escapeHtml(`尝试 ${event.attempt}`)}</span><strong>${escapeHtml(event.result)}</strong><small>${escapeHtml(formatDuration(event.duration))}</small>${attemptStart}</button>`;
    }).join("");
    const attemptContent = attemptNodes || '<span class="workflow-attempt-empty">未发现可核验阶段记录</span>';
    return `<section class="workflow-stage-group" data-stage-state="${summary.events.length ? "recorded" : "empty"}" style="--group-x:${position.x}px;--group-y:${position.y}px;--group-width:${position.width}px" aria-label="${stage} ${escapeHtml(STAGE_NAMES[stage])}"><button type="button" class="workflow-stage-summary" data-stage-summary="${stage}" data-result="${escapeHtml(result)}" aria-controls="canvas-inspector" aria-expanded="false" aria-label="打开 ${stage} ${escapeHtml(STAGE_NAMES[stage])} 详情，起始时间 ${escapeHtml(stageStartLabel)}"><span class="workflow-stage-summary__index">${stage}</span><span class="workflow-stage-summary__identity"><strong>${escapeHtml(STAGE_NAMES[stage])}</strong><small>${escapeHtml(meta)}</small>${stageStart}</span><span class="workflow-stage-summary__result">${escapeHtml(result)}</span></button><div class="workflow-stage-branch"><span class="workflow-stage-branch__label"><b>阶段内尝试</b><small>${numberFormat.format(summary.events.length)} 条</small></span><div class="workflow-attempt-grid">${attemptContent}</div></div></section>`;
  }).join("");
  const mainRoutes = STAGES.slice(1).map((stage, index) => {
    const fromStage = STAGES[index];
    const from = layout.positions.get(fromStage);
    const to = layout.positions.get(stage);
    return `<path class="workflow-route" d="${workflowMainRoute(from, to)}" marker-end="url(#workflow-arrow)"/>`;
  }).join("");
  const reworkRoutes = reworkTransitions.map((transition) => {
    const route = workflowReworkRoute(transition, layout);
    return `<path class="workflow-route is-rework" d="${route.path}" marker-end="url(#workflow-return-arrow)"/><circle class="workflow-return-origin" cx="${route.sourceX}" cy="${route.sourceY}" r="4"/><g class="workflow-return-callout"><rect x="${route.labelX - route.labelWidth / 2}" y="${route.labelY - 14}" width="${route.labelWidth}" height="28" rx="6"/><text class="workflow-return-label" x="${route.labelX}" y="${route.labelY + 4}" text-anchor="middle">${escapeHtml(route.label)}</text></g>`;
  }).join("");
  const reworkSummary = reworkTransitions.length
    ? `<div class="workflow-return-band" aria-hidden="true"><span>阶段回流路径</span><strong>${numberFormat.format(reworkTransitions.length)} 条</strong></div><ol class="sr-only" aria-label="阶段回流路径，不等于返工事件数">${reworkTransitions.map((transition) => `<li>${escapeHtml(`记录 ${String(transition.fromSequence).padStart(2, "0")} 从 ${transition.from} ${transition.fromResult} 返回 ${transition.to}，记录 ${String(transition.toSequence).padStart(2, "0")} 重新进入`)}</li>`).join("")}</ol>`
    : "";
  elements.timelinePlane.dataset.width = String(layout.width);
  elements.timelinePlane.dataset.height = String(layout.height);
  elements.timelinePlane.style.width = `${layout.width}px`;
  elements.timelinePlane.style.height = `${layout.height}px`;
  elements.timelinePlane.innerHTML = `${reworkSummary}<svg width="${layout.width}" height="${layout.height}" viewBox="0 0 ${layout.width} ${layout.height}" aria-hidden="true"><defs><marker id="workflow-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z"/></marker><marker id="workflow-return-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z"/></marker></defs>${mainRoutes}${reworkRoutes}</svg>${stageGroups}`;
  elements.timelineCaption.textContent = task.records.length ? `${events.length} 条 metrics.md 记录；S1–S6 横向推进，红色轨道表示阶段回流；拖动浏览，Ctrl/⌘ + 滚轮缩放，普通滚轮滚动页面` : `${events.length} 个阶段产物节点；S1–S6 横向推进，拖动浏览，时间缺失时不推算时长`;
  scheduleTimelineCamera({ forceFit: true });
}

function updateTimelineSelection(index) {
  state.selectedEvent = index;
  elements.timelinePlane.querySelectorAll("[aria-controls='canvas-inspector']").forEach((item) => {
    const selected = item.matches(`[data-event-index="${index}"]`);
    item.classList.toggle("is-selected", selected);
    if (item.hasAttribute("aria-pressed")) item.setAttribute("aria-pressed", String(selected));
    item.setAttribute("aria-expanded", String(selected));
  });
}

function showInspector(title, trigger, focusInspector = false) {
  clearTimeout(state.inspectorTimer);
  if (state.inspectorTrigger && state.inspectorTrigger !== trigger) state.inspectorTrigger.setAttribute("aria-expanded", "false");
  state.inspectorTrigger = trigger;
  if (trigger) trigger.setAttribute("aria-expanded", "true");
  elements.inspectorTitle.textContent = title;
  elements.canvasInspector.hidden = false;
  requestAnimationFrame(() => {
    elements.canvasInspector.classList.add("is-open");
    if (focusInspector) elements.canvasInspector.focus({ preventScroll: true });
  });
}

function hideInspector(options = {}) {
  clearTimeout(state.inspectorTimer);
  const trigger = state.inspectorTrigger;
  if (trigger) trigger.setAttribute("aria-expanded", "false");
  elements.canvasInspector.classList.remove("is-open");
  state.inspectorTrigger = null;
  state.selectedEvent = -1;
  elements.timelinePlane.querySelectorAll(".workflow-attempt").forEach((item) => {
    item.classList.remove("is-selected");
    item.setAttribute("aria-pressed", "false");
  });
  const finish = () => {
    elements.canvasInspector.hidden = true;
    if (options.restoreFocus && trigger?.isConnected) trigger.focus({ preventScroll: true });
  };
  if (options.immediate) finish();
  else state.inspectorTimer = setTimeout(finish, 220);
}

function renderStageDetail(stage, events) {
  const summary = summarizeStage(events, stage);
  const latestResult = summary.latest?.result || "无记录";
  const attemptRows = summary.events.map((event) => {
    const eventIndex = events.indexOf(event);
    return `<button type="button" class="inspector-attempt" data-inspector-event-index="${eventIndex}"><span>${escapeHtml(`尝试 ${event.attempt}`)}</span><strong>${escapeHtml(`${event.result} · ${formatDuration(event.duration)}`)}</strong></button>`;
  }).join("");
  elements.eventDetail.innerHTML = `<div class="event-detail__grid"><span>阶段<strong>${escapeHtml(`${stage} · ${STAGE_NAMES[stage]}`)}</strong></span><span>最近结果<strong>${escapeHtml(latestResult)}</strong></span><span>尝试记录<strong>${numberFormat.format(summary.events.length)}</strong></span><span>记录区间耗时<strong>${escapeHtml(recordedMetricLabel(summary.duration, summary.durationCoverage, summary.events.length, formatDuration))}</strong></span><span>记录 Token<strong>${escapeHtml(recordedMetricLabel(summary.tokens, summary.tokenCoverage, summary.events.length, formatTokens))}</strong></span><span>显式等待<strong>${escapeHtml(waitingLabel(summary.waitDuration))}</strong></span></div>${attemptRows ? `<div class="inspector-attempts"><span>尝试记录，不代表独立返工事件</span>${attemptRows}</div>` : '<p class="event-note">state.md、metrics.md 与阶段产物均未提供该阶段记录。</p>'}`;
}

function renderEventDetail(event) {
  if (!event) return;
  elements.eventDetail.innerHTML = `<div class="event-detail__grid"><span>阶段<strong>${escapeHtml(`${event.stage} · 尝试 ${event.attempt}`)}</strong></span><span>结果<strong>${escapeHtml(event.result)}</strong></span><span>记录区间耗时<strong>${escapeHtml(formatDuration(event.duration))}</strong></span><span>Token<strong title="${Number.isFinite(event.tokenTotal) ? numberFormat.format(event.tokenTotal) : "缺失"}">${escapeHtml(formatTokens(event.tokenTotal))}</strong></span><span>显式等待<strong>${escapeHtml(waitingLabel(event.waitDuration))}</strong></span><span>旧轮次数（未对齐）<strong>${Number.isFinite(event.legacyReworkCount) ? numberFormat.format(event.legacyReworkCount) : "NOT_AVAILABLE"}</strong></span><span>开始<strong>${escapeHtml(formatDateTime(event.start))}</strong></span><span>结束<strong>${escapeHtml(formatDateTime(event.end))}</strong></span></div><p class="event-note"><strong>证据备注：</strong>${escapeHtml(event.note || "该记录没有备注。")} <span class="mono-meta">${escapeHtml(event.source || "metrics.md")}</span></p>`;
}

function sumAvailable(records, field) {
  const values = records.map((record) => record[field]).filter(Number.isFinite);
  return {
    count: values.length,
    total: values.length ? values.reduce((sum, value) => sum + value, 0) : null,
  };
}

function metricTimeBoundary(records, field, direction) {
  return records.reduce((selected, record) => {
    const parsed = parseDate(record[field]);
    if (!parsed) return selected;
    if (!selected || (direction === "min" ? parsed.getTime() < selected.getTime() : parsed.getTime() > selected.getTime())) return parsed;
    return selected;
  }, null);
}

function buildMetricModel(task) {
  const records = task.records || [];
  const tokenMetric = sumAvailable(records, "tokenTotal");
  const durationMetric = sumAvailable(records, "duration");
  const waitMetric = sumAvailable(records, "waitDuration");
  const rows = STAGES.map((stage) => {
    const stageRecords = records.filter((record) => record.stage === stage);
    const summary = summarizeStage(records, stage);
    const tokens = sumAvailable(stageRecords, "tokenTotal");
    const duration = sumAvailable(stageRecords, "duration");
    const waiting = sumAvailable(stageRecords, "waitDuration");
    return {
      stage,
      name: STAGE_NAMES[stage],
      records: stageRecords,
      attempts: stageRecords.length,
      result: summary.latest?.result || "无记录",
      start: summary.start,
      end: metricTimeBoundary(stageRecords, "end", "max"),
      duration: duration.total,
      durationCoverage: duration.count,
      tokens: tokens.total,
      tokenCoverage: tokens.count,
      waitDuration: waiting.total,
      waitCoverage: waiting.count,
      rework: reworkSummary(task, stage),
    };
  });
  rows.forEach((row) => {
    row.tokenShare = Number.isFinite(row.tokens) && tokenMetric.total ? row.tokens / tokenMetric.total : null;
    row.durationShare = Number.isFinite(row.duration) && durationMetric.total ? row.duration / durationMetric.total : null;
  });
  return {
    records,
    rows,
    start: metricTimeBoundary(records, "start", "min"),
    end: metricTimeBoundary(records, "end", "max"),
    tokenTotal: tokenMetric.total,
    tokenCoverage: tokenMetric.count,
    durationTotal: durationMetric.total,
    durationCoverage: durationMetric.count,
    waitTotal: waitMetric.total,
    waitCoverage: waitMetric.count,
    rework: reworkSummary(task),
    failCount: records.filter((record) => record.result === "FAIL").length,
    blockedCount: records.filter((record) => record.result === "BLOCKED").length,
  };
}

function renderMetricKpis(model) {
  const activeStages = model.rows.filter((row) => row.attempts).length;
  const cards = [
    { label: "阶段尝试", value: numberFormat.format(model.records.length), note: `${activeStages} / ${STAGES.length} 个阶段有记录` },
    { label: "记录区间耗时", value: recordedMetricLabel(model.durationTotal, model.durationCoverage, model.records.length, formatDuration), note: `覆盖 ${model.durationCoverage} / ${model.records.length}；可含等待及重叠` },
    { label: "Token", value: recordedMetricLabel(model.tokenTotal, model.tokenCoverage, model.records.length, formatTokens), note: `有数值 ${model.tokenCoverage} / ${model.records.length}；缺失未补零` },
    { label: "显式等待", value: waitingLabel(model.waitTotal), note: `已记录 ${model.waitCoverage} / ${model.records.length}；不从间隙推算` },
    { label: "已登记返工事件", value: eventCountLabel(model.rework), note: reworkCoverageNote(model.rework) },
  ];
  elements.metricDrilldownKpis.innerHTML = cards.map((card) => `<article><span>${escapeHtml(card.label)}</span><strong>${escapeHtml(card.value)}</strong><small>${escapeHtml(card.note)}</small></article>`).join("");
}

function renderTokenComposition(model) {
  if (!Number.isFinite(model.tokenTotal) || !model.tokenTotal) {
    elements.tokenCompositionChart.innerHTML = `<div class="metric-empty"><strong>${model.tokenTotal === 0 ? "已记录 Token 合计为 0" : "没有可绘制的 Token"}</strong><span>有数值 ${model.tokenCoverage} / ${model.records.length}；缺失未补零。</span></div>`;
    return;
  }
  let offset = 0;
  const segments = model.rows.filter((row) => Number.isFinite(row.tokens) && row.tokens > 0).sort((a, b) => b.tokens - a.tokens).map((row) => {
    const percent = row.tokenShare * 100;
    const markup = `<circle class="token-donut__segment" data-metric-stage="${row.stage}" data-active="${state.metricStage === "all" || state.metricStage === row.stage}" cx="70" cy="70" r="52" pathLength="100" stroke-dasharray="${percent} ${100 - percent}" stroke-dashoffset="${-offset}"/>`;
    offset += percent;
    return markup;
  }).join("");
  const ariaSummary = model.rows.filter((row) => Number.isFinite(row.tokenShare)).map((row) => `${row.stage} ${formatPercent(row.tokenShare)}`).join("，");
  const legend = model.rows.filter((row) => row.attempts).map((row) => `<button type="button" class="metric-legend__item" data-metric-stage="${row.stage}" aria-pressed="${state.metricStage === row.stage}"><span class="metric-swatch" aria-hidden="true"></span><span><strong>${row.stage} · ${escapeHtml(row.name)}</strong><small>${escapeHtml(recordedMetricLabel(row.tokens, row.tokenCoverage, row.attempts, formatTokens))} · ${row.tokenCoverage}/${row.attempts}</small></span><b>${escapeHtml(formatPercent(row.tokenShare))}</b></button>`).join("");
  elements.tokenCompositionChart.innerHTML = `<div class="token-donut"><svg viewBox="0 0 140 140" role="img" aria-label="已记录 Token 阶段构成：${escapeHtml(ariaSummary)}"><circle class="token-donut__track" cx="70" cy="70" r="52"/><g transform="rotate(-90 70 70)">${segments}</g></svg><span><small>${model.tokenCoverage < model.records.length ? "Token 部分合计" : "已记录 Token"}</small><strong>${escapeHtml(formatTokens(model.tokenTotal))}</strong></span></div><div class="metric-legend">${legend}</div>`;
}

function renderDurationDistribution(model) {
  if (!Number.isFinite(model.durationTotal) || !model.durationTotal) {
    elements.durationDistributionChart.innerHTML = `<div class="metric-empty"><strong>${model.durationTotal === 0 ? "已记录区间合计为 0 秒" : "没有可绘制的用时"}</strong><span>有数值 ${model.durationCoverage} / ${model.records.length}；缺失未补零。</span></div>`;
    return;
  }
  elements.durationDistributionChart.innerHTML = model.rows.map((row) => {
    const share = Number.isFinite(row.durationShare) ? row.durationShare : 0;
    const selected = state.metricStage === "all" || state.metricStage === row.stage;
    return `<button type="button" class="duration-bar" data-metric-stage="${row.stage}" data-active="${selected}" aria-pressed="${state.metricStage === row.stage}" aria-label="${row.stage} ${escapeHtml(row.name)}，${escapeHtml(recordedMetricLabel(row.duration, row.durationCoverage, row.attempts, formatDuration))}，占已记录区间 ${escapeHtml(formatPercent(row.durationShare))}"><span class="duration-bar__label"><strong>${row.stage}</strong><small>${escapeHtml(row.name)}</small></span><span class="duration-bar__track"><i aria-hidden="true" style="--metric-share:${share * 100}%"></i></span><span class="duration-bar__value"><strong>${escapeHtml(recordedMetricLabel(row.duration, row.durationCoverage, row.attempts, formatDuration))}</strong><small>${escapeHtml(formatPercent(row.durationShare))} · ${row.durationCoverage}/${row.attempts}</small></span></button>`;
  }).join("");
}

function renderMetricStageDetail(model) {
  const selected = state.metricStage === "all" ? null : model.rows.find((row) => row.stage === state.metricStage);
  if (!selected) {
    const tokenHotspot = model.rows.filter((row) => Number.isFinite(row.tokens)).sort((a, b) => b.tokens - a.tokens)[0];
    const durationHotspot = model.rows.filter((row) => Number.isFinite(row.duration)).sort((a, b) => b.duration - a.duration)[0];
    elements.metricStageDetailTitle.textContent = "全部阶段";
    elements.metricStageDetailCaption.textContent = `${model.records.length} 条记录 · ${formatDateTime(model.start)} 至 ${formatDateTime(model.end)}`;
    elements.metricStageDetailBody.innerHTML = `<div class="metric-diagnosis"><article><span>已记录 Token 集中阶段</span><strong>${tokenHotspot ? `${tokenHotspot.stage} · ${formatPercent(tokenHotspot.tokenShare)}` : "—"}</strong><small>${tokenHotspot ? escapeHtml(tokenHotspot.name) : "无可核验数据"}</small></article><article><span>已记录区间最长阶段</span><strong>${durationHotspot ? `${durationHotspot.stage} · ${formatPercent(durationHotspot.durationShare)}` : "—"}</strong><small>${durationHotspot ? escapeHtml(formatDuration(durationHotspot.duration)) : "无可核验数据"}</small></article><article><span>已登记返工事件</span><strong>${escapeHtml(eventCountLabel(model.rework))}</strong><small>${escapeHtml(reworkCoverageNote(model.rework))}</small></article></div>`;
    return;
  }
  elements.metricStageDetailTitle.textContent = `${selected.stage} · ${selected.name}`;
  elements.metricStageDetailCaption.textContent = `${selected.attempts} 条尝试 · ${formatCanvasStart(selected.start)} 至 ${formatDateTime(selected.end)} · 最近结果 ${selected.result}`;
  const summary = `<div class="metric-stage-summary"><span><small>记录区间耗时</small><strong>${escapeHtml(recordedMetricLabel(selected.duration, selected.durationCoverage, selected.attempts, formatDuration))}</strong></span><span><small>Token</small><strong>${escapeHtml(recordedMetricLabel(selected.tokens, selected.tokenCoverage, selected.attempts, formatTokens))}</strong></span><span><small>显式等待</small><strong>${escapeHtml(waitingLabel(selected.waitDuration))}</strong></span><span><small>来源阶段事件</small><strong>${escapeHtml(eventCountLabel(selected.rework))}</strong></span></div>`;
  const attempts = selected.records.length ? selected.records.map((record) => `<article class="metric-attempt" data-result="${escapeHtml(record.result)}"><header><span>${escapeHtml(`${record.stage} · 尝试 ${record.attempt}`)}</span><strong>${escapeHtml(record.result)}</strong></header><dl><div><dt>开始</dt><dd>${escapeHtml(formatCanvasStart(record.start))}</dd></div><div><dt>区间耗时</dt><dd>${escapeHtml(formatDuration(record.duration))}</dd></div><div><dt>Token</dt><dd>${escapeHtml(formatTokens(record.tokenTotal))}</dd></div><div><dt>显式等待</dt><dd>${escapeHtml(waitingLabel(record.waitDuration))}</dd></div></dl></article>`).join("") : '<div class="metric-empty"><strong>该阶段没有 metrics.md 记录</strong><span>不使用 state.md 或阶段产物推算指标。</span></div>';
  elements.metricStageDetailBody.innerHTML = `${summary}<p class="event-note">${escapeHtml(reworkCoverageNote(selected.rework))}</p><div class="metric-attempts">${attempts}</div>`;
}

function renderMetricStageTable(model) {
  elements.metricStageTable.innerHTML = model.rows.map((row) => `<tr data-selected="${state.metricStage === row.stage}"><td><button type="button" class="metric-table__stage" data-metric-stage="${row.stage}" aria-pressed="${state.metricStage === row.stage}"><span class="metric-swatch" aria-hidden="true"></span><strong>${row.stage}</strong><small>${escapeHtml(row.name)}</small></button></td><td>${numberFormat.format(row.attempts)}</td><td><span class="metric-result" data-result="${escapeHtml(row.result)}">${escapeHtml(row.result)}</span></td><td><strong>${escapeHtml(recordedMetricLabel(row.duration, row.durationCoverage, row.attempts, formatDuration))}</strong><small>${escapeHtml(formatPercent(row.durationShare))} · ${row.durationCoverage}/${row.attempts}</small></td><td><strong title="${Number.isFinite(row.tokens) ? numberFormat.format(row.tokens) : "缺失"}">${escapeHtml(recordedMetricLabel(row.tokens, row.tokenCoverage, row.attempts, formatTokens))}</strong><small>${escapeHtml(formatPercent(row.tokenShare))} · ${row.tokenCoverage}/${row.attempts}</small></td><td>${escapeHtml(waitingLabel(row.waitDuration))}<small>${row.waitCoverage}/${row.attempts}</small></td><td title="${escapeHtml(reworkCoverageNote(row.rework))}">${escapeHtml(eventCountLabel(row.rework))}</td></tr>`).join("");
}

function renderMetricDrilldown(task) {
  renderEfficiencyDetail(task);
  const model = buildMetricModel(task);
  if (state.metricTaskId !== task.id) {
    state.metricTaskId = task.id;
    const hotspot = model.rows.filter((row) => Number.isFinite(row.tokens)).sort((a, b) => b.tokens - a.tokens)[0];
    state.metricStage = hotspot?.stage || "all";
  }
  if (state.metricStage !== "all" && !STAGES.includes(state.metricStage)) state.metricStage = "all";
  const allButton = elements.metricDrilldown.querySelector('[data-metric-stage="all"]');
  allButton.setAttribute("aria-pressed", String(state.metricStage === "all"));
  elements.metricDrilldownSource.textContent = model.records.length ? `SOURCE · metrics.md · ${model.records.length} RECORDS` : "SOURCE · metrics.md · NOT AVAILABLE";
  elements.metricDrilldownCaption.textContent = model.records.length ? `${formatDateTime(model.start)} 至 ${formatDateTime(model.end)} · Token ${model.tokenCoverage}/${model.records.length} · 区间 ${model.durationCoverage}/${model.records.length} · 等待 ${model.waitCoverage}/${model.records.length}` : "当前需求没有可读取的阶段区间记录；事件记录单独展示。";
  renderMetricKpis(model);
  renderTokenComposition(model);
  renderDurationDistribution(model);
  renderMetricStageDetail(model);
  renderMetricStageTable(model);
}

function renderArtifacts(task) {
  const artifacts = (task.detail.artifacts || []).filter((artifact) => artifact.name !== "prd" && artifact.name !== "metrics.md");
  elements.artifactTabs.innerHTML = artifacts.map((artifact) => `<button type="button" class="artifact-tab" data-artifact="${escapeHtml(artifact.name)}" ${artifact.exists && artifact.readable !== false ? "" : "disabled"} aria-disabled="${!(artifact.exists && artifact.readable !== false)}">${escapeHtml(artifact.label)}</button>`).join("");
  elements.artifactContent.textContent = artifacts.some((artifact) => artifact.exists) ? "选择一个现有产物。" : "该需求没有可读取的阶段产物。";
}

function renderDetail() {
  const task = state.tasks.find((item) => item.id === state.selectedTaskId);
  if (!task) {
    elements.detailEmpty.hidden = false;
    elements.detailContent.hidden = true;
    return;
  }
  elements.detailEmpty.hidden = true;
  elements.detailContent.hidden = false;
  elements.detailId.textContent = task.id;
  elements.detailTitle.textContent = task.title;
  const evidenceTitle = task.lifecycle?.evidence || "尚无独立证据；生命周期不推导验收、合入或部署状态";
  const evidenceBadges = lifecycleEvidence(task).map(({ label, value }) => `<span class="badge" title="${escapeHtml(evidenceTitle)}">${escapeHtml(label)} · ${escapeHtml(value)}</span>`).join("");
  const issues = task.lifecycle?.issues || [];
  elements.detailBadges.innerHTML = `<span class="badge" data-tone="${task.statusMeta.key}">${escapeHtml(task.statusMeta.label)}</span><span class="badge">${escapeHtml(task.phase || "未开始")}</span><span class="badge">${escapeHtml(task.category)}</span>${evidenceBadges}${issues.length ? `<span class="badge" data-tone="blocked" title="${escapeHtml(issues.join("；"))}">生命周期待核对</span>` : ""}${task.loadError ? '<span class="badge" data-tone="cancelled">读取不完整</span>' : ""}`;
  elements.detailDuration.textContent = recordedMetricLabel(task.aggregate.duration, task.aggregate.durationCoverage, task.records.length, formatDuration);
  elements.detailTokens.textContent = recordedMetricLabel(task.aggregate.tokens, task.aggregate.tokenCoverage, task.records.length, formatTokens);
  const tokenCoverage = `${task.aggregate.tokenCoverage}/${task.records.length}`;
  elements.detailTokens.title = Number.isFinite(task.aggregate.tokens) ? `${numberFormat.format(task.aggregate.tokens)}（精确记录 ${tokenCoverage}）` : "缺失";
  elements.detailEfficiency.textContent = waitingLabel(task.aggregate.waitDuration);
  elements.detailEfficiency.title = `显式等待覆盖 ${task.aggregate.waitCoverage}/${task.records.length}；缺失为 NOT_AVAILABLE`;
  hideInspector({ immediate: true });
  state.selectedEvent = -1;
  renderTimeline(task);
  renderMetricDrilldown(task);
  renderArtifacts(task);
}

async function loadArtifact(name, button) {
  const task = state.tasks.find((item) => item.id === state.selectedTaskId);
  if (!task) return;
  elements.artifactTabs.querySelectorAll(".artifact-tab").forEach((item) => item.classList.toggle("is-active", item === button));
  button.dataset.state = "loading";
  button.disabled = true;
  elements.artifactContent.textContent = "正在读取本地产物…";
  try {
    const artifact = await api(`/api/tasks/${encodeURIComponent(task.id)}/artifacts/${encodeURIComponent(name)}`);
    elements.artifactContent.textContent = artifact.content || "该产物为空。";
    elements.artifactContent.focus({ preventScroll: true });
  } catch (error) {
    button.dataset.state = "error";
    elements.artifactContent.textContent = `${error.message}\n请检查对应 Markdown 文件是否仍可读。`;
  } finally {
    if (button.dataset.state !== "error") button.dataset.state = "default";
    button.disabled = false;
  }
}

function renderAnalysis() {
  renderDemandList();
  renderDetail();
}

function renderAll() {
  renderOverview();
  renderAnalysis();
  renderCommandResults();
}

function setDemandDrawer(open, options = {}) {
  state.drawerOpen = Boolean(open);
  elements.analysisLayout.dataset.drawer = state.drawerOpen ? "open" : "closed";
  elements.demandDrawerToggle.setAttribute("aria-expanded", String(state.drawerOpen));
  elements.demandDrawerToggle.setAttribute("aria-label", state.drawerOpen ? "收起需求抽屉" : "展开需求抽屉");
  elements.demandDrawer.setAttribute("aria-hidden", String(!state.drawerOpen));
  elements.demandDrawer.inert = !state.drawerOpen;
  const docked = window.matchMedia("(min-width: 60rem)").matches;
  elements.demandDrawerScrim.hidden = !(state.drawerOpen && !docked);
  if (state.view === "analysis" && !elements.detailContent.hidden) scheduleTimelineCamera({ forceFit: true });
  if (options.focusSearch && state.drawerOpen) elements.demandSearch.focus({ preventScroll: true });
  if (options.restoreToggle && !state.drawerOpen) elements.demandDrawerToggle.focus({ preventScroll: true });
}

function switchView(view, options = {}) {
  state.view = view === "analysis" ? "analysis" : "overview";
  const overview = state.view === "overview";
  elements.appShell.dataset.view = state.view;
  elements.overviewView.hidden = !overview;
  elements.analysisView.hidden = overview;
  elements.viewContext.textContent = overview ? "总览" : "需求分析";
  elements.contextTitle.textContent = overview ? "状态与过程证据" : "需求复盘与时间线";
  document.querySelectorAll("[data-view-target]").forEach((button) => {
    const active = button.dataset.viewTarget === state.view;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-current", active ? "page" : "false");
  });
  closeMobileMenu();
  if (!overview && !elements.detailContent.hidden) scheduleTimelineCamera({ forceFit: true });
  if (options.focusMain) document.querySelector("#main-content").focus({ preventScroll: true });
}

function selectTask(taskId, options = {}) {
  if (!state.tasks.some((task) => task.id === taskId)) return;
  state.selectedTaskId = taskId;
  state.selectedEvent = -1;
  switchView("analysis");
  renderDemandList();
  renderDetail();
  if (state.drawerOpen) setDemandDrawer(false);
  if (options.scroll && window.matchMedia("(max-width: 59.99rem)").matches) {
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    document.querySelector("#demand-detail").scrollIntoView({ behavior: reducedMotion ? "auto" : "smooth", block: "start" });
  }
}

function commandOptions(query = "") {
  const normalized = query.trim().toLowerCase();
  const options = [
    { type: "view", value: "overview", label: "总览", meta: "状态与过程证据" },
    { type: "view", value: "analysis", label: "需求分析", meta: "复盘与时间线" },
    ...state.tasks.map((task) => ({ type: "task", value: task.id, label: task.title, meta: `${task.id} · ${task.statusMeta.label}` })),
  ];
  return normalized ? options.filter((option) => `${option.label} ${option.meta}`.toLowerCase().includes(normalized)) : options;
}

function renderCommandResults() {
  state.commandItems = commandOptions(elements.commandInput.value);
  state.commandIndex = Math.min(state.commandIndex, Math.max(state.commandItems.length - 1, 0));
  if (!state.commandItems.length) {
    elements.commandResults.innerHTML = '<div class="empty-inline"><strong>没有匹配结果</strong><span>换一个需求 id 或标题关键词。</span></div>';
    return;
  }
  elements.commandResults.innerHTML = state.commandItems.map((item, index) => `<button type="button" class="command-option${index === state.commandIndex ? " is-selected" : ""}" role="option" aria-selected="${index === state.commandIndex}" data-command-index="${index}"><span>${escapeHtml(item.label)}</span><small>${escapeHtml(item.meta)}</small></button>`).join("");
}

function runCommand(index) {
  const item = state.commandItems[index];
  if (!item) return;
  elements.commandDialog.close();
  if (item.type === "view") switchView(item.value, { focusMain: true });
  if (item.type === "task") selectTask(item.value, { scroll: true });
}

function openCommand(initial = "") {
  elements.commandInput.value = initial;
  state.commandIndex = 0;
  renderCommandResults();
  elements.commandDialog.showModal();
  elements.appShell.inert = true;
  requestAnimationFrame(() => elements.commandInput.focus());
}

function closeMobileMenu() {
  elements.appShell.classList.remove("is-menu-open");
  elements.mobileMenu.setAttribute("aria-expanded", "false");
}

function openMobileMenu() {
  elements.appShell.classList.add("is-menu-open");
  elements.mobileMenu.setAttribute("aria-expanded", "true");
  elements.sidebar.querySelector(".nav-item").focus();
}

function bindEvents() {
  document.querySelectorAll("[data-view-target]").forEach((button) => {
    button.addEventListener("click", () => switchView(button.dataset.viewTarget, { focusMain: true }));
  });
  elements.sidebarToggle.addEventListener("click", () => {
    const collapsed = elements.appShell.dataset.sidebar === "collapsed";
    elements.appShell.dataset.sidebar = collapsed ? "expanded" : "collapsed";
    elements.sidebarToggle.setAttribute("aria-label", collapsed ? "收起侧边栏" : "展开侧边栏");
    elements.sidebarToggle.title = collapsed ? "收起侧边栏" : "展开侧边栏";
  });
  elements.mobileMenu.addEventListener("click", () => {
    if (elements.appShell.classList.contains("is-menu-open")) closeMobileMenu();
    else openMobileMenu();
  });
  elements.sidebarScrim.addEventListener("click", closeMobileMenu);
  elements.demandDrawerToggle.addEventListener("click", () => {
    const opening = !state.drawerOpen;
    setDemandDrawer(opening, { focusSearch: opening });
  });
  elements.demandDrawerClose.addEventListener("click", () => setDemandDrawer(false, { restoreToggle: true }));
  elements.demandDrawerScrim.addEventListener("click", () => setDemandDrawer(false, { restoreToggle: true }));
  elements.refreshButton.addEventListener("click", loadDashboard);
  elements.errorRetry.addEventListener("click", loadDashboard);
  elements.commandTrigger.addEventListener("click", () => openCommand());
  elements.commandDialog.addEventListener("close", () => { elements.appShell.inert = false; });
  elements.commandDialog.addEventListener("click", (event) => {
    if (event.target === elements.commandDialog) elements.commandDialog.close();
  });
  elements.commandInput.addEventListener("input", () => {
    state.commandIndex = 0;
    renderCommandResults();
  });
  elements.commandInput.addEventListener("keydown", (event) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      state.commandIndex = Math.min(state.commandIndex + 1, state.commandItems.length - 1);
      renderCommandResults();
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      state.commandIndex = Math.max(state.commandIndex - 1, 0);
      renderCommandResults();
    } else if (event.key === "Enter") {
      event.preventDefault();
      runCommand(state.commandIndex);
    }
  });
  elements.commandResults.addEventListener("click", (event) => {
    const button = event.target.closest("[data-command-index]");
    if (button) runCommand(Number(button.dataset.commandIndex));
  });
  let searchTimer = null;
  elements.demandSearch.addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      state.filters.search = elements.demandSearch.value;
      renderDemandList();
      elements.liveRegion.textContent = elements.analysisCount.textContent;
    }, 250);
  });
  elements.timeFilter.addEventListener("change", () => { state.filters.time = elements.timeFilter.value; renderDemandList(); });
  elements.statusFilter.addEventListener("change", () => { state.filters.status = elements.statusFilter.value; renderDemandList(); });
  elements.sortFilter.addEventListener("change", () => { state.filters.sort = elements.sortFilter.value; renderDemandList(); });
  elements.demandList.addEventListener("click", (event) => {
    const button = event.target.closest("[data-task-id]");
    if (button) selectTask(button.dataset.taskId, { scroll: true });
  });
  elements.timelinePlane.addEventListener("click", (event) => {
    if (elements.timelineViewport.dataset.justPanned === "true") return;
    const task = state.tasks.find((item) => item.id === state.selectedTaskId);
    const events = task ? detailEvents(task) : [];
    const stageButton = event.target.closest("[data-stage-summary]");
    if (stageButton) {
      updateTimelineSelection(-1);
      renderStageDetail(stageButton.dataset.stageSummary, events);
      showInspector(`${stageButton.dataset.stageSummary} · ${STAGE_NAMES[stageButton.dataset.stageSummary]}`, stageButton, event.detail === 0);
      return;
    }
    const eventButton = event.target.closest("[data-event-index]");
    if (!eventButton) return;
    const eventIndex = Number(eventButton.dataset.eventIndex);
    updateTimelineSelection(eventIndex);
    renderEventDetail(events[eventIndex]);
    showInspector(`${events[eventIndex].stage} · 尝试 ${events[eventIndex].attempt}`, eventButton, event.detail === 0);
  });
  elements.eventDetail.addEventListener("click", (event) => {
    const button = event.target.closest("[data-inspector-event-index]");
    if (!button) return;
    const task = state.tasks.find((item) => item.id === state.selectedTaskId);
    const events = task ? detailEvents(task) : [];
    const eventIndex = Number(button.dataset.inspectorEventIndex);
    const timelineButton = elements.timelinePlane.querySelector(`[data-event-index="${eventIndex}"]`);
    updateTimelineSelection(eventIndex);
    renderEventDetail(events[eventIndex]);
    showInspector(`${events[eventIndex].stage} · 尝试 ${events[eventIndex].attempt}`, timelineButton || button);
  });
  elements.inspectorClose.addEventListener("click", () => hideInspector({ restoreFocus: true }));
  elements.artifactTabs.addEventListener("click", (event) => {
    const button = event.target.closest("[data-artifact]");
    if (button && !button.disabled) loadArtifact(button.dataset.artifact, button);
  });
  document.querySelector(".canvas-tools").addEventListener("click", (event) => {
    const button = event.target.closest("[data-zoom]");
    if (!button) return;
    if (button.dataset.zoom === "in") zoomTimeline(state.timelineCamera.scale + 0.25);
    if (button.dataset.zoom === "out") zoomTimeline(state.timelineCamera.scale - 0.25);
    if (button.dataset.zoom === "reset") fitTimelineToViewport();
  });
  elements.metricDrilldown.addEventListener("click", (event) => {
    const trigger = event.target.closest("[data-metric-stage]");
    if (!trigger || !elements.metricDrilldown.contains(trigger)) return;
    const task = state.tasks.find((item) => item.id === state.selectedTaskId);
    if (!task) return;
    state.metricStage = trigger.dataset.metricStage;
    renderMetricDrilldown(task);
    elements.liveRegion.textContent = state.metricStage === "all" ? "指标下钻已切换到全部阶段。" : `指标下钻已切换到 ${state.metricStage} ${STAGE_NAMES[state.metricStage]}。`;
  });
  window.matchMedia("(min-width: 60rem)").addEventListener("change", () => setDemandDrawer(state.drawerOpen));
  document.addEventListener("keydown", (event) => {
    const target = event.target;
    const typing = target instanceof HTMLInputElement || target instanceof HTMLSelectElement || target instanceof HTMLTextAreaElement;
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      if (!elements.commandDialog.open) openCommand();
      return;
    }
    if (!typing && event.key === "/") {
      event.preventDefault();
      if (!elements.commandDialog.open) openCommand();
      return;
    }
    if (!typing && !elements.commandDialog.open && event.key === "1") switchView("overview", { focusMain: true });
    if (!typing && !elements.commandDialog.open && event.key === "2") switchView("analysis", { focusMain: true });
    if (event.key === "Escape" && elements.commandDialog.open) return;
    if (event.key === "Escape" && !elements.canvasInspector.hidden) {
      hideInspector({ restoreFocus: true });
      return;
    }
    if (event.key === "Escape" && state.view === "analysis" && state.drawerOpen) {
      setDemandDrawer(false, { restoreToggle: true });
      return;
    }
    if (event.key === "Escape" && elements.appShell.classList.contains("is-menu-open")) closeMobileMenu();
  });
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { statusMeta, lifecycleEvidence, fieldValue, parseMetricNumber, parseMetrics, parseReworkEvents, reworkSummary, eventCountLabel, reworkCoverageNote, aggregateTask, overviewMetricModel, buildMetricModel, summarizeStage, sumAvailable, recordedMetricLabel, waitingLabel, formatDuration, formatTokens, scoreValue, efficiencyScopeMarkup, efficiencyDetailMarkup, enrichTask };
}
if (typeof document !== "undefined") {
  bindTimelineCamera();
  bindEvents();
  setDemandDrawer(true);
  loadDashboard();
}
