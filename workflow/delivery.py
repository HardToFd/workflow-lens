"""Bind reviewable delivery artifacts to the exact local evidence used to prepare them."""

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict

try:
    from .core import validate_task_id
except ImportError:
    from core import validate_task_id


SNAPSHOT = "delivery-snapshot.json"
INPUTS = ("plan.md", "impl-log.md", "verify.md")
STATUS_RE = re.compile(r"^- 交付状态[:：]\s*`?(CURRENT|STALE)`?\s*$", re.MULTILINE)


def _inside(path: Path, parent: Path) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(parent.resolve())
    except ValueError:
        raise ValueError("delivery path escapes task directory: " + str(path))
    return resolved


def _task_dir(task_id: str, root: Path) -> Path:
    valid, reason = validate_task_id(task_id)
    if not valid:
        raise ValueError(reason)
    return _inside(root / "work" / task_id, root / "work")


def _digest(path: Path, task: Path) -> str:
    return hashlib.sha256(_inside(path, task).read_bytes()).hexdigest()


def _binding(state: Dict[str, Any]) -> list:
    # 完成/闸口/计时会正常更新，不把这些展示字段当作交付内容变更。
    fields = (("project", "项目"), ("branch", "分支"), ("test_branch", "联测分支"))
    rows = [
        {keys[-1]: str(next((row[key] for key in keys if row.get(key)), "")).strip().strip("`")
         for keys in fields}
        for row in state.get("projects", [])
    ]
    return sorted(rows, key=lambda row: row["项目"])


def _delivery_projects(state: Dict[str, Any]) -> list:
    rows = state.get("projects", [])
    phases = [row.get("phase") or row.get("stage") or row.get("阶段") for row in rows]
    # 逐项目交付不能被较早的顶层摘要阶段挡住；旧表没有行阶段时才回退顶层。
    if not any(phases):
        phases = [state.get("stage") or state.get("环节")] * len(rows)
    return sorted(
        str(row.get("project") or row.get("项目") or "").strip().strip("`")
        for row, phase in zip(rows, phases) if phase in ("S5", "S6")
    )


def _fingerprints(task: Path, root: Path) -> Dict[str, Dict[str, str]]:
    inputs = {name: _digest(task / name, task) for name in INPUTS}
    # PRD/分析可能先于方案被修订；旧模板缺少这些文件时仍可登记现有证据。
    if (task / "analysis.md").exists():
        inputs["analysis.md"] = _digest(task / "analysis.md", task)
    prd = root / "prds" / (task.name + ".md")
    if prd.exists():
        inputs["prds/" + prd.name] = _digest(prd, root)
    outputs = {"delivery.md": _digest(task / "delivery.md", task)}
    attachment_dir = task / "delivery"
    if attachment_dir.exists():
        _inside(attachment_dir, task)
        for path in sorted(attachment_dir.rglob("*")):
            relative = path.relative_to(task)
            # 历史材料继续保留，但不再属于当前可交付附件。
            if "history" not in relative.parts and path.is_file():
                outputs[relative.as_posix()] = _digest(path, task)
    for pattern in ("*.patch", "*.diff"):
        for path in sorted(task.glob(pattern)):
            outputs[path.name] = _digest(path, task)
    return {"inputs": inputs, "artifacts": outputs}


def check_delivery(task_id: str, root: Path, state: Dict[str, Any]) -> Dict[str, Any]:
    """Read-only freshness check; CURRENT is consistency, never approval or test success."""
    task = _task_dir(task_id, root)
    delivery = task / "delivery.md"
    result = {"status": "ABSENT", "ok": False, "reasons": [], "snapshot": None}
    if not delivery.is_file():
        return result
    try:
        content = _inside(delivery, task).read_text(encoding="utf-8-sig")
        declarations = STATUS_RE.findall(content)
        if "STALE" in declarations or not _delivery_projects(state):
            return dict(result, status="STALE", reasons=["delivery invalidated or task returned before S5"])
        snapshot_path = task / SNAPSHOT
        if not snapshot_path.is_file():
            return dict(result, status="UNVERIFIED", reasons=["no delivery snapshot; review existing evidence before recording"])
        snapshot = json.loads(_inside(snapshot_path, task).read_text(encoding="utf-8"))
        if not isinstance(snapshot, dict) or snapshot.get("schema_version") != 1 or snapshot.get("task_id") != task_id:
            raise ValueError("invalid delivery snapshot")
        fingerprints = _fingerprints(task, root)
        reasons = []
        if declarations != ["CURRENT"]:
            reasons.append("delivery.md must declare one CURRENT status")
        for group, current in fingerprints.items():
            if snapshot.get(group) != current:
                reasons.append(group + " changed since delivery was reviewed")
        if snapshot.get("projects") != _binding(state):
            reasons.append("project/feature/test binding changed since delivery was reviewed")
        if snapshot.get("delivery_projects") != _delivery_projects(state):
            reasons.append("projects ready for delivery changed; review the bundle again")
        return dict(result, status="STALE" if reasons else "CURRENT", ok=not reasons,
                    reasons=reasons, snapshot="work/{}/{}".format(task_id, SNAPSHOT))
    except (OSError, ValueError, TypeError) as exc:
        return dict(result, status="STALE", reasons=[str(exc)])


def record_delivery(task_id: str, root: Path, state: Dict[str, Any]) -> Dict[str, Any]:
    """Record a reviewed local bundle without changing workflow stage or approval."""
    task = _task_dir(task_id, root)
    if not _delivery_projects(state):
        raise ValueError("delivery can only be recorded in S5 or S6 after verification")
    content = _inside(task / "delivery.md", task).read_text(encoding="utf-8-sig")
    if STATUS_RE.findall(content) != ["CURRENT"]:
        raise ValueError("review and regenerate delivery.md with '- 交付状态: CURRENT' first")
    fingerprints = _fingerprints(task, root)
    snapshot = dict(fingerprints, schema_version=1, task_id=task_id, projects=_binding(state),
                    delivery_projects=_delivery_projects(state),
                    recorded_at=datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"))
    target = _inside(task / SNAPSHOT, task)
    if target.is_file():
        previous = target.read_bytes()
        digest = hashlib.sha256(previous).hexdigest()
        history = _inside(task / "delivery" / "history", task)
        history.mkdir(parents=True, exist_ok=True)
        old = _inside(history / ("snapshot-" + digest + ".json"), task)
        if old.exists() and old.read_bytes() != previous:
            raise ValueError("delivery snapshot history collision")
        if not old.exists():
            old.write_bytes(previous)
    # 同目录原子替换；失败时旧快照仍在，避免半写入被误认为当前交付。
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=task,
                                         prefix=".delivery-", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(snapshot, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary, target)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()
    return check_delivery(task_id, root, state)
