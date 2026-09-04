#!/usr/bin/env python3
"""Inspect and validate the workflow without loading the complete documentation set."""

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from .core import MANIFEST, STAGES, can_transition, stage_definition, validate_task_id
    from .token_usage import (
        collect_runtime_usage,
        current_codex_session_ids,
        current_omp_session_files,
        default_codex_home,
    )
except ImportError:
    from core import MANIFEST, STAGES, can_transition, stage_definition, validate_task_id
    from token_usage import (
        collect_runtime_usage,
        current_codex_session_ids,
        current_omp_session_files,
        default_codex_home,
    )


ROOT = Path(__file__).resolve().parent.parent
TOP_FIELD_RE = re.compile(r"^- (?P<label>环节|状态|闸口A|闸口B|NOT_RUN 确认):\s*(?P<value>.*)$")
METRIC_SECTION_RE = re.compile(
    r"(?ms)^## (?P<stage>S[1-6]) · 尝试 (?P<attempt>\d+)\n(?P<body>.*?)(?=^## S[1-6] · 尝试 \d+\n|\Z)"
)
METRIC_OUTCOMES = ("PASS", "FAIL", "NOT_RUN", "BLOCKED", "CANCELLED")
METRIC_TIMEZONE = timezone(timedelta(hours=8))


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def parse_state(path: Path) -> Dict[str, Any]:
    if path.suffix.lower() == ".json":
        data = json.loads(_read_text(path))
        if not isinstance(data, dict):
            raise ValueError("state.json must contain an object")
        return data
    result = {}  # type: Dict[str, Any]
    projects = []  # type: List[Dict[str, str]]
    headers = []  # type: List[str]
    for raw in _read_text(path).splitlines():
        match = TOP_FIELD_RE.match(raw)
        if match:
            result[match.group("label")] = match.group("value").strip()
        stripped = raw.strip()
        if not (stripped.startswith("|") and stripped.endswith("|")):
            continue
        cells = [cell.strip() for cell in stripped[1:-1].split("|")]
        if "项目" in cells and "阶段" in cells and "行状态" in cells:
            headers = cells
            continue
        if headers and len(cells) == len(headers) and not all(set(cell) <= set("-:") for cell in cells):
            projects.append(dict(zip(headers, cells)))
    result["projects"] = projects
    return result


def state_for(task_id: str, root: Path) -> Dict[str, Any]:
    task = root / "work" / task_id
    for name in ("state.json", "state.md"):
        path = task / name
        if path.is_file():
            state = parse_state(path)
            state["_path"] = str(path.relative_to(root)).replace("\\", "/")
            return state
    return {"环节": "S1", "状态": "未初始化", "projects": [], "_path": None}


def _artifact(root: Path, task_id: str, template: str) -> str:
    return template.replace("<id>", task_id)


def _enabled_stage_skills(root: Path, stage: str) -> List[str]:
    registry = root / "config" / "skills.md"
    if not registry.is_file():
        return []
    rows = []
    in_table = False
    for raw in _read_text(registry).splitlines():
        if raw.strip() == "## 当前挂载表":
            in_table = True
            continue
        if not in_table or not raw.strip().startswith("|"):
            continue
        cells = [cell.strip().strip("`") for cell in raw.strip()[1:-1].split("|")]
        if len(cells) != 4 or cells[0] in ("技能文件", "----------"):
            continue
        mounts = [item.strip() for item in cells[1].split(",")]
        if stage in mounts and cells[3] == "启用":
            rows.append(cells[0])
    return rows


def _metric_now() -> str:
    return datetime.now(METRIC_TIMEZONE).replace(microsecond=0).isoformat()


def _normalize_metric_timestamp(value: str) -> str:
    return _parse_utc(value).astimezone(METRIC_TIMEZONE).replace(microsecond=0).isoformat()


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def _metrics_path(root: Path, task_id: str) -> Path:
    return root / "work" / task_id / "metrics.md"


