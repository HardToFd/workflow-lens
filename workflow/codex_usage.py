"""Collect exact token deltas from local Codex session token_count events."""

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


SESSION_ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)
USAGE_KEYS = (
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
    "total_tokens",
)


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Codex token timestamp must include timezone")
    return parsed


def _normalized_session_ids(values: Iterable[str]) -> List[str]:
    result = []
    for value in values:
        candidate = (value or "").strip().lower()
        if candidate and SESSION_ID_RE.fullmatch(candidate) and candidate not in result:
            result.append(candidate)
    return result


def current_codex_session_ids(environ: Optional[Mapping[str, str]] = None) -> List[str]:
    source = environ if environ is not None else os.environ
    return _normalized_session_ids(
        source.get(name, "") for name in ("CODEX_SESSION_ID", "CODEX_THREAD_ID")
    )


def default_codex_home(environ: Optional[Mapping[str, str]] = None) -> Path:
    source = environ if environ is not None else os.environ
    configured = (source.get("CODEX_HOME") or "").strip()
    return Path(configured).expanduser() if configured else Path.home() / ".codex"


def _usage_fingerprint(usage: Any) -> Optional[Tuple[int, ...]]:
    if not isinstance(usage, dict):
        return None
    return tuple(int(usage.get(key, 0) or 0) for key in USAGE_KEYS)


def _session_logs(codex_home: Path, session_ids: Sequence[str]) -> List[Path]:
    matches = set()
    for root_name in ("sessions", "archived_sessions"):
        root = codex_home / root_name
        if not root.is_dir():
            continue
        for session_id in session_ids:
            for path in root.rglob("*{}*.jsonl".format(session_id)):
                if path.is_file():
                    matches.add(path.resolve())
    return sorted(matches, key=lambda path: str(path).lower())


def _events(paths: Sequence[Path], session_ids: Sequence[str]) -> List[Dict[str, Any]]:
    result = []
    for path in paths:
        lowered_name = path.name.lower()
        session_id = next((value for value in session_ids if value in lowered_name), None)
        if session_id is None:
            continue
        try:
            handle = path.open("r", encoding="utf-8", errors="replace")
        except OSError:
            continue
        with handle:
            for line_number, line in enumerate(handle, 1):
                if '"token_count"' not in line:
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                payload = item.get("payload") or {}
                if payload.get("type") != "token_count":
                    continue
                info = payload.get("info") or {}
                usage = info.get("last_token_usage")
                timestamp = item.get("timestamp")
                usage_fingerprint = _usage_fingerprint(usage)
                if not timestamp or usage_fingerprint is None:
                    continue
                try:
                    parsed_timestamp = _parse_timestamp(timestamp)
                except (TypeError, ValueError):
                    continue
                result.append(
                    {
                        "session_id": session_id,
                        "timestamp": parsed_timestamp,
                        "usage": usage_fingerprint,
                        "total_usage": _usage_fingerprint(info.get("total_token_usage")),
                        "path": str(path),
                        "line": line_number,
                    }
                )
    return result


def collect_codex_usage(
    started_at: str,
    ended_at: str,
    session_ids: Optional[Sequence[str]] = None,
    codex_home: Optional[Path] = None,
    environ: Optional[Mapping[str, str]] = None,
) -> Dict[str, Any]:
    start = _parse_timestamp(started_at)
    end = _parse_timestamp(ended_at)
    if end < start:
        raise ValueError("Codex token collection end precedes start")
    selected_sessions = _normalized_session_ids(
        session_ids if session_ids is not None else current_codex_session_ids(environ)
    )
    if not selected_sessions:
        return {"available": False, "reason": "Codex session id is unavailable"}
    home = (codex_home or default_codex_home(environ)).expanduser().resolve()
    paths = _session_logs(home, selected_sessions)
    if not paths:
        return {"available": False, "reason": "matching Codex session log was not found"}

    events = sorted(
        _events(paths, selected_sessions),
        key=lambda item: (item["timestamp"], item["session_id"], item["path"], item["line"]),
    )
    seen = set()
    last_total_by_session = {}  # type: Dict[str, Tuple[int, ...]]
    deduplicated = []
    for event in events:
        signature = (event["session_id"], event["timestamp"], event["usage"], event["total_usage"])
        if signature in seen:
            continue
        seen.add(signature)
        total_usage = event["total_usage"]
        if total_usage is not None:
            if last_total_by_session.get(event["session_id"]) == total_usage:
                continue
            last_total_by_session[event["session_id"]] = total_usage
        deduplicated.append(event)

    selected = [event for event in deduplicated if start <= event["timestamp"] <= end]
    if not selected:
        return {"available": False, "reason": "no Codex token_count event exists in the stage window"}

    sums = [sum(event["usage"][index] for event in selected) for index in range(len(USAGE_KEYS))]
    values = dict(zip(USAGE_KEYS, sums))
    if values["total_tokens"] != values["input_tokens"] + values["output_tokens"]:
        return {"available": False, "reason": "Codex token totals are internally inconsistent"}
    if values["cached_input_tokens"] > values["input_tokens"]:
        return {"available": False, "reason": "Codex cached input exceeds input"}
    if values["reasoning_output_tokens"] > values["output_tokens"]:
        return {"available": False, "reason": "Codex reasoning output exceeds output"}

    used_sessions = {event["session_id"] for event in selected}
    return {
        "available": True,
        "input_tokens": values["input_tokens"],
        "cached_input_tokens": values["cached_input_tokens"],
        "output_tokens": values["output_tokens"],
        "reasoning_tokens": values["reasoning_output_tokens"],
        "total_tokens": values["total_tokens"],
        "event_count": len(selected),
        "session_count": len(used_sessions),
        "source": "Codex token_count last_token_usage ({} session(s), {} event(s))".format(
            len(used_sessions), len(selected)
        ),
        "started_at": started_at,
        "ended_at": ended_at,
    }
