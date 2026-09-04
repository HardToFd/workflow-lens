"""Collect exact stage token usage from local Codex or OMP session logs."""

import json
import os
import re
import tempfile
import time
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
OMP_ACTIVITY_MAX_AGE_SECONDS = 120


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("token timestamp must include timezone")
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


def default_omp_agent_dir(environ: Optional[Mapping[str, str]] = None) -> Path:
    source = environ if environ is not None else os.environ
    configured = (source.get("PI_CODING_AGENT_DIR") or "").strip()
    return Path(configured).expanduser() if configured else Path.home() / ".omp" / "agent"


def _usage_fingerprint(usage: Any) -> Optional[Tuple[int, ...]]:
    if not isinstance(usage, dict):
        return None
    try:
        values = tuple(int(usage.get(key, 0) or 0) for key in USAGE_KEYS)
    except (TypeError, ValueError):
        return None
    return values if all(value >= 0 for value in values) else None


def _codex_session_logs(codex_home: Path, session_ids: Sequence[str]) -> List[Path]:
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


def _codex_events(paths: Sequence[Path], session_ids: Sequence[str]) -> List[Dict[str, Any]]:
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
    paths = _codex_session_logs(home, selected_sessions)
    if not paths:
        return {"available": False, "reason": "matching Codex session log was not found"}

    events = sorted(
        _codex_events(paths, selected_sessions),
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
        "runtime": "codex",
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


def _truthy(value: Optional[str]) -> bool:
    return (value or "").strip().lower() not in ("", "0", "false", "no", "off")


def _same_path(left: Any, right: Any) -> bool:
    try:
        return os.path.normcase(str(Path(left).expanduser().resolve())) == os.path.normcase(
            str(Path(right).expanduser().resolve())
        )
    except (OSError, TypeError, ValueError):
        return False


def _relative_to(path: Path, parent: Path) -> Optional[Path]:
    try:
        return path.relative_to(parent)
    except ValueError:
        return None


def _encoded_omp_session_dir(cwd: Path, sessions_root: Path) -> Path:
    resolved = cwd.expanduser().resolve()
    home = Path.home().resolve()
    temp_root = Path(tempfile.gettempdir()).resolve()
    home_relative = _relative_to(resolved, home)
    temp_relative = _relative_to(resolved, temp_root)
    if home_relative is not None:
        encoded = str(home_relative).replace("/", "-").replace("\\", "-").replace(":", "-")
        name = "-" + encoded if encoded else "-"
    elif temp_relative is not None:
        encoded = str(temp_relative).replace("/", "-").replace("\\", "-").replace(":", "-")
        name = "-tmp-" + encoded if encoded else "-tmp"
    else:
        encoded = str(resolved).lstrip("/\\").replace("/", "-").replace("\\", "-").replace(":", "-")
        name = "--" + encoded + "--"
    return sessions_root / name


def _omp_session_header(path: Path) -> Optional[Dict[str, Any]]:
    try:
        handle = path.open("r", encoding="utf-8", errors="replace")
    except OSError:
        return None
    with handle:
        for _, line in zip(range(8), handle):
            if '"type":"session"' not in line and '"type": "session"' not in line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                return None
            return item if item.get("type") == "session" else None
    return None


def _omp_tool_invocations(path: Path) -> List[Tuple[float, str]]:
    try:
        with path.open("rb") as handle:
            size = handle.seek(0, os.SEEK_END)
            offset = max(0, size - 65536)
            handle.seek(offset)
            payload = handle.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    lines = payload.splitlines()
    if offset and lines:
        lines = lines[1:]
    result = []
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (
            not isinstance(entry, dict)
            or entry.get("type") != "custom"
            or entry.get("customType") != "tool_execution_start"
        ):
            continue
        data = entry.get("data") or {}
        if data.get("toolName") not in ("bash", "eval"):
            continue
        timestamp = data.get("startedAt") or entry.get("timestamp")
        args = data.get("args") or {}
        command = args.get("command") if isinstance(args, dict) else ""
        try:
            result.append(
                (_parse_timestamp(timestamp).timestamp(), command if isinstance(command, str) else "")
            )
        except (AttributeError, TypeError, ValueError):
            continue
    return result


def discover_omp_session_files(
    environ: Optional[Mapping[str, str]] = None,
    cwd: Optional[Path] = None,
    omp_agent_dir: Optional[Path] = None,
    now: Optional[float] = None,
    command_hints: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    source = environ if environ is not None else os.environ
    configured = (source.get("PI_SESSION_FILE") or "").strip()
    if configured:
        path = Path(configured).expanduser().resolve()
        if path.is_file() and path.suffix.lower() == ".jsonl":
            return {"available": True, "files": [str(path)], "source": "PI_SESSION_FILE"}
        return {"available": False, "files": [], "reason": "PI_SESSION_FILE does not name an OMP JSONL file"}
    if not _truthy(source.get("OMPCODE")):
        return {"available": False, "files": [], "reason": "OMP runtime marker is unavailable"}

    active_cwd = (cwd or Path.cwd()).expanduser().resolve()
    sessions_root = (omp_agent_dir or default_omp_agent_dir(source)).expanduser().resolve() / "sessions"
    if not sessions_root.is_dir():
        return {"available": False, "files": [], "reason": "OMP sessions directory was not found"}
    expected = _encoded_omp_session_dir(active_cwd, sessions_root)
    if expected.is_dir():
        directories = [expected]
    else:
        try:
            directories = [path for path in sessions_root.iterdir() if path.is_dir()]
        except OSError:
            return {"available": False, "files": [], "reason": "OMP sessions directory could not be listed"}
    candidates = []
    for directory in directories:
        try:
            direct_logs = list(directory.glob("*.jsonl"))
        except OSError:
            continue
        for path in direct_logs:
            try:
                modified = path.stat().st_mtime
            except OSError:
                continue
            candidates.append((modified, path))
    current_time = time.time() if now is None else now
    matching = []
    for modified, path in sorted(candidates, key=lambda item: item[0], reverse=True):
        age = current_time - modified
        if age > OMP_ACTIVITY_MAX_AGE_SECONDS:
            break
        header = _omp_session_header(path)
        if header and _same_path(header.get("cwd"), active_cwd):
            matching.append((modified, path))
    invocation_matches = []
    for modified, path in matching:
        for invoked_at, command in _omp_tool_invocations(path):
            if 0 <= current_time - invoked_at <= 30:
                invocation_matches.append((invoked_at, path, command))
    normalized_hints = [str(hint) for hint in command_hints or () if str(hint)]
    if normalized_hints:
        hinted_matches = [
            item for item in invocation_matches if all(hint in item[2] for hint in normalized_hints)
        ]
        if hinted_matches:
            path = max(hinted_matches, key=lambda item: item[0])[1]
            return {"available": True, "files": [str(path.resolve())], "source": "OMP current command session"}
    invocation_paths = {os.path.normcase(str(item[1].resolve())): item[1] for item in invocation_matches}
    if len(invocation_paths) == 1:
        path = next(iter(invocation_paths.values()))
        return {"available": True, "files": [str(path.resolve())], "source": "OMP current tool session"}
    if len(invocation_paths) > 1:
        return {"available": False, "files": [], "reason": "multiple recent OMP tool sessions are ambiguous"}
    if len(matching) == 1:
        path = matching[0][1]
        return {"available": True, "files": [str(path.resolve())], "source": "OMP recent cwd session"}
    if len(matching) > 1:
        return {"available": False, "files": [], "reason": "multiple recently active OMP cwd sessions are ambiguous"}
    return {"available": False, "files": [], "reason": "no recently active OMP session matches the current cwd"}


def current_omp_session_files(
    environ: Optional[Mapping[str, str]] = None,
    cwd: Optional[Path] = None,
    omp_agent_dir: Optional[Path] = None,
    command_hints: Optional[Sequence[str]] = None,
) -> List[str]:
    return list(
        discover_omp_session_files(
            environ=environ,
            cwd=cwd,
            omp_agent_dir=omp_agent_dir,
            command_hints=command_hints,
        ).get("files")
        or []
    )


def _normalized_omp_session_files(values: Iterable[Any]) -> List[Path]:
    result = []
    seen = set()
    for value in values:
        if not value:
            continue
        path = Path(value).expanduser().resolve()
        key = os.path.normcase(str(path))
        if key in seen or not path.is_file() or path.suffix.lower() != ".jsonl":
            continue
        seen.add(key)
        result.append(path)
    return result


def _associated_omp_logs(main_session_files: Sequence[Path]) -> List[Path]:
    result = []
    seen = set()
    for main_path in main_session_files:
        paths = [main_path]
        artifacts = main_path.with_suffix("")
        if artifacts.is_dir():
            try:
                paths.extend(path for path in artifacts.rglob("*.jsonl") if path.is_file())
            except OSError:
                pass
        for path in paths:
            resolved = path.resolve()
            key = os.path.normcase(str(resolved))
            if key not in seen:
                seen.add(key)
                result.append(resolved)
    return sorted(result, key=lambda path: str(path).lower())


def _omp_usage_fingerprint(usage: Any) -> Optional[Tuple[int, ...]]:
    if not isinstance(usage, dict):
        return None
    raw_keys = ("input", "output", "cacheRead", "cacheWrite", "totalTokens", "reasoningTokens")
    raw = []
    for key in raw_keys:
        value = usage.get(key, 0)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return None
        raw.append(value)
    input_tokens, output_tokens, cache_read, cache_write, total_tokens, reasoning_tokens = raw
    inclusive_input = input_tokens + cache_read + cache_write
    if total_tokens != inclusive_input + output_tokens or reasoning_tokens > output_tokens:
        return None
    return inclusive_input, cache_read, output_tokens, reasoning_tokens, total_tokens


def _omp_events(paths: Sequence[Path]) -> Tuple[List[Dict[str, Any]], int]:
    result = []
    invalid_count = 0
    for path in paths:
        try:
            handle = path.open("r", encoding="utf-8", errors="replace")
        except OSError:
            continue
        with handle:
            for line_number, line in enumerate(handle, 1):
                if '"usage"' not in line:
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    invalid_count += 1
                    continue
                usage = None
                if item.get("type") == "model_usage":
                    usage = item.get("usage")
                elif item.get("type") == "message":
                    message = item.get("message") or {}
                    if message.get("role") == "assistant":
                        usage = message.get("usage")
                if usage is None:
                    continue
                fingerprint = _omp_usage_fingerprint(usage)
                timestamp = item.get("timestamp")
                if fingerprint is None or not timestamp:
                    invalid_count += 1
                    continue
                try:
                    parsed_timestamp = _parse_timestamp(timestamp)
                except (TypeError, ValueError):
                    invalid_count += 1
                    continue
                if fingerprint[-1] <= 0:
                    continue
                result.append(
                    {
                        "entry_id": str(item.get("id") or "{}:{}".format(path, line_number)),
                        "timestamp": parsed_timestamp,
                        "usage": fingerprint,
                        "path": str(path),
                        "line": line_number,
                    }
                )
    return result, invalid_count


def collect_omp_usage(
    started_at: str,
    ended_at: str,
    session_files: Sequence[Any],
) -> Dict[str, Any]:
    start = _parse_timestamp(started_at)
    end = _parse_timestamp(ended_at)
    if end < start:
        raise ValueError("OMP token collection end precedes start")
    main_paths = _normalized_omp_session_files(session_files)
    if not main_paths:
        return {"available": False, "reason": "matching OMP main session log was not found"}
    transcript_paths = _associated_omp_logs(main_paths)
    events, invalid_count = _omp_events(transcript_paths)
    selected = []
    seen = set()
    for event in sorted(events, key=lambda item: (item["timestamp"], item["path"], item["line"])):
        signature = (os.path.normcase(event["path"]), event["entry_id"])
        if signature in seen:
            continue
        seen.add(signature)
        if start <= event["timestamp"] <= end:
            selected.append(event)
    if not selected:
        reason = "no valid OMP usage event exists in the stage window"
        if invalid_count:
            reason += " ({} invalid record(s) skipped)".format(invalid_count)
        return {"available": False, "reason": reason}

    sums = [sum(event["usage"][index] for event in selected) for index in range(len(USAGE_KEYS))]
    values = dict(zip(USAGE_KEYS, sums))
    if values["total_tokens"] != values["input_tokens"] + values["output_tokens"]:
        return {"available": False, "reason": "OMP token totals are internally inconsistent"}
    used_transcripts = {event["path"] for event in selected}
    return {
        "available": True,
        "runtime": "omp",
        "input_tokens": values["input_tokens"],
        "cached_input_tokens": values["cached_input_tokens"],
        "output_tokens": values["output_tokens"],
        "reasoning_tokens": values["reasoning_output_tokens"],
        "total_tokens": values["total_tokens"],
        "event_count": len(selected),
        "session_count": len(main_paths),
        "transcript_count": len(used_transcripts),
        "source": "OMP session usage ({} main session(s), {} transcript(s), {} event(s))".format(
            len(main_paths), len(used_transcripts), len(selected)
        ),
        "started_at": started_at,
        "ended_at": ended_at,
    }


def collect_runtime_usage(
    started_at: str,
    ended_at: str,
    codex_session_ids: Optional[Sequence[str]] = None,
    codex_home: Optional[Path] = None,
    omp_session_files: Optional[Sequence[Any]] = None,
    omp_agent_dir: Optional[Path] = None,
    environ: Optional[Mapping[str, str]] = None,
    cwd: Optional[Path] = None,
    command_hints: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    selected_codex_sessions = _normalized_session_ids(
        codex_session_ids if codex_session_ids is not None else current_codex_session_ids(environ)
    )
    if selected_codex_sessions:
        return collect_codex_usage(
            started_at,
            ended_at,
            selected_codex_sessions,
            codex_home or default_codex_home(environ),
            environ,
        )

    if omp_session_files is None:
        discovery = discover_omp_session_files(environ, cwd, omp_agent_dir, command_hints=command_hints)
        if not discovery.get("available"):
            return {
                "available": False,
                "reason": "Codex session id is unavailable; " + str(discovery.get("reason") or "OMP session is unavailable"),
            }
        selected_omp_sessions = discovery["files"]
    else:
        selected_omp_sessions = list(omp_session_files)
    return collect_omp_usage(started_at, ended_at, selected_omp_sessions)
