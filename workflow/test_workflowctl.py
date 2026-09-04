import json
import os
import tempfile
import time
import unittest
from unittest.mock import patch
from datetime import datetime, timedelta, timezone
from pathlib import Path

from workflow.token_usage import (
    collect_codex_usage,
    collect_omp_usage,
    collect_runtime_usage,
    discover_omp_session_files,
)
from workflow.core import STAGES, can_transition, validate_task_id
from workflow.workflowctl import (
    backfill_stage_metrics,
    context,
    doctor,
    main,
    parse_state,
    record_stage_metrics,
    start_stage_metrics,
)


ROOT = Path(__file__).resolve().parent.parent


def write_codex_log(codex_home, session_id, events):
    path = codex_home / "sessions" / "2026" / "08" / "31" / ("rollout-" + session_id + ".jsonl")
    path.parent.mkdir(parents=True)
    lines = []
    for timestamp, usage, total_usage in events:
        lines.append(
            json.dumps(
                {
                    "timestamp": timestamp,
                    "type": "event_msg",
                    "payload": {
                        "type": "token_count",
                        "info": {"last_token_usage": usage, "total_token_usage": total_usage},
                    },
                }
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def omp_usage(input_tokens, cached, cache_write, output, reasoning):
    return {
        "input": input_tokens,
        "output": output,
        "cacheRead": cached,
        "cacheWrite": cache_write,
        "totalTokens": input_tokens + cached + cache_write + output,
        "reasoningTokens": reasoning,
    }


def write_omp_session(path, cwd, events):
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps({"type": "session", "version": 3, "id": path.stem, "timestamp": events[0]["timestamp"], "cwd": str(cwd)})]
    lines.extend(json.dumps(event) if not isinstance(event, str) else event for event in events)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


class WorkflowCoreTests(unittest.TestCase):
    def test_task_ids(self):
        for value in ("demo-1", "PRD_2026.07"):
            self.assertTrue(validate_task_id(value)[0])
        for value in ("CON", "foo.lock", "a..b", "trail-", "has space", "a" * 65):
            self.assertFalse(validate_task_id(value)[0])

    def test_transitions(self):
        self.assertEqual(STAGES, ("S1", "S2", "S3", "S4", "S5", "S6"))
        self.assertTrue(can_transition("S4", "S3"))
        self.assertTrue(can_transition("S4", "S5"))
        self.assertFalse(can_transition("S1", "S5"))

    def test_doctor_and_budget(self):
        result = doctor(ROOT)
        self.assertTrue(result["ok"], result)
        self.assertLessEqual(
            len((ROOT / "AGENTS.md").read_text(encoding="utf-8")),
            2500,
        )

    def test_new_task_context_is_progressive(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "prds").mkdir()
            (root / "work").mkdir()
            (root / "prds" / "demo.md").write_text("# demo\n", encoding="utf-8")
            for relative in (
                "workflow/stages/S1/SKILL.md",
                "workflow/references/metrics.md",
                "config/projects/index.json",
            ):
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                source = ROOT / relative
                target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
            mounted = root / "skills" / "demo.md"
            mounted.parent.mkdir(parents=True)
            mounted.write_text("# demo skill\n", encoding="utf-8")
            registry = root / "config" / "skills.md"
            registry.write_text(
                "## 当前挂载表\n\n"
                "| 技能文件 | 挂载点 | 触发条件 | 状态 |\n"
                "|----------|--------|----------|------|\n"
                "| `skills/demo.md` | S1 | 总是 | 启用 |\n",
                encoding="utf-8",
            )
            payload = context("demo", root)
            self.assertEqual(payload["stage"], "S1")
            self.assertIn("workflow/stages/S1/SKILL.md", payload["required"])
            self.assertIn("skills/demo.md", payload["required"])
            self.assertNotIn("workflow/stages/S6/SKILL.md", payload["required"])
            self.assertEqual(main(["--workspace", str(root), "context", "demo"]), 0)

    def test_metrics_document_records_tokens_rework_efficiency_and_duration(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "work" / "demo").mkdir(parents=True)
            started = start_stage_metrics("demo", root, "S1", "2026-08-27T00:00:00Z")
            self.assertEqual(started["status"], "STARTED")
            result = record_stage_metrics(
                "demo",
                root,
                "S1",
                "PASS",
                100,
                20,
                50,
                10,
                150,
                "unit-test",
                1,
                4,
                1,
                "evidence",
            )
            content = (root / "work" / "demo" / "metrics.md").read_text(encoding="utf-8")
            self.assertEqual(result["efficiency"], "80.00%")
            self.assertIn("input=100, cached_input=20, output=50, reasoning=10, total=150", content)
            self.assertIn("返工次数：`1`", content)
            self.assertIn("效率比：`80.00%`", content)

    def test_codex_usage_deduplicates_cumulative_snapshots_and_backfills(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            codex_home = root / ".codex"
            session_id = "01a00000-0000-7000-8000-000000000001"

            def usage(input_tokens, cached, output, reasoning):
                return {
                    "input_tokens": input_tokens,
                    "cached_input_tokens": cached,
                    "output_tokens": output,
                    "reasoning_output_tokens": reasoning,
                    "total_tokens": input_tokens + output,
                }

            write_codex_log(
                codex_home,
                session_id,
                [
                    ("2026-08-31T00:00:00Z", usage(100, 50, 10, 2), usage(100, 50, 10, 2)),
                    ("2026-08-31T00:01:00Z", usage(200, 100, 20, 4), usage(300, 150, 30, 6)),
                    ("2026-08-31T00:01:10Z", usage(200, 100, 20, 4), usage(300, 150, 30, 6)),
                    ("2026-08-31T00:02:00Z", usage(300, 150, 30, 5), usage(600, 300, 60, 11)),
                    ("2026-08-31T00:03:00Z", usage(400, 200, 40, 6), usage(1000, 500, 100, 17)),
                    ("2026-08-31T00:04:00Z", usage(500, 250, 50, 7), usage(1500, 750, 150, 24)),
                ],
            )
            collected = collect_codex_usage(
                "2026-08-31T00:01:00Z",
                "2026-08-31T00:03:00Z",
                [session_id],
                codex_home,
            )
            self.assertTrue(collected["available"], collected)
            self.assertEqual(collected["event_count"], 3)
            self.assertEqual(collected["input_tokens"], 900)
            self.assertEqual(collected["cached_input_tokens"], 450)
            self.assertEqual(collected["output_tokens"], 90)
            self.assertEqual(collected["reasoning_tokens"], 15)
            self.assertEqual(collected["total_tokens"], 990)

            metrics = root / "work" / "demo" / "metrics.md"
            metrics.parent.mkdir(parents=True)
            metrics.write_text(
                "# metrics\n\n"
                "## S1 · 尝试 1\n\n"
                "- 结果：`PASS`\n"
                "- 开始：`2026-08-31T00:01:00Z`\n"
                "- 结束：`2026-08-31T00:03:00Z`\n"
                "- Token 来源：`NOT_AVAILABLE`\n"
                "- Token：`NOT_AVAILABLE`\n",
                encoding="utf-8",
            )
            preview = backfill_stage_metrics("demo", root, ["S1"], [session_id], codex_home, dry_run=True)
            self.assertEqual(preview["would_change"], 1)
            self.assertIn("Token：`NOT_AVAILABLE`", metrics.read_text(encoding="utf-8"))
            result = backfill_stage_metrics("demo", root, ["S1"], [session_id], codex_home)
            self.assertEqual(result["changed"], 1)
            content = metrics.read_text(encoding="utf-8")
            self.assertIn("input=900, cached_input=450, output=90, reasoning=15, total=990", content)

    def test_metrics_record_auto_collects_current_codex_session(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            codex_home = root / ".codex"
            session_id = "01a00000-0000-7000-8000-000000000002"
            now = datetime.now(timezone.utc).replace(microsecond=0)
            started_at = (now - timedelta(seconds=5)).isoformat().replace("+00:00", "Z")
            event_time = (now - timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
            usage = {
                "input_tokens": 120,
                "cached_input_tokens": 80,
                "output_tokens": 30,
                "reasoning_output_tokens": 10,
                "total_tokens": 150,
            }
            write_codex_log(codex_home, session_id, [(event_time, usage, usage)])
            (root / "work" / "demo").mkdir(parents=True)
            started = start_stage_metrics("demo", root, "S1", started_at)
            self.assertTrue(started["started_at"].endswith("+08:00"), started)
            result = record_stage_metrics(
                "demo",
                root,
                "S1",
                "PASS",
                None,
                None,
                None,
                None,
                None,
                None,
                0,
                1,
                0,
                "auto",
                True,
                [session_id],
                codex_home,
            )
            self.assertEqual(result["tokens"]["total_tokens"], 150)
            content = (root / "work" / "demo" / "metrics.md").read_text(encoding="utf-8")
            self.assertIn("Codex token_count last_token_usage", content)
            self.assertIn("input=120, cached_input=80, output=30, reasoning=10, total=150", content)
            self.assertRegex(content, r"- 开始：`[^`]+\+08:00`")
            self.assertRegex(content, r"- 结束：`[^`]+\+08:00`")

    def test_omp_usage_collects_main_model_and_nested_events_once(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            main = root / "sessions" / "project" / "session.jsonl"
            nested = main.with_suffix("") / "child.jsonl"
            main_usage = omp_usage(100, 50, 10, 20, 5)
            side_usage = omp_usage(10, 5, 2, 3, 1)
            child_usage = omp_usage(10, 4, 1, 2, 2)
            write_omp_session(
                main,
                root,
                [
                    {
                        "type": "message",
                        "id": "before",
                        "timestamp": "2026-08-31T00:00:00Z",
                        "message": {"role": "assistant", "usage": omp_usage(99, 0, 0, 1, 0)},
                    },
                    {
                        "type": "message",
                        "id": "main",
                        "timestamp": "2026-08-31T00:01:00Z",
                        "message": {"role": "assistant", "usage": main_usage},
                    },
                    {
                        "type": "message",
                        "id": "main",
                        "timestamp": "2026-08-31T00:01:01Z",
                        "message": {"role": "assistant", "usage": main_usage},
                    },
                    {
                        "type": "model_usage",
                        "id": "side",
                        "timestamp": "2026-08-31T00:02:00Z",
                        "usage": side_usage,
                    },
                    {
                        "type": "model_usage",
                        "id": "zero",
                        "timestamp": "2026-08-31T00:02:10Z",
                        "usage": omp_usage(0, 0, 0, 0, 0),
                    },
                    {
                        "type": "model_usage",
                        "id": "invalid",
                        "timestamp": "2026-08-31T00:02:20Z",
                        "usage": dict(side_usage, totalTokens=999),
                    },
                    '{"type":"model_usage","id":"broken","timestamp":"2026-08-31T00:02:30Z","usage":',
                ],
            )
            write_omp_session(
                nested,
                root,
                [
                    {
                        "type": "message",
                        "id": "child",
                        "timestamp": "2026-08-31T00:03:00Z",
                        "message": {"role": "assistant", "usage": child_usage},
                    }
                ],
            )

            collected = collect_omp_usage(
                "2026-08-31T00:01:00Z",
                "2026-08-31T00:03:00Z",
                [main],
            )

            self.assertTrue(collected["available"], collected)
            self.assertEqual(collected["event_count"], 3)
            self.assertEqual(collected["transcript_count"], 2)
            self.assertEqual(collected["input_tokens"], 192)
            self.assertEqual(collected["cached_input_tokens"], 59)
            self.assertEqual(collected["output_tokens"], 25)
            self.assertEqual(collected["reasoning_tokens"], 8)
            self.assertEqual(collected["total_tokens"], 217)

    def test_omp_discovery_uses_command_hint_to_isolate_parallel_tool_sessions(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            agent_dir = root / "agent"
            session_dir = agent_dir / "sessions" / "fixture"
            now = time.time()
            current_timestamp = datetime.fromtimestamp(now - 2, timezone.utc).isoformat().replace("+00:00", "Z")
            parallel_timestamp = datetime.fromtimestamp(now - 1, timezone.utc).isoformat().replace("+00:00", "Z")
            current = write_omp_session(
                session_dir / "current.jsonl",
                root,
                [
                    {
                        "type": "custom",
                        "customType": "tool_execution_start",
                        "id": "tool-current",
                        "timestamp": current_timestamp,
                        "data": {
                            "toolName": "bash",
                            "startedAt": current_timestamp,
                            "args": {"command": "python workflow/workflowctl.py metrics-record PRD-current"},
                        },
                    },
                    {
                        "type": "custom",
                        "customType": "tool_execution_start",
                        "id": "tool-later-same-session",
                        "timestamp": parallel_timestamp,
                        "data": {
                            "toolName": "bash",
                            "startedAt": parallel_timestamp,
                            "args": {"command": "python workflow/workflowctl.py doctor"},
                        },
                    },
                ],
            )
            parallel = write_omp_session(
                session_dir / "parallel.jsonl",
                root,
                [{
                    "type": "custom",
                    "customType": "tool_execution_start",
                    "id": "tool-parallel",
                    "timestamp": parallel_timestamp,
                    "data": {
                        "toolName": "bash",
                        "startedAt": parallel_timestamp,
                        "args": {"command": "python workflow/workflowctl.py metrics-record PRD-parallel"},
                    },
                }],
            )
            os.utime(current, (now - 2, now - 2))
            os.utime(parallel, (now - 1, now - 1))

            ambiguous = discover_omp_session_files(
                {"OMPCODE": "1"},
                cwd=root,
                omp_agent_dir=agent_dir,
                now=now,
            )
            discovered = discover_omp_session_files(
                {"OMPCODE": "1"},
                cwd=root,
                omp_agent_dir=agent_dir,
                now=now,
                command_hints=["metrics-record", "PRD-current"],
            )

            self.assertFalse(ambiguous["available"], ambiguous)
            self.assertIn("ambiguous", ambiguous["reason"])
            self.assertTrue(discovered["available"], discovered)
            self.assertEqual(discovered["files"], [str(current.resolve())])
            self.assertEqual(discovered["source"], "OMP current command session")

    def test_runtime_usage_prefers_codex_without_reading_omp(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            codex_home = root / ".codex"
            session_id = "01a00000-0000-7000-8000-000000000003"
            usage = {
                "input_tokens": 50,
                "cached_input_tokens": 20,
                "output_tokens": 10,
                "reasoning_output_tokens": 4,
                "total_tokens": 60,
            }
            write_codex_log(codex_home, session_id, [("2026-08-31T00:01:00Z", usage, usage)])

            collected = collect_runtime_usage(
                "2026-08-31T00:00:00Z",
                "2026-08-31T00:02:00Z",
                [session_id],
                codex_home,
                omp_agent_dir=root / "missing-omp",
                environ={"OMPCODE": "1"},
            )

            self.assertTrue(collected["available"], collected)
            self.assertEqual(collected["runtime"], "codex")
            self.assertEqual(collected["total_tokens"], 60)

    def test_metrics_record_and_backfill_accept_omp_session(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            now = datetime.now(timezone.utc).replace(microsecond=0)
            started_at = (now - timedelta(seconds=5)).isoformat().replace("+00:00", "Z")
            event_time = (now - timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
            main = write_omp_session(
                root / "omp-session.jsonl",
                root,
                [{"type": "message", "id": "live", "timestamp": event_time, "message": {"role": "assistant", "usage": omp_usage(40, 30, 5, 10, 3)}}],
            )
            (root / "work" / "live").mkdir(parents=True)
            start_stage_metrics("live", root, "S1", started_at)
            with patch.dict(os.environ, {"CODEX_SESSION_ID": "01a00000-0000-7000-8000-000000000004"}):
                result = record_stage_metrics(
                    "live",
                    root,
                    "S1",
                    "PASS",
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    0,
                    1,
                    0,
                    "omp",
                    True,
                    None,
                    None,
                    [str(main)],
                )
            self.assertEqual(result["tokens"]["total_tokens"], 85)
            self.assertIn("OMP session usage", result["token_source"])

            metrics = root / "work" / "history" / "metrics.md"
            metrics.parent.mkdir(parents=True)
            metrics.write_text(
                "# metrics\n\n"
                "## S1 · 尝试 1\n\n"
                "- 结果：`PASS`\n"
                "- 开始：`{}`\n"
                "- 结束：`{}`\n"
                "- Token 来源：`NOT_AVAILABLE`\n"
                "- Token：`NOT_AVAILABLE`\n".format(started_at, now.isoformat().replace("+00:00", "Z")),
                encoding="utf-8",
            )
            before = metrics.read_bytes()
            with patch.dict(os.environ, {"CODEX_SESSION_ID": "01a00000-0000-7000-8000-000000000004"}):
                preview = backfill_stage_metrics(
                    "history",
                    root,
                    ["S1"],
                    None,
                    None,
                    dry_run=True,
                    omp_session_files=[str(main)],
                )
                self.assertEqual(preview["would_change"], 1)
                self.assertEqual(metrics.read_bytes(), before)
                actual = backfill_stage_metrics(
                    "history",
                    root,
                    ["S1"],
                    None,
                    None,
                    omp_session_files=[str(main)],
                )
            self.assertEqual(actual["changed"], 1)
            self.assertIn("total=85", metrics.read_text(encoding="utf-8"))

    def test_legacy_markdown_state(self):
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp) / "state.md"
            state.write_text(
                "- 环节: S4\n"
                "- 状态: 进行中\n\n"
                "| 项目 | 阶段 | 行状态 |\n"
                "|---|---|---|\n"
                "| api | S4 | 进行中 |\n",
                encoding="utf-8",
            )
            parsed = parse_state(state)
            self.assertEqual(parsed["环节"], "S4")
            self.assertEqual(parsed["projects"][0]["项目"], "api")


if __name__ == "__main__":
    unittest.main()