def _metrics_template(task_id: str) -> str:
    return """# 需求过程效率度量：{task_id}

> 本文件仅属于 `work/{task_id}/` 过程产物，不得加入任何目标项目的需求分支、commit、MR/PR 或正式变更文档。

## 统一口径

- 开始和结束时间统一显示为 UTC+8 的 ISO 8601 时间（`+08:00`），实际时刻和墙钟用时不变。
- 有效 Codex session id 优先从 `token_count.info.last_token_usage` 自动采集并去重；否则 OMP 从当前主 session 及其嵌套 agent 的 assistant `usage` / `model_usage` 按阶段窗口汇总。其他环境可显式传入精确值。`cached input` 是 input 的子集，`reasoning` 是 output 的子集，总量不得重复相加。取不到精确值时写 `NOT_AVAILABLE`，不得用 0 冒充。
- 返工次数只统计阶段重新进入：Gate B 打回、S4 FAIL 回 S3、Gate C 评审回流或实质偏离退回 S2；同一轮内的小修不计。
- 效率比 = 有效产出单元 /（有效产出单元 + 返工影响单元）；分母为 0 时写 `N/A`。单元定义按阶段产物中的验收项、改动项或验证项计数。
- 用时为本阶段 `metrics-start` 至本次阶段退出的墙钟时间，阻塞和取消也必须留记录。

## 阶段记录

""".format(task_id=task_id)


def _metric_marker_path(root: Path, task_id: str, stage: str) -> Path:
    return root / "work" / task_id / "scratch" / "metrics" / (stage + "-active.json")


def _unfinished_metric_stages(root: Path, task_id: str, current_stage: str) -> List[str]:
    directory = root / "work" / task_id / "scratch" / "metrics"
    if not directory.is_dir():
        return []
    return sorted(
        path.name[: -len("-active.json")]
        for path in directory.glob("*-active.json")
        if path.name != current_stage + "-active.json"
    )


def _merge_unique(*groups: Optional[List[str]]) -> List[str]:
    result = []
    for group in groups:
        for value in group or []:
            if value and value not in result:
                result.append(value)
    return result


def _start_stage_metrics(root: Path, task_id: str, stage: str, started_at: str) -> Dict[str, Any]:
    document = _metrics_path(root, task_id)
    if not document.is_file():
        _atomic_write_text(document, _metrics_template(task_id))
    marker = _metric_marker_path(root, task_id, stage)
    current_codex_sessions = current_codex_session_ids()
    current_omp_sessions = [] if current_codex_sessions else current_omp_session_files(
        command_hints=["metrics-start", task_id]
    )
    if marker.is_file():
        active = json.loads(_read_text(marker))
        normalized_started_at = _normalize_metric_timestamp(active["started_at"])
        marker_changed = normalized_started_at != active["started_at"]
        active["started_at"] = normalized_started_at
        tracked_codex_sessions = _merge_unique(active.get("codex_session_ids"), current_codex_sessions)
        tracked_omp_sessions = _merge_unique(active.get("omp_session_files"), current_omp_sessions)
        if tracked_codex_sessions != active.get("codex_session_ids", []):
            active["codex_session_ids"] = tracked_codex_sessions
            marker_changed = True
        if tracked_omp_sessions != active.get("omp_session_files", []):
            active["omp_session_files"] = tracked_omp_sessions
            marker_changed = True
        if marker_changed:
            _atomic_write_text(marker, json.dumps(active, ensure_ascii=False, indent=2) + "\n")
        return {
            "status": "ALREADY_RUNNING",
            "stage": stage,
            "attempt": active.get("attempt"),
            "codex_session_count": len(tracked_codex_sessions),
            "omp_session_count": len(tracked_omp_sessions),
        }
    attempts = len(re.findall(r"^## " + re.escape(stage) + r" · 尝试 \d+$", _read_text(document), re.MULTILINE))
    active = {
        "schema_version": 1,
        "stage": stage,
        "attempt": attempts + 1,
        "started_at": started_at,
        "codex_session_ids": current_codex_sessions,
        "omp_session_files": current_omp_sessions,
    }
    _atomic_write_text(marker, json.dumps(active, ensure_ascii=False, indent=2) + "\n")
    return {
        "status": "STARTED",
        "stage": stage,
        "attempt": active["attempt"],
        "started_at": started_at,
        "codex_session_count": len(current_codex_sessions),
        "omp_session_count": len(current_omp_sessions),
    }


