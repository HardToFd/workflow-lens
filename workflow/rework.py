"""An append-only event ledger inside the existing per-task metrics document."""

import re
from datetime import datetime, timedelta, timezone

try:
    from .core import MANIFEST, STAGES, validate_task_id
    from .metrics_store import metrics_lock
except ImportError:
    from core import MANIFEST, STAGES, validate_task_id
    from metrics_store import metrics_lock


FIELDS = {
    "类型": "type", "回路": "loop", "项目": "project", "来源阶段": "from_stage",
    "目标阶段": "to_stage", "事件时间": "occurred_at", "原因": "reason",
    "关联验收": "acceptance", "证据": "evidence",
}
EVENT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
ZONE = timezone(timedelta(hours=8))


def _line(value, label):
    if not isinstance(value, str) or not value.strip() or any(ord(c) < 32 for c in value):
        raise ValueError(label + " must be a nonempty single line")
    return value.strip()


def validate_event(event):
    result = {key: _line(event.get(key), key) for key in ["id"] + list(FIELDS.values())}
    if not EVENT_ID.fullmatch(result["id"]):
        raise ValueError("invalid rework event id")
    if result["type"] not in MANIFEST["metrics"]["rework_types"]:
        raise ValueError("invalid rework type")
    if result["loop"] not in ("L1", "L2", "L3", "NONE"):
        raise ValueError("invalid rework loop")
    if result["from_stage"] not in STAGES or result["to_stage"] not in STAGES:
        raise ValueError("invalid rework stage")
    if result["loop"] == "L1" and (result["type"], result["from_stage"], result["to_stage"]) != ("defect", "S4", "S3"):
        raise ValueError("L1 requires an implementation defect returning from S4 to S3")
    if result["occurred_at"] != "NOT_AVAILABLE":
        stamp = datetime.fromisoformat(result["occurred_at"].replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            raise ValueError("event time must include timezone")
        result["occurred_at"] = stamp.astimezone(ZONE).isoformat(timespec="seconds")
    return result


def read_rework(content):
    events, invalid_ids, issues = {}, set(), []
    # 所有二级节均为边界，不能把事件字段串到最后一条阶段记录。
    for block in re.split(r"(?m)^## ", content)[1:]:
        title, _, body = block.partition("\n")
        if not title.startswith("返工事件 "):
            continue
        event_id = title[len("返工事件 "):].strip()
        event = {"id": event_id}
        try:
            for label, key in FIELDS.items():
                values = re.findall(r"^- " + label + r"[：:][ \t]*(.*)$", body, re.M)
                if len(values) != 1:
                    raise ValueError(label + "缺少唯一值")
                raw = values[0].strip()
                if key not in ("reason", "acceptance", "evidence"):
                    quoted = re.fullmatch(r"(`+)(.*?)\1", raw)
                    raw = quoted.group(2).strip() if quoted else raw
                event[key] = raw
            event = validate_event(event)
            if event_id in events and events[event_id] != event:
                raise ValueError("同一事件 ID 内容冲突")
            events[event_id] = event
        except ValueError as error:
            invalid_ids.add(event_id)
            issues.append(event_id + ": " + str(error))
    valid = [event for key, event in events.items() if key not in invalid_ids]
    legacy = len(re.findall(r"(?m)^- 返工次数[：:][ \t]*`?[1-9]\d*`?[ \t]*$", content))
    return {
        "status": "INVALID" if issues else "PARTIAL" if legacy else "RECORDED" if valid else "ABSENT",
        "events": valid, "event_count": len(valid),
        "l1_count": sum(event["type"] == "defect" and event["loop"] == "L1" for event in valid),
        "legacy_records": legacy, "issues": issues,
    }


def check_rework(task_id, root):
    valid, reason = validate_task_id(task_id)
    if not valid:
        raise ValueError(reason)
    path = root / "work" / task_id / "metrics.md"
    return dict(read_rework(path.read_text(encoding="utf-8") if path.exists() else ""), task_id=task_id)


def record_rework(task_id, root, event):
    valid, reason = validate_task_id(task_id)
    if not valid:
        raise ValueError(reason)
    event = validate_event(event)
    directory = root / "work" / task_id
    if not directory.is_dir():
        raise ValueError("task work directory must already exist")
    path = directory / "metrics.md"
    with metrics_lock(directory):
        content = path.read_text(encoding="utf-8") if path.exists() else "# 需求过程度量：" + task_id + "\n"
        current = read_rework(content)
        if current["issues"]:
            raise ValueError("existing rework ledger is invalid: " + "; ".join(current["issues"]))
        previous = next((row for row in current["events"] if row["id"] == event["id"]), None)
        if previous:
            if previous != event:
                raise ValueError("rework event id already has different content")
            return {"ok": True, "status": "ALREADY_RECORDED", "event": previous}
        lines = ["", "## 返工事件 " + event["id"], ""]
        lines += ["- " + label + "：" + (event[key] if key in ("reason", "acceptance", "evidence") else "`" + event[key] + "`") for label, key in FIELDS.items()]
        lines += ["- 登记时间：`" + datetime.now(ZONE).isoformat(timespec="seconds") + "`", ""]
        # 追加保留原始阶段字节；锁与 metrics-record 共用，避免并行项目覆盖记录。
        with path.open("ab") as handle:
            if handle.tell() == 0:
                handle.write(content.encode("utf-8"))
            handle.write((("" if content.endswith("\n") else "\n") + "\n".join(lines)).encode("utf-8"))
        return {"ok": True, "status": "RECORDED", "event": event}
