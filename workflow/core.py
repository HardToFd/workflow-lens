#!/usr/bin/env python3
"""Shared, dependency-free workflow definitions used by agents, CLI, and GUI."""

import json
import re
from pathlib import Path
from typing import Any, Dict, Tuple


WORKFLOW_ROOT = Path(__file__).resolve().parent
MANIFEST_PATH = WORKFLOW_ROOT / "manifest.json"


def load_manifest(path: Path = MANIFEST_PATH) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    if manifest.get("schema_version") != 1:
        raise ValueError("unsupported workflow manifest schema")
    stages = manifest.get("stages")
    if not isinstance(stages, dict) or not stages:
        raise ValueError("workflow manifest has no stages")
    return manifest


MANIFEST = load_manifest()
STAGES = tuple(MANIFEST["stages"])
GATES = tuple(MANIFEST["gates"])
RISK_LEVELS = tuple(MANIFEST["risk_levels"])
ID_RE = re.compile(MANIFEST["task_id"]["pattern"])
RESERVED_STEMS = frozenset(item.upper() for item in MANIFEST["task_id"]["windows_reserved_stems"])


def validate_task_id(value: Any) -> Tuple[bool, str]:
    if not isinstance(value, str):
        return False, "需求 id 必须是字符串"
    stem = value.split(".", 1)[0].upper()
    config = MANIFEST["task_id"]
    invalid = (
        not ID_RE.fullmatch(value)
        or (config.get("forbid_double_dot") and ".." in value)
        or "/" in value
        or "\\" in value
        or value != value.strip()
        or any(ch.isspace() for ch in value)
        or any(value.endswith(item) for item in config.get("forbid_trailing", []))
        or any(value.lower().endswith(item.lower()) for item in config.get("forbid_suffix_case_insensitive", []))
        or stem in RESERVED_STEMS
    )
    if invalid:
        return False, "需求 id 不符合 workflow/manifest.json"
    return True, ""


def stage_definition(stage: str) -> Dict[str, Any]:
    try:
        return MANIFEST["stages"][stage]
    except KeyError:
        raise ValueError("unknown stage: " + stage)


def can_transition(current: str, target: str) -> bool:
    if current == target:
        return True
    return target in stage_definition(current)["allowed_next"]
