"use strict";

const STAGES = ["S1", "S2", "S3", "S4", "S5", "S6"];
const STAGE_NAMES = {
  S1: "解析与影响面",
  S2: "技术方案",
  S3: "实现",
  S4: "验证",
  S5: "交付",
  S6: "完成归档",
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

const elements = {
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

function formatPercent(value) {
  return Number.isFinite(value) ? `${(value * 100).toFixed(1)}%` : "—";
}

function average(values) {
  const valid = values.filter(Number.isFinite);
  return valid.length ? valid.reduce((sum, value) => sum + value, 0) / valid.length : null;
}

function statusMeta(task) {
  const value = `${task.status || ""} ${task.phase || ""}`.toLowerCase();
  if (/作废|cancel/.test(value)) return { key: "cancelled", label: "已作废" };
  if (/blocked|阻塞|等待/.test(value)) return { key: "blocked", label: "阻塞" };
  if (/archived|已完成|完成|已验收/.test(value) || task.phase === "S6") return { key: "archived", label: "已归档" };
  return { key: "active", label: "进行中" };
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

function reworkReason(note) {
  const value = note || "";
  if (/冲突|合同|契约|方案|口径|不一致/.test(value)) return "方案或合同不一致";
  if (/环境|授权|not_run|部署|redis|数据库|媒体/.test(value.toLowerCase())) return "环境或授权不足";
  if (/测试|验证|构建|依赖/.test(value)) return "验证或依赖问题";
  if (/范围|用户|需求变更/.test(value)) return "范围调整";
  return "未归类备注";
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
  const expression = new RegExp(`^- ${escapeRegExp(label)}[：:]\\s*(?:\u0060([^\u0060\\n]*)\u0060|([^\\n]*))$`, "m");
  const match = block.match(expression);
  return match ? (match[1] ?? match[2] ?? "").trim() : "";
}

function parseMetrics(content) {
  if (!content) return [];
  const headers = [...content.matchAll(/^##\s+(S[1-6])\s+·\s+尝试\s+(\d+)\s*$/gm)];
  return headers.map((match, index) => {
    const startIndex = match.index + match[0].length;
    const endIndex = index + 1 < headers.length ? headers[index + 1].index : content.length;
    const block = content.slice(startIndex, endIndex);
    const tokenLine = fieldValue(block, "Token");
    const tokenMatch = tokenLine.match(/(?:^|,\s*)total=(\d+)/);
    const duration = Number(fieldValue(block, "用时").replace(/[^\d.-]/g, ""));
    const reworkCount = Number(fieldValue(block, "返工次数").replace(/[^\d.-]/g, ""));
    const acceptedUnits = Number(fieldValue(block, "有效产出单元").replace(/[^\d.-]/g, ""));
    const reworkUnits = Number(fieldValue(block, "返工影响单元").replace(/[^\d.-]/g, ""));
    const efficiencyText = fieldValue(block, "效率比");
    const efficiency = /%$/.test(efficiencyText) ? Number(efficiencyText.replace("%", "")) / 100 : null;
    return {
      stage: match[1],
      attempt: Number(match[2]),
      result: fieldValue(block, "结果") || "UNKNOWN",
      start: fieldValue(block, "开始"),
      end: fieldValue(block, "结束"),
      duration: Number.isFinite(duration) ? duration : null,
      tokenSource: fieldValue(block, "Token 来源"),
      tokenTotal: tokenMatch ? Number(tokenMatch[1]) : null,
      reworkCount: Number.isFinite(reworkCount) ? reworkCount : 0,
      acceptedUnits: Number.isFinite(acceptedUnits) ? acceptedUnits : 0,
      reworkUnits: Number.isFinite(reworkUnits) ? reworkUnits : 0,
      efficiency: Number.isFinite(efficiency) ? efficiency : null,
      note: fieldValue(block, "备注"),
      source: "metrics.md",
    };
  });
}

function aggregateTask(task) {
  const records = task.records || [];
  const allDurations = records.length && records.every((record) => Number.isFinite(record.duration));
  const allTokens = records.length && records.every((record) => Number.isFinite(record.tokenTotal));
  const acceptedUnits = records.reduce((sum, record) => sum + record.acceptedUnits, 0);
  const reworkUnits = records.reduce((sum, record) => sum + record.reworkUnits, 0);
  const denominator = acceptedUnits + reworkUnits;
  return {
    duration: allDurations ? records.reduce((sum, record) => sum + record.duration, 0) : null,
    tokens: allTokens ? records.reduce((sum, record) => sum + record.tokenTotal, 0) : null,
    efficiency: denominator ? acceptedUnits / denominator : null,
    reworkCount: records.length ? Math.max(...records.map((record) => record.reworkCount)) : 0,
    acceptedUnits,
    reworkUnits,
  };
}

async function enrichTask(task) {
  try {
    const detail = await api(`/api/tasks/${encodeURIComponent(task.id)}`);
    const metrics = detail.artifacts.find((artifact) => artifact.name === "metrics.md");
    let records = [];
    if (metrics?.exists && metrics.readable !== false) {
      const artifact = await api(`/api/tasks/${encodeURIComponent(task.id)}/artifacts/metrics.md`);
      records = parseMetrics(artifact.content);
    }
    const enriched = { ...task, detail, records };
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

function completionEvidence() {
  const completed = state.tasks.filter((task) => task.statusMeta.key === "archived");
  return {
    completed,
    durations: completed.map((task) => task.aggregate.duration).filter(Number.isFinite),
    tokens: completed.map((task) => task.aggregate.tokens).filter(Number.isFinite),
  };
}

function renderMetrics() {
  const evidence = completionEvidence();
  const metricTasks = state.tasks.filter((task) => task.records.length);
  const totalAccepted = metricTasks.reduce((sum, task) => sum + task.aggregate.acceptedUnits, 0);
  const totalReworkUnits = metricTasks.reduce((sum, task) => sum + task.aggregate.reworkUnits, 0);
  const efficiencyDenominator = totalAccepted + totalReworkUnits;
  const totalRework = metricTasks.reduce((sum, task) => sum + task.aggregate.reworkCount, 0);
  const durationAverage = average(evidence.durations);
  const tokenAverage = average(evidence.tokens);

  elements.metricTotal.textContent = numberFormat.format(state.tasks.length);
  elements.metricTotalNote.textContent = `${evidence.completed.length} 已归档 · ${state.tasks.length - evidence.completed.length} 未归档`;
  elements.metricDurationAverage.textContent = formatDuration(durationAverage);
  elements.metricDurationRange.textContent = evidence.durations.length
    ? `最短 ${formatDuration(Math.min(...evidence.durations))} · 最长 ${formatDuration(Math.max(...evidence.durations))}`
    : `最短 — · 最长 — · 0/${evidence.completed.length} 个完成需求具备完整度量`;
  elements.metricTokenAverage.textContent = formatTokens(tokenAverage);
  elements.metricTokenRange.textContent = evidence.tokens.length
    ? `最低 ${formatTokens(Math.min(...evidence.tokens))} · 最高 ${formatTokens(Math.max(...evidence.tokens))}`
    : `最低 — · 最高 — · 0/${evidence.completed.length} 个完成需求具备完整 Token`;
  elements.metricEfficiency.textContent = formatPercent(efficiencyDenominator ? totalAccepted / efficiencyDenominator : null);
  elements.metricRework.textContent = `返工 ${numberFormat.format(totalRework)} 次 · ${metricTasks.length} 个需求有度量`;
  elements.coverageValue.textContent = `${metricTasks.length}/${state.tasks.length || 0}`;
  elements.coverageCaption.textContent = state.tasks.length ? `${((metricTasks.length / state.tasks.length) * 100).toFixed(1)}% 的需求存在 metrics.md` : "没有需求";
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
    ["blocked", "阻塞"],
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
  let events = state.tasks.flatMap((task) => task.records.filter((record) => record.result === "FAIL").map((record) => ({ task, record })));
  if (!events.length) {
    events = state.tasks.flatMap((task) => task.records.filter((record) => record.reworkCount > 0).map((record) => ({ task, record })));
  }
  if (!events.length) {
    elements.reworkList.innerHTML = '<div class="empty-inline"><strong>没有可核验返工原因</strong><span>当前 metrics.md 中没有 FAIL 或返工备注。</span></div>';
    return;
  }
  const grouped = new Map();
  events.forEach(({ task, record }) => {
    const reason = reworkReason(record.note);
    const group = grouped.get(reason) || { reason, count: 0, samples: [] };
    group.count += 1;
    if (group.samples.length < 2) group.samples.push(`${task.id} · ${record.stage} 尝试 ${record.attempt} · ${record.note || "备注缺失"}`);
    grouped.set(reason, group);
  });
  const rows = [...grouped.values()].sort((a, b) => b.count - a.count);
  elements.reworkList.innerHTML = rows.map((row) => `<article class="rework-item"><strong>${escapeHtml(row.reason)} · ${row.count} 次</strong>${row.samples.map((sample) => `<span title="${escapeHtml(sample)}">${escapeHtml(sample)}</span>`).join("")}</article>`).join("");
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
    if (state.filters.sort === "duration-desc") return (b.aggregate.duration || -1) - (a.aggregate.duration || -1);
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
  elements.demandList.innerHTML = tasks.map((task) => `<button class="demand-card${task.id === state.selectedTaskId ? " is-active" : ""}" type="button" data-task-id="${escapeHtml(task.id)}" aria-pressed="${task.id === state.selectedTaskId}"><span class="demand-card__title" title="${escapeHtml(task.title)}">${escapeHtml(task.title)}</span><span class="demand-card__meta"><span>${escapeHtml(task.statusMeta.label)} · ${escapeHtml(task.phase || "未开始")}</span><span>${escapeHtml(formatDate(task.eventDate))}</span></span><span class="demand-card__metrics"><span>${formatDuration(task.aggregate.duration)}</span><span>${formatTokens(task.aggregate.tokens)} Token</span></span></button>`).join("");
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
    reworkCount: 0,
    acceptedUnits: 0,
    reworkUnits: 0,
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
  const completeDurations = stageEvents.length > 0 && stageEvents.every((event) => Number.isFinite(event.duration));
  const completeTokens = stageEvents.length > 0 && stageEvents.every((event) => Number.isFinite(event.tokenTotal));
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
    duration: completeDurations ? stageEvents.reduce((sum, event) => sum + event.duration, 0) : null,
    tokens: completeTokens ? stageEvents.reduce((sum, event) => sum + event.tokenTotal, 0) : null,
    reworkCount: stageEvents.length ? Math.max(...stageEvents.map((event) => event.reworkCount || 0)) : 0,
  };
}

function workflowGroupHeight(attemptCount) {
  const rows = Math.max(1, Math.ceil(attemptCount / 2));
  return 92 + 46 + rows * 72 + Math.max(0, rows - 1) * 8 + 16;
}

function workflowLayout(events) {
  const groupWidth = 286;
  const columnGap = 38;
  const paddingX = 28;
  const topY = 82;
  const attemptCounts = Object.fromEntries(STAGES.map((stage) => [stage, events.filter((event) => event.stage === stage).length]));
  const topHeight = Math.max(...STAGES.slice(0, 3).map((stage) => workflowGroupHeight(attemptCounts[stage])));
  const bottomY = topY + topHeight + 58;
  const bottomHeight = Math.max(...STAGES.slice(3).map((stage) => workflowGroupHeight(attemptCounts[stage])));
  const width = paddingX * 2 + groupWidth * 3 + columnGap * 2;
  const height = bottomY + bottomHeight + 48;
  const positions = new Map(STAGES.map((stage, index) => {
    const row = index < 3 ? 0 : 1;
    const column = row === 0 ? index : STAGES.length - 1 - index;
    return [stage, {
      stage,
      row,
      column,
      x: paddingX + column * (groupWidth + columnGap),
      y: row === 0 ? topY : bottomY,
      width: groupWidth,
      summaryHeight: 92,
    }];
  }));
  return { width, height, positions };
}

function workflowMainRoute(from, to, layout) {
  if (from.row === to.row) {
    const leftToRight = to.x > from.x;
    return leftToRight
      ? `M${from.x + from.width},${from.y + from.summaryHeight / 2} H${to.x}`
      : `M${from.x},${from.y + from.summaryHeight / 2} H${to.x + to.width}`;
  }
  const outsideX = layout.width - 14;
  return `M${from.x + from.width},${from.y + from.summaryHeight / 2} H${outsideX} V${to.y + to.summaryHeight / 2} H${to.x + to.width}`;
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
    }];
  });
}

function workflowReworkRoute(transition, transitionIndex, layout) {
  const from = layout.positions.get(transition.from);
  const to = layout.positions.get(transition.to);
  const fromX = from.x + from.width / 2;
  const toX = to.x + to.width / 2;
  if (from.row === to.row) {
    const topChannel = from.row === 0;
    const channelY = topChannel ? 28 + transitionIndex * 14 : layout.height - 24 - transitionIndex * 14;
    const fromY = topChannel ? from.y : from.y + from.summaryHeight;
    const toY = topChannel ? to.y : to.y + to.summaryHeight;
    return {
      path: `M${fromX},${fromY} C${fromX},${channelY} ${toX},${channelY} ${toX},${toY}`,
      labelX: (fromX + toX) / 2,
      labelY: topChannel ? channelY - 8 : channelY + 16,
    };
  }
  const outsideX = Math.max(from.x + from.width, to.x + to.width) + 22 + transitionIndex * 12;
  const fromY = from.y + from.summaryHeight / 2;
  const toY = to.y + to.summaryHeight / 2;
  return {
    path: `M${from.x + from.width},${fromY} H${outsideX} V${toY} H${to.x + to.width}`,
    labelX: outsideX - 8,
    labelY: (fromY + toY) / 2 - 8,
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
  camera.x = (metrics.viewportWidth - metrics.width) / 2;
  camera.y = (metrics.viewportHeight - metrics.height) / 2;
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
  const layout = workflowLayout(events);
  const stageGroups = STAGES.map((stage) => {
    const position = layout.positions.get(stage);
    const summary = summarizeStage(events, stage);
    const result = summary.latest?.result || "无记录";
    const meta = summary.events.length ? `${numberFormat.format(summary.events.length)} 次 · ${formatDuration(summary.duration)}` : "暂无阶段证据";
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
    return `<path class="workflow-route" d="${workflowMainRoute(from, to, layout)}" marker-end="url(#workflow-arrow)"/>`;
  }).join("");
  const reworkRoutes = workflowReworkTransitions(events).map((transition, index) => {
    const route = workflowReworkRoute(transition, index, layout);
    return `<path class="workflow-route is-rework" d="${route.path}" marker-end="url(#workflow-return-arrow)"/><text class="workflow-return-label" x="${route.labelX}" y="${route.labelY}" text-anchor="middle">返工回 ${transition.to} · #${String(transition.fromSequence).padStart(2, "0")}→#${String(transition.toSequence).padStart(2, "0")}</text>`;
  }).join("");
  elements.timelinePlane.dataset.width = String(layout.width);
  elements.timelinePlane.dataset.height = String(layout.height);
  elements.timelinePlane.style.width = `${layout.width}px`;
  elements.timelinePlane.style.height = `${layout.height}px`;
  elements.timelinePlane.innerHTML = `<svg width="${layout.width}" height="${layout.height}" viewBox="0 0 ${layout.width} ${layout.height}" aria-hidden="true"><defs><marker id="workflow-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z"/></marker><marker id="workflow-return-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z"/></marker></defs>${mainRoutes}${reworkRoutes}</svg>${stageGroups}`;
  elements.timelineCaption.textContent = task.records.length ? `${events.length} 条 metrics.md 记录；100% 原生清晰度，拖动空白处或用方向键浏览，Ctrl/⌘ + 滚轮缩放，普通滚轮滚动页面` : `${events.length} 个阶段产物节点；100% 原生清晰度，拖动空白处或用方向键浏览，时间缺失时不推算时长`;
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
  elements.eventDetail.innerHTML = `<div class="event-detail__grid"><span>阶段<strong>${escapeHtml(`${stage} · ${STAGE_NAMES[stage]}`)}</strong></span><span>最近结果<strong>${escapeHtml(latestResult)}</strong></span><span>尝试次数<strong>${numberFormat.format(summary.events.length)}</strong></span><span>累计用时<strong>${escapeHtml(formatDuration(summary.duration))}</strong></span><span>累计 Token<strong>${escapeHtml(formatTokens(summary.tokens))}</strong></span><span>返工次数<strong>${numberFormat.format(summary.reworkCount)}</strong></span></div>${attemptRows ? `<div class="inspector-attempts"><span>尝试记录</span>${attemptRows}</div>` : '<p class="event-note">state.md、metrics.md 与阶段产物均未提供该阶段记录。</p>'}`;
}

function renderEventDetail(event) {
  if (!event) return;
  elements.eventDetail.innerHTML = `<div class="event-detail__grid"><span>阶段<strong>${escapeHtml(`${event.stage} · 尝试 ${event.attempt}`)}</strong></span><span>结果<strong>${escapeHtml(event.result)}</strong></span><span>用时<strong>${escapeHtml(formatDuration(event.duration))}</strong></span><span>Token<strong title="${Number.isFinite(event.tokenTotal) ? numberFormat.format(event.tokenTotal) : "缺失"}">${escapeHtml(formatTokens(event.tokenTotal))}</strong></span><span>效率<strong>${escapeHtml(formatPercent(event.efficiency))}</strong></span><span>返工次数<strong>${numberFormat.format(event.reworkCount || 0)}</strong></span><span>开始<strong>${escapeHtml(formatDateTime(event.start))}</strong></span><span>结束<strong>${escapeHtml(formatDateTime(event.end))}</strong></span></div><p class="event-note"><strong>证据备注：</strong>${escapeHtml(event.note || "该记录没有备注。")} <span class="mono-meta">${escapeHtml(event.source || "metrics.md")}</span></p>`;
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
  const efficiencyRecords = records.filter((record) => Number.isFinite(record.efficiency));
  const acceptedUnits = efficiencyRecords.reduce((sum, record) => sum + (record.acceptedUnits || 0), 0);
  const reworkUnits = efficiencyRecords.reduce((sum, record) => sum + (record.reworkUnits || 0), 0);
  const efficiencyDenominator = acceptedUnits + reworkUnits;
  const rows = STAGES.map((stage) => {
    const stageRecords = records.filter((record) => record.stage === stage);
    const summary = summarizeStage(records, stage);
    const tokens = sumAvailable(stageRecords, "tokenTotal");
    const duration = sumAvailable(stageRecords, "duration");
    const eligible = stageRecords.filter((record) => Number.isFinite(record.efficiency));
    const stageAccepted = eligible.reduce((sum, record) => sum + (record.acceptedUnits || 0), 0);
    const stageReworkUnits = eligible.reduce((sum, record) => sum + (record.reworkUnits || 0), 0);
    const denominator = stageAccepted + stageReworkUnits;
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
      efficiency: denominator ? stageAccepted / denominator : null,
      acceptedUnits: stageAccepted,
      reworkUnits: stageReworkUnits,
      reworkCount: stageRecords.length ? Math.max(...stageRecords.map((record) => record.reworkCount || 0)) : 0,
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
    efficiency: efficiencyDenominator ? acceptedUnits / efficiencyDenominator : null,
    acceptedUnits,
    reworkUnits,
    reworkCount: records.length ? Math.max(...records.map((record) => record.reworkCount || 0)) : 0,
    failCount: records.filter((record) => record.result === "FAIL").length,
    blockedCount: records.filter((record) => record.result === "BLOCKED").length,
  };
}

function renderMetricKpis(model) {
  const activeStages = model.rows.filter((row) => row.attempts).length;
  const cards = [
    { label: "阶段尝试", value: numberFormat.format(model.records.length), note: `${activeStages} / ${STAGES.length} 个阶段有记录` },
    { label: "记录用时", value: formatDuration(model.durationTotal), note: `完整度 ${model.durationCoverage} / ${model.records.length}` },
    { label: "Token", value: formatTokens(model.tokenTotal), note: `精确值 ${model.tokenCoverage} / ${model.records.length}` },
    { label: "过程效率", value: formatPercent(model.efficiency), note: `有效 ${numberFormat.format(model.acceptedUnits)} · 返工影响 ${numberFormat.format(model.reworkUnits)}` },
    { label: "阶段回流", value: numberFormat.format(model.reworkCount), note: `${model.failCount} FAIL · ${model.blockedCount} BLOCKED` },
  ];
  elements.metricDrilldownKpis.innerHTML = cards.map((card) => `<article><span>${escapeHtml(card.label)}</span><strong>${escapeHtml(card.value)}</strong><small>${escapeHtml(card.note)}</small></article>`).join("");
}

function renderTokenComposition(model) {
  if (!Number.isFinite(model.tokenTotal) || !model.tokenTotal) {
    elements.tokenCompositionChart.innerHTML = '<div class="metric-empty"><strong>没有可绘制的 Token</strong><span>metrics.md 未提供精确 total。</span></div>';
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
  const legend = model.rows.filter((row) => row.attempts).map((row) => `<button type="button" class="metric-legend__item" data-metric-stage="${row.stage}" aria-pressed="${state.metricStage === row.stage}"><span class="metric-swatch" aria-hidden="true"></span><span><strong>${row.stage} · ${escapeHtml(row.name)}</strong><small>${escapeHtml(formatTokens(row.tokens))}</small></span><b>${escapeHtml(formatPercent(row.tokenShare))}</b></button>`).join("");
  elements.tokenCompositionChart.innerHTML = `<div class="token-donut"><svg viewBox="0 0 140 140" role="img" aria-label="Token 阶段构成：${escapeHtml(ariaSummary)}"><circle class="token-donut__track" cx="70" cy="70" r="52"/><g transform="rotate(-90 70 70)">${segments}</g></svg><span><small>记录 Token</small><strong>${escapeHtml(formatTokens(model.tokenTotal))}</strong></span></div><div class="metric-legend">${legend}</div>`;
}

function renderDurationDistribution(model) {
  if (!Number.isFinite(model.durationTotal) || !model.durationTotal) {
    elements.durationDistributionChart.innerHTML = '<div class="metric-empty"><strong>没有可绘制的用时</strong><span>metrics.md 未提供阶段用时。</span></div>';
    return;
  }
  elements.durationDistributionChart.innerHTML = model.rows.map((row) => {
    const share = Number.isFinite(row.durationShare) ? row.durationShare : 0;
    const selected = state.metricStage === "all" || state.metricStage === row.stage;
    return `<button type="button" class="duration-bar" data-metric-stage="${row.stage}" data-active="${selected}" aria-pressed="${state.metricStage === row.stage}" aria-label="${row.stage} ${escapeHtml(row.name)}，${escapeHtml(formatDuration(row.duration))}，占 ${escapeHtml(formatPercent(row.durationShare))}"><span class="duration-bar__label"><strong>${row.stage}</strong><small>${escapeHtml(row.name)}</small></span><span class="duration-bar__track"><i aria-hidden="true" style="--metric-share:${share * 100}%"></i></span><span class="duration-bar__value"><strong>${escapeHtml(formatDuration(row.duration))}</strong><small>${escapeHtml(formatPercent(row.durationShare))}</small></span></button>`;
  }).join("");
}

function renderMetricStageDetail(model) {
  const selected = state.metricStage === "all" ? null : model.rows.find((row) => row.stage === state.metricStage);
  if (!selected) {
    const tokenHotspot = model.rows.filter((row) => Number.isFinite(row.tokens)).sort((a, b) => b.tokens - a.tokens)[0];
    const durationHotspot = model.rows.filter((row) => Number.isFinite(row.duration)).sort((a, b) => b.duration - a.duration)[0];
    elements.metricStageDetailTitle.textContent = "全部阶段";
    elements.metricStageDetailCaption.textContent = `${model.records.length} 条记录 · ${formatDateTime(model.start)} 至 ${formatDateTime(model.end)}`;
    elements.metricStageDetailBody.innerHTML = `<div class="metric-diagnosis"><article><span>Token 集中阶段</span><strong>${tokenHotspot ? `${tokenHotspot.stage} · ${formatPercent(tokenHotspot.tokenShare)}` : "—"}</strong><small>${tokenHotspot ? escapeHtml(tokenHotspot.name) : "无可核验数据"}</small></article><article><span>耗时最长阶段</span><strong>${durationHotspot ? `${durationHotspot.stage} · ${formatPercent(durationHotspot.durationShare)}` : "—"}</strong><small>${durationHotspot ? escapeHtml(formatDuration(durationHotspot.duration)) : "无可核验数据"}</small></article><article><span>回流影响</span><strong>${numberFormat.format(model.reworkCount)} 次</strong><small>${numberFormat.format(model.reworkUnits)} 个返工影响单元</small></article></div>`;
    return;
  }
  elements.metricStageDetailTitle.textContent = `${selected.stage} · ${selected.name}`;
  elements.metricStageDetailCaption.textContent = `${selected.attempts} 条尝试 · ${formatCanvasStart(selected.start)} 至 ${formatDateTime(selected.end)} · 最近结果 ${selected.result}`;
  const summary = `<div class="metric-stage-summary"><span><small>记录用时</small><strong>${escapeHtml(formatDuration(selected.duration))}</strong></span><span><small>Token</small><strong>${escapeHtml(formatTokens(selected.tokens))}</strong></span><span><small>效率</small><strong>${escapeHtml(formatPercent(selected.efficiency))}</strong></span><span><small>返工</small><strong>${numberFormat.format(selected.reworkCount)}</strong></span></div>`;
  const attempts = selected.records.length ? selected.records.map((record) => `<article class="metric-attempt" data-result="${escapeHtml(record.result)}"><header><span>${escapeHtml(`${record.stage} · 尝试 ${record.attempt}`)}</span><strong>${escapeHtml(record.result)}</strong></header><dl><div><dt>开始</dt><dd>${escapeHtml(formatCanvasStart(record.start))}</dd></div><div><dt>用时</dt><dd>${escapeHtml(formatDuration(record.duration))}</dd></div><div><dt>Token</dt><dd>${escapeHtml(formatTokens(record.tokenTotal))}</dd></div><div><dt>效率</dt><dd>${escapeHtml(formatPercent(record.efficiency))}</dd></div></dl></article>`).join("") : '<div class="metric-empty"><strong>该阶段没有 metrics.md 记录</strong><span>不使用 state.md 或阶段产物推算指标。</span></div>';
  elements.metricStageDetailBody.innerHTML = `${summary}<div class="metric-attempts">${attempts}</div>`;
}

function renderMetricStageTable(model) {
  elements.metricStageTable.innerHTML = model.rows.map((row) => `<tr data-selected="${state.metricStage === row.stage}"><td><button type="button" class="metric-table__stage" data-metric-stage="${row.stage}" aria-pressed="${state.metricStage === row.stage}"><span class="metric-swatch" aria-hidden="true"></span><strong>${row.stage}</strong><small>${escapeHtml(row.name)}</small></button></td><td>${numberFormat.format(row.attempts)}</td><td><span class="metric-result" data-result="${escapeHtml(row.result)}">${escapeHtml(row.result)}</span></td><td><strong>${escapeHtml(formatDuration(row.duration))}</strong><small>${escapeHtml(formatPercent(row.durationShare))}</small></td><td><strong title="${Number.isFinite(row.tokens) ? numberFormat.format(row.tokens) : "缺失"}">${escapeHtml(formatTokens(row.tokens))}</strong><small>${escapeHtml(formatPercent(row.tokenShare))}</small></td><td>${escapeHtml(formatPercent(row.efficiency))}</td><td>${numberFormat.format(row.reworkCount)}</td></tr>`).join("");
}

function renderMetricDrilldown(task) {
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
  elements.metricDrilldownCaption.textContent = model.records.length ? `${formatDateTime(model.start)} 至 ${formatDateTime(model.end)} · Token ${model.tokenCoverage}/${model.records.length} · 用时 ${model.durationCoverage}/${model.records.length}` : "当前需求没有可读取的 metrics.md；下方不展示推算值。";
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
  elements.detailBadges.innerHTML = `<span class="badge" data-tone="${task.statusMeta.key}">${escapeHtml(task.statusMeta.label)}</span><span class="badge">${escapeHtml(task.phase || "未开始")}</span><span class="badge">${escapeHtml(task.category)}</span>${task.loadError ? '<span class="badge" data-tone="cancelled">读取不完整</span>' : ""}`;
  elements.detailDuration.textContent = formatDuration(task.aggregate.duration);
  elements.detailTokens.textContent = formatTokens(task.aggregate.tokens);
  elements.detailTokens.title = Number.isFinite(task.aggregate.tokens) ? numberFormat.format(task.aggregate.tokens) : "缺失";
  elements.detailEfficiency.textContent = formatPercent(task.aggregate.efficiency);
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
  elements.contextTitle.textContent = overview ? "效率与需求事件" : "需求复盘与时间线";
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
    { type: "view", value: "overview", label: "总览", meta: "效率与需求事件" },
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

bindTimelineCamera();
bindEvents();
setDemandDrawer(true);
loadDashboard();
