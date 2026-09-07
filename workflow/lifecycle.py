"""Read the current lifecycle summary without interpreting delivery as deployment."""

import re

try:
    from .core import MANIFEST
except ImportError:
    from core import MANIFEST


LABELS = {
    "生命周期": "state", "关闭原因": "closure_reason", "交付形态": "delivery_form",
    "人工验收": "acceptance", "合入": "merge", "部署": "deployment", "清理": "cleanup",
    "状态依据": "evidence", "检查时间": "checked_at",
}


def _value(value):
    return str(value or "").strip().strip("`").strip()


def _legacy_state(phase, status):
    # “完成本地实现”只是进度文字；只有明确 S6 才能兼容推导归档。
    if re.search(r"作废|取消|\bcancel(?:led|ed)?\b", status, re.I):
        return "CANCELLED"
    if re.match(r"BLOCKED\b|阻塞|挂起", status, re.I):
        return "BLOCKED"
    if re.match(r"等待|WAITING\b", status, re.I):
        return "WAITING"
    if phase == "S6":
        return "ARCHIVED"
    return "ACTIVE"


def read_lifecycle(content, phase=None, status=None):
    """Only the unique current section is authoritative; history stays untouched."""
    top = content.split("\n## ", 1)[0]
    if phase is None:
        match = re.search(r"^- 环节:\s*(.*)$", top, re.M)
        phase = _value(match.group(1)) if match else ""
    if status is None:
        match = re.search(r"^- 状态:\s*(.*)$", top, re.M)
        status = _value(match.group(1)) if match else ""
    fallback = _legacy_state(_value(phase), _value(status))
    result = {key: "UNKNOWN" for key in LABELS.values()}
    result.update(state=fallback, source="legacy", issues=[], evidence="", checked_at="")
    result["closure_reason"] = "CANCELLED" if fallback == "CANCELLED" else "NONE" if fallback in ("ACTIVE", "BLOCKED", "WAITING") else "UNKNOWN"
    sections = list(re.finditer(r"(?m)^## 当前状态摘要\s*$", content))
    if not sections:
        return result
    if len(sections) != 1:
        result["issues"].append("当前状态摘要不唯一，使用阶段兼容分类")
        return result
    result["source"] = "explicit"
    body = re.split(r"(?m)^## ", content[sections[0].end():], maxsplit=1)[0]
    schema = MANIFEST["lifecycle"]
    for label, key in LABELS.items():
        values = re.findall(r"^- " + re.escape(label) + r"[：:][ \t]*(.*)$", body, re.M)
        if len(values) != 1:
            result["issues"].append(label + "缺少唯一值")
            continue
        value = _value(values[0])
        if key in schema and value not in schema[key]:
            result["issues"].append(label + "枚举无效")
            continue
        result[key] = value
    if result["state"] == "ARCHIVED" and _value(phase) != "S6":
        result["issues"].append("归档摘要与当前阶段冲突，按当前阶段分类")
        result["state"] = fallback
    # 缺证据时不让结构化字段把未核验的验收/上线/清理提升为已完成。
    if not result["evidence"]:
        for key in ("acceptance", "merge", "deployment", "cleanup"):
            if result[key] in ("PASS", "MERGED", "VERIFIED", "COMPLETE"):
                result[key] = "UNKNOWN"
                result["issues"].append(key + "缺少状态依据")
    return result
