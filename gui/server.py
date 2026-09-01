#!/usr/bin/env python3
"""Local, dependency-free GUI for the Markdown workflow."""

import argparse
import fnmatch
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import threading
from collections import deque
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import unquote, urlparse

WORKSPACE_PACKAGE_ROOT = Path(__file__).resolve().parent.parent
if str(WORKSPACE_PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_PACKAGE_ROOT))

from workflow.core import GATES, STAGES, validate_task_id

TOP_FIELDS = {
    "环节": "phase",
    "状态": "status",
    "闸口A": "gate_a",
    "闸口B": "gate_b",
    "NOT_RUN 确认": "not_run_confirmation",
}
PROJECT_FIELDS = {
    "项目": "project",
    "工作目录": "workspace",
    "分支": "branch",
    "联测分支": "test_branch",
    "联测状态": "test_status",
    "阶段": "phase",
    "回修轮次": "repair_round",
    "MR/PR": "merge_request",
    "闸口C": "gate_c",
    "行状态": "row_status",
}
ARTIFACTS = [
    ("prd", "PRD"),
    ("state.md", "状态"),
    ("metrics.md", "效率度量"),
    ("analysis.md", "分析"),
    ("questions.md", "闸口 A"),
    ("plan.md", "方案"),
    ("impact-map-review.md", "影响面图审查"),
    ("impl-log.md", "实现记录"),
    ("verify.md", "验证"),
    ("delivery.md", "交付"),
]
ARTIFACT_NAMES = {name for name, _ in ARTIFACTS}
MAX_BODY = 512 * 1024
MAX_FILE = 2 * 1024 * 1024
MAX_SKILL_FILE = 128 * 1024
MAX_AGENT_CONFIG = 512 * 1024
MAX_SKILL_DEPTH = 4
MAX_SKILLS_PER_ROOT = 200
MAX_SKILL_CATALOG = 1000
MAX_SKILL_ENTRIES_PER_ROOT = 5000
MAX_PROJECTS = 100
SKILL_STATES = ("启用", "停用")
SKILL_SOURCE_STATES = ("已确认启用", "已发现未确认", "失效", "无效")
SKILL_SOURCE_TYPES = {
    "external": "外部 Agent Skill",
    "native": "工作区原生技能",
    "imported": "工作区外部适配器",
    "diagnostic": "扫描诊断",
}
CAPABILITY_MODES = ("自动检测", "档位1", "档位2", "档位3")
SKIP_SKILL_DIRS = frozenset((".git", ".tmp", "__pycache__", "cache", "node_modules", "staging", "tmp"))


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def validate_id(value: Any) -> str:
    valid, reason = validate_task_id(value)
    if not valid:
        raise ApiError(400, reason)
    return value


def split_table_row(line: str) -> List[str]:
    stripped = line.strip()
    if not (stripped.startswith("|") and stripped.endswith("|")):
        return []
    return [cell.strip() for cell in stripped[1:-1].split("|")]


def replace_bullet(content: str, label: str, value: str) -> str:
    pattern = re.compile(r"^- " + re.escape(label) + r":.*$", re.MULTILINE)
    matches = list(pattern.finditer(content))
    if len(matches) != 1:
        raise ApiError(409, "state.md 缺少唯一字段: " + label)
    return pattern.sub(
        lambda _match: "- {}: {}".format(label, value),
        content,
        count=1,
    )


def first_heading(content: str, fallback: str) -> str:
    for line in content.splitlines():
        if line.startswith("# "):
            return line[2:].strip() or fallback
    return fallback


def bundled_file(name: str) -> Path:
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return bundle_root / name


def find_workspace(start: Path) -> Optional[Path]:
    start = start.expanduser().resolve()
    for candidate in (start,) + tuple(start.parents):
        if (candidate / "AGENTS.md").is_file() and (candidate / "prds").is_dir():
            return candidate
    return None


def default_workspace() -> Path:
    if getattr(sys, "frozen", False):
        executable_dir = Path(sys.executable).resolve().parent
        workspace = find_workspace(executable_dir)
        if workspace and workspace.parent.name.endswith("-worktrees"):
            main = workspace.parent.parent / workspace.parent.name[: -len("-worktrees")]
            if (main / "AGENTS.md").is_file() and (main / "prds").is_dir():
                return main.resolve()
        return workspace or executable_dir
    return Path(__file__).resolve().parents[1]


def console(message: str, error: bool = False) -> None:
    stream = sys.stderr if error else sys.stdout
    if stream is not None:
        print(message, file=stream, flush=True)


