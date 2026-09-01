import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from workflow.codex_usage import collect_codex_usage
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
