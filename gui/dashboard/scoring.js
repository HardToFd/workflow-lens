"use strict";

(function (root) {
  const FORMULA = "efficiency-v1";
  const FIELDS = {
    "公式版本": "formulaVersion", "基准版本": "baselineVersion", "基准分组": "baselineGroup",
    "基准耗时秒数": "baselineTime", "基准Token": "baselineTokens", "验收项数": "acceptanceItems",
    "基准冻结时间": "frozenAt", "基准依据": "evidence", "记录核对": "recordsChecked",
    "返工核对": "reworkChecked", "核对依据": "reviewEvidence", "核对记录数": "checkedRecordCount",
    "核对事件数": "checkedEventCount", "旧返工映射": "legacyMapping",
  };
  const EVENT_TYPES = new Set(["defect", "scope_change", "baseline_adaptation", "environment", "workflow_migration"]);
  const EVENT_KEYS = ["id", "type", "loop", "project", "fromStage", "toStage", "time", "reason", "acceptance", "evidence"];

  function unwrap(value) {
    const text = String(value ?? "").trim();
    return text.match(/^(`+)(.*?)\1$/)?.[2].trim() ?? text;
  }

  function meaningful(value) {
    return typeof value === "string" && value.trim() !== ""
      && !/^(?:NOT_AVAILABLE|UNKNOWN|N\/A|<[^>]*>)$/i.test(unwrap(value));
  }

  function timestamp(value) {
    if (typeof value !== "string") return null;
    const parts = value.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d{1,3})?(Z|[+-]\d{2}:\d{2})$/);
    if (!parts) return null;
    const [, year, month, day, hour, minute, second, zone] = parts;
    const y = Number(year), m = Number(month), d = Number(day);
    const leap = y % 4 === 0 && (y % 100 !== 0 || y % 400 === 0);
    const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
    if (y < 1 || m < 1 || m > 12 || d < 1 || d > days[m - 1]
      || Number(hour) > 23 || Number(minute) > 59 || Number(second) > 59
      || (zone !== "Z" && (Number(zone.slice(1, 3)) > 23 || Number(zone.slice(4)) > 59))) return null;
    const result = Date.parse(value);
    return Number.isFinite(result) ? result : null;
  }

  function finiteNumber(value, integer = false, positive = false) {
    return typeof value === "number" && Number.isFinite(value) && value <= Number.MAX_SAFE_INTEGER
      && (positive ? value > 0 : value >= 0) && (!integer || Number.isSafeInteger(value));
  }

  function parseScoreBasis(content) {
    const result = { valid: false, issues: [] };
    if (typeof content !== "string") {
      result.issues.push("评分依据内容不可读取");
      return result;
    }
    const headings = [...content.matchAll(/^##[ \t]+([^\r\n]+)[ \t]*\r?$/gm)];
    const sections = headings.map((heading, index) => ({
      title: heading[1].trim(), body: content.slice(heading.index + heading[0].length, headings[index + 1]?.index ?? content.length),
    })).filter((section) => section.title === "综合效率评分依据");
    if (sections.length !== 1) {
      result.issues.push(sections.length ? "综合效率评分依据不唯一" : "缺少综合效率评分依据");
      return result;
    }
    for (const [label, key] of Object.entries(FIELDS)) {
      const values = [...sections[0].body.matchAll(new RegExp(`^- ${label}[：:][ \\t]*([^\\r\\n]*)`, "gm"))];
      if (!values.length && key === "legacyMapping") continue;
      if (values.length !== 1) {
        result.issues.push(`${label}缺少唯一值`);
        continue;
      }
      result[key] = ["evidence", "reviewEvidence"].includes(key) ? values[0][1].trim() : unwrap(values[0][1]);
    }
    for (const key of ["baselineTime", "baselineTokens", "acceptanceItems", "checkedRecordCount", "checkedEventCount"]) {
      const raw = result[key];
      const integer = key !== "baselineTime";
      const positive = ["baselineTime", "baselineTokens", "acceptanceItems"].includes(key);
      if (typeof raw !== "string" || !(integer ? /^\d+$/ : /^\d+(?:\.\d+)?$/).test(raw)
        || !finiteNumber(Number(raw), integer, positive)) {
        result.issues.push(`${Object.keys(FIELDS).find((label) => FIELDS[label] === key)}数值无效`);
        result[key] = null;
      } else result[key] = Number(raw);
    }
    if (result.formulaVersion !== FORMULA) result.issues.push("公式版本不支持");
    for (const key of ["baselineVersion", "baselineGroup", "evidence", "reviewEvidence"]) {
      if (!meaningful(result[key])) result.issues.push(`${Object.keys(FIELDS).find((label) => FIELDS[label] === key)}未提供`);
    }
    if (timestamp(result.frozenAt) === null) result.issues.push("基准冻结时间必须为有效的带时区 ISO 时间");
    if (result.recordsChecked !== "COMPLETE") result.issues.push("阶段记录尚未完整核对");
    if (result.reworkChecked !== "COMPLETE") result.issues.push("返工事件尚未完整核对");
    if (result.legacyMapping !== undefined && result.legacyMapping !== "COMPLETE") result.issues.push("旧返工映射尚未完成");
    result.valid = result.issues.length === 0;
    return result;
  }

  function accepted(task) {
    const lifecycle = task?.lifecycle || task?.detail?.lifecycle;
    return lifecycle?.source === "explicit" && lifecycle.state === "ARCHIVED" && lifecycle.acceptance === "PASS"
      && Array.isArray(lifecycle.issues) && lifecycle.issues.length === 0;
  }

  function scoreTask(task) {
    const result = { status: "NOT_AVAILABLE", score: null, reasons: [], factors: null, totals: null, baselineTime: null };
    const fail = (reason) => result.reasons.push(reason);
    if (!accepted(task)) fail("缺少已验收归档的明确记录，或状态记录存在冲突");
    if ((task?.detail?.delivery || task?.delivery)?.status === "STALE") fail("交付材料已失效，需重新核对验收和评分依据");
    const basis = task?.scoreBasis;
    const basisReady = basis?.valid && Array.isArray(basis.issues) && basis.issues.length === 0;
    if (!basisReady) {
      if (Array.isArray(basis?.issues) && basis.issues.length) result.reasons.push(...basis.issues);
      else fail("缺少综合效率评分依据");
    } else {
      if (!finiteNumber(basis.baselineTime, false, true) || !finiteNumber(basis.baselineTokens, true, true)
        || !finiteNumber(basis.acceptanceItems, true, true) || basis.formulaVersion !== FORMULA) fail("冻结基准数值或公式版本无效");
      if (basis.recordsChecked !== "COMPLETE" || basis.reworkChecked !== "COMPLETE"
        || !meaningful(basis.reviewEvidence)) fail("记录及返工完整性缺少核对依据");
    }
    const records = Array.isArray(task?.records) ? task.records : [];
    if (!records.length) fail("没有完整阶段记录");
    if (basisReady && records.length && basis.checkedRecordCount !== records.length) fail("阶段记录数与核对记录数不符，需重新核对");
    const identifiers = new Set(), implementationStarts = [];
    let time = 0, tokens = 0;
    for (const record of records) {
      const key = `${record?.stage}/${record?.attempt}`;
      if (!/^S[1-6]$/.test(record?.stage) || !finiteNumber(record?.attempt, true, true) || identifiers.has(key)) fail("阶段记录标识无效或重复");
      identifiers.add(key);
      const start = timestamp(record?.start), end = timestamp(record?.end);
      if (start === null || end === null || end < start) fail("阶段记录时间窗口无效或缺失");
      if (/^S[3-6]$/.test(record?.stage) && start !== null) implementationStarts.push(start);
      if (!finiteNumber(record?.duration, true) || !finiteNumber(record?.tokenTotal, true)) fail("阶段记录存在缺失或无效的耗时/Token");
      else {
        time += record.duration;
        tokens += record.tokenTotal;
        if (start !== null && end !== null && Math.abs(record.duration - (end - start) / 1000) >= 1) fail("阶段用时与开始结束窗口不一致");
      }
      if (!meaningful(record?.tokenSource) || /^NOT_AVAILABLE\b/.test(record.tokenSource)) fail("阶段 Token 缺少明确来源");
    }
    // 冻结时间必须先于实施，不能用交付后补的预算美化历史成绩。
    if (basisReady && records.length) {
      const frozen = timestamp(basis.frozenAt);
      if (!records.some((record) => record?.stage === "S3") || !implementationStarts.length) fail("缺少 S3 实施时间证据");
      if (frozen === null || (implementationStarts.length && frozen > Math.min(...implementationStarts))) fail("基准未在实施前冻结");
      if (records.some((record) => record?.hasLegacyRework || record?.legacyReworkCount > 0) && basis.legacyMapping !== "COMPLETE") fail("旧返工数字尚未按事件完成映射");
    }
    const ledger = task?.rework;
    const events = new Map();
    if (!ledger || !Array.isArray(ledger.events) || !Array.isArray(ledger.conflicts) || !Array.isArray(ledger.invalid)) fail("缺少可核对的返工事件账本");
    else {
      if (ledger.conflicts.length || ledger.invalid.length) fail("返工事件存在冲突或无效记录");
      for (const event of ledger.events) {
        if (!event || EVENT_KEYS.some((key) => !meaningful(event[key]) && !(key === "time" && event[key] === "NOT_AVAILABLE"))
          || EVENT_KEYS.some((key) => /[\u0000-\u001f]/.test(event[key]))
          || !/^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/.test(event.id) || !EVENT_TYPES.has(event.type)
          || !["L1", "L2", "L3", "NONE"].includes(event.loop) || !/^S[1-6]$/.test(event.fromStage) || !/^S[1-6]$/.test(event.toStage)
          || (event.loop === "L1" && (event.type !== "defect" || event.fromStage !== "S4" || event.toStage !== "S3"))
          || (event.time !== "NOT_AVAILABLE" && timestamp(event.time) === null)) {
          fail("返工事件字段无效");
          continue;
        }
        const signature = JSON.stringify(EVENT_KEYS.map((key) => key === "time" && event.time !== "NOT_AVAILABLE" ? timestamp(event.time) : event[key]));
        if (events.has(event.id) && events.get(event.id).signature !== signature) fail("同一返工事件 ID 内容冲突");
        else events.set(event.id, { event, signature });
      }
    }
    if (basisReady && basis.checkedEventCount !== events.size) fail("事件数与核对事件数不符，需重新核对");
    if (!finiteNumber(time, true) || !finiteNumber(tokens, true)) fail("合计耗时或 Token 超出有效范围");
    result.reasons = [...new Set(result.reasons)];
    if (result.reasons.length) return result;
    const defects = [...events.values()].filter(({ event }) => event.type === "defect").length;
    const factors = {
      time: basis.baselineTime / Math.max(basis.baselineTime, time),
      token: basis.baselineTokens / Math.max(basis.baselineTokens, tokens),
      quality: basis.acceptanceItems / (basis.acceptanceItems + defects),
    };
    // 等待已包含在区间耗时中，不再单独扣分；保留全精度供总览加权。
    return { status: "SCORED", score: 100 * factors.time ** 0.35 * factors.token ** 0.25 * factors.quality ** 0.40,
      reasons: [], factors, totals: { time, tokens, defects, acceptanceItems: basis.acceptanceItems }, baselineTime: basis.baselineTime };
  }

  function scoreOverview(tasks) {
    const source = Array.isArray(tasks) ? tasks : [];
    const results = source.map(scoreTask);
    const scored = results.filter((result) => result.status === "SCORED");
    const acceptedCount = source.filter(accepted).length;
    const maxWeight = scored.length ? Math.max(...scored.map((result) => result.baselineTime)) : 1;
    const weights = scored.map((result) => result.baselineTime / maxWeight);
    const denominator = weights.reduce((total, weight) => total + weight, 0);
    return {
      score: scored.length ? scored.reduce((total, result, index) => total + weights[index] * result.score, 0) / denominator : null,
      scoredCount: scored.length, acceptedCount, totalCount: source.length,
      coverage: acceptedCount ? scored.length / acceptedCount : null,
      allCoverage: source.length ? scored.length / source.length : null, results,
    };
  }

  const api = { parseScoreBasis, scoreTask, scoreOverview };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (root) root.WorkflowEfficiency = api;
})(typeof window !== "undefined" ? window : null);