class WorkflowWorkspace:
    def __init__(self, root: Path):
        self.root = root.expanduser().resolve()
        self.prds = self.root / "prds"
        self.work = self.root / "work"
        self.config = self.root / "config"
        self.skills = self.root / "skills"
        self.home = Path.home().resolve()

        def environment_path(value: Optional[str], fallback: Optional[Path]) -> Optional[Path]:
            if not value:
                return fallback
            try:
                if len(value) > 4096 or any(ord(char) < 32 for char in value):
                    return fallback
                configured = Path(value).expanduser()
                if not configured.is_absolute():
                    return fallback
                return Path(os.path.abspath(str(configured)))
            except (OSError, ValueError):
                return fallback

        self.copilot_home = environment_path(os.environ.get("COPILOT_HOME"), self.home / ".copilot")
        self.gemini_home = environment_path(os.environ.get("GEMINI_CLI_HOME"), self.home)
        self.copilot_extra_roots = []
        for value in (
            item.strip()
            for item in os.environ.get("COPILOT_SKILLS_DIRS", "").split(",")
            if item.strip()
        ):
            path = environment_path(value, None)
            if path is not None:
                self.copilot_extra_roots.append(path)
            if len(self.copilot_extra_roots) >= 10:
                break
        self.program_data = environment_path(os.environ.get("PROGRAMDATA"), None)
        if not (self.root / "AGENTS.md").is_file():
            raise ApiError(400, "工作区缺少 AGENTS.md")
        if not self.prds.is_dir():
            raise ApiError(400, "工作区缺少 prds/目录")
        self.work.mkdir(exist_ok=True)
        for label, path in (
            ("prds", self.prds),
            ("work", self.work),
            ("config", self.config),
            ("skills", self.skills),
        ):
            if path.exists() or self._is_link(path):
                if self._is_link(path) or not path.is_dir() or not self._inside(self.root, path.resolve()):
                    raise ApiError(400, "工作区受控目录不安全: " + label)
        self._write_lock = threading.Lock()
        self._log_lock = threading.Lock()
        self._logs = deque(maxlen=100)  # type: deque

    def _safe_path(self, base: Path, *parts: str) -> Path:
        if self._is_link(base):
            raise ApiError(400, "允许目录不能是链接")
        cursor = base
        for part in parts:
            cursor = cursor / part
            if self._is_link(cursor):
                raise ApiError(400, "路径不能经过符号链接或 junction")
        base_resolved = base.resolve(strict=False)
        candidate = base.joinpath(*parts).resolve(strict=False)
        if not self._inside(self.root, base_resolved) or not self._inside(base_resolved, candidate):
            raise ApiError(400, "路径不在工作区内")
        return candidate

    def _read_text(self, path: Path, required: bool = True) -> str:
        if not path.is_file():
            if required:
                raise ApiError(404, "文件不存在")
            return ""
        if path.stat().st_size > MAX_FILE:
            raise ApiError(413, "文件过大，GUI 拒绝读取")
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            raise ApiError(422, "文件不是有效 UTF-8")

    def _atomic_write(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_name = None  # type: Optional[str]
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                dir=str(path.parent),
                prefix="." + path.name + ".",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temp_name = handle.name
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, str(path))
            temp_name = None
        finally:
            if temp_name and os.path.exists(temp_name):
                os.unlink(temp_name)

    def _atomic_create(self, path: Path, content: str) -> None:
        if not path.parent.is_dir():
            raise ApiError(409, "新增文件的父目录不存在")
        temp_name = None  # type: Optional[str]
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                dir=str(path.parent),
                prefix="." + path.name + ".",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temp_name = handle.name
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temp_name, str(path))
            except FileExistsError:
                raise ApiError(409, "新增文件已存在，请重新检测技能")
        finally:
            if temp_name and os.path.exists(temp_name):
                try:
                    os.unlink(temp_name)
                except OSError:
                    # The hard link is already the committed file. A failed best-effort
                    # cleanup must not turn that successful create into a transaction
                    # failure that leaves an untracked target behind.
                    pass

    def _log(self, action: str, task_id: str, detail: str) -> None:
        entry = {
            "time": datetime.now().astimezone().isoformat(timespec="seconds"),
            "action": action,
            "task_id": task_id,
            "detail": detail,
        }
        with self._log_lock:
            self._logs.appendleft(entry)

    def logs(self) -> List[Dict[str, str]]:
        with self._log_lock:
            return list(self._logs)

    @staticmethod
    def _revision(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    @staticmethod
    def _line_body(line: str) -> str:
        return line.rstrip("\r\n")

    @staticmethod
    def _newline(content: str) -> str:
        return "\r\n" if "\r\n" in content else "\n"

    def _read_config(self, name: str) -> Tuple[Path, str]:
        if name not in ("skills.md", "projects.md", "capabilities.md"):
            raise ApiError(400, "配置文件不在允许清单内")
        path = self._safe_path(self.config, name)
        if not path.is_file():
            raise ApiError(404, "缺少配置文件: config/" + name)
        return path, self._read_preserved(path, "config/" + name)

    @staticmethod
    def _read_preserved(path: Path, label: str) -> str:
        if path.stat().st_size > MAX_FILE:
            raise ApiError(413, label + " 文件过大")
        try:
            return path.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            raise ApiError(422, label + " 不是有效 UTF-8")

    def _atomic_write_many(self, changes: List[Tuple[Path, str, Optional[str]]]) -> None:
        pending = [(path, updated, original) for path, updated, original in changes if updated != original]
        if len({str(path) for path, _, _ in pending}) != len(pending):
            raise ApiError(400, "同一文件不能在一次事务中重复写入")
        for path, _, original in pending:
            if original is None:
                if path.exists():
                    raise ApiError(409, "新增文件已存在，请重新检测技能")
                continue
            try:
                current = self._read_preserved(path, str(path))
            except (OSError, ApiError):
                raise ApiError(409, "配置已被其他程序修改，请重新打开设置")
            if current != original:
                raise ApiError(409, "配置已被其他程序修改，请重新打开设置")
        written = []  # type: List[Tuple[Path, str, Optional[str]]]
        try:
            for path, updated, original in pending:
                if original is None:
                    self._atomic_create(path, updated)
                else:
                    self._atomic_write(path, updated)
                written.append((path, updated, original))
        except Exception:
            rollback_error = None  # type: Optional[Exception]
            for path, updated, original in reversed(written):
                try:
                    if self._read_preserved(path, str(path)) != updated:
                        rollback_error = RuntimeError("配置在回滚前被外部修改")
                        continue
                    if original is None:
                        path.unlink()
                    else:
                        self._atomic_write(path, original)
                except Exception as error:  # pragma: no cover - disk failure safety net
                    rollback_error = error
            if rollback_error:
                raise ApiError(500, "配置写入失败且自动回滚未完成，请检查磁盘")
            raise

    @staticmethod
    def _clean_setting(value: Any, label: str, limit: int = 5000, allow_pipe: bool = True) -> str:
        if not isinstance(value, str):
            raise ApiError(400, label + "必须是字符串")
        cleaned = value.strip()
        if not cleaned:
            raise ApiError(400, label + "不能为空")
        if len(cleaned) > limit or "\x00" in cleaned or "\r" in cleaned or "\n" in cleaned:
            raise ApiError(400, label + "过长或包含换行/控制字符")
        if not allow_pipe and "|" in cleaned:
            raise ApiError(400, label + "不能包含竖线")
        return cleaned

    @staticmethod
    def _unwrap_code(value: str) -> str:
        value = value.strip()
        return value[1:-1] if len(value) >= 2 and value.startswith("`") and value.endswith("`") else value

    @staticmethod
    def _code(value: str) -> str:
        return value if "`" in value else "`" + value + "`"

    @staticmethod
    def _is_link(path: Path) -> bool:
        try:
            info = path.lstat()
        except OSError:
            return False
        return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)

    @staticmethod
    def _inside(base: Path, path: Path) -> bool:
        try:
            return os.path.commonpath([os.path.normcase(str(base)), os.path.normcase(str(path))]) == os.path.normcase(str(base))
        except ValueError:
            return False

    @staticmethod
    def _source_id(path: Path, strict: bool = True) -> str:
        canonical = path.resolve(strict=strict)
        return hashlib.sha256(os.path.normcase(str(canonical)).encode("utf-8")).hexdigest()

    @staticmethod
    def _bounded_text(path: Path, limit: int, label: str) -> str:
        try:
            if path.stat().st_size > limit:
                raise ApiError(413, label + "过大")
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            raise ApiError(422, label + "不是有效 UTF-8")
        except OSError as error:
            raise ApiError(422, label + "无法读取: " + str(error))

    def _candidate(
        self,
        path: Path,
        name: str,
        description: str,
        products: List[str],
        scopes: List[str],
        status: str,
        reason: str,
        kind: str = "external",
        strict: bool = True,
    ) -> Dict[str, Any]:
        source_id = self._source_id(path, strict=strict)
        return {
            "id": source_id,
            "source_id": source_id,
            "name": name,
            "description": description,
            "products": sorted(set(products)),
            "scope": "、".join(sorted(set(scopes))),
            "scopes": sorted(set(scopes)),
            "status": status,
            "path": str(path.resolve(strict=strict)),
            "reason": reason,
            "evidence": reason,
            "source_type": SKILL_SOURCE_TYPES[kind],
            "orchestrated": False,
            "file": "",
            "_kind": kind,
        }

    def _invalid_candidate(
        self, path: Path, products: List[str], scopes: List[str], reason: str, name: Optional[str] = None
    ) -> Dict[str, Any]:
        absolute = Path(os.path.abspath(str(path)))
        source_id = hashlib.sha256(("invalid\0" + os.path.normcase(str(absolute))).encode("utf-8")).hexdigest()
        return {
            "id": source_id,
            "source_id": source_id,
            "name": name or path.parent.name or path.name,
            "description": "",
            "products": sorted(set(products)),
            "scope": "、".join(sorted(set(scopes))),
            "scopes": sorted(set(scopes)),
            "status": "无效",
            "path": str(absolute),
            "reason": reason,
            "evidence": reason,
            "source_type": SKILL_SOURCE_TYPES["diagnostic"],
            "orchestrated": False,
            "file": "",
            "_kind": "diagnostic",
        }

    def _base_skill_roots(self) -> List[Dict[str, Any]]:
        roots = [
            (self.root / ".codex" / "skills", ("Codex", "Cursor"), "工作区"),
            (self.root / ".claude" / "skills", ("Claude Code", "Cursor", "GitHub Copilot"), "工作区"),
            (self.root / ".cursor" / "skills", ("Cursor",), "工作区"),
            (self.root / ".gemini" / "skills", ("Gemini CLI",), "工作区"),
            (self.root / ".github" / "skills", ("GitHub Copilot",), "工作区"),
            (self.root / ".windsurf" / "skills", ("Windsurf",), "工作区"),
            (self.root / ".agents" / "skills", ("Cursor", "Gemini CLI", "GitHub Copilot", "Windsurf"), "工作区"),
            (self.home / ".codex" / "skills", ("Codex", "Cursor"), "用户"),
            (self.home / ".claude" / "skills", ("Claude Code", "Cursor", "GitHub Copilot"), "用户"),
            (self.home / ".cursor" / "skills", ("Cursor",), "用户"),
            (self.gemini_home / ".gemini" / "skills", ("Gemini CLI",), "用户"),
            (self.copilot_home / "skills", ("GitHub Copilot",), "用户"),
            (self.home / ".codeium" / "windsurf" / "skills", ("Windsurf",), "用户"),
            (self.home / ".agents" / "skills", ("Cursor", "Gemini CLI", "GitHub Copilot", "Windsurf"), "用户"),
        ]
        if self.program_data:
            roots.append((self.program_data / "Windsurf" / "skills", ("Windsurf",), "系统"))
        roots.extend((path, ("GitHub Copilot",), "环境") for path in self.copilot_extra_roots)
        return [
            {
                "path": path,
                "products": list(products),
                "scopes": [scope],
                "status": "已发现未确认",
                "reason": "位于官方固定技能目录，未核对当前 Agent 会话",
            }
            for path, products, scope in roots
        ]

    def _codex_enabled_plugins(self) -> Tuple[List[str], List[Dict[str, Any]]]:
        config = self.home / ".codex" / "config.toml"
        if not config.exists():
            return [], []
        if self._is_link(config) or os.path.normcase(os.path.abspath(str(config))) != os.path.normcase(str(config.resolve())):
            return [], [self._invalid_candidate(config, ["Codex"], ["插件"], "Codex 配置是链接，已跳过")]
        try:
            content = self._bounded_text(config, MAX_AGENT_CONFIG, "Codex 配置")
        except ApiError as error:
            return [], [self._invalid_candidate(config, ["Codex"], ["插件"], error.message)]
        values = {}  # type: Dict[str, List[bool]]
        current = None  # type: Optional[str]
        section_re = re.compile(r'^\s*\[plugins\.(?:"([A-Za-z0-9._-]+@[A-Za-z0-9._-]+)"|\'([A-Za-z0-9._-]+@[A-Za-z0-9._-]+)\')\]\s*(?:#.*)?$')
        for line in content.splitlines():
            section = section_re.match(line)
            if section:
                current = section.group(1) or section.group(2)
                values.setdefault(current, [])
                continue
            if line.lstrip().startswith("["):
                current = None
                continue
            if current:
                enabled = re.match(r"^\s*enabled\s*=\s*(true|false)\s*(?:#.*)?$", line, re.IGNORECASE)
                if enabled:
                    values[current].append(enabled.group(1).lower() == "true")
        enabled_ids = [plugin_id for plugin_id, flags in values.items() if flags == [True]]
        diagnostics = []
        if len(enabled_ids) > 100:
            diagnostics.append(self._invalid_candidate(config, ["Codex"], ["插件"], "启用插件数量超过上限"))
        return enabled_ids[:100], diagnostics

    def _codex_plugin_roots(self) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        plugin_ids, diagnostics = self._codex_enabled_plugins()
        cache = self.home / ".codex" / "plugins" / "cache"
        for plugin_id in plugin_ids:
            name, registry = plugin_id.rsplit("@", 1)
            registry_names = [registry]
            if registry == "openai-curated":
                registry_names.insert(0, "openai-curated-remote")
            plugin_roots = []
            for registry_name in registry_names:
                candidate = cache / registry_name / name
                if (
                    candidate.is_dir()
                    and not self._is_link(candidate)
                    and os.path.normcase(os.path.abspath(str(candidate))) == os.path.normcase(str(candidate.resolve()))
                ):
                    plugin_roots.append(candidate)
                    break
            unique_roots = {os.path.normcase(str(path.resolve())): path for path in plugin_roots}
            if len(unique_roots) != 1:
                if plugin_roots:
                    diagnostics.append(
                        self._invalid_candidate(plugin_roots[0], ["Codex"], ["插件"], "启用插件缓存位置不唯一", plugin_id)
                    )
                continue
            plugin_root = next(iter(unique_roots.values()))
            versions = []
            try:
                with os.scandir(str(plugin_root)) as iterator:
                    for index, entry in enumerate(iterator):
                        if index >= 100:
                            versions = []
                            break
                        version = Path(entry.path)
                        if entry.name.startswith(".") or self._is_link(version) or not entry.is_dir(follow_symlinks=False):
                            continue
                        if not self._inside(plugin_root.resolve(), version.resolve()):
                            continue
                        versions.append(version)
            except OSError:
                continue
            if len(versions) != 1:
                diagnostics.append(
                    self._invalid_candidate(plugin_root, ["Codex"], ["插件"], "启用插件无法唯一确定物理版本", plugin_id)
                )
                continue
            version = versions[0]
            manifest = version / ".codex-plugin" / "plugin.json"
            try:
                if self._is_link(manifest):
                    raise ApiError(422, "插件 manifest 是链接")
                raw = self._bounded_text(manifest, MAX_AGENT_CONFIG, "插件 manifest")
                data = json.loads(raw)
                if not isinstance(data, dict) or data.get("name") != name:
                    raise ApiError(422, "插件 manifest 名称不匹配")
                skill_values = data.get("skills", "./skills/")
                if isinstance(skill_values, str):
                    skill_values = [skill_values]
                if not isinstance(skill_values, list) or not 1 <= len(skill_values) <= 10:
                    raise ApiError(422, "插件 skills 字段不合法")
                if any(
                    not isinstance(value, str)
                    or not 1 <= len(value) <= 500
                    or any(ord(char) < 32 for char in value)
                    for value in skill_values
                ):
                    raise ApiError(422, "插件 skills 路径不合法")
            except (json.JSONDecodeError, ApiError, OSError, ValueError, RecursionError) as error:
                reason = error.message if isinstance(error, ApiError) else "插件 manifest 不是有效 JSON"
                diagnostics.append(self._invalid_candidate(manifest, ["Codex"], ["插件"], reason, plugin_id))
                continue
            for value in skill_values:
                try:
                    relative = Path(value)
                    if relative.is_absolute() or ".." in relative.parts:
                        raise ApiError(422, "插件 skills 路径越界")
                    skill_root = version / relative
                    if not self._inside(version.resolve(), skill_root.resolve(strict=False)):
                        raise ApiError(422, "插件 skills 路径越界")
                except (ApiError, OSError, ValueError):
                    diagnostics.append(
                        self._invalid_candidate(manifest, ["Codex"], ["插件"], "插件 skills 路径越界", plugin_id)
                    )
                    continue
                diagnostics_root = {
                    "path": skill_root,
                    "products": ["Codex"],
                    "scopes": ["插件"],
                    "status": "已确认启用",
                    "reason": "Codex config.toml 已启用且 manifest 唯一确定物理版本",
                }
                diagnostics.append(diagnostics_root)
        roots = [item for item in diagnostics if "status" in item and "id" not in item]
        diagnostics = [item for item in diagnostics if "id" in item]
        return roots, diagnostics

    @staticmethod
    def _strip_jsonc(content: str) -> str:
        result = []
        index = 0
        in_string = False
        escaped = False
        while index < len(content):
            char = content[index]
            if in_string:
                result.append(char)
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                index += 1
                continue
            if char == '"':
                in_string = True
                result.append(char)
                index += 1
                continue
            if content.startswith("//", index):
                index += 2
                while index < len(content) and content[index] not in "\r\n":
                    index += 1
                continue
            if content.startswith("/*", index):
                end = content.find("*/", index + 2)
                if end < 0:
                    raise ApiError(422, "JSONC 块注释未闭合")
                result.extend(char for char in content[index : end + 2] if char in "\r\n")
                index = end + 2
                continue
            result.append(char)
            index += 1
        if in_string:
            raise ApiError(422, "JSON 字符串未闭合")

        content = "".join(result)
        result = []
        index = 0
        in_string = False
        escaped = False
        while index < len(content):
            char = content[index]
            if in_string:
                result.append(char)
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                index += 1
                continue
            if char == '"':
                in_string = True
            if char == ",":
                lookahead = index + 1
                while lookahead < len(content) and content[lookahead].isspace():
                    lookahead += 1
                if lookahead < len(content) and content[lookahead] in "]}":
                    index += 1
                    continue
            result.append(char)
            index += 1
        return "".join(result)

    def _json_object(self, path: Path, label: str, jsonc: bool = False) -> Dict[str, Any]:
        if self._is_link(path) or os.path.normcase(os.path.abspath(str(path))) != os.path.normcase(str(path.resolve())):
            raise ApiError(422, label + " 是链接或经过链接")
        content = self._bounded_text(path, MAX_AGENT_CONFIG, label).lstrip("\ufeff")
        try:
            data = json.loads(self._strip_jsonc(content) if jsonc else content)
        except (json.JSONDecodeError, ValueError, RecursionError):
            raise ApiError(422, label + " 不是有效 JSON")
        if not isinstance(data, dict):
            raise ApiError(422, label + " 顶层必须是对象")
        return data

    def _plugin_settings(
        self,
        paths: List[Path],
        product: str,
        jsonc: bool = False,
        user_skill_settings: Optional[Path] = None,
    ) -> Tuple[Dict[str, bool], set, List[Path], List[Dict[str, Any]], bool]:
        enabled = {}  # type: Dict[str, bool]
        disabled_skills = set()
        skill_roots = []
        diagnostics = []
        settings_trusted = True
        for path in paths:
            if not path.exists():
                continue
            try:
                data = self._json_object(path, product + " settings", jsonc=jsonc)
                values = data.get("enabledPlugins", {})
                if values is not None and not isinstance(values, dict):
                    raise ApiError(422, "enabledPlugins 必须是对象")
                if isinstance(values, dict):
                    if len(values) > 100:
                        raise ApiError(422, "enabledPlugins 超过数量上限")
                    for name, state in values.items():
                        if (
                            not isinstance(name, str)
                            or not re.fullmatch(r"[A-Za-z0-9._-]+(?:@[A-Za-z0-9._-]+)?", name)
                            or not isinstance(state, bool)
                        ):
                            raise ApiError(422, "enabledPlugins 条目不合法")
                        enabled[name] = state
                disabled = data.get("disabledSkills", [])
                if disabled is not None and not isinstance(disabled, list):
                    raise ApiError(422, "disabledSkills 必须是列表")
                if isinstance(disabled, list):
                    if len(disabled) > MAX_SKILLS_PER_ROOT:
                        raise ApiError(422, "disabledSkills 超过数量上限")
                    for name in disabled:
                        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}", name):
                            raise ApiError(422, "disabledSkills 条目不合法")
                        disabled_skills.add(name)
                directories = data.get("skillDirectories", []) if path == user_skill_settings else []
                if directories is not None and not isinstance(directories, list):
                    raise ApiError(422, "skillDirectories 必须是列表")
                if isinstance(directories, list):
                    if len(directories) > 10:
                        raise ApiError(422, "skillDirectories 超过数量上限")
                    for value in directories:
                        if (
                            not isinstance(value, str)
                            or not 1 <= len(value) <= 4096
                            or any(ord(char) < 32 for char in value)
                        ):
                            raise ApiError(422, "skillDirectories 条目不合法")
                        root = Path(value).expanduser()
                        if not root.is_absolute():
                            raise ApiError(422, "skillDirectories 只接受绝对路径")
                        skill_roots.append(Path(os.path.abspath(str(root))))
            except (ApiError, OSError) as error:
                settings_trusted = False
                reason = error.message if isinstance(error, ApiError) else product + " settings 无法读取"
                diagnostics.append(self._invalid_candidate(path, [product], ["配置"], reason, path.name))
        return enabled, disabled_skills, skill_roots, diagnostics, settings_trusted

    def _direct_plugin_dirs(
        self, root: Path, product: str, scope: str
    ) -> Tuple[List[Path], List[Dict[str, Any]]]:
        if not root.exists():
            return [], []
        if (
            self._is_link(root)
            or not root.is_dir()
            or os.path.normcase(os.path.abspath(str(root))) != os.path.normcase(str(root.resolve()))
        ):
            return [], [self._invalid_candidate(root, [product], [scope], "插件或扩展根是链接或不是安全目录")]
        directories = []
        diagnostics = []
        try:
            with os.scandir(str(root)) as iterator:
                entries = []
                for index, entry in enumerate(iterator):
                    if index >= MAX_SKILL_ENTRIES_PER_ROOT:
                        return [], [
                            self._invalid_candidate(root, [product], [scope], "插件或扩展根超过遍历上限")
                        ]
                    entries.append(entry)
        except OSError:
            return [], [self._invalid_candidate(root, [product], [scope], "插件或扩展根无法读取")]
        for entry in sorted(entries, key=lambda item: item.name.casefold()):
            path = Path(entry.path)
            if entry.name.startswith("."):
                continue
            if self._is_link(path):
                diagnostics.append(self._invalid_candidate(path, [product], [scope], "插件或扩展目录链接已跳过"))
                continue
            try:
                is_directory = entry.is_dir(follow_symlinks=False)
            except OSError:
                diagnostics.append(self._invalid_candidate(path, [product], [scope], "插件或扩展目录无法读取"))
                continue
            if is_directory:
                directories.append(path)
                if len(directories) > 100:
                    diagnostics.append(self._invalid_candidate(root, [product], [scope], "插件或扩展数量超过上限"))
                    break
        return directories[:100], diagnostics

    def _extend_candidates(
        self,
        current: List[Dict[str, Any]],
        additions: List[Dict[str, Any]],
        root: Path,
        product: str,
        scope: str,
    ) -> bool:
        remaining = MAX_SKILL_CATALOG - len(current)
        if len(additions) <= remaining:
            current.extend(additions)
            return True
        if remaining > 0:
            current.extend(additions[: max(0, remaining - 1)])
            current.append(self._invalid_candidate(root, [product], [scope], "该来源超过目录总结果上限"))
        return False

    def _plugin_manifest(
        self,
        plugin_root: Path,
        manifest: Path,
        product: str,
        scope: str,
        require_version: bool = False,
    ) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
        try:
            if not self._inside(plugin_root.resolve(), manifest.resolve(strict=False)):
                raise ApiError(422, "manifest 路径越界")
            data = self._json_object(manifest, product + " manifest")
            name = data.get("name")
            if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}", name):
                raise ApiError(422, "manifest name 不合法")
            if require_version:
                version = data.get("version")
                if (
                    not isinstance(version, str)
                    or not 1 <= len(version) <= 100
                    or any(ord(char) < 32 for char in version)
                ):
                    raise ApiError(422, "manifest version 不合法")
            return data, []
        except (ApiError, OSError) as error:
            reason = error.message if isinstance(error, ApiError) else "manifest 无法读取"
            return None, [self._invalid_candidate(manifest, [product], [scope], reason, plugin_root.name)]

    def _manifest_targets(
        self, plugin_root: Path, value: str, product: str, scope: str
    ) -> Tuple[List[Path], List[Dict[str, Any]]]:
        normalized = value.replace("\\", "/")
        if (
            not 1 <= len(normalized) <= 500
            or any(ord(char) < 32 for char in normalized)
            or Path(normalized).is_absolute()
        ):
            return [], [self._invalid_candidate(plugin_root, [product], [scope], "manifest skills 路径不合法")]
        parts = [part for part in normalized.split("/") if part not in ("", ".")]
        if not parts or ".." in parts or any("**" in part for part in parts):
            return [], [self._invalid_candidate(plugin_root, [product], [scope], "manifest skills 路径越界或递归过深")]
        nodes = [plugin_root]
        entries_seen = 0
        for part in parts:
            next_nodes = []
            wildcard = any(char in part for char in "*?[")
            for node in nodes:
                if wildcard:
                    if (
                        not node.is_dir()
                        or self._is_link(node)
                        or os.path.normcase(os.path.abspath(str(node))) != os.path.normcase(str(node.resolve()))
                    ):
                        continue
                    try:
                        with os.scandir(str(node)) as iterator:
                            entries = []
                            for entry in iterator:
                                entries_seen += 1
                                if entries_seen > MAX_SKILL_ENTRIES_PER_ROOT:
                                    return [], [
                                        self._invalid_candidate(
                                            plugin_root, [product], [scope], "manifest skills 展开超过上限"
                                        )
                                    ]
                                entries.append(entry)
                    except OSError:
                        continue
                    for entry in sorted(entries, key=lambda item: item.name.casefold()):
                        path = Path(entry.path)
                        if fnmatch.fnmatchcase(entry.name, part) and not self._is_link(path):
                            next_nodes.append(path)
                else:
                    next_nodes.append(node / part)
            nodes = next_nodes
            if len(nodes) > 100:
                return [], [self._invalid_candidate(plugin_root, [product], [scope], "manifest skills 结果超过上限")]
        root_real = plugin_root.resolve()
        targets = []
        for path in nodes:
            try:
                resolved = path.resolve(strict=False)
                if (
                    not self._inside(root_real, resolved)
                    or self._is_link(path)
                    or (
                        path.exists()
                        and os.path.normcase(os.path.abspath(str(path))) != os.path.normcase(str(resolved))
                    )
                ):
                    raise ApiError(422, "manifest skills 路径经过链接或越界")
                if path.exists():
                    targets.append(path)
            except (ApiError, OSError) as error:
                reason = error.message if isinstance(error, ApiError) else "manifest skills 路径无法解析"
                return [], [self._invalid_candidate(path, [product], [scope], reason)]
        return targets[:100], []

    def _scan_external_file(
        self, path: Path, boundary: Path, product: str, scope: str, status: str, reason: str
    ) -> List[Dict[str, Any]]:
        try:
            if (
                self._is_link(path)
                or not path.is_file()
                or not self._inside(boundary.resolve(), path.resolve())
                or os.path.normcase(os.path.abspath(str(path))) != os.path.normcase(str(path.resolve()))
            ):
                raise ApiError(422, "技能入口是链接、越界或不是文件")
            name, description = self._external_skill_metadata(path)
            return [self._candidate(path, name, description, [product], [scope], status, reason)]
        except (ApiError, OSError, ValueError) as error:
            message = error.message if isinstance(error, ApiError) else "技能入口无法解析"
            return [self._invalid_candidate(path, [product], [scope], message)]

    def _plugin_skill_candidates(
        self,
        plugin_root: Path,
        data: Dict[str, Any],
        product: str,
        scope: str,
        status: str,
        reason: str,
        fixed_skills: bool = False,
    ) -> List[Dict[str, Any]]:
        raw = None if fixed_skills else data.get("skills")
        if raw is None:
            values = ["skills"]
        elif isinstance(raw, str):
            values = [raw]
        elif isinstance(raw, list) and 1 <= len(raw) <= 20 and all(isinstance(value, str) for value in raw):
            values = raw
        else:
            return [self._invalid_candidate(plugin_root, [product], [scope], "manifest skills 字段不合法")]
        targets = []
        diagnostics = []
        for value in values:
            found, errors = self._manifest_targets(plugin_root, value, product, scope)
            targets.extend(found)
            diagnostics.extend(errors)
        if raw is None and not fixed_skills and not targets and (plugin_root / "SKILL.md").is_file():
            targets.append(plugin_root / "SKILL.md")
        candidates = list(diagnostics)
        seen = set()
        for target in targets:
            key = os.path.normcase(str(target.resolve()))
            if key in seen:
                continue
            seen.add(key)
            if target.is_file():
                found = []
                if target.name != "SKILL.md":
                    found.append(
                        self._invalid_candidate(target, [product], [scope], "manifest skills 文件不是 SKILL.md")
                    )
                else:
                    found = self._scan_external_file(target, plugin_root, product, scope, status, reason)
            else:
                spec = {
                    "path": target,
                    "products": [product],
                    "scopes": [scope],
                    "status": status,
                    "reason": reason,
                }
                found = self._scan_external_root(spec)
            remaining = MAX_SKILLS_PER_ROOT - len(candidates)
            if len(found) <= remaining:
                candidates.extend(found)
                continue
            if remaining > 0:
                candidates.extend(found[: max(0, remaining - 1)])
                candidates.append(
                    self._invalid_candidate(plugin_root, [product], [scope], "单个插件技能超过结果上限")
                )
            break
        return candidates[:MAX_SKILLS_PER_ROOT]

    def _cursor_plugin_candidates(self) -> List[Dict[str, Any]]:
        roots, diagnostics = self._direct_plugin_dirs(
            self.home / ".cursor" / "plugins" / "local", "Cursor", "本地插件"
        )
        candidates = list(diagnostics)
        for plugin_root in roots:
            manifest = plugin_root / ".cursor-plugin" / "plugin.json"
            if not manifest.is_file():
                candidates.append(
                    self._invalid_candidate(manifest, ["Cursor"], ["本地插件"], "缺少 .cursor-plugin/plugin.json")
                )
                continue
            data, errors = self._plugin_manifest(plugin_root, manifest, "Cursor", "本地插件")
            if not self._extend_candidates(candidates, errors, plugin_root, "Cursor", "本地插件"):
                break
            if data:
                found = self._plugin_skill_candidates(
                        plugin_root,
                        data,
                        "Cursor",
                        "本地插件",
                        "已发现未确认",
                        "Cursor 官方本地插件目录与 manifest 有效，未核对当前会话",
                    )
                if not self._extend_candidates(candidates, found, plugin_root, "Cursor", "本地插件"):
                    break
        return candidates

    def _gemini_extension_candidates(self) -> List[Dict[str, Any]]:
        roots, diagnostics = self._direct_plugin_dirs(
            self.gemini_home / ".gemini" / "extensions", "Gemini CLI", "本地扩展"
        )
        candidates = list(diagnostics)
        for plugin_root in roots:
            manifest = plugin_root / "gemini-extension.json"
            if not manifest.is_file():
                candidates.append(
                    self._invalid_candidate(manifest, ["Gemini CLI"], ["本地扩展"], "缺少 gemini-extension.json")
                )
                continue
            data, errors = self._plugin_manifest(
                plugin_root, manifest, "Gemini CLI", "本地扩展", require_version=True
            )
            if not self._extend_candidates(candidates, errors, plugin_root, "Gemini CLI", "本地扩展"):
                break
            if data:
                found = self._plugin_skill_candidates(
                        plugin_root,
                        data,
                        "Gemini CLI",
                        "本地扩展",
                        "已发现未确认",
                        "Gemini 扩展 manifest 有效，未核对工作区启停覆盖",
                        fixed_skills=True,
                    )
                if not self._extend_candidates(candidates, found, plugin_root, "Gemini CLI", "本地扩展"):
                    break
        return candidates

    def _copilot_plugin_candidates(self) -> Tuple[List[Dict[str, Any]], set]:
        user_settings = self.copilot_home / "settings.json"
        enabled, disabled, extra_roots, diagnostics, settings_trusted = self._plugin_settings(
            [
                user_settings,
                self.root / ".claude" / "settings.json",
                self.root / ".github" / "copilot" / "settings.json",
                self.root / ".claude" / "settings.local.json",
                self.root / ".github" / "copilot" / "settings.local.json",
            ],
            "GitHub Copilot",
            jsonc=True,
            user_skill_settings=user_settings,
        )
        candidates = []
        self._extend_candidates(
            candidates, diagnostics, self.copilot_home, "GitHub Copilot", "配置"
        )
        for root in extra_roots:
            found = self._scan_external_root(
                {
                    "path": root,
                    "products": ["GitHub Copilot"],
                    "scopes": ["配置"],
                    "status": "已发现未确认",
                    "reason": "Copilot settings.json 显式声明的技能目录",
                }
            )
            if not self._extend_candidates(
                candidates, found, root, "GitHub Copilot", "配置"
            ):
                return candidates, disabled

        installed = self.copilot_home / "installed-plugins"
        markets, errors = self._direct_plugin_dirs(installed, "GitHub Copilot", "已安装插件")
        if not self._extend_candidates(
            candidates, errors, installed, "GitHub Copilot", "已安装插件"
        ):
            return candidates, disabled
        plugin_roots = []
        plugin_roots_truncated = False
        for market_root in markets:
            if market_root.name == "_direct":
                direct_roots, direct_errors = self._direct_plugin_dirs(
                    market_root, "GitHub Copilot", "直装插件"
                )
                if not self._extend_candidates(
                    candidates, direct_errors, market_root, "GitHub Copilot", "直装插件"
                ):
                    return candidates, disabled
                for root in direct_roots:
                    if len(plugin_roots) >= 100:
                        plugin_roots_truncated = True
                        break
                    plugin_roots.append((root, "_direct"))
                continue
            roots, market_errors = self._direct_plugin_dirs(
                market_root, "GitHub Copilot", "Marketplace 插件"
            )
            if not self._extend_candidates(
                candidates, market_errors, market_root, "GitHub Copilot", "Marketplace 插件"
            ):
                return candidates, disabled
            for root in roots:
                if len(plugin_roots) >= 100:
                    plugin_roots_truncated = True
                    break
                plugin_roots.append((root, market_root.name))
            if plugin_roots_truncated:
                break
        if plugin_roots_truncated:
            self._extend_candidates(
                candidates,
                [
                    self._invalid_candidate(
                        installed,
                        ["GitHub Copilot"],
                        ["已安装插件"],
                        "已安装插件数量超过扫描上限",
                    )
                ],
                installed,
                "GitHub Copilot",
                "已安装插件",
            )
        for plugin_root, market in plugin_roots:
            manifest = next(
                (
                    path
                    for path in (
                        plugin_root / ".plugin" / "plugin.json",
                        plugin_root / "plugin.json",
                        plugin_root / ".github" / "plugin" / "plugin.json",
                        plugin_root / ".claude-plugin" / "plugin.json",
                    )
                    if path.is_file()
                ),
                None,
            )
            if manifest is None:
                if not self._extend_candidates(
                    candidates,
                    [
                        self._invalid_candidate(
                            plugin_root, ["GitHub Copilot"], ["已安装插件"], "缺少插件 manifest"
                        )
                    ],
                    plugin_root,
                    "GitHub Copilot",
                    "已安装插件",
                ):
                    break
                continue
            data, manifest_errors = self._plugin_manifest(
                plugin_root, manifest, "GitHub Copilot", "已安装插件"
            )
            if not self._extend_candidates(
                candidates,
                manifest_errors,
                plugin_root,
                "GitHub Copilot",
                "已安装插件",
            ):
                break
            if not data:
                continue
            name = data["name"]
            plugin_id = "{}@{}".format(name, market)
            configured = enabled.get(plugin_id)
            if market == "_direct" and name in enabled:
                configured = enabled[name]
            confirmed = settings_trusted and configured is True
            status = "已确认启用" if confirmed else "已发现未确认"
            if not settings_trusted:
                reason = "部分 Copilot settings 无效，无法确认插件启停状态"
            elif configured is False:
                reason = "Copilot settings 明确禁用该已安装插件"
            elif confirmed:
                reason = "Copilot settings 已明确启用该已安装插件"
            else:
                reason = "Copilot 官方安装目录与 manifest 有效，未找到明确启用配置"
            found = self._plugin_skill_candidates(
                plugin_root, data, "GitHub Copilot", "已安装插件", status, reason
            )
            for candidate in found:
                if settings_trusted and candidate.get("name") in disabled:
                    candidate["status"] = "已发现未确认"
                    candidate["reason"] = "Copilot settings 明确禁用该技能"
                    candidate["evidence"] = candidate["reason"]
            if not self._extend_candidates(
                candidates, found, plugin_root, "GitHub Copilot", "已安装插件"
            ):
                break
        return candidates, disabled if settings_trusted else set()

    @staticmethod
    def _frontmatter_scalar(value: str) -> Optional[str]:
        value = value.strip()
        if not value or value[0] in "|>[{":
            return None
        if value.startswith('"'):
            try:
                parsed = json.loads(value)
            except (json.JSONDecodeError, ValueError, RecursionError):
                return None
            return parsed if isinstance(parsed, str) else None
        if value.startswith("'"):
            if len(value) < 2 or not value.endswith("'"):
                return None
            return value[1:-1].replace("''", "'")
        return value

    def _external_skill_metadata(self, path: Path) -> Tuple[str, str]:
        content = self._bounded_text(path, MAX_SKILL_FILE, "SKILL.md")
        lines = content.splitlines()
        if not lines or lines[0].strip() != "---":
            raise ApiError(422, "SKILL.md 缺少 YAML frontmatter")
        close = next(
            (
                index
                for index, line in enumerate(lines[1:101], 1)
                if line == line.lstrip() and line.strip() == "---"
            ),
            -1,
        )
        if close < 0:
            raise ApiError(422, "SKILL.md frontmatter 未闭合或过长")
        metadata = {}  # type: Dict[str, str]
        frontmatter = lines[1:close]
        index = 0
        while index < len(frontmatter):
            line = frontmatter[index]
            if len(line) > 2000:
                raise ApiError(422, "SKILL.md 元数据行过长")
            match = re.match(r"^(name|description)\s*:\s*(.*)$", line)
            if not match:
                index += 1
                continue
            key, raw = match.groups()
            if key in metadata:
                raise ApiError(422, "SKILL.md name/description 不能重复")
            block = re.fullmatch(r"([>|])[+-]?", raw.strip()) if key == "description" else None
            if block:
                index += 1
                values = []
                while index < len(frontmatter):
                    value_line = frontmatter[index]
                    if len(value_line) > 2000:
                        raise ApiError(422, "SKILL.md 元数据行过长")
                    if value_line and not value_line[0].isspace():
                        break
                    if "\t" in value_line:
                        raise ApiError(422, "SKILL.md description 缩进不合法")
                    values.append(value_line)
                    index += 1
                nonempty = [value for value in values if value.strip()]
                if not nonempty:
                    raise ApiError(422, "SKILL.md description 不能为空")
                indent = min(len(value) - len(value.lstrip(" ")) for value in nonempty)
                unfolded = "\n".join(value[indent:] if value.strip() else "" for value in values)
                value = re.sub(r"\s+", " ", unfolded).strip()
            else:
                value = self._frontmatter_scalar(raw)
                if value is None:
                    raise ApiError(422, "SKILL.md 只支持标量 name/description")
                value = value.strip()
                index += 1
            metadata[key] = value
        name = metadata.get("name", "")
        description = metadata.get("description", "")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}", name):
            raise ApiError(422, "SKILL.md name 不合法")
        if not description or len(description) > 1024 or any(ord(char) < 32 for char in description):
            raise ApiError(422, "SKILL.md description 不合法")
        return name, description

    def _scan_external_root(self, spec: Dict[str, Any]) -> List[Dict[str, Any]]:
        root = spec["path"]
        if not root.exists():
            return []
        if self._is_link(root) or not root.is_dir():
            return [self._invalid_candidate(root, spec["products"], spec["scopes"], "技能根目录是链接或不是目录")]
        if os.path.normcase(os.path.abspath(str(root))) != os.path.normcase(str(root.resolve())):
            return [self._invalid_candidate(root, spec["products"], spec["scopes"], "技能根目录经过链接或 junction")]
        root_real = root.resolve()
        found = []  # type: List[Dict[str, Any]]
        stack = [(root, 0)]
        seen = 0
        entries_seen = 0
        limited = False
        while stack and not limited:
            directory, depth = stack.pop()
            try:
                iterator = os.scandir(str(directory))
            except OSError as error:
                found.append(
                    self._invalid_candidate(directory, spec["products"], spec["scopes"], "目录无法读取: " + str(error))
                )
                continue
            try:
                entries = []
                with iterator:
                    for entry in iterator:
                        entries_seen += 1
                        if entries_seen > MAX_SKILL_ENTRIES_PER_ROOT:
                            found.append(
                                self._invalid_candidate(
                                    root, spec["products"], spec["scopes"], "单个技能根超过遍历上限", root.name
                                )
                            )
                            limited = True
                            break
                        entries.append(entry)
                if limited:
                    break
                for entry in sorted(entries, key=lambda item: item.name.casefold(), reverse=True):
                    path = Path(entry.path)
                    if self._is_link(path):
                        found.append(
                            self._invalid_candidate(path, spec["products"], spec["scopes"], "符号链接或 junction 已跳过")
                        )
                        continue
                    try:
                        is_directory = entry.is_dir(follow_symlinks=False)
                        is_file = entry.is_file(follow_symlinks=False)
                    except OSError:
                        found.append(
                            self._invalid_candidate(path, spec["products"], spec["scopes"], "目录条目无法读取")
                        )
                        continue
                    if is_directory:
                        if entry.name.casefold() not in SKIP_SKILL_DIRS and depth < MAX_SKILL_DEPTH:
                            stack.append((path, depth + 1))
                        continue
                    if entry.name != "SKILL.md" or not is_file:
                        continue
                    seen += 1
                    if seen > MAX_SKILLS_PER_ROOT:
                        found.append(
                            self._invalid_candidate(
                                root, spec["products"], spec["scopes"], "单个技能根超过结果上限", root.name
                            )
                        )
                        limited = True
                        break
                    try:
                        resolved = path.resolve(strict=True)
                        if not self._inside(root_real, resolved):
                            raise ApiError(422, "SKILL.md 越出允许根目录")
                        name, description = self._external_skill_metadata(path)
                        found.append(
                            self._candidate(
                                path,
                                name,
                                description,
                                spec["products"],
                                spec["scopes"],
                                spec["status"],
                                spec["reason"],
                            )
                        )
                    except (OSError, ApiError) as error:
                        reason = error.message if isinstance(error, ApiError) else "SKILL.md 无法解析: " + str(error)
                        found.append(self._invalid_candidate(path, spec["products"], spec["scopes"], reason))
            except OSError as error:
                found.append(
                    self._invalid_candidate(directory, spec["products"], spec["scopes"], "目录无法读取: " + str(error))
                )
        return found

    def _scan_claude_commands(self, root: Path, scope: str) -> List[Dict[str, Any]]:
        if not root.exists():
            return []
        if self._is_link(root) or not root.is_dir():
            return [self._invalid_candidate(root, ["Claude Code"], [scope], "commands 目录是链接或不是目录")]
        if os.path.normcase(os.path.abspath(str(root))) != os.path.normcase(str(root.resolve())):
            return [self._invalid_candidate(root, ["Claude Code"], [scope], "commands 目录经过链接或 junction")]
        found = []  # type: List[Dict[str, Any]]
        entries = []
        try:
            with os.scandir(str(root)) as iterator:
                for index, entry in enumerate(iterator):
                    if index >= MAX_SKILL_ENTRIES_PER_ROOT:
                        return [self._invalid_candidate(root, ["Claude Code"], [scope], "commands 目录超过遍历上限")]
                    entries.append(entry)
        except OSError as error:
            return [self._invalid_candidate(root, ["Claude Code"], [scope], "commands 目录无法读取: " + str(error))]
        files = sorted(
            [entry for entry in entries if entry.name.endswith(".md")], key=lambda item: item.name.casefold()
        )
        if len(files) > MAX_SKILLS_PER_ROOT:
            found.append(self._invalid_candidate(root, ["Claude Code"], [scope], "commands 目录超过结果上限"))
        for entry in files[:MAX_SKILLS_PER_ROOT]:
            path = Path(entry.path)
            try:
                is_file = entry.is_file(follow_symlinks=False)
            except OSError:
                found.append(self._invalid_candidate(path, ["Claude Code"], [scope], "commands 文件无法读取"))
                continue
            if self._is_link(path) or not is_file:
                found.append(self._invalid_candidate(path, ["Claude Code"], [scope], "commands 文件链接已跳过"))
                continue
            try:
                content = self._bounded_text(path, MAX_SKILL_FILE, "Claude command")
                name = first_heading(content, path.stem)
                description = next(
                    (
                        line.strip()
                        for line in content.splitlines()
                        if line.strip() and not line.lstrip().startswith(("#", "---", "name:", "description:"))
                    ),
                    "",
                )[:500]
                if not name or len(name) > 100 or any(ord(char) < 32 for char in name + description):
                    raise ApiError(422, "Claude command 元数据不合法")
                found.append(
                    self._candidate(
                        path,
                        name,
                        description,
                        ["Claude Code"],
                        [scope],
                        "已发现未确认",
                        "Claude Code 旧式 commands 固定目录",
                    )
                )
            except ApiError as error:
                found.append(self._invalid_candidate(path, ["Claude Code"], [scope], error.message))
        return found

    @staticmethod
    def _adapter_metadata(content: str) -> Optional[Dict[str, Any]]:
        values = {}  # type: Dict[str, Any]
        labels = {
            "外部源标识": "source_id",
            "外部技能入口(JSON)": "path",
            "外部技能名称(JSON)": "name",
            "外部技能描述(JSON)": "description",
            "来源产品(JSON)": "products",
        }
        for label, key in labels.items():
            match = re.search(r"^- " + re.escape(label) + r":\s*(.+)$", content, re.MULTILINE)
            if not match:
                return None
            raw = match.group(1).strip()
            if key == "source_id":
                values[key] = raw
            else:
                try:
                    values[key] = json.loads(raw)
                except (json.JSONDecodeError, ValueError, RecursionError):
                    return None
        if (
            not re.fullmatch(r"[0-9a-f]{64}", values["source_id"])
            or not isinstance(values["path"], str)
            or not 1 <= len(values["path"]) <= 4096
            or not Path(values["path"]).is_absolute()
            or any(ord(char) < 32 for char in values["path"])
            or not isinstance(values["name"], str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}", values["name"])
            or not isinstance(values["description"], str)
            or len(values["description"]) > 1024
            or any(ord(char) < 32 for char in values["description"])
            or not isinstance(values["products"], list)
            or not 1 <= len(values["products"]) <= 10
            or any(
                not isinstance(value, str)
                or not 1 <= len(value) <= 100
                or any(ord(char) < 32 for char in value)
                for value in values["products"]
            )
        ):
            return None
        return values

    def _native_skill_candidate(self, path: Path, content: str) -> Dict[str, Any]:
        adapter = self._adapter_metadata(content)
        if adapter:
            source = Path(adapter["path"])
            candidate = self._candidate(
                source,
                adapter["name"],
                adapter["description"],
                adapter["products"],
                ["外部"],
                "失效",
                "未在受控扫描中发现，可能已移动、删除或无效",
                kind="imported",
                strict=False,
            )
            if candidate["source_id"] != adapter["source_id"]:
                raise ApiError(422, "外部技能适配器的来源标识与入口路径不匹配")
            candidate["file"] = "skills/" + path.name
            return candidate
        if path.name.startswith("imported-"):
            raise ApiError(422, "外部技能适配器元数据不完整")
        title = first_heading(content, path.stem)
        name = title.split(":", 1)[1].strip() if title.startswith("技能:") else title
        effect = re.search(r"^- 作用:\s*(.*)$", content, re.MULTILINE)
        candidate = self._candidate(
            path,
            name or path.stem,
            effect.group(1).strip() if effect else "",
            ["Workflow"],
            ["工作区"],
            "已发现未确认",
            "工作区原生技能文件",
            kind="native",
        )
        candidate["file"] = "skills/" + path.name
        return candidate

    @staticmethod
    def _merge_candidate(catalog: Dict[str, Dict[str, Any]], candidate: Dict[str, Any]) -> None:
        current = catalog.get(candidate["id"])
        if not current:
            catalog[candidate["id"]] = candidate
            return
        current["products"] = sorted(set(current["products"] + candidate["products"]))
        current["scopes"] = sorted(set(current["scopes"] + candidate["scopes"]))
        current["scope"] = "、".join(current["scopes"])
        priority = {"无效": 0, "失效": 1, "已发现未确认": 2, "已确认启用": 3}
        if priority[candidate["status"]] > priority[current["status"]]:
            current["status"] = candidate["status"]
            current["reason"] = candidate["reason"]
            current["evidence"] = candidate["evidence"]
            current["description"] = candidate["description"] or current["description"]
        if candidate.get("file"):
            current["file"] = candidate["file"]
        if current.get("_kind") == "diagnostic" and candidate.get("_kind") != "diagnostic":
            current["_kind"] = candidate["_kind"]
            current["source_type"] = candidate["source_type"]

    def _discover_skill_catalog(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        catalog = {}  # type: Dict[str, Dict[str, Any]]
        plugin_roots, diagnostics = self._codex_plugin_roots()
        for spec in self._base_skill_roots() + plugin_roots:
            for candidate in self._scan_external_root(spec):
                self._merge_candidate(catalog, candidate)
                if len(catalog) >= MAX_SKILL_CATALOG:
                    break
            if len(catalog) >= MAX_SKILL_CATALOG:
                break
        for candidate in diagnostics:
            self._merge_candidate(catalog, candidate)
        for discover in (
            self._cursor_plugin_candidates,
            self._gemini_extension_candidates,
        ):
            for candidate in discover():
                self._merge_candidate(catalog, candidate)
                if len(catalog) >= MAX_SKILL_CATALOG:
                    break
            if len(catalog) >= MAX_SKILL_CATALOG:
                break
        copilot_disabled = set()
        if len(catalog) < MAX_SKILL_CATALOG:
            copilot_candidates, copilot_disabled = self._copilot_plugin_candidates()
            for candidate in copilot_candidates:
                self._merge_candidate(catalog, candidate)
                if len(catalog) >= MAX_SKILL_CATALOG:
                    break
        for command_root, scope in (
            (self.root / ".claude" / "commands", "工作区"),
            (self.home / ".claude" / "commands", "用户"),
        ):
            for candidate in self._scan_claude_commands(command_root, scope):
                self._merge_candidate(catalog, candidate)

        if self.skills.exists() and (self._is_link(self.skills) or not self.skills.is_dir()):
            self._merge_candidate(
                catalog, self._invalid_candidate(self.skills, ["Workflow"], ["工作区"], "工作区技能根是链接或不是目录")
            )
        elif self.skills.is_dir():
            entries = []
            try:
                with os.scandir(str(self.skills)) as iterator:
                    for index, entry in enumerate(iterator):
                        if index >= MAX_SKILL_ENTRIES_PER_ROOT:
                            self._merge_candidate(
                                catalog,
                                self._invalid_candidate(self.skills, ["Workflow"], ["工作区"], "工作区技能超过遍历上限"),
                            )
                            break
                        entries.append(entry)
            except OSError as error:
                self._merge_candidate(
                    catalog,
                    self._invalid_candidate(self.skills, ["Workflow"], ["工作区"], "工作区技能无法读取: " + str(error)),
                )
            paths = sorted(
                [Path(entry.path) for entry in entries if entry.name.endswith(".md")],
                key=lambda item: item.name.casefold(),
            )
            if len(paths) > MAX_SKILLS_PER_ROOT:
                self._merge_candidate(
                    catalog, self._invalid_candidate(self.skills, ["Workflow"], ["工作区"], "工作区技能超过结果上限")
                )
            for path in paths[:MAX_SKILLS_PER_ROOT]:
                if self._is_link(path):
                    self._merge_candidate(
                        catalog, self._invalid_candidate(path, ["Workflow"], ["工作区"], "符号链接或 junction 已跳过")
                    )
                    continue
                try:
                    content = self._bounded_text(path, MAX_SKILL_FILE, "工作区技能")
                    self._merge_candidate(catalog, self._native_skill_candidate(path, content))
                except (ApiError, OSError, ValueError) as error:
                    message = error.message if isinstance(error, ApiError) else "工作区技能路径或元数据不合法"
                    self._merge_candidate(
                        catalog, self._invalid_candidate(path, ["Workflow"], ["工作区"], message)
                    )

        by_file = {candidate.get("file"): candidate for candidate in catalog.values() if candidate.get("file")}
        by_path = {
            os.path.normcase(candidate["path"]): candidate
            for candidate in catalog.values()
            if candidate.get("path")
        }
        for row in rows:
            candidate = by_file.get(row["file"])
            if not candidate:
                try:
                    path = self._skill_path(row["file"])
                    candidate = by_path.get(os.path.normcase(str(path.resolve())))
                except ApiError:
                    candidate = None
            if not candidate:
                continue
            candidate["orchestrated"] = True
            candidate["file"] = row["file"]

        for candidate in catalog.values():
            if (
                candidate["name"] in copilot_disabled
                and "GitHub Copilot" in candidate["products"]
                and candidate["status"] not in ("失效", "无效")
            ):
                disabled_reason = "Copilot settings 明确禁用该技能"
                if candidate["products"] == ["GitHub Copilot"]:
                    candidate["status"] = "已发现未确认"
                    candidate["reason"] = disabled_reason
                    candidate["evidence"] = disabled_reason
                elif disabled_reason not in candidate["evidence"]:
                    candidate["evidence"] = candidate["evidence"] + "；" + disabled_reason

        result = list(catalog.values())[:MAX_SKILL_CATALOG]
        result.sort(key=lambda item: (item["name"].casefold(), item["path"].casefold()))
        return result

    def _skills_snapshot(self, content: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], int, int]:
        rows, start, end = self._parse_skills(content)
        catalog = self._discover_skill_catalog(rows)
        file_to_source = {item["file"]: item["id"] for item in catalog if item.get("file")}
        enriched = []
        for row in rows:
            item = dict(row)
            if row["file"] not in file_to_source:
                item["source_id"] = self._source_id(self._skill_path(row["file"]))
            else:
                item["source_id"] = file_to_source[row["file"]]
            enriched.append(item)
        return enriched, catalog, start, end

    @staticmethod
    def _adapter_filename(candidate: Dict[str, Any]) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", candidate["name"].lower()).strip("-") or "skill"
        return "skills/imported-{}-{}.md".format(slug[:32].rstrip("-"), candidate["id"][:10])

    @staticmethod
    def _adapter_content(candidate: Dict[str, Any], mounts: List[str], trigger: str) -> str:
        dump = lambda value: json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        return """# 技能: {name}
- 挂载点: {mounts}
- 触发条件: {trigger}
- 作用: 以只读方式使用已发现的外部 Agent Skill
- 外部源标识: {source_id}
- 外部技能入口(JSON): {path}
- 外部技能名称(JSON): {json_name}
- 外部技能描述(JSON): {description}
- 来源产品(JSON): {products}

## 使用

先读取“外部技能入口”指向的入口文件；相对脚本、资源和引用均以该入口所在目录为基准。
不得修改或执行外部技能内容；工作流协议与闸口约束优先。
""".format(
            name=candidate["name"],
            mounts=", ".join(mounts),
            trigger=trigger,
            source_id=candidate["id"],
            path=dump(candidate["path"]),
            json_name=dump(candidate["name"]),
            description=dump(candidate["description"]),
            products=dump(candidate["products"]),
        )

    def _skill_path(self, value: str) -> Path:
        normalized = value.replace("\\", "/")
        parts = normalized.split("/")
        if len(parts) != 2 or parts[0] != "skills" or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*\.md", parts[1]):
            raise ApiError(400, "技能文件路径不合法: " + value)
        path = self._safe_path(self.skills, parts[1])
        if not path.is_file() or self._is_link(path):
            raise ApiError(404, "技能文件不存在: " + value)
        return path

    def _parse_skills(self, content: str) -> Tuple[List[Dict[str, Any]], int, int]:
        lines = content.splitlines(keepends=True)
        headings = [index for index, line in enumerate(lines) if self._line_body(line).strip() == "## 当前挂载表"]
        if len(headings) != 1:
            raise ApiError(409, "config/skills.md 缺少唯一的当前挂载表")
        header = -1
        for index in range(headings[0] + 1, len(lines)):
            cells = split_table_row(self._line_body(lines[index]))
            if cells:
                header = index
                break
        if header < 0 or split_table_row(self._line_body(lines[header])) != ["技能文件", "挂载点", "触发条件", "状态"]:
            raise ApiError(409, "config/skills.md 挂载表表头不符合协议")
        separator = split_table_row(self._line_body(lines[header + 1])) if header + 1 < len(lines) else []
        if len(separator) != 4 or any(not re.fullmatch(r":?-{3,}:?", cell) for cell in separator):
            raise ApiError(409, "config/skills.md 挂载表缺少分隔行")
        start = header + 2
        end = start
        rows = []  # type: List[Dict[str, Any]]
        while end < len(lines):
            cells = split_table_row(self._line_body(lines[end]))
            if not cells:
                break
            if len(cells) != 4:
                raise ApiError(409, "config/skills.md 挂载表存在非四列行")
            skill_file = cells[0].strip("`")
            self._skill_path(skill_file)
            mounts = [item.strip() for item in cells[1].split(",") if item.strip()]
            if not mounts or len(set(mounts)) != len(mounts) or any(item not in STAGES for item in mounts):
                raise ApiError(409, "技能挂载点不合法: " + skill_file)
            trigger = self._clean_setting(cells[2], "技能触发条件", 200, allow_pipe=False)
            if cells[3] not in SKILL_STATES:
                raise ApiError(409, "技能状态不合法: " + skill_file)
            rows.append({"file": skill_file, "mounts": mounts, "trigger": trigger, "state": cells[3]})
            end += 1
        if not rows:
            raise ApiError(409, "config/skills.md 当前挂载表为空")
        files = [row["file"] for row in rows]
        if len(set(files)) != len(files):
            raise ApiError(409, "config/skills.md 存在重复技能")
        return rows, start, end

    @staticmethod
    def _replace_skill_metadata(content: str, mounts: List[str], trigger: str) -> str:
        updates = (("挂载点", ", ".join(mounts)), ("触发条件", trigger))
        updated = content
        for label, value in updates:
            pattern = re.compile(r"^- " + re.escape(label) + r":[^\r\n]*(?=\r?$)", re.MULTILINE)
            if len(pattern.findall(updated)) != 1:
                raise ApiError(409, "技能文件缺少唯一元数据字段: " + label)
            updated = pattern.sub(
                lambda _match, replacement="- {}: {}".format(label, value): replacement,
                updated,
                count=1,
            )
        return updated

    @staticmethod
    def _markdown_sections(content: str) -> Tuple[List[str], List[Tuple[str, int, int]]]:
        lines = content.splitlines(keepends=True)
        headers = []  # type: List[Tuple[str, int]]
        fenced = False
        for index, line in enumerate(lines):
            body = line.rstrip("\r\n")
            if body.lstrip().startswith("```"):
                fenced = not fenced
                continue
            if not fenced and body.startswith("## "):
                headers.append((body[3:].strip(), index))
        sections = []  # type: List[Tuple[str, int, int]]
        for index, (name, start) in enumerate(headers):
            end = headers[index + 1][1] if index + 1 < len(headers) else len(lines)
            sections.append((name, start, end))
        return lines, sections

    @staticmethod
    def _section_fields(lines: List[str]) -> Dict[str, Tuple[int, str]]:
        fields = {}  # type: Dict[str, Tuple[int, str]]
        fenced = False
        for index, line in enumerate(lines):
            body = line.rstrip("\r\n")
            if body.lstrip().startswith("```"):
                fenced = not fenced
                continue
            if fenced:
                continue
            match = re.match(r"^- ([^:]+):\s*(.*)$", body)
            if not match:
                continue
            label = match.group(1).strip()
            if label in fields:
                raise ApiError(409, "项目注册项存在重复字段: " + label)
            fields[label] = (index, match.group(2).strip())
        return fields

    def _project_data(self, name: str, lines: List[str]) -> Optional[Dict[str, Any]]:
        fields = self._section_fields(lines)
        if "路径" not in fields:
            return None
        required = ("规范文件", "验证命令", "分支模型")
        if any(label not in fields for label in required):
            raise ApiError(409, "项目注册项缺少必填字段: " + name)
        command_index, inline = fields["验证命令"]
        commands = []  # type: List[str]
        if inline:
            commands.append(self._unwrap_code(inline))
        else:
            index = command_index + 1
            while index < len(lines):
                match = re.match(r"^\s+\d+\.\s+(.*)$", self._line_body(lines[index]))
                if not match:
                    break
                commands.append(self._unwrap_code(match.group(1).strip()))
                index += 1
        if not commands:
            raise ApiError(409, "项目验证命令为空: " + name)
        return {
            "name": name,
            "path": self._unwrap_code(fields["路径"][1]),
            "specifications": fields["规范文件"][1],
            "commands": commands,
            "branch_model": fields["分支模型"][1],
            "extension": fields.get("流程扩展", (-1, "无"))[1] or "无",
            "integration": fields.get("联测方式", (-1, ""))[1],
        }

    def _parse_projects(self, content: str) -> Tuple[List[Dict[str, Any]], List[str], List[Tuple[str, int, int]]]:
        lines, sections = self._markdown_sections(content)
        projects = []  # type: List[Dict[str, Any]]
        project_sections = []  # type: List[Tuple[str, int, int]]
        for name, start, end in sections:
            data = self._project_data(name, lines[start:end])
            if data:
                projects.append(data)
                project_sections.append((name, start, end))
        names = [project["name"] for project in projects]
        if not projects or len(set(names)) != len(names):
            raise ApiError(409, "config/projects.md 没有项目或存在重复项目")
        return projects, lines, project_sections

    def _project_location(
        self,
        value: Any,
        allow_absolute: bool = False,
        must_exist: bool = True,
    ) -> Tuple[str, Path]:
        path_value = self._clean_setting(value, "项目路径", 1000)
        if "`" in path_value:
            raise ApiError(400, "项目路径不能包含反引号")
        raw = Path(path_value).expanduser()
        if raw.is_absolute():
            if not allow_absolute:
                raise ApiError(400, "项目路径必须是工作区内的相对路径")
            candidate = raw.resolve(strict=False)
            if not self._inside(self.root, candidate):
                raise ApiError(400, "只能导入当前工作区内的项目")
            relative = Path(os.path.relpath(str(candidate), str(self.root)))
            path_value = "./" if str(relative) == "." else relative.as_posix() + "/"
        else:
            relative = raw
            if ".." in relative.parts:
                raise ApiError(400, "项目路径必须是工作区内的相对路径")
        project_path = self._safe_path(self.root, *relative.parts)
        if must_exist and not project_path.is_dir():
            raise ApiError(400, "项目路径必须指向工作区内已存在的目录")
        return path_value, project_path

    def _valid_git_root(self, project_path: Path) -> bool:
        try:
            result = subprocess.run(
                ["git", "-C", str(project_path), "rev-parse", "--show-toplevel"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                encoding="utf-8",
                errors="replace",
                timeout=5,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError:
            marker = project_path / ".git"
            if marker.is_dir():
                return (marker / "HEAD").is_file() and (marker / "objects").is_dir()
            try:
                if not marker.is_file() or marker.stat().st_size > 4096:
                    return False
                match = re.fullmatch(r"gitdir:\s*(.+)\s*", marker.read_text(encoding="utf-8"))
                if not match:
                    return False
                git_dir = Path(match.group(1))
                if not git_dir.is_absolute():
                    git_dir = marker.parent / git_dir
                return (git_dir.resolve(strict=False) / "HEAD").is_file()
            except (OSError, UnicodeDecodeError, ValueError):
                return False
        except subprocess.TimeoutExpired:
            return False
        if result.returncode != 0:
            return False
        top = result.stdout.strip()
        return bool(top) and os.path.normcase(os.path.abspath(top)) == os.path.normcase(
            os.path.abspath(str(project_path))
        )

    def inspect_project(self, value: Any) -> Dict[str, Any]:
        path_value, project_path = self._project_location(value, allow_absolute=True)
        if not self._valid_git_root(project_path):
            raise ApiError(400, "导入目录必须是 Git 仓库根目录")
        name = self._clean_setting(project_path.name, "项目名", 120)
        if name in ("注册项模板", "跨项目需求约定"):
            raise ApiError(400, "项目目录名与配置保留节冲突")
        specifications = [
            filename
            for filename in ("AGENTS.md", "CLAUDE.md", "CONTRIBUTING.md", "README.md")
            if (project_path / filename).is_file() and not self._is_link(project_path / filename)
        ]
        return {
            "name": name,
            "path": path_value,
            "specifications": "、".join(self._code(filename) for filename in specifications) or "无，遵循仓库既有代码风格",
            "commands": ["git diff --check"],
            "branch_model": "",
            "extension": "无",
            "integration": "",
        }

    def _capability_setting(self, content: str) -> Tuple[List[str], Optional[int], str]:
        lines, sections = self._markdown_sections(content)
        current = [(start, end) for name, start, end in sections if name == "当前运行设置"]
        if len(current) > 1:
            raise ApiError(409, "config/capabilities.md 存在重复当前运行设置")
        if not current:
            return lines, None, "自动检测"
        start, end = current[0]
        matches = []  # type: List[Tuple[int, str]]
        fenced = False
        for index in range(start + 1, end):
            body = self._line_body(lines[index])
            if body.lstrip().startswith("```"):
                fenced = not fenced
                continue
            if fenced:
                continue
            match = re.match(r"^- 运行档位偏好:\s*(.*)$", body)
            if match:
                matches.append((index, match.group(1).strip()))
        if len(matches) != 1:
            raise ApiError(409, "config/capabilities.md 当前运行设置缺少唯一运行档位偏好")
        index, mode = matches[0]
        if mode not in CAPABILITY_MODES:
            raise ApiError(409, "运行档位偏好不合法")
        return lines, index, mode

    def _parse_capability_mode(self, content: str) -> str:
        return self._capability_setting(content)[2]

    def settings(self) -> Dict[str, Any]:
        with self._write_lock:
            _, skills_content = self._read_config("skills.md")
            _, projects_content = self._read_config("projects.md")
            _, capabilities_content = self._read_config("capabilities.md")
            skill_rows, skill_catalog, _, _ = self._skills_snapshot(skills_content)
            project_rows, _, _ = self._parse_projects(projects_content)
            return {
                "skills": {
                    "revision": self._revision(skills_content),
                    "rows": skill_rows,
                    "catalog": [{key: value for key, value in item.items() if not key.startswith("_")} for item in skill_catalog],
                    "stages": list(STAGES),
                },
                "projects": {"revision": self._revision(projects_content), "rows": project_rows},
                "capabilities": {
                    "revision": self._revision(capabilities_content),
                    "mode": self._parse_capability_mode(capabilities_content),
                    "modes": list(CAPABILITY_MODES),
                },
            }

    def _prepare_skills(self, content: str, payload: Any) -> Tuple[str, List[Tuple[Path, str, Optional[str]]]]:
        if not isinstance(payload, list):
            raise ApiError(400, "技能设置必须是列表")
        if len(payload) > MAX_SKILLS_PER_ROOT:
            raise ApiError(400, "技能设置超过数量上限")
        current, catalog, start, end = self._skills_snapshot(content)
        current_files = [row["file"] for row in current]
        current_by_file = {row["file"]: row for row in current}
        catalog_by_id = {item["id"]: item for item in catalog}
        normalized = []  # type: List[Dict[str, Any]]
        creates = []  # type: List[Tuple[Path, str, Optional[str]]]
        created_files = set()
        for item in payload:
            if not isinstance(item, dict):
                raise ApiError(400, "技能设置行不合法")
            source_id = self._clean_setting(item.get("source_id"), "技能来源标识", 64, allow_pipe=False)
            if not re.fullmatch(r"[0-9a-f]{64}", source_id):
                raise ApiError(400, "技能来源标识不合法")
            raw_file = item.get("file", "")
            if raw_file is None:
                raw_file = ""
            if not isinstance(raw_file, str):
                raise ApiError(400, "技能文件必须是字符串")
            skill_file = raw_file.strip()
            mounts_value = item.get("mounts")
            if not isinstance(mounts_value, list):
                raise ApiError(400, "技能挂载点必须是列表")
            mounts = [stage for stage in STAGES if stage in mounts_value]
            if not mounts or len(mounts) != len(mounts_value) or len(set(mounts_value)) != len(mounts_value):
                raise ApiError(400, "技能至少挂载一个合法环节")
            trigger = self._clean_setting(item.get("trigger"), "技能触发条件", 200, allow_pipe=False)
            state = item.get("state")
            if state not in SKILL_STATES:
                raise ApiError(400, "技能状态必须是启用或停用")
            if skill_file:
                skill_file = self._clean_setting(skill_file, "技能文件", 200, allow_pipe=False)
                before = current_by_file.get(skill_file)
                if before:
                    if before["source_id"] != source_id:
                        raise ApiError(400, "既有技能文件或来源标识不匹配")
                    candidate = catalog_by_id.get(source_id)
                    if (
                        before["state"] != "启用"
                        and state == "启用"
                        and (
                            not candidate
                            or candidate["status"] in ("失效", "无效")
                        )
                    ):
                        raise ApiError(400, "失效或无效技能不能从停用改为启用")
                else:
                    candidate = catalog_by_id.get(source_id)
                    if (
                        not candidate
                        or candidate.get("_kind") != "native"
                        or candidate.get("file") != skill_file
                        or candidate["orchestrated"]
                        or candidate["status"] in ("失效", "无效")
                    ):
                        raise ApiError(400, "工作区原生技能来源不匹配")
                    if state != "停用":
                        raise ApiError(400, "新加入技能必须先保持停用")
                self._skill_path(skill_file)
            else:
                candidate = catalog_by_id.get(source_id)
                if not candidate or candidate["status"] in ("失效", "无效") or candidate.get("_kind") == "diagnostic":
                    raise ApiError(400, "技能来源不存在、已失效或无效，请重新检测")
                if candidate["orchestrated"]:
                    raise ApiError(400, "技能已加入编排")
                if state != "停用":
                    raise ApiError(400, "新加入技能必须先保持停用")
                existing_file = candidate.get("file", "")
                if existing_file:
                    skill_file = existing_file
                    self._skill_path(skill_file)
                elif candidate.get("_kind") == "external":
                    skill_file = self._adapter_filename(candidate)
                    target = self._safe_path(self.skills, skill_file.split("/", 1)[1])
                    if target.exists():
                        raise ApiError(409, "适配器文件已存在，请重新检测技能")
                    creates.append((target, self._adapter_content(candidate, mounts, trigger), None))
                    created_files.add(skill_file)
                else:
                    raise ApiError(400, "该技能来源不能加入编排")
            normalized.append(
                {"file": skill_file, "source_id": source_id, "mounts": mounts, "trigger": trigger, "state": state}
            )
        files = [row["file"] for row in normalized]
        source_ids = [row["source_id"] for row in normalized]
        if (
            len(set(files)) != len(files)
            or len(set(source_ids)) != len(source_ids)
            or not set(current_files).issubset(set(files))
        ):
            raise ApiError(400, "既有技能不能删除、改名或重复")

        newline = self._newline(content)
        lines = content.splitlines(keepends=True)
        table_lines = [
            "| `{}` | {} | {} | {} |{}".format(row["file"], ", ".join(row["mounts"]), row["trigger"], row["state"], newline)
            for row in normalized
        ]
        lines[start:end] = table_lines
        skill_changes = list(creates)
        for row in normalized:
            before = current_by_file.get(row["file"])
            if row["file"] in created_files or (
                before and row["mounts"] == before["mounts"] and row["trigger"] == before["trigger"]
            ):
                continue
            path = self._skill_path(row["file"])
            original = self._read_preserved(path, row["file"])
            updated = self._replace_skill_metadata(original, row["mounts"], row["trigger"])
            skill_changes.append((path, updated, original))
        return "".join(lines), skill_changes

    def _normalize_project_payload(self, item: Any) -> Dict[str, Any]:
        if not isinstance(item, dict):
            raise ApiError(400, "项目设置行不合法")
        name = self._clean_setting(item.get("name"), "项目名", 120)
        if name in ("注册项模板", "跨项目需求约定"):
            raise ApiError(400, "项目名与配置保留节冲突")
        path_value, project_path = self._project_location(item.get("path"), must_exist=False)
        specifications = self._clean_setting(item.get("specifications"), "规范文件", 5000)
        branch_model = self._clean_setting(item.get("branch_model"), "分支模型", 5000)
        command_values = item.get("commands")
        if not isinstance(command_values, list) or not 1 <= len(command_values) <= 20:
            raise ApiError(400, "验证命令必须为 1～20 条")
        commands = [self._clean_setting(value, "验证命令", 1000) for value in command_values]
        return {
            "name": name,
            "path": path_value,
            "specifications": specifications,
            "commands": commands,
            "branch_model": branch_model,
            "_path_key": os.path.normcase(str(project_path.resolve())),
        }

    def _update_project_section(self, section_lines: List[str], item: Dict[str, Any]) -> List[str]:
        fields = self._section_fields(section_lines)
        newline = self._newline("".join(section_lines))
        replacements = {
            "路径": self._code(item["path"]),
            "规范文件": item["specifications"],
            "分支模型": item["branch_model"],
        }
        for label, value in replacements.items():
            index = fields[label][0]
            ending = section_lines[index][len(self._line_body(section_lines[index])) :]
            section_lines[index] = "- {}: {}{}".format(label, value, ending or newline)
        fields = self._section_fields(section_lines)
        command_index = fields["验证命令"][0]
        block_end = command_index + 1
        while block_end < len(section_lines) and re.match(r"^\s+\d+\.\s+", self._line_body(section_lines[block_end])):
            block_end += 1
        ending = section_lines[command_index][len(self._line_body(section_lines[command_index])) :] or newline
        command_lines = ["- 验证命令:" + ending]
        command_lines.extend("  {}. {}{}".format(index + 1, self._code(command), newline) for index, command in enumerate(item["commands"]))
        section_lines[command_index:block_end] = command_lines
        return section_lines

    def _new_project_section(self, item: Dict[str, Any], newline: str) -> List[str]:
        lines = [
            "## " + item["name"] + newline,
            newline,
            "- 路径: " + self._code(item["path"]) + newline,
            "- 技术栈: 待补充" + newline,
            "- 判定信号: 涉及 " + item["name"] + " 的需求" + newline,
            "- 规范文件: " + item["specifications"] + newline,
            "- 验证命令:" + newline,
        ]
        lines.extend(
            "  {}. {}{}".format(index + 1, self._code(command), newline)
            for index, command in enumerate(item["commands"])
        )
        lines.extend(
            [
                "- 分支模型: " + item["branch_model"] + newline,
                "- 远端: 未配置；S5 降级为本地 patch + MR/PR 描述文本" + newline,
                "- 流程扩展: 无" + newline,
                "- 过程产物入库: 禁止" + newline,
                newline,
            ]
        )
        return lines

    def _prepare_projects(self, content: str, payload: Any) -> str:
        if not isinstance(payload, list) or not 1 <= len(payload) <= MAX_PROJECTS:
            raise ApiError(400, "项目设置必须包含 1～{} 个项目".format(MAX_PROJECTS))
        current, lines, sections = self._parse_projects(content)
        normalized = [self._normalize_project_payload(item) for item in payload]
        current_names = [project["name"] for project in current]
        names = [project["name"] for project in normalized]
        if len(set(names)) != len(names) or not set(current_names).issubset(set(names)):
            raise ApiError(400, "既有项目不能删除、改名或重复")
        path_keys = [project["_path_key"] for project in normalized]
        if len(set(path_keys)) != len(path_keys):
            raise ApiError(400, "项目路径不能重复注册")
        submitted = {project["name"]: project for project in normalized}
        current_by_name = {project["name"]: project for project in current}
        changed_paths = [
            Path(item["_path_key"])
            for item in normalized
            if item["name"] not in current_by_name
            or item["path"] != current_by_name[item["name"]]["path"]
        ]
        if any(not path.is_dir() or not self._valid_git_root(path) for path in changed_paths):
            raise ApiError(400, "新增或修改的项目路径必须是 Git 仓库根目录")
        for name, item in submitted.items():
            if name not in current_by_name:
                continue
            existing = current_by_name[name]
            if "dual-baseline-test" in existing["extension"]:
                required = ("origin/master", "origin/dev", "feature/<需求id>", "test/<需求id>")
                if any(value not in item["branch_model"] for value in required) or not existing["integration"]:
                    raise ApiError(400, "项目 {} 的双基线分支契约或联测方式不完整".format(name))
        additions = [item for item in normalized if item["name"] not in current_by_name]
        if additions:
            newline = self._newline(content)
            insert_at = sections[-1][2]
            inserted = []  # type: List[str]
            if insert_at and not lines[insert_at - 1].endswith(("\r", "\n")):
                lines[insert_at - 1] += newline
            if insert_at and self._line_body(lines[insert_at - 1]).strip():
                inserted.append(newline)
            for item in additions:
                inserted.extend(self._new_project_section(item, newline))
            lines[insert_at:insert_at] = inserted
        for name, start, end in reversed(sections):
            item = submitted[name]
            existing = current_by_name[name]
            changed = any(
                item[key] != existing[key]
                for key in ("path", "specifications", "commands", "branch_model")
            )
            if changed:
                lines[start:end] = self._update_project_section(lines[start:end], item)
        prepared = "".join(lines)
        if len(prepared.encode("utf-8")) > MAX_FILE:
            raise ApiError(413, "项目配置超过大小上限")
        reparsed, _, _ = self._parse_projects(prepared)
        if {project["name"] for project in reparsed} != set(names):
            raise ApiError(500, "项目配置生成后校验失败")
        return prepared

    def _prepare_capabilities(self, content: str, mode: Any) -> str:
        if mode not in CAPABILITY_MODES:
            raise ApiError(400, "运行档位偏好不合法")
        lines, setting_index, _ = self._capability_setting(content)
        if setting_index is not None:
            ending = lines[setting_index][len(self._line_body(lines[setting_index])) :]
            lines[setting_index] = "- 运行档位偏好: " + mode + ending
            return "".join(lines)
        _, sections = self._markdown_sections(content)
        indexes = [start for name, start, _ in sections if name == "能力自检清单"]
        if len(indexes) != 1:
            raise ApiError(409, "config/capabilities.md 缺少唯一能力自检清单")
        newline = self._newline(content)
        section = [
            "## 当前运行设置" + newline,
            newline,
            "- 运行档位偏好: " + mode + newline,
            newline,
            "> 该偏好只能要求代理主动降级；实际能力不足时仍按更低档位运行。" + newline,
            newline,
        ]
        lines[indexes[0] : indexes[0]] = section
        return "".join(lines)

    def save_settings(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            raise ApiError(400, "设置内容必须是对象")
        with self._write_lock:
            skills_path, skills_content = self._read_config("skills.md")
            projects_path, projects_content = self._read_config("projects.md")
            capabilities_path, capabilities_content = self._read_config("capabilities.md")
            sections = (("skills", skills_content), ("projects", projects_content), ("capabilities", capabilities_content))
            for key, current in sections:
                value = payload.get(key)
                if not isinstance(value, dict) or value.get("revision") != self._revision(current):
                    raise ApiError(409, "配置已被其他程序修改，请重新打开设置")
            updated_skills, skill_changes = self._prepare_skills(skills_content, payload["skills"].get("rows"))
            updated_projects = self._prepare_projects(projects_content, payload["projects"].get("rows"))
            updated_capabilities = self._prepare_capabilities(capabilities_content, payload["capabilities"].get("mode"))
            changes = skill_changes + [
                (skills_path, updated_skills, skills_content),
                (projects_path, updated_projects, projects_content),
                (capabilities_path, updated_capabilities, capabilities_content),
            ]
            self._atomic_write_many(changes)
        self._log("save_settings", "-", "技能/项目/能力设置已更新")
        return self.settings()

    def parse_state(self, content: str) -> Dict[str, Any]:
        top = {}  # type: Dict[str, str]
        for label, key in TOP_FIELDS.items():
            match = re.search(r"^- " + re.escape(label) + r":\s*(.*)$", content, re.MULTILINE)
            if match:
                top[key] = match.group(1).strip()

        lines = content.splitlines()
        header_index = -1
        headers = []  # type: List[str]
        for index, line in enumerate(lines):
            cells = split_table_row(line)
            if "项目" in cells and "行状态" in cells:
                header_index = index
                headers = cells
                break

        projects = []  # type: List[Dict[str, str]]
        if header_index >= 0:
            for line in lines[header_index + 2 :]:
                if not line.strip().startswith("|"):
                    break
                cells = split_table_row(line)
                if len(cells) != len(headers):
                    continue
                raw = dict(zip(headers, cells))
                projects.append({key: raw.get(label, "") for label, key in PROJECT_FIELDS.items()})

        return {"top": top, "projects": projects}

    def _state_path(self, task_id: str) -> Path:
        validate_id(task_id)
        return self._safe_path(self.work, task_id, "state.md")

    def _artifact_path(self, task_id: str, name: str) -> Path:
        validate_id(task_id)
        if name not in ARTIFACT_NAMES:
            raise ApiError(400, "不允许读取该产物")
        if name == "prd":
            return self._safe_path(self.prds, task_id + ".md")
        return self._safe_path(self.work, task_id, name)

    def _task_snapshot(self, task_id: str) -> Dict[str, Any]:
        contents = {"prd": "", "state": ""}
        paths = {}  # type: Dict[str, Path]
        errors = []
        mtimes = []
        stamps = []
        for key, artifact in (("prd", "prd"), ("state", "state.md")):
            path = None  # type: Optional[Path]
            try:
                path = self._artifact_path(task_id, artifact)
                paths[key] = path
                contents[key] = self._read_text(path, required=False)
                if path.exists():
                    info = path.stat()
                    mtimes.append(info.st_mtime)
            except (ApiError, OSError, ValueError, RecursionError) as error:
                errors.append(key)
                code = error.status if isinstance(error, ApiError) else type(error).__name__
                try:
                    info = path.lstat() if path is not None else None
                    stamps.append(
                        "{}:error:{}:{}:{}".format(
                            key,
                            code,
                            info.st_size if info else 0,
                            getattr(info, "st_mtime_ns", 0) if info else 0,
                        )
                    )
                except OSError:
                    stamps.append("{}:error:{}".format(key, code))
        state = (
            self.parse_state(contents["state"])
            if contents["state"]
            else {"top": {}, "projects": []}
        )
        if errors:
            state["top"] = dict(state["top"])
            state["top"]["phase"] = "异常"
            state["top"]["status"] = "读取失败"
        return {
            "contents": contents,
            "paths": paths,
            "errors": errors,
            "state": state,
            "mtimes": mtimes,
            "stamps": stamps,
        }

    def list_tasks(self) -> List[Dict[str, Any]]:
        ids = set()
        for path in self.prds.glob("*.md"):
            if path.name != "TEMPLATE.md":
                try:
                    ids.add(validate_id(path.stem))
                except ApiError:
                    continue
        for path in self.work.iterdir():
            if path.is_dir():
                try:
                    ids.add(validate_id(path.name))
                except ApiError:
                    continue

        tasks = []
        for task_id in ids:
            snapshot = self._task_snapshot(task_id)
            prd = snapshot["contents"]["prd"]
            state_content = snapshot["contents"]["state"]
            state = snapshot["state"]
            mtimes = snapshot["mtimes"]
            tasks.append(
                {
                    "id": task_id,
                    "title": first_heading(prd, task_id),
                    "phase": state["top"].get("phase", "未开始"),
                    "status": state["top"].get("status", "仅有 PRD"),
                    "project_count": len(state["projects"]),
                    "revision": self._revision(
                        prd + "\0" + state_content + "\0" + "|".join(snapshot["stamps"])
                    ),
                    "updated_at": datetime.fromtimestamp(max(mtimes)).astimezone().isoformat(timespec="seconds") if mtimes else "",
                }
            )
        return sorted(tasks, key=lambda item: (item["updated_at"], item["id"]), reverse=True)

    def task_detail(self, task_id: str) -> Dict[str, Any]:
        task_id = validate_id(task_id)
        snapshot = self._task_snapshot(task_id)
        prd = snapshot["contents"]["prd"]
        state_content = snapshot["contents"]["state"]
        state = snapshot["state"]

        actions = []  # type: List[Dict[str, Any]]
        if state_content and not snapshot["errors"]:
            if state["top"].get("phase") == "S1" and state["top"].get("status") == "等待闸口" and state["top"].get("gate_a", "").startswith("等待中"):
                actions.append({"gate": "A", "label": "答复闸口 A"})
            if state["top"].get("phase") == "S2" and state["top"].get("status") == "等待闸口" and state["top"].get("gate_b", "").startswith("等待中"):
                actions.append({"gate": "B", "label": "批准方案"})
            for project in state["projects"]:
                if project.get("phase") == "S5" and project.get("row_status") == "等待闸口C" and project.get("gate_c") == "等待中":
                    actions.append(
                        {
                            "gate": "C",
                            "label": "确认闸口 C",
                            "project": project.get("project", ""),
                            "results": (
                                ["已验收(无MR)"]
                                if project.get("merge_request") == "补丁+文件清单"
                                else ["已合并"]
                            ),
                        }
                    )

        artifacts = []
        for name, label in ARTIFACTS:
            try:
                path = self._artifact_path(task_id, name)
                key = "prd" if name == "prd" else "state" if name == "state.md" else ""
                artifacts.append(
                    {
                        "name": name,
                        "label": label,
                        "exists": path.is_file(),
                        "readable": not key or key not in snapshot["errors"],
                    }
                )
            except (ApiError, OSError, ValueError):
                artifacts.append({"name": name, "label": label, "exists": False, "readable": False})

        return {
            "id": task_id,
            "title": first_heading(prd, task_id),
            "top": state["top"],
            "projects": state["projects"],
            "artifacts": artifacts,
            "actions": actions,
            "diagnostic": "、".join(snapshot["errors"]) + " 读取失败" if snapshot["errors"] else "",
            "run_prompt": "读 AGENTS.md，执行需求 {}；先运行 python workflow/workflowctl.py context {}，只加载当前阶段文件。".format(task_id, task_id),
        }

    def read_artifact(self, task_id: str, name: str) -> Dict[str, str]:
        path = self._artifact_path(task_id, name)
        label = dict(ARTIFACTS)[name]
        return {"name": name, "label": label, "content": self._read_text(path)}

    @staticmethod
    def _clean_field(value: Any, label: str, required: bool = False, limit: int = 20000) -> str:
        if value is None:
            value = ""
        if not isinstance(value, str):
            raise ApiError(400, label + "必须是字符串")
        cleaned = value.strip()
        if required and not cleaned:
            raise ApiError(400, label + "不能为空")
        if len(cleaned) > limit:
            raise ApiError(413, label + "过长")
        return cleaned

    @staticmethod
    def _markdown_list(value: str, numbered: bool) -> str:
        items = []
        for line in value.splitlines():
            item = re.sub(r"^(?:[-*]\s+|\d+[.)]\s*)", "", line.strip())
            if item:
                items.append(item)
        if not items:
            return ""
        if numbered:
            return "\n".join("{}. {}".format(index, item) for index, item in enumerate(items, 1))
        return "\n".join("- " + item for item in items)

    def create_prd(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        task_id = validate_id(payload.get("id"))
        title = self._clean_field(payload.get("title"), "标题", required=True, limit=120)
        if "\n" in title or "\r" in title:
            raise ApiError(400, "标题必须是单行")
        background = self._clean_field(payload.get("background"), "背景") or "待补充"
        description = self._clean_field(payload.get("description"), "功能描述", required=True)
        acceptance_raw = self._clean_field(payload.get("acceptance"), "验收标准", required=True)
        acceptance = self._markdown_list(acceptance_raw, numbered=True)
        if not acceptance:
            raise ApiError(400, "至少需要一条验收标准")
        out_of_scope = self._markdown_list(self._clean_field(payload.get("out_of_scope"), "范围外"), numbered=False) or "- 待补充"
        content = (
            "# {title}\n\n"
            "## 背景\n\n{background}\n\n"
            "## 功能描述\n\n{description}\n\n"
            "## 验收标准\n\n{acceptance}\n\n"
            "## 范围外\n\n{out_of_scope}\n"
        ).format(
            title=title,
            background=background,
            description=description,
            acceptance=acceptance,
            out_of_scope=out_of_scope,
        )
        path = self._artifact_path(task_id, "prd")
        with self._write_lock:
            try:
                descriptor = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                raise ApiError(409, "同名 PRD 已存在，不会覆盖")
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                    handle.write(content)
                    handle.flush()
                    os.fsync(handle.fileno())
            except Exception:
                if path.exists():
                    path.unlink()
                raise
        self._log("create_prd", task_id, "创建 " + path.name)
        return self.task_detail(task_id)

    @staticmethod
    def _quote(value: Any) -> Tuple[str, str]:
        if not isinstance(value, str) or not value.strip():
            raise ApiError(400, "人工原话不能为空")
        original = value.strip()
        if len(original) > 4000:
            raise ApiError(413, "人工原话过长")
        one_line = " ".join(original.splitlines()).replace('"', "'")
        return original, one_line

    def _gate_record_change(
        self, path: Path, heading: str, lines: List[str]
    ) -> Tuple[Path, str, Optional[str]]:
        original = self._read_preserved(path, str(path)) if path.is_file() else None
        current = (original or "").rstrip()
        section = "## {}\n\n{}\n".format(heading, "\n".join(lines))
        updated = (current + "\n\n" if current else "") + section
        return path, updated, original

    def _update_project_gate(self, content: str, project_name: str, result: str) -> str:
        lines = content.splitlines()
        header_index = -1
        headers = []  # type: List[str]
        for index, line in enumerate(lines):
            cells = split_table_row(line)
            if "项目" in cells and "阶段" in cells and "MR/PR" in cells and "闸口C" in cells and "行状态" in cells:
                header_index = index
                headers = cells
                break
        if header_index < 0:
            raise ApiError(409, "state.md 缺少项目状态表")
        project_index = headers.index("项目")
        phase_index = headers.index("阶段")
        merge_index = headers.index("MR/PR")
        gate_index = headers.index("闸口C")
        status_index = headers.index("行状态")
        found = False
        for index in range(header_index + 2, len(lines)):
            if not lines[index].strip().startswith("|"):
                break
            cells = split_table_row(lines[index])
            if len(cells) != len(headers) or cells[project_index] != project_name:
                continue
            found = True
            if cells[phase_index] != "S5" or cells[status_index] != "等待闸口C" or cells[gate_index] != "等待中":
                raise ApiError(409, "项目当前不在闸口 C 等待状态")
            expected = "已验收(无MR)" if cells[merge_index] == "补丁+文件清单" else "已合并"
            if result != expected:
                raise ApiError(400, "闸口 C 结果与 MR/PR 交付方式不匹配")
            cells[gate_index] = result
            lines[index] = "| " + " | ".join(cells) + " |"
            break
        if not found:
            raise ApiError(404, "state.md 中不存在该项目")
        complete = ("已合并", "已验收(无MR)")
        project_rows = []
        for index in range(header_index + 2, len(lines)):
            if not lines[index].strip().startswith("|"):
                break
            cells = split_table_row(lines[index])
            if len(cells) == len(headers):
                project_rows.append((index, cells))
        all_complete = project_rows and all(cells[gate_index] in complete for _, cells in project_rows)
        if all_complete:
            for index, cells in project_rows:
                cells[phase_index] = "S6"
                cells[status_index] = "进行中"
                lines[index] = "| " + " | ".join(cells) + " |"
        updated = "\n".join(lines) + ("\n" if content.endswith("\n") else "")
        if all_complete:
            updated = replace_bullet(replace_bullet(updated, "环节", "S6"), "状态", "进行中")
        return updated

    def approve_gate(self, task_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        task_id = validate_id(task_id)
        gate = str(payload.get("gate", "")).upper()
        if gate not in GATES:
            raise ApiError(400, "闸口只能是 A、B 或 C")
        original, one_line = self._quote(payload.get("quote"))
        today = date.today().isoformat()
        state_path = self._state_path(task_id)

        with self._write_lock:
            state_content = self._read_preserved(state_path, "state.md")
            state_original = state_content
            parsed = self.parse_state(state_content)
            changes = []  # type: List[Tuple[Path, str, Optional[str]]]
            if gate == "A":
                if parsed["top"].get("phase") != "S1" or parsed["top"].get("status") != "等待闸口" or not parsed["top"].get("gate_a", "").startswith("等待中"):
                    raise ApiError(409, "当前不在闸口 A 等待状态")
                questions = self._safe_path(self.work, task_id, "questions.md")
                quote_lines = ["> " + line for line in original.splitlines()]
                changes.append(self._gate_record_change(questions, "闸口A答复 " + today, quote_lines))
                state_content = replace_bullet(state_content, "闸口A", "已通过 {}(答复见 questions.md)".format(today))
                detail = "闸口 A 已答复"
            elif gate == "B":
                if parsed["top"].get("phase") != "S2" or parsed["top"].get("status") != "等待闸口" or not parsed["top"].get("gate_b", "").startswith("等待中"):
                    raise ApiError(409, "当前不在闸口 B 等待状态")
                state_content = replace_bullet(state_content, "闸口B", '已通过 {}("{}")'.format(today, one_line))
                detail = "闸口 B 已批准"
            else:
                project = self._clean_field(payload.get("project"), "项目", required=True, limit=120)
                result = payload.get("result")
                if result not in ("已合并", "已验收(无MR)"):
                    raise ApiError(400, "闸口 C 结果不合法")
                state_content = self._update_project_gate(state_content, project, result)
                delivery = self._safe_path(self.work, task_id, "delivery.md")
                changes.append(
                    self._gate_record_change(
                        delivery,
                        "闸口C确认 " + today,
                        ["- 项目: " + project, "- 结果: " + result, "- 原话: " + one_line],
                    )
                )
                detail = "{}: {}".format(project, result)
            changes.append((state_path, state_content, state_original))
            self._atomic_write_many(changes)

        self._log("approve_gate_" + gate.lower(), task_id, detail)
        return self.task_detail(task_id)

    def git_status(self) -> Dict[str, Any]:
        try:
            result = subprocess.run(
                ["git", "-C", str(self.root), "status", "--short", "--branch"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                encoding="utf-8",
                errors="replace",
                timeout=5,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            return {"available": False, "output": str(error)}
        output = (result.stdout + result.stderr).strip()
        return {"available": result.returncode == 0, "output": output, "returncode": result.returncode}


def build_handler(app: WorkflowWorkspace, index_html: str):
    class Handler(BaseHTTPRequestHandler):
        server_version = "WorkflowGUI/1.0"

        def _security_headers(self) -> None:
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
            self.send_header("Cross-Origin-Resource-Policy", "same-origin")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self._security_headers()
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, payload: Any) -> None:
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self._send(status, body, "application/json; charset=utf-8")

        def _check_host(self) -> None:
            host = self.headers.get("Host", "").split(":", 1)[0].lower()
            if host not in ("127.0.0.1", "localhost"):
                raise ApiError(403, "仅允许本机 Host")

        def _read_json(self) -> Dict[str, Any]:
            self._check_host()
            if self.headers.get("X-Requested-With") != "workflow-gui":
                raise ApiError(403, "缺少同源请求标记")
            origin = self.headers.get("Origin")
            if origin:
                allowed = {
                    "http://127.0.0.1:{}".format(self.server.server_port),
                    "http://localhost:{}".format(self.server.server_port),
                }
                if origin not in allowed:
                    raise ApiError(403, "拒绝跨来源写入")
            if not self.headers.get("Content-Type", "").lower().startswith("application/json"):
                raise ApiError(415, "只接受 application/json")
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                raise ApiError(400, "Content-Length 不合法")
            if length <= 0 or length > MAX_BODY:
                raise ApiError(413, "请求体为空或过大")
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError):
                raise ApiError(400, "JSON 请求体不合法")
            if not isinstance(payload, dict):
                raise ApiError(400, "JSON 顶层必须是对象")
            return payload

        @staticmethod
        def _parts(path: str) -> List[str]:
            return [unquote(part) for part in urlparse(path).path.strip("/").split("/") if part]

        def do_GET(self) -> None:
            try:
                self._check_host()
                parts = self._parts(self.path)
                if not parts:
                    self._send(200, index_html.encode("utf-8"), "text/html; charset=utf-8")
                elif parts == ["api", "health"]:
                    self._json(200, {"ok": True, "workspace": str(app.root)})
                elif parts == ["api", "tasks"]:
                    self._json(200, {"tasks": app.list_tasks()})
                elif parts == ["api", "git"]:
                    self._json(200, app.git_status())
                elif parts == ["api", "logs"]:
                    self._json(200, {"logs": app.logs()})
                elif len(parts) == 3 and parts[:2] == ["api", "tasks"]:
                    self._json(200, app.task_detail(parts[2]))
                elif len(parts) == 5 and parts[:2] == ["api", "tasks"] and parts[3] == "artifacts":
                    self._json(200, app.read_artifact(parts[2], parts[4]))
                else:
                    raise ApiError(404, "接口不存在")
            except ApiError as error:
                self._json(error.status, {"error": error.message})
            except Exception as error:  # pragma: no cover - final HTTP safety net
                console("GET error: " + repr(error), error=True)
                self._json(500, {"error": "服务器内部错误"})

        def do_POST(self) -> None:
            try:
                parts = self._parts(self.path)
                payload = self._read_json()
                if parts == ["api", "tasks"]:
                    self._json(201, app.create_prd(payload))
                elif len(parts) == 4 and parts[:2] == ["api", "tasks"] and parts[3] == "gates":
                    self._json(200, app.approve_gate(parts[2], payload))
                else:
                    raise ApiError(404, "接口不存在")
            except ApiError as error:
                self._json(error.status, {"error": error.message})
            except Exception as error:  # pragma: no cover - final HTTP safety net
                console("POST error: " + repr(error), error=True)
                self._json(500, {"error": "服务器内部错误"})

        def log_message(self, message: str, *args: Any) -> None:
            console("[{}] {}".format(self.log_date_time_string(), message % args), error=True)

    return Handler


def expect_api_error(status: int, action) -> None:
    try:
        action()
    except ApiError as error:
        assert error.status == status, (error.status, error.message)
    else:
        raise AssertionError("expected ApiError {}".format(status))


def run_self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="workflow-gui-test-") as temp:
        root = Path(temp)
        (root / "AGENTS.md").write_text("# test\n", encoding="utf-8")
        (root / "prds").mkdir()
        (root / "work").mkdir()
        environment_names = ("COPILOT_HOME", "GEMINI_CLI_HOME", "PROGRAMDATA", "COPILOT_SKILLS_DIRS")
        previous_environment = {name: os.environ.get(name) for name in environment_names}
        try:
            os.environ["COPILOT_HOME"] = "relative-copilot"
            os.environ["GEMINI_CLI_HOME"] = "relative-gemini"
            os.environ["PROGRAMDATA"] = "relative-program-data"
            os.environ["COPILOT_SKILLS_DIRS"] = "relative-extra," + str(root / "absolute-extra")
            guarded = WorkflowWorkspace(root)
            assert guarded.copilot_home == guarded.home / ".copilot"
            assert guarded.gemini_home == guarded.home
            assert guarded.program_data is None
            assert guarded.copilot_extra_roots == [root / "absolute-extra"]
        finally:
            for name, value in previous_environment.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value
        main_workspace = root / "default-main"
        worktree_workspace = root / "default-main-worktrees" / "demo"
        for workspace in (main_workspace, worktree_workspace):
            workspace.mkdir(parents=True)
            (workspace / "AGENTS.md").write_text("# test\n", encoding="utf-8")
            (workspace / "prds").mkdir()
        frozen_before = getattr(sys, "frozen", None)
        executable_before = sys.executable
        try:
            sys.frozen = True
            sys.executable = str(worktree_workspace / "dist" / "WorkflowDesk.exe")
            assert default_workspace() == main_workspace.resolve()
            (main_workspace / "AGENTS.md").unlink()
            assert default_workspace() == worktree_workspace.resolve()
        finally:
            sys.executable = executable_before
            if frozen_before is None:
                delattr(sys, "frozen")
            else:
                sys.frozen = frozen_before
        app = WorkflowWorkspace(root)
        app.home = root
        app.copilot_home = root / ".copilot"
        app.gemini_home = root
        app.copilot_extra_roots = []
        app.program_data = root / "ProgramData"
        expect_api_error(400, lambda: app._safe_path(root.parent / "outside-config", "skills.md"))
        cleanup_target = root / "atomic-create-cleanup.md"
        original_unlink = os.unlink
        leaked_temps = []

        def fail_temp_cleanup(path: str) -> None:
            leaked_temps.append(path)
            raise PermissionError("injected temp cleanup failure")

        os.unlink = fail_temp_cleanup
        try:
            app._atomic_create(cleanup_target, "committed\n")
        finally:
            os.unlink = original_unlink
        assert cleanup_target.read_text(encoding="utf-8") == "committed\n"
        for leaked_temp in leaked_temps:
            if os.path.exists(leaked_temp):
                original_unlink(leaked_temp)
        cleanup_target.unlink()

        assert validate_id("demo-1") == "demo-1"
        for invalid in ("foo.lock", "CON", "aux.txt", "a..b", "trail-", "has space", " demo", "demo ", "a/b", "a" * 65):
            expect_api_error(400, lambda value=invalid: validate_id(value))
        metadata = "- 挂载点: S1\n- 触发条件: old\n"
        replaced_metadata = app._replace_skill_metadata(metadata, ["S2"], r"path\new\g<1>")
        assert "- 挂载点: S2\n" in replaced_metadata
        assert r"- 触发条件: path\new\g<1>" in replaced_metadata
        replaced_bullet = replace_bullet("- 状态: old\n", "状态", r"ok\new\g<1>")
        assert replaced_bullet == "- 状态: " + r"ok\new\g<1>" + "\n"

        app.create_prd(
            {
                "id": "demo-1",
                "title": "GUI 自测",
                "background": "测试背景",
                "description": "测试功能",
                "acceptance": "可创建 PRD\n不覆盖已有文件",
                "out_of_scope": "无",
            }
        )
        expect_api_error(409, lambda: app.create_prd({"id": "demo-1", "title": "重复", "description": "x", "acceptance": "x"}))

        task_work = root / "work" / "demo-1"
        task_work.mkdir()
        state = """# state: demo-1

- 环节: S1
- 状态: 等待闸口
- 闸口A: 等待中
- 闸口B: 等待中
- NOT_RUN 确认: 无

## 项目状态表

| 项目 | 工作目录 | 分支 | 联测分支 | 联测状态 | 阶段 | 回修轮次 | MR/PR | 闸口C | 行状态 |
|------|----------|------|----------|----------|------|----------|-------|-------|--------|
| demo-project | /demo | feature/demo-1 | - | - | S5 | 0 | !1 | 等待中 | 等待闸口C |
"""
        (task_work / "state.md").write_text(state, encoding="utf-8")
        parsed = app.parse_state(state)
        assert parsed["top"]["phase"] == "S1"
        assert parsed["projects"][0]["project"] == "demo-project"
        task_before_touch = app.list_tasks()
        assert len(task_before_touch) == 1
        os.utime(str(task_work / "state.md"), None)
        assert app.list_tasks()[0]["revision"] == task_before_touch[0]["revision"]
        unreadable_work = root / "work" / "unreadable"
        unreadable_work.mkdir()
        (unreadable_work / "state.md").write_bytes(b"\xff\xfe")
        task_rows = app.list_tasks()
        assert next(item for item in task_rows if item["id"] == "demo-1")["status"] == "等待闸口"
        unreadable_row = next(item for item in task_rows if item["id"] == "unreadable")
        assert unreadable_row["phase"] == "异常" and unreadable_row["status"] == "读取失败"
        unreadable_detail = app.task_detail("unreadable")
        assert unreadable_detail["diagnostic"] == "state 读取失败"
        assert not next(
            item for item in unreadable_detail["artifacts"] if item["name"] == "state.md"
        )["readable"]
        assert app.read_artifact("demo-1", "prd")["content"].startswith("# GUI 自测")
        assert "workflowctl.py context demo-1" in app.task_detail("demo-1")["run_prompt"]
        expect_api_error(400, lambda: app.read_artifact("demo-1", "../AGENTS.md"))

        gate_state_before = (task_work / "state.md").read_bytes()
        original_gate_atomic_write = app._atomic_write

        def fail_gate_state(path: Path, content: str) -> None:
            if path == task_work / "state.md":
                raise OSError("injected gate state failure")
            original_gate_atomic_write(path, content)

        app._atomic_write = fail_gate_state
        try:
            try:
                app.approve_gate("demo-1", {"gate": "A", "quote": "不应留下半条记录"})
            except OSError:
                pass
            else:
                raise AssertionError("expected injected gate failure")
        finally:
            app._atomic_write = original_gate_atomic_write
        assert (task_work / "state.md").read_bytes() == gate_state_before
        assert not (task_work / "questions.md").exists()

        app.approve_gate("demo-1", {"gate": "A", "quote": "选择方案一"})
        expect_api_error(409, lambda: app.approve_gate("demo-1", {"gate": "B", "quote": "错误阶段"}))
        after_a = (task_work / "state.md").read_text(encoding="utf-8")
        app._atomic_write(task_work / "state.md", replace_bullet(after_a, "环节", "S2"))
        app.approve_gate("demo-1", {"gate": "B", "quote": "同意方案"})
        after_b = (task_work / "state.md").read_text(encoding="utf-8")
        app._atomic_write(task_work / "state.md", replace_bullet(after_b, "环节", "S5"))
        gate_c_state_before = (task_work / "state.md").read_bytes()
        app._atomic_write = fail_gate_state
        try:
            try:
                app.approve_gate(
                    "demo-1",
                    {"gate": "C", "project": "demo-project", "result": "已合并", "quote": "不应留下半条记录"},
                )
            except OSError:
                pass
            else:
                raise AssertionError("expected injected gate C failure")
        finally:
            app._atomic_write = original_gate_atomic_write
        assert (task_work / "state.md").read_bytes() == gate_c_state_before
        assert not (task_work / "delivery.md").exists()
        detail = app.approve_gate(
            "demo-1",
            {"gate": "C", "project": "demo-project", "result": "已合并", "quote": "已合并，可以归档"},
        )
        assert detail["top"]["gate_a"].startswith("已通过")
        assert detail["top"]["gate_b"].startswith("已通过")
        assert detail["top"]["phase"] == "S6" and detail["top"]["status"] == "进行中"
        assert detail["projects"][0]["gate_c"] == "已合并"
        assert detail["projects"][0]["phase"] == "S6" and detail["projects"][0]["row_status"] == "进行中"
        assert "选择方案一" in (task_work / "questions.md").read_text(encoding="utf-8")
        assert "已合并，可以归档" in (task_work / "delivery.md").read_text(encoding="utf-8")
        expect_api_error(409, lambda: app.approve_gate("demo-1", {"gate": "C", "project": "demo-project", "result": "已合并", "quote": "重复"}))
        patch_state = state.replace("| !1 |", "| 补丁+文件清单 |")
        expect_api_error(400, lambda: app._update_project_gate(patch_state, "demo-project", "已合并"))
        patch_state = app._update_project_gate(patch_state, "demo-project", "已验收(无MR)")
        assert app.parse_state(patch_state)["top"]["phase"] == "S6"
        multi_state = replace_bullet(state, "环节", "S5") + (
            "| patch-project | /patch | feature/patch | - | - | S5 | 0 | 补丁+文件清单 | 等待中 | 等待闸口C |\n"
        )
        multi_state = app._update_project_gate(multi_state, "demo-project", "已合并")
        assert app.parse_state(multi_state)["top"]["phase"] == "S5"
        multi_state = app._update_project_gate(multi_state, "patch-project", "已验收(无MR)")
        assert all(project["phase"] == "S6" for project in app.parse_state(multi_state)["projects"])
        expect_api_error(
            409,
            lambda: app._update_project_gate(
                state.replace("| MR/PR ", "| 交付方式 "),
                "demo-project",
                "已合并",
            ),
        )
        assert len(app.logs()) == 4

        (root / "config").mkdir()
        (root / "skills").mkdir()
        skills_config = """# skills

## 当前挂载表

| 技能文件 | 挂载点 | 触发条件 | 状态 |
|----------|--------|----------|------|
| `skills/skill-a.md` | S2 | 总是 | 启用 |
| `skills/skill-b.md` | S3 | 涉及接口 | 停用 |

<!-- skills-sentinel -->
""".replace("\n", "\r\n")
        (root / "config" / "skills.md").write_bytes(skills_config.encode("utf-8"))
        (root / "skills" / "skill-a.md").write_bytes("# 技能: A\r\n- 挂载点: S2\r\n- 触发条件: 总是\r\n- 作用: A\r\n".encode("utf-8"))
        (root / "skills" / "skill-b.md").write_text("# 技能: B\n- 挂载点: S3\n- 触发条件: 涉及接口\n- 作用: B\n", encoding="utf-8")
        (root / "skills" / "skill-c.md").write_text("# 技能: C\n- 挂载点: S1\n- 触发条件: 总是\n- 作用: C\n", encoding="utf-8")
        (root / "skills" / "imported-bad.md").write_text(
            "# 技能: bad\n"
            "- 挂载点: S1\n"
            "- 触发条件: 总是\n"
            "- 作用: bad\n"
            "- 外部源标识: " + "f" * 64 + "\n"
            '- 外部技能入口(JSON): \"\\\\u0000\"\n'
            '- 外部技能名称(JSON): \"bad\"\n'
            '- 外部技能描述(JSON): \"bad\"\n'
            '- 来源产品(JSON): [\"test\"]\n',
            encoding="utf-8",
        )
        (root / "skills" / "imported-deep.md").write_text(
            "# 技能: deep\n"
            "- 挂载点: S1\n"
            "- 触发条件: 总是\n"
            "- 作用: deep\n"
            "- 外部源标识: " + "e" * 64 + "\n"
            '- 外部技能入口(JSON): "C:\\\\deep"\n'
            '- 外部技能名称(JSON): "deep"\n'
            '- 外部技能描述(JSON): "deep"\n'
            "- 来源产品(JSON): " + "[" * 1500 + "0" + "]" * 1500 + "\n",
            encoding="utf-8",
        )
        mismatch_source = root / "mismatched-external" / "SKILL.md"
        (root / "skills" / "imported-mismatch.md").write_text(
            "# 技能: mismatch\n"
            "- 挂载点: S1\n"
            "- 触发条件: 总是\n"
            "- 作用: mismatch\n"
            "- 外部源标识: " + "d" * 64 + "\n"
            "- 外部技能入口(JSON): " + json.dumps(str(mismatch_source)) + "\n"
            '- 外部技能名称(JSON): "mismatch"\n'
            '- 外部技能描述(JSON): "mismatch"\n'
            '- 来源产品(JSON): ["test"]\n',
            encoding="utf-8",
        )
        malformed_skills = skills_config.replace("|----------|--------|----------|------|\r\n", "", 1)
        expect_api_error(409, lambda: app._parse_skills(malformed_skills))
        projects_config = """# projects

## 注册项模板

```markdown
## fake
- 路径: `ignored/`
- 规范文件: ignored
- 验证命令: ignored
- 分支模型: ignored
```

---

## demo

- 路径: `demo/`
- 技术栈: Python
- 判定信号: demo
- 规范文件: `AGENTS.md`
- 验证命令:
  1. `python -m compileall .`
- 分支模型: 从 `origin/master` 拉 `feature/<需求id>`,从 `origin/dev` 拉 `test/<需求id>`,MR 合入 master
- 远端: 无
- 流程扩展: dual-baseline-test
- 联测方式: 推送 test 分支后人工验证
- 过程产物入库: 禁止

<!-- projects-sentinel -->
"""
        projects_path = root / "config" / "projects.md"
        projects_path.write_text(projects_config, encoding="utf-8")
        projects_original = projects_path.read_bytes()
        external_projects = projects_original + b"\n<!-- external-change -->\n"
        projects_path.write_bytes(external_projects)
        expect_api_error(
            409,
            lambda: app._atomic_write_many(
                [(projects_path, projects_original.decode("utf-8") + "\n<!-- own-change -->\n", projects_original.decode("utf-8"))]
            ),
        )
        assert projects_path.read_bytes() == external_projects
        projects_path.write_bytes(projects_original)
        capabilities_config = """# capabilities

```text
- 运行档位偏好: 档位3
```

## 能力自检清单

| 能力 | 有 | 无 |
|------|----|----|
| shell | 执行 | 中继 |

<!-- capabilities-sentinel -->
"""
        (root / "config" / "capabilities.md").write_text(capabilities_config, encoding="utf-8")
        def init_test_repo(path: Path) -> None:
            path.mkdir(parents=True)
            try:
                subprocess.run(
                    ["git", "init", str(path)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=True,
                )
            except OSError:
                (path / ".git" / "objects").mkdir(parents=True)
                (path / ".git" / "HEAD").write_text("ref: refs/heads/master\n", encoding="utf-8")

        demo_project = root / "services" / "demo"
        init_test_repo(demo_project)
        imported_project = root / "services" / "imported-go"
        init_test_repo(imported_project)
        (imported_project / "AGENTS.md").write_text("# rules\n", encoding="utf-8")
        plain_project = root / "services" / "plain"
        plain_project.mkdir()
        fake_git_project = root / "services" / "fake-git"
        fake_git_project.mkdir()
        (fake_git_project / ".git").write_text("not a gitfile\n", encoding="utf-8")

        def write_agent_skill(path: Path, name: str, description: str = "test skill") -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("---\nname: {}\ndescription: {}\n---\n\n# {}\n".format(name, description, name), encoding="utf-8")

        agent_skills = [
            (root / ".codex" / "skills" / "codex-home" / "SKILL.md", "codex-home"),
            (root / ".codex" / "skills" / "long-description" / "SKILL.md", "long-description"),
            (root / ".claude" / "skills" / "shared" / "SKILL.md", "shared"),
            (root / ".cursor" / "skills" / "shared" / "SKILL.md", "shared"),
            (root / ".gemini" / "skills" / "gemini-home" / "SKILL.md", "gemini-home"),
            (root / ".copilot" / "skills" / "copilot-home" / "SKILL.md", "copilot-home"),
            (root / ".codeium" / "windsurf" / "skills" / "windsurf-home" / "SKILL.md", "windsurf-home"),
            (root / ".agents" / "skills" / "common-home" / "SKILL.md", "common-home"),
            (root / ".github" / "skills" / "copilot-project" / "SKILL.md", "copilot-project"),
            (root / ".windsurf" / "skills" / "windsurf-project" / "SKILL.md", "windsurf-project"),
            (root / "ProgramData" / "Windsurf" / "skills" / "windsurf-system" / "SKILL.md", "windsurf-system"),
        ]
        for skill_path, skill_name in agent_skills:
            write_agent_skill(skill_path, skill_name, "x" * 700 if skill_name == "long-description" else "test skill")
        folded_skill = root / ".cursor" / "skills" / "folded-description" / "SKILL.md"
        folded_skill.parent.mkdir(parents=True)
        folded_skill.write_text(
            "---\nname: folded-description\ndescription: >\n  first folded line\n  ---\n  second folded line\nlicense: MIT\n---\n",
            encoding="utf-8",
        )
        legacy_command = root / ".claude" / "commands" / "legacy.md"
        legacy_command.parent.mkdir(parents=True)
        legacy_command.write_text("# legacy-command\n\nLegacy Claude command.\n", encoding="utf-8")
        bad_skill = root / ".claude" / "skills" / "bad" / "SKILL.md"
        bad_skill.parent.mkdir(parents=True)
        bad_skill.write_text("# missing frontmatter\n", encoding="utf-8")
        large_skill = root / ".claude" / "skills" / "large" / "SKILL.md"
        large_skill.parent.mkdir(parents=True)
        large_skill.write_text("x" * (MAX_SKILL_FILE + 1), encoding="utf-8")
        deep_skill = root / ".claude" / "skills" / "a" / "b" / "c" / "d" / "e" / "SKILL.md"
        write_agent_skill(deep_skill, "too-deep")
        skipped_skill = root / ".claude" / "skills" / "Cache" / "ignored" / "SKILL.md"
        write_agent_skill(skipped_skill, "must-not-scan")
        outside_skill = root / "outside" / "SKILL.md"
        write_agent_skill(outside_skill, "outside")
        linked_skill = root / ".claude" / "skills" / "linked" / "SKILL.md"
        linked_skill.parent.mkdir(parents=True)
        link_created = False
        try:
            os.symlink(str(outside_skill), str(linked_skill))
            link_created = True
        except OSError:
            pass
        for index in range(MAX_SKILLS_PER_ROOT + 1):
            write_agent_skill(
                root / ".gemini" / "skills" / "limit-{:03d}".format(index) / "SKILL.md",
                "limit-{:03d}".format(index),
            )

        codex_config = root / ".codex" / "config.toml"
        codex_config.write_text(
            '[plugins."demo@test-reg"]\nenabled = true\n\n'
            '[plugins."multi@test-reg"]\nenabled = true\n\n'
            '[plugins."badpath@test-reg"]\nenabled = true\n\n'
            '[plugins."disabled@test-reg"]\nenabled = false\n',
            encoding="utf-8",
        )
        plugin_version = root / ".codex" / "plugins" / "cache" / "test-reg" / "demo" / "1.0"
        (plugin_version / ".codex-plugin").mkdir(parents=True)
        (plugin_version / ".codex-plugin" / "plugin.json").write_text(
            json.dumps({"name": "demo", "skills": "./skills/"}, ensure_ascii=False),
            encoding="utf-8",
        )
        write_agent_skill(plugin_version / "skills" / "codex-plugin" / "SKILL.md", "codex-plugin")
        for version_name, skill_name in (("1.0", "codex-old-cache"), ("2.0", "codex-new-cache")):
            multi_version = root / ".codex" / "plugins" / "cache" / "test-reg" / "multi" / version_name
            (multi_version / ".codex-plugin").mkdir(parents=True)
            (multi_version / ".codex-plugin" / "plugin.json").write_text(
                json.dumps({"name": "multi", "skills": "./skills/"}),
                encoding="utf-8",
            )
            write_agent_skill(multi_version / "skills" / skill_name / "SKILL.md", skill_name)
        badpath_version = root / ".codex" / "plugins" / "cache" / "test-reg" / "badpath" / "1.0"
        (badpath_version / ".codex-plugin").mkdir(parents=True)
        (badpath_version / ".codex-plugin" / "plugin.json").write_text(
            json.dumps({"name": "badpath", "skills": "\u0000"}),
            encoding="utf-8",
        )

        cursor_plugin = root / ".cursor" / "plugins" / "local" / "cursor-demo"
        (cursor_plugin / ".cursor-plugin").mkdir(parents=True)
        (cursor_plugin / ".cursor-plugin" / "plugin.json").write_text(
            json.dumps({"name": "cursor-demo", "skills": "./custom-skills/*"}),
            encoding="utf-8",
        )
        write_agent_skill(cursor_plugin / "custom-skills" / "cursor-plugin-skill" / "SKILL.md", "cursor-plugin-skill")
        write_agent_skill(cursor_plugin / "skills" / "must-not-use-default" / "SKILL.md", "must-not-use-default")
        cursor_bad = root / ".cursor" / "plugins" / "local" / "cursor-bad"
        (cursor_bad / ".cursor-plugin").mkdir(parents=True)
        (cursor_bad / ".cursor-plugin" / "plugin.json").write_text(
            json.dumps({"name": "cursor-bad", "skills": "../../outside"}),
            encoding="utf-8",
        )
        write_agent_skill(
            root / ".cursor" / "plugins" / "cache" / "stale" / "skills" / "cursor-cache-stale" / "SKILL.md",
            "cursor-cache-stale",
        )

        gemini_extension = root / ".gemini" / "extensions" / "gemini-demo"
        gemini_extension.mkdir(parents=True)
        (gemini_extension / "gemini-extension.json").write_text(
            json.dumps({"name": "gemini-demo", "version": "1.0.0"}),
            encoding="utf-8",
        )
        write_agent_skill(gemini_extension / "skills" / "gemini-extension-skill" / "SKILL.md", "gemini-extension-skill")
        write_agent_skill(gemini_extension / "SKILL.md", "gemini-root-must-not-load")
        gemini_bad = root / ".gemini" / "extensions" / "gemini-bad"
        gemini_bad.mkdir(parents=True)
        (gemini_bad / "gemini-extension.json").write_text(
            json.dumps({"name": "gemini-bad"}),
            encoding="utf-8",
        )

        copilot_extra = root / "copilot-extra"
        write_agent_skill(copilot_extra / "copilot-extra-skill" / "SKILL.md", "copilot-extra-skill")
        copilot_settings = root / ".copilot" / "settings.json"
        copilot_settings.parent.mkdir(parents=True, exist_ok=True)
        copilot_settings.write_text(
            "{\n"
            "  // JSONC and trailing commas are supported\n"
            '  "enabledPlugins": {"copilot-demo@market-a": true, "copilot-on@market-a": true, "copilot-off@market-a": true,},\n'
            '  "disabledSkills": ["copilot-disabled", "copilot-project"],\n'
            '  "skillDirectories": [' + json.dumps(str(copilot_extra)) + "],\n"
            "}\n",
            encoding="utf-8",
        )
        copilot_project_settings = root / ".github" / "copilot" / "settings.json"
        copilot_project_settings.parent.mkdir(parents=True)
        copilot_project_escape = root / "project-skill-directory-must-not-load"
        write_agent_skill(
            copilot_project_escape / "project-setting-skill" / "SKILL.md", "project-setting-skill"
        )
        copilot_project_settings.write_text(
            json.dumps(
                {
                    "enabledPlugins": {"copilot-off@market-a": False},
                    "skillDirectories": [str(copilot_project_escape)],
                }
            ),
            encoding="utf-8",
        )
        copilot_project_local_settings = root / ".github" / "copilot" / "settings.local.json"
        copilot_project_local_settings.write_text(
            json.dumps({"enabledPlugins": {"copilot-demo@market-a": False}}),
            encoding="utf-8",
        )
        copilot_plugin = root / ".copilot" / "installed-plugins" / "market-a" / "copilot-demo"
        copilot_plugin.mkdir(parents=True)
        (copilot_plugin / "plugin.json").write_text(json.dumps({"name": "copilot-demo"}), encoding="utf-8")
        write_agent_skill(copilot_plugin / "skills" / "copilot-plugin-skill" / "SKILL.md", "copilot-plugin-skill")
        write_agent_skill(copilot_plugin / "skills" / "copilot-disabled" / "SKILL.md", "copilot-disabled")
        copilot_on = root / ".copilot" / "installed-plugins" / "market-a" / "copilot-on"
        copilot_on.mkdir(parents=True)
        (copilot_on / "plugin.json").write_text(json.dumps({"name": "copilot-on"}), encoding="utf-8")
        write_agent_skill(copilot_on / "skills" / "copilot-on-skill" / "SKILL.md", "copilot-on-skill")
        copilot_off = root / ".copilot" / "installed-plugins" / "market-a" / "copilot-off"
        copilot_off.mkdir(parents=True)
        (copilot_off / "plugin.json").write_text(json.dumps({"name": "copilot-off"}), encoding="utf-8")
        write_agent_skill(copilot_off / "skills" / "copilot-off-skill" / "SKILL.md", "copilot-off-skill")
        copilot_direct = root / ".copilot" / "installed-plugins" / "_direct" / "source-id"
        (copilot_direct / ".plugin").mkdir(parents=True)
        (copilot_direct / ".plugin" / "plugin.json").write_text(
            json.dumps({"name": "copilot-direct"}),
            encoding="utf-8",
        )
        write_agent_skill(copilot_direct / "skills" / "copilot-direct-skill" / "SKILL.md", "copilot-direct-skill")
        copilot_bad = root / ".copilot" / "installed-plugins" / "market-a" / "copilot-bad"
        copilot_bad.mkdir(parents=True)
        (copilot_bad / "plugin.json").write_text(
            json.dumps({"name": "copilot-bad", "skills": "../../outside"}),
            encoding="utf-8",
        )
        write_agent_skill(
            root / ".claude" / "plugins" / "cache" / "market" / "stale" / "1.0" / "skills" / "claude-cache-stale" / "SKILL.md",
            "claude-cache-stale",
        )

        settings = app.settings()
        assert len(settings["skills"]["rows"]) == 2
        catalog = settings["skills"]["catalog"]
        assert any(item["status"] == "无效" and item["path"].endswith("imported-bad.md") for item in catalog)
        assert any(item["status"] == "无效" and item["path"].endswith("imported-deep.md") for item in catalog)
        assert any(item["status"] == "无效" and item["path"].endswith("imported-mismatch.md") for item in catalog)
        expected_names = {
                "codex-home",
                "long-description",
                "folded-description",
                "shared",
                "gemini-home",
                "copilot-home",
                "windsurf-home",
                "common-home",
                "copilot-project",
                "windsurf-project",
                "windsurf-system",
                "codex-plugin",
                "cursor-plugin-skill",
                "gemini-extension-skill",
                "copilot-plugin-skill",
                "copilot-on-skill",
                "copilot-disabled",
                "copilot-off-skill",
                "copilot-direct-skill",
                "copilot-extra-skill",
                "legacy-command",
            }
        assert {item["name"] for item in catalog}.issuperset(expected_names), expected_names - {
            item["name"] for item in catalog
        }
        assert next(item for item in catalog if item["name"] == "folded-description")["description"] == (
            "first folded line --- second folded line"
        )
        assert len(next(item for item in catalog if item["name"] == "long-description")["description"]) == 700
        assert not any(item["name"] == "must-not-use-default" for item in catalog)
        assert not any(item["name"] == "gemini-root-must-not-load" for item in catalog)
        assert not any(item["name"] in ("cursor-cache-stale", "claude-cache-stale") for item in catalog)
        assert not any(item["name"] == "project-setting-skill" for item in catalog)
        assert not any(item["name"] in ("codex-old-cache", "codex-new-cache") for item in catalog)
        assert any("无法唯一确定物理版本" in item["reason"] for item in catalog)
        assert any("插件 skills 路径不合法" in item["reason"] for item in catalog)
        assert next(item for item in catalog if item["name"] == "cursor-plugin-skill")["status"] == "已发现未确认"
        assert next(item for item in catalog if item["name"] == "gemini-extension-skill")["status"] == "已发现未确认"
        copilot_plugin_skill = next(item for item in catalog if item["name"] == "copilot-plugin-skill")
        assert copilot_plugin_skill["status"] == "已发现未确认"
        assert "明确禁用该已安装插件" in copilot_plugin_skill["reason"]
        assert next(item for item in catalog if item["name"] == "copilot-on-skill")["status"] == "已确认启用"
        assert next(item for item in catalog if item["name"] == "copilot-disabled")["status"] == "已发现未确认"
        copilot_project_skill = next(item for item in catalog if item["name"] == "copilot-project")
        assert copilot_project_skill["status"] == "已发现未确认"
        assert "明确禁用该技能" in copilot_project_skill["evidence"]
        assert next(item for item in catalog if item["name"] == "copilot-off-skill")["status"] == "已发现未确认"
        assert next(item for item in catalog if item["name"] == "copilot-direct-skill")["status"] == "已发现未确认"
        assert any("manifest skills 路径" in item["reason"] for item in catalog if item["status"] == "无效")
        copilot_local_original = copilot_project_local_settings.read_text(encoding="utf-8")
        copilot_project_local_settings.write_text('{"invalid":', encoding="utf-8")
        try:
            uncertain_catalog = app.settings()["skills"]["catalog"]
            uncertain_copilot = next(item for item in uncertain_catalog if item["name"] == "copilot-on-skill")
            assert uncertain_copilot["status"] == "已发现未确认"
            assert "settings 无效" in uncertain_copilot["reason"]
        finally:
            copilot_project_local_settings.write_text(copilot_local_original, encoding="utf-8")
        shared = [item for item in catalog if item["name"] == "shared"]
        assert len(shared) == 2
        claude_shared = next(item for item in shared if ".claude" in item["path"])
        assert set(claude_shared["scopes"]) == {"工作区", "用户"}
        assert "Windsurf" not in claude_shared["products"]
        assert len([item for item in catalog if item["path"] == claude_shared["path"]]) == 1
        assert next(item for item in catalog if item["name"] == "codex-plugin")["status"] == "已确认启用"
        assert any(item["status"] == "无效" and item["path"] == str(bad_skill.resolve()) for item in catalog)
        assert any(item["status"] == "无效" and item["path"] == str(large_skill.resolve()) for item in catalog)
        assert not any(item["name"] == "too-deep" for item in catalog)
        assert not any(item["name"] == "must-not-scan" for item in catalog)
        assert any("结果上限" in item["reason"] for item in catalog)
        if link_created:
            assert any(item["status"] == "无效" and item["path"] == str(linked_skill.absolute()) for item in catalog)
        assert all(re.fullmatch(r"[0-9a-f]{64}", row["source_id"]) for row in settings["skills"]["rows"])
        assert len(settings["projects"]["rows"]) == 1
        assert settings["capabilities"]["mode"] == "自动检测"
        inspected_project = app.inspect_project(str(imported_project))
        assert inspected_project["path"] == "services/imported-go/"
        assert inspected_project["commands"] == ["git diff --check"]
        assert "`AGENTS.md`" in inspected_project["specifications"]
        assert inspected_project["branch_model"] == ""
        expect_api_error(400, lambda: app.inspect_project(str(root.parent)))
        expect_api_error(400, lambda: app.inspect_project(str(fake_git_project)))
        payload = json.loads(json.dumps(settings, ensure_ascii=False))
        payload["skills"]["rows"].reverse()
        payload["skills"]["rows"][0].update({"mounts": ["S3", "S4"], "trigger": "涉及接口或安全", "state": "启用"})
        native_skill = next(item for item in catalog if item.get("file") == "skills/skill-c.md")
        payload["skills"]["rows"].append(
            {
                "source_id": native_skill["id"],
                "file": native_skill["file"],
                "mounts": ["S5"],
                "trigger": "准备交付",
                "state": "停用",
            }
        )
        payload["skills"]["rows"].append(
            {"source_id": claude_shared["id"], "file": "", "mounts": ["S1"], "trigger": "总是", "state": "停用"}
        )
        payload["projects"]["rows"][0].update(
            {
                "path": "services/demo",
                "specifications": "`AGENTS.md`、`CONTRIBUTING.md`",
                "commands": ["python -m compileall .", "python -m unittest"],
                "branch_model": "从 `origin/master` 拉 `feature/<需求id>`,从 `origin/dev` 拉 `test/<需求id>`,MR 合入 master",
            }
        )
        inspected_project["branch_model"] = "从 `origin/master` 拉 `feature/<需求id>`，MR 合入 `master`"
        payload["projects"]["rows"].append(inspected_project)
        no_newline = app._prepare_projects(projects_config.rstrip("\r\n"), payload["projects"]["rows"])
        assert {row["name"] for row in app._parse_projects(no_newline)[0]} == {"demo", "imported-go"}
        expect_api_error(
            400,
            lambda: app._prepare_projects(projects_config, payload["projects"]["rows"] * (MAX_PROJECTS + 1)),
        )
        prefix = projects_config + "<!-- "
        near_limit = prefix + "x" * (MAX_FILE - len(prefix.encode("utf-8")) - 4) + " -->"
        assert len(near_limit.encode("utf-8")) == MAX_FILE
        expect_api_error(413, lambda: app._prepare_projects(near_limit, payload["projects"]["rows"]))
        payload["capabilities"]["mode"] = "档位2"
        saved = app.save_settings(payload)
        assert saved["skills"]["rows"][0]["file"] == "skills/skill-b.md"
        imported_row = next(row for row in saved["skills"]["rows"] if row["source_id"] == claude_shared["id"])
        assert imported_row["state"] == "停用"
        assert next(row for row in saved["skills"]["rows"] if row["source_id"] == native_skill["id"])["mounts"] == ["S5"]
        imported_path = root / imported_row["file"]
        assert imported_path.is_file()
        assert "外部源标识: " + claude_shared["id"] in imported_path.read_text(encoding="utf-8")
        assert saved["projects"]["rows"][0]["commands"] == ["python -m compileall .", "python -m unittest"]
        assert len(saved["projects"]["rows"]) == 2
        assert next(row for row in saved["projects"]["rows"] if row["name"] == "imported-go")["commands"] == ["git diff --check"]
        assert saved["capabilities"]["mode"] == "档位2"
        saved_capabilities = (root / "config" / "capabilities.md").read_text(encoding="utf-8")
        assert "## 当前运行设置" in saved_capabilities
        assert "```text\n- 运行档位偏好: 档位3\n```" in saved_capabilities
        assert "技能/项目/能力设置已更新" in app.logs()[0]["detail"]
        assert b"\r\n" in (root / "config" / "skills.md").read_bytes()
        assert "skills-sentinel" in (root / "config" / "skills.md").read_text(encoding="utf-8")
        assert "projects-sentinel" in (root / "config" / "projects.md").read_text(encoding="utf-8")
        assert "capabilities-sentinel" in (root / "config" / "capabilities.md").read_text(encoding="utf-8")
        assert "- 挂载点: S3, S4" in (root / "skills" / "skill-b.md").read_text(encoding="utf-8")
        expect_api_error(409, lambda: app.save_settings(payload))

        invalid = json.loads(json.dumps(saved, ensure_ascii=False))
        invalid["skills"]["rows"][0]["mounts"] = ["S9"]
        expect_api_error(400, lambda: app.save_settings(invalid))
        invalid = json.loads(json.dumps(saved, ensure_ascii=False))
        invalid["projects"]["rows"][0]["branch_model"] = "main only"
        expect_api_error(400, lambda: app.save_settings(invalid))
        invalid = json.loads(json.dumps(saved, ensure_ascii=False))
        invalid["projects"]["rows"][0]["path"] = "../escape"
        expect_api_error(400, lambda: app.save_settings(invalid))
        invalid = json.loads(json.dumps(saved, ensure_ascii=False))
        invalid["projects"]["rows"][0]["path"] = "AGENTS.md"
        expect_api_error(400, lambda: app.save_settings(invalid))
        invalid = json.loads(json.dumps(saved, ensure_ascii=False))
        invalid["projects"]["rows"][0]["path"] = "missing/repository"
        expect_api_error(400, lambda: app.save_settings(invalid))
        invalid = json.loads(json.dumps(saved, ensure_ascii=False))
        invalid["projects"]["rows"][0]["path"] = "services/plain"
        expect_api_error(400, lambda: app.save_settings(invalid))
        invalid = json.loads(json.dumps(saved, ensure_ascii=False))
        duplicate_project = dict(invalid["projects"]["rows"][1])
        duplicate_project["name"] = "imported-go-copy"
        invalid["projects"]["rows"].append(duplicate_project)
        expect_api_error(400, lambda: app.save_settings(invalid))
        invalid = json.loads(json.dumps(saved, ensure_ascii=False))
        invalid["projects"]["rows"] = invalid["projects"]["rows"][1:]
        expect_api_error(400, lambda: app.save_settings(invalid))
        assert app.settings()["capabilities"]["mode"] == "档位2"

        arbitrary = json.loads(json.dumps(saved, ensure_ascii=False))
        arbitrary["skills"]["rows"].append(
            {"source_id": "0" * 64, "file": "", "mounts": ["S1"], "trigger": "总是", "state": "停用"}
        )
        expect_api_error(400, lambda: app.save_settings(arbitrary))

        rollback_snapshot = app.settings()
        cursor_shared = next(
            item for item in rollback_snapshot["skills"]["catalog"] if item["name"] == "shared" and ".cursor" in item["path"]
        )
        rollback_payload = json.loads(json.dumps(rollback_snapshot, ensure_ascii=False))
        rollback_payload["skills"]["rows"].append(
            {"source_id": cursor_shared["id"], "file": "", "mounts": ["S2"], "trigger": "总是", "state": "停用"}
        )
        rollback_target = root / app._adapter_filename(cursor_shared)
        skills_before_rollback = (root / "config" / "skills.md").read_bytes()
        original_atomic_write = app._atomic_write

        def fail_skills_config(path: Path, content: str) -> None:
            if path == root / "config" / "skills.md":
                raise OSError("injected write failure")
            original_atomic_write(path, content)

        app._atomic_write = fail_skills_config
        try:
            try:
                app.save_settings(rollback_payload)
            except OSError:
                pass
            else:
                raise AssertionError("expected injected write failure")
        finally:
            app._atomic_write = original_atomic_write
        assert not rollback_target.exists()
        assert (root / "config" / "skills.md").read_bytes() == skills_before_rollback

        rollback_target.write_text("do not overwrite\n", encoding="utf-8")
        expect_api_error(409, lambda: app.save_settings(rollback_payload))
        assert rollback_target.read_text(encoding="utf-8") == "do not overwrite\n"
        rollback_target.unlink()

        claude_shared_path = Path(claude_shared["path"])
        claude_shared_path.unlink()
        lost = next(item for item in app.settings()["skills"]["catalog"] if item["id"] == claude_shared["id"])
        assert lost["status"] == "失效" and lost["orchestrated"]
        lost_payload = app.settings()
        next(
            row for row in lost_payload["skills"]["rows"] if row["source_id"] == claude_shared["id"]
        )["state"] = "启用"
        expect_api_error(400, lambda: app.save_settings(lost_payload))
        restarted = WorkflowWorkspace(root)
        restarted.home = root
        restarted.copilot_home = root / ".copilot"
        restarted.gemini_home = root
        restarted.copilot_extra_roots = []
        restarted.program_data = root / "ProgramData"
        restarted_settings = restarted.settings()
        assert any(row["source_id"] == claude_shared["id"] for row in restarted_settings["skills"]["rows"])

        nested = root / "dist"
        nested.mkdir()
        assert find_workspace(nested) == root

    console(
        "SELF_TEST_OK ids=11 create=2 parse=1 path_guard=3 gate_cases=9 "
        "settings=10 project_import=8 parallel_prompt=1 atomic_writes=5 workspace=3"
    )


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="AI 开发工作流本地 GUI")
    parser.add_argument("--workspace", default=str(default_workspace()), help="工作流根目录，默认从程序位置向上查找")
    parser.add_argument("--port", type=int, default=8765, help="本机监听端口，默认 8765")
    parser.add_argument("--self-test", action="store_true", help="运行内置自测后退出")
    args = parser.parse_args(argv)

    if args.self_test:
        run_self_test()
        return 0
    if args.port < 0 or args.port > 65535:
        parser.error("port 必须在 0..65535")

    app = WorkflowWorkspace(Path(args.workspace))
    index_path = bundled_file("index.html")
    index_html = index_path.read_text(encoding="utf-8")
    server = ThreadingHTTPServer(("127.0.0.1", args.port), build_handler(app, index_html))
    url = "http://127.0.0.1:{}/".format(server.server_port)
    console("Workflow GUI: " + url)
    console("Workspace: " + str(app.root))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        console("Stopped.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