def start_stage_metrics(
    task_id: str,
    root: Path,
    stage: Optional[str],
    started_at: Optional[str],
) -> Dict[str, Any]:
    valid, reason = validate_task_id(task_id)
    if not valid:
        raise ValueError(reason)
    state = state_for(task_id, root)
    current_stage = state.get("stage") or state.get("环节") or "S1"
    selected_stage = stage or current_stage
    if selected_stage not in STAGES:
        raise ValueError("unknown stage: " + str(selected_stage))
    unfinished = _unfinished_metric_stages(root, task_id, selected_stage)
    if unfinished:
        raise ValueError("previous stage metrics are unfinished: " + ", ".join(unfinished))
    metric_started_at = _normalize_metric_timestamp(started_at) if started_at else _metric_now()
    result = _start_stage_metrics(root, task_id, selected_stage, metric_started_at)
    result.update({"ok": True, "task_id": task_id})
    return result


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("metric timestamp must include timezone")
    return parsed


def _nonnegative(value: Optional[int], label: str) -> Optional[int]:
    if value is not None and value < 0:
        raise ValueError(label + " must be non-negative")
    return value


def _token_text(values: Dict[str, Optional[int]]) -> str:
    token_keys = ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_tokens", "total_tokens")
    if not any(values.get(key) is not None for key in token_keys):
        return "NOT_AVAILABLE"
    return (
        "input={input_tokens}, cached_input={cached_input_tokens}, output={output_tokens}, "
        "reasoning={reasoning_tokens}, total={total_tokens}"
    ).format(**{key: ("NOT_AVAILABLE" if values.get(key) is None else values[key]) for key in token_keys})


def _validate_token_values(values: Dict[str, Optional[int]], token_source: Optional[str]) -> None:
    token_keys = ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_tokens", "total_tokens")
    token_values = [values.get(key) for key in token_keys]
    if any(value is not None for value in token_values) and not token_source:
        raise ValueError("token_source is required when token values are recorded")
    if (
        values.get("cached_input_tokens") is not None
        and values.get("input_tokens") is not None
        and values["cached_input_tokens"] > values["input_tokens"]
    ):
        raise ValueError("cached_input_tokens cannot exceed input_tokens")
    if (
        values.get("reasoning_tokens") is not None
        and values.get("output_tokens") is not None
        and values["reasoning_tokens"] > values["output_tokens"]
    ):
        raise ValueError("reasoning_tokens cannot exceed output_tokens")
    if (
        values.get("total_tokens") is not None
        and values.get("input_tokens") is not None
        and values.get("output_tokens") is not None
        and values["total_tokens"] != values["input_tokens"] + values["output_tokens"]
    ):
        raise ValueError("total_tokens must equal input_tokens + output_tokens")
    if values.get("total_tokens") is None and values.get("input_tokens") is not None and values.get("output_tokens") is not None:
        values["total_tokens"] = values["input_tokens"] + values["output_tokens"]


def record_stage_metrics(
    task_id: str,
    root: Path,
    stage: Optional[str],
    outcome: str,
    input_tokens: Optional[int],
    cached_input_tokens: Optional[int],
    output_tokens: Optional[int],
    reasoning_tokens: Optional[int],
    total_tokens: Optional[int],
    token_source: Optional[str],
    rework_count: int,
    accepted_units: Optional[int],
    rework_units: Optional[int],
    note: Optional[str],
    auto_tokens: bool = True,
    codex_session_ids: Optional[List[str]] = None,
    codex_home: Optional[Path] = None,
    omp_session_files: Optional[List[str]] = None,
    omp_agent_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    valid, reason = validate_task_id(task_id)
    if not valid:
        raise ValueError(reason)
    current_stage = state_for(task_id, root).get("stage") or state_for(task_id, root).get("环节") or "S1"
    selected_stage = stage or current_stage
    if selected_stage not in STAGES:
        raise ValueError("unknown stage: " + str(selected_stage))
    if outcome not in METRIC_OUTCOMES:
        raise ValueError("outcome must be one of " + ", ".join(METRIC_OUTCOMES))
    values = {
        "input_tokens": _nonnegative(input_tokens, "input_tokens"),
        "cached_input_tokens": _nonnegative(cached_input_tokens, "cached_input_tokens"),
        "output_tokens": _nonnegative(output_tokens, "output_tokens"),
        "reasoning_tokens": _nonnegative(reasoning_tokens, "reasoning_tokens"),
        "total_tokens": _nonnegative(total_tokens, "total_tokens"),
        "accepted_units": _nonnegative(accepted_units, "accepted_units"),
        "rework_units": _nonnegative(rework_units, "rework_units"),
    }
    _nonnegative(rework_count, "rework_count")
    _validate_token_values(values, token_source)
    marker = _metric_marker_path(root, task_id, selected_stage)
    if not marker.is_file():
        raise ValueError("no active metrics marker for " + selected_stage + "; run metrics-start first")
    active = json.loads(_read_text(marker))
    if active.get("schema_version") != 1 or active.get("stage") != selected_stage:
        raise ValueError("invalid active metrics marker for " + selected_stage)
    ended_at = _metric_now()
    elapsed_seconds = max(0, int((_parse_utc(ended_at) - _parse_utc(active["started_at"])).total_seconds()))
    explicit_tokens = any(
        values[key] is not None
        for key in ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_tokens", "total_tokens")
    )
    token_collection = None
    if auto_tokens and not explicit_tokens:
        if omp_session_files is not None and not codex_session_ids:
            selected_codex_sessions = []
        else:
            selected_codex_sessions = _merge_unique(
                active.get("codex_session_ids"), codex_session_ids, current_codex_session_ids()
            )
        if omp_session_files is not None:
            selected_omp_sessions = _merge_unique(omp_session_files)
        else:
            current_omp_sessions = [] if selected_codex_sessions else current_omp_session_files(
                omp_agent_dir=omp_agent_dir,
                command_hints=["metrics-record", task_id],
            )
            selected_omp_sessions = _merge_unique(active.get("omp_session_files"), current_omp_sessions)
        token_collection = collect_runtime_usage(
            active["started_at"],
            ended_at,
            selected_codex_sessions,
            codex_home or default_codex_home(),
            selected_omp_sessions or None,
            omp_agent_dir,
        )
        if token_collection.get("available"):
            for key in ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_tokens", "total_tokens"):
                values[key] = token_collection[key]
            token_source = token_collection["source"]
        else:
            reason = str(token_collection.get("reason") or "unknown reason").replace("`", "'")
            token_source = "NOT_AVAILABLE: " + reason
    _validate_token_values(values, token_source)
    denominator = None
    efficiency = "N/A"
    if values["accepted_units"] is not None and values["rework_units"] is not None:
        denominator = values["accepted_units"] + values["rework_units"]
        if denominator:
            efficiency = "{:.2%}".format(values["accepted_units"] / denominator)
    token_text = _token_text(values)
    clean_note = (note or "无").replace("\r", " ").replace("\n", " ").strip() or "无"
    section = """## {stage} · 尝试 {attempt}

- 结果：`{outcome}`
- 开始：`{started_at}`
- 结束：`{ended_at}`
- 用时：`{elapsed_seconds}` 秒
- Token 来源：`{token_source}`
- Token：`{token_text}`
- 返工次数：`{rework_count}`
- 有效产出单元：`{accepted_units}`
- 返工影响单元：`{rework_units}`
- 效率比：`{efficiency}`
- 备注：{note}

""".format(
        stage=selected_stage,
        attempt=active["attempt"],
        outcome=outcome,
        started_at=active["started_at"],
        ended_at=ended_at,
        elapsed_seconds=elapsed_seconds,
        token_source=token_source or "NOT_AVAILABLE",
        token_text=token_text,
        rework_count=rework_count,
        accepted_units="N/A" if values["accepted_units"] is None else values["accepted_units"],
        rework_units="N/A" if values["rework_units"] is None else values["rework_units"],
        efficiency=efficiency,
        note=clean_note,
    )
    document = _metrics_path(root, task_id)
    content = _read_text(document) if document.is_file() else _metrics_template(task_id)
    _atomic_write_text(document, content.rstrip() + "\n\n" + section)
    marker.unlink()
    return {
        "ok": True,
        "task_id": task_id,
        "stage": selected_stage,
        "attempt": active["attempt"],
        "outcome": outcome,
        "elapsed_seconds": elapsed_seconds,
        "efficiency": efficiency,
        "token_source": token_source or "NOT_AVAILABLE",
        "tokens": {
            key: values[key]
            for key in ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_tokens", "total_tokens")
        },
        "metrics_path": str(document.relative_to(root)).replace("\\", "/"),
    }


def backfill_stage_metrics(
    task_id: str,
    root: Path,
    stages: Optional[List[str]],
    codex_session_ids: Optional[List[str]],
    codex_home: Optional[Path],
    dry_run: bool = False,
    force: bool = False,
    omp_session_files: Optional[List[str]] = None,
    omp_agent_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    valid, reason = validate_task_id(task_id)
    if not valid:
        raise ValueError(reason)
    selected_stages = stages or list(STAGES)
    unknown = [stage for stage in selected_stages if stage not in STAGES]
    if unknown:
        raise ValueError("unknown stage: " + ", ".join(unknown))
    document = _metrics_path(root, task_id)
    if not document.is_file():
        raise ValueError("metrics document does not exist: " + str(document))
    if omp_session_files is not None and not codex_session_ids:
        session_ids = []
    else:
        session_ids = _merge_unique(
            codex_session_ids if codex_session_ids else current_codex_session_ids()
        )
    if omp_session_files is not None:
        selected_omp_sessions = _merge_unique(omp_session_files)
    else:
        selected_omp_sessions = _merge_unique(
            [] if session_ids else current_omp_session_files(
                omp_agent_dir=omp_agent_dir,
                command_hints=["metrics-backfill", task_id],
            )
        )
    home = codex_home or default_codex_home()
    results = []  # type: List[Dict[str, Any]]
    changed = 0

    def replace_section(match: re.Match) -> str:
        nonlocal changed
        stage = match.group("stage")
        attempt = int(match.group("attempt"))
        section = match.group(0)
        if stage not in selected_stages:
            return section
        started = re.search(r"(?m)^- 开始：`([^`]+)`$", section)
        ended = re.search(r"(?m)^- 结束：`([^`]+)`$", section)
        token_line = re.search(r"(?m)^- Token：`([^`]+)`$", section)
        if not started or not ended or not token_line:
            results.append({"stage": stage, "attempt": attempt, "status": "SKIPPED", "reason": "incomplete metric section"})
            return section
        if token_line.group(1) != "NOT_AVAILABLE" and not force:
            results.append({"stage": stage, "attempt": attempt, "status": "UNCHANGED", "reason": "token values already exist"})
            return section
        collection = collect_runtime_usage(
            started.group(1),
            ended.group(1),
            session_ids,
            home,
            selected_omp_sessions or None,
            omp_agent_dir,
        )
        if not collection.get("available"):
            results.append(
                {
                    "stage": stage,
                    "attempt": attempt,
                    "status": "NOT_AVAILABLE",
                    "reason": collection.get("reason"),
                }
            )
            return section
        source = str(collection["source"]).replace("`", "'")
        values = {
            key: collection[key]
            for key in ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_tokens", "total_tokens")
        }
        updated = re.sub(r"(?m)^- Token 来源：`[^`]*`$", "- Token 来源：`{}`".format(source), section, count=1)
        updated = re.sub(r"(?m)^- Token：`[^`]*`$", "- Token：`{}`".format(_token_text(values)), updated, count=1)
        changed += 1
        results.append(
            {
                "stage": stage,
                "attempt": attempt,
                "status": "BACKFILLED" if not dry_run else "WOULD_BACKFILL",
                "event_count": collection["event_count"],
                "tokens": values,
            }
        )
        return updated

    content = _read_text(document)
    updated_content = METRIC_SECTION_RE.sub(replace_section, content)
    if changed and not dry_run:
        _atomic_write_text(document, updated_content)
    return {
        "ok": True,
        "task_id": task_id,
        "dry_run": dry_run,
        "changed": 0 if dry_run else changed,
        "would_change": changed,
        "results": results,
        "metrics_path": str(document.relative_to(root)).replace("\\", "/"),
    }


def _project_context_files(root: Path, state: Dict[str, Any], stage: str) -> List[str]:
    index_path = root / "config" / "projects" / "index.json"
    if not index_path.is_file():
        return ["config/projects.md"]
    relative_index = "config/projects/index.json"
    if stage == "S1":
        return [relative_index]
    index = json.loads(_read_text(index_path))
    entries = {item["name"]: item for item in index.get("projects", []) if isinstance(item, dict) and "name" in item}
    selected = []
    for project in state.get("projects", []):
        name = project.get("project") or project.get("项目")
        if name and name in entries:
            selected.append(entries[name]["detail"])
    return list(dict.fromkeys(selected)) or [relative_index]


def _extension_context_files(root: Path, project_files: List[str], stage: str) -> List[str]:
    if stage not in ("S3", "S4", "S5", "S6"):
        return []
    result = []
    for relative in project_files:
        if not relative.endswith(".json") or relative.endswith("index.json"):
            continue
        data = json.loads(_read_text(root / relative))
        for name in data.get("extensions", []):
            candidates = (
                "workflow/extensions/{}/SKILL.md".format(name),
                "workflow/extensions/{}.md".format(name),
            )
            match = next((candidate for candidate in candidates if (root / candidate).is_file()), None)
            if match:
                result.append(match)
            else:
                raise ValueError("configured extension not found: " + str(name))
    return list(dict.fromkeys(result))


def context(task_id: str, root: Path) -> Dict[str, Any]:
    valid, reason = validate_task_id(task_id)
    if not valid:
        raise ValueError(reason)
    state = state_for(task_id, root)
    stage = state.get("stage") or state.get("环节") or "S1"
    if stage not in STAGES:
        raise ValueError("state contains unknown stage: " + str(stage))
    definition = stage_definition(stage)
    required = [state["_path"]] if state.get("_path") else []
    required.append(definition["instruction"])
    required.extend(_artifact(root, task_id, item) for item in definition["inputs"])
    required.extend(definition.get("policies", []))
    project_files = []
    if stage in ("S1", "S2", "S3", "S4", "S5"):
        project_files = _project_context_files(root, state, stage)
        required.extend(project_files)
        required.extend(_extension_context_files(root, project_files, stage))
    required.extend(_enabled_stage_skills(root, stage))
    required = list(dict.fromkeys(item for item in required if item))
    references = list(definition.get("references", []))
    existing = []
    missing = []
    total_characters = 0
    guidance_characters = 0
    for item in required:
        path = root / item
        if path.is_file():
            existing.append(item)
            size = len(_read_text(path))
            total_characters += size
            if not item.startswith(("prds/", "work/")):
                guidance_characters += size
        else:
            missing.append(item)
    return {
        "task_id": task_id,
        "stage": stage,
        "stage_name": definition["name"],
        "state": state.get("状态") or state.get("status"),
        "required": existing,
        "missing": missing,
        "references_on_demand": references,
        "estimated_guidance_characters": guidance_characters,
        "estimated_total_file_characters": total_characters,
        "stage_budget_characters": MANIFEST["context_budgets"]["stage_instruction_characters"],
    }


def doctor(root: Path) -> Dict[str, Any]:
    errors = []
    warnings = []
    checked = []
    entry = root / "AGENTS.md"
    if not entry.is_file():
        errors.append("missing AGENTS.md")
    else:
        size = len(_read_text(entry))
        checked.append("AGENTS.md")
        budget = MANIFEST["context_budgets"]["entry_characters"]
        if size > budget:
            errors.append("AGENTS.md exceeds entry budget: {} > {}".format(size, budget))
    for stage, definition in MANIFEST["stages"].items():
        instruction = root / definition["instruction"]
        if not instruction.is_file():
            errors.append("missing stage instruction: " + definition["instruction"])
            continue
        checked.append(definition["instruction"])
        size = len(_read_text(instruction))
        policy_size = 0
        if size > MANIFEST["context_budgets"]["stage_instruction_characters"]:
            errors.append("{} exceeds stage budget".format(stage))
        for reference in definition.get("references", []):
            if not (root / reference).is_file():
                errors.append("missing reference: " + reference)
        for policy in definition.get("policies", []):
            if not (root / policy).is_file():
                errors.append("missing stage policy: " + policy)
            else:
                policy_size += len(_read_text(root / policy))
        if size + policy_size > MANIFEST["context_budgets"]["stage_instruction_characters"]:
            errors.append("{} instruction and required policies exceed stage budget".format(stage))
    skill_registry = root / "config" / "skills.md"
    if not skill_registry.is_file():
        errors.append("missing config/skills.md")
    else:
        checked.append("config/skills.md")
        for stage in STAGES:
            for skill in _enabled_stage_skills(root, stage):
                if not (root / skill).is_file():
                    errors.append("missing enabled skill: " + skill)
    metrics = MANIFEST.get("metrics")
    if not isinstance(metrics, dict) or metrics.get("document") != "work/<id>/metrics.md":
        errors.append("manifest metrics.document must be work/<id>/metrics.md")
    elif metrics.get("auto_collect_on_record") is not True:
        errors.append("manifest metrics.auto_collect_on_record must be true")
    elif metrics.get("display_timezone") != "UTC+08:00":
        errors.append("manifest metrics.display_timezone must be UTC+08:00")
    elif not isinstance(metrics.get("collector"), str) or not (root / metrics["collector"]).is_file():
        errors.append("manifest metrics.collector is missing")
    else:
        checked.append(metrics["collector"])
    project_index = root / "config" / "projects" / "index.json"
    if not project_index.is_file():
        warnings.append("structured project index not found; S1 falls back to config/projects.md")
    else:
        try:
            index = json.loads(_read_text(project_index))
            if index.get("schema_version") != 1 or not isinstance(index.get("projects"), list):
                errors.append("invalid structured project index")
            names = [project.get("name") for project in index.get("projects", []) if isinstance(project, dict)]
            if len(names) != len(set(names)):
                errors.append("structured project index contains duplicate names")
            for project in index.get("projects", []):
                detail = root / project["detail"]
                if not detail.is_file():
                    errors.append("missing project detail: " + project["detail"])
                else:
                    detail_data = json.loads(_read_text(detail))
                    policy = detail_data.get("approval_policy", {})
                    change_tracking = detail_data.get("change_tracking")
                    verification = detail_data.get("verification")
                    advisory_verification = detail_data.get("advisory_verification", [])
                    request_form_generation = detail_data.get("request_form_generation")
                    if not isinstance(verification, list) or not all(isinstance(command, str) and command.strip() for command in verification):
                        errors.append("{} verification must be a list of commands".format(project["name"]))
                    if not isinstance(advisory_verification, list) or not all(isinstance(command, str) and command.strip() for command in advisory_verification):
                        errors.append("{} advisory_verification must be a list of commands".format(project["name"]))
                    if request_form_generation is not None:
                        required_form_fields = ("define_path", "generated_path", "command", "overwrite_confirmation", "generated_files_policy")
                        if not isinstance(request_form_generation, dict) or request_form_generation.get("required") is not True:
                            errors.append("{} request_form_generation.required must be true".format(project["name"]))
                        elif any(not isinstance(request_form_generation.get(field), str) or not request_form_generation[field].strip() for field in required_form_fields):
                            errors.append("{} request_form_generation fields are incomplete".format(project["name"]))
                    if not isinstance(change_tracking, dict) or change_tracking.get("required") is not True:
                        errors.append("{} change_tracking.required must be true".format(project["name"]))
                    elif not isinstance(change_tracking.get("document_path"), str) or not change_tracking["document_path"].strip():
                        errors.append("{} change_tracking.document_path is required".format(project["name"]))
                    elif "central_changelog" in change_tracking and change_tracking["central_changelog"] is not None and not isinstance(change_tracking["central_changelog"], str):
                        errors.append("{} change_tracking.central_changelog must be a string or null".format(project["name"]))
                    if any(risk not in policy for risk in MANIFEST["risk_levels"]):
                        errors.append("{} approval policy must define R0-R3".format(project["name"]))
                    for risk in ("R2", "R3"):
                        if policy.get(risk) == "auto":
                            errors.append("{} approval policy cannot auto-approve {}".format(project["name"], risk))
                    checked.append(project["detail"])
            checked.append("config/projects/index.json")
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            errors.append("invalid structured project configuration: " + str(exc))
    result = {"ok": not errors, "errors": errors, "warnings": warnings, "checked": checked}
    return result


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", default=str(ROOT))
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate-id")
    validate.add_argument("task_id")
    show = sub.add_parser("context")
    show.add_argument("task_id")
    metric_start = sub.add_parser("metrics-start")
    metric_start.add_argument("task_id")
    metric_start.add_argument("--stage", choices=STAGES)
    metric_start.add_argument("--started-at", help="阶段开始时记录的带时区 ISO 时间")
    metric = sub.add_parser("metrics-record")
    metric.add_argument("task_id")
    metric.add_argument("--stage", choices=STAGES)
    metric.add_argument("--outcome", required=True, choices=METRIC_OUTCOMES)
    metric.add_argument("--input-tokens", type=int)
    metric.add_argument("--cached-input-tokens", type=int)
    metric.add_argument("--output-tokens", type=int)
    metric.add_argument("--reasoning-tokens", type=int)
    metric.add_argument("--total-tokens", type=int)
    metric.add_argument("--token-source")
    metric.add_argument("--codex-session-id", action="append", help="覆盖或补充自动采集的 Codex session UUID")
    metric.add_argument("--codex-home", help="Codex 数据目录，默认使用 CODEX_HOME 或当前用户 .codex")
    metric.add_argument("--omp-session-file", action="append", help="显式指定 OMP 主 session JSONL，可重复")
    metric.add_argument("--omp-agent-dir", help="OMP agent 数据目录，默认使用 PI_CODING_AGENT_DIR 或当前用户 .omp/agent")
    metric.add_argument("--no-auto-tokens", action="store_true", help="禁用本次 session Token 自动采集")
    metric.add_argument("--rework-count", type=int, default=0)
    metric.add_argument("--accepted-units", type=int)
    metric.add_argument("--rework-units", type=int)
    metric.add_argument("--note")
    backfill = sub.add_parser("metrics-backfill")
    backfill.add_argument("task_id")
    backfill.add_argument("--stage", action="append", choices=STAGES, help="只回填指定阶段，可重复")
    backfill.add_argument("--codex-session-id", action="append", help="提供历史阶段对应的 Codex session UUID，可重复")
    backfill.add_argument("--codex-home", help="Codex 数据目录，默认使用 CODEX_HOME 或当前用户 .codex")
    backfill.add_argument("--omp-session-file", action="append", help="提供历史阶段对应的 OMP 主 session JSONL，可重复")
    backfill.add_argument("--omp-agent-dir", help="OMP agent 数据目录，默认使用 PI_CODING_AGENT_DIR 或当前用户 .omp/agent")
    backfill.add_argument("--dry-run", action="store_true")
    backfill.add_argument("--force", action="store_true", help="覆盖已有精确 Token 值")
    transition = sub.add_parser("can-transition")
    transition.add_argument("current", choices=STAGES)
    transition.add_argument("target", choices=STAGES)
    sub.add_parser("doctor")
    args = parser.parse_args(argv)
    root = Path(args.workspace).resolve()
    try:
        if args.command == "validate-id":
            valid, reason = validate_task_id(args.task_id)
            payload = {"ok": valid, "task_id": args.task_id, "error": reason or None}
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0 if valid else 2
        if args.command == "context":
            payload = context(args.task_id, root)
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0
        if args.command == "metrics-start":
            result = start_stage_metrics(args.task_id, root, args.stage, args.started_at)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command == "metrics-record":
            result = record_stage_metrics(
                args.task_id,
                root,
                args.stage,
                args.outcome,
                args.input_tokens,
                args.cached_input_tokens,
                args.output_tokens,
                args.reasoning_tokens,
                args.total_tokens,
                args.token_source,
                args.rework_count,
                args.accepted_units,
                args.rework_units,
                args.note,
                not args.no_auto_tokens,
                args.codex_session_id,
                Path(args.codex_home).resolve() if args.codex_home else None,
                args.omp_session_file,
                Path(args.omp_agent_dir).resolve() if args.omp_agent_dir else None,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command == "metrics-backfill":
            result = backfill_stage_metrics(
                args.task_id,
                root,
                args.stage,
                args.codex_session_id,
                Path(args.codex_home).resolve() if args.codex_home else None,
                dry_run=args.dry_run,
                force=args.force,
                omp_session_files=args.omp_session_file,
                omp_agent_dir=Path(args.omp_agent_dir).resolve() if args.omp_agent_dir else None,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command == "can-transition":
            allowed = can_transition(args.current, args.target)
            print(json.dumps({"ok": allowed, "current": args.current, "target": args.target}, ensure_ascii=False, indent=2))
            return 0 if allowed else 3
        result = doctor(root)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ok"] else 1
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
