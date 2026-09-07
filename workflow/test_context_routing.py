import json
import io
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from workflow.metrics_store import metrics_lock
from workflow.workflowctl import METRIC_SECTION_RE, backfill_stage_metrics, context, main, parse_state, record_stage_metrics, start_stage_metrics


SOURCE = Path(__file__).resolve().parent.parent


class ContextRoutingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="workflow-context-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.task = self.root / "work" / "demo"
        self.task.mkdir(parents=True)
        relatives = [
            "AGENTS.md",
            "workflow/references/metrics.md",
            "workflow/extensions/dual-baseline-test.md",
            "skills/security-baseline.md",
        ]
        relatives.extend("workflow/stages/{}/SKILL.md".format(stage) for stage in ("S1", "S2", "S3", "S4", "S5", "S6"))
        for relative in relatives:
            destination = self.root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(SOURCE / relative, destination)
        # 项目注册及挂载来自隔离夹具，不能依赖开发者本机的业务项目配置。
        projects = self.root / "config/projects"
        projects.mkdir(parents=True)
        entries = []
        for name, extensions in (("project-api", ["dual-baseline-test"]),
                                 ("project-worker", ["dual-baseline-test"]), ("project-report", [])):
            detail = "config/projects/" + name + ".json"
            data = {"schema_version": 1, "name": name, "path": "projects/" + name + "/", "extensions": extensions}
            (self.root / detail).write_text(json.dumps(data), encoding="utf-8")
            entries.append({"name": name, "path": data["path"], "detail": detail})
        (projects / "index.json").write_text(json.dumps({"schema_version": 1, "projects": entries}), encoding="utf-8")
        (self.root / "config/skills.md").write_text(
            "## 当前挂载表\n\n| 技能文件 | 挂载点 | 触发条件 | 状态 |\n"
            "|----------|--------|----------|------|\n"
            "| skills/security-baseline.md | S3,S4 | 总是 | 启用 |\n", encoding="utf-8")
        for name in ("analysis.md", "plan.md", "impl-log.md", "verify.md", "delivery.md"):
            (self.task / name).write_text("# fixture\n", encoding="utf-8")

    def write_state(self, stage, table):
        path = self.task / "state.md"
        path.write_text("- 环节: {}\n- 状态: 进行中\n\n{}\n".format(stage, table), encoding="utf-8")
        return path

    def test_code_formatted_project_names_load_selected_project_extensions(self):
        self.write_state(
            "S4",
            "| 项目 | 阶段 | 行状态 |\n|---|---|---|\n"
            "| `project-api` | S4 | BLOCKED |\n"
            "| `project-worker` | S4 | BLOCKED |",
        )
        for selected, other in (("project-api", "project-worker"), ("project-worker", "project-api")):
            payload = context("demo", self.root, "`" + selected + "`")
            self.assertIn("config/projects/" + selected + ".json", payload["required"])
            self.assertNotIn("config/projects/" + other + ".json", payload["required"])
            self.assertEqual(payload["required"].count("workflow/extensions/dual-baseline-test.md"), 1)
            self.assertFalse(payload["runnable"])

    def test_legacy_status_column_loads_s6_cleanup_rules(self):
        path = self.write_state(
            "S6",
            "| 项目 | 正式基线 | 风险 | 阶段 | 状态 |\n|---|---|---|---|---|\n"
            "| project-worker | `origin/master` | R2 | S6 | 已完成（无 MR 验收） |",
        )
        state = parse_state(path)
        self.assertEqual(state["projects"][0]["行状态"], "已完成（无 MR 验收）")
        payload = context("demo", self.root)
        self.assertIn("config/projects/project-worker.json", payload["required"])
        self.assertIn("workflow/extensions/dual-baseline-test.md", payload["required"])

    def test_later_evidence_table_is_not_another_project_row(self):
        path = self.write_state(
            "S4",
            "| 项目 | 阶段 | 行状态 |\n|---|---|---|\n"
            "| project-worker | S4 | 进行中 |\n\n"
            "## 验证补充\n\n| 检查 | 结果 | 证据 |\n|---|---|---|\n| 单测 | PASS | 输出 |",
        )
        self.assertEqual(len(parse_state(path)["projects"]), 1)
        self.assertIn("config/projects/project-worker.json", context("demo", self.root)["required"])

    def test_unknown_declared_project_fails_instead_of_partial_loading(self):
        self.write_state(
            "S4",
            "| 项目 | 阶段 | 行状态 |\n|---|---|---|\n"
            "| project-worker | S4 | 进行中 |\n| `unknown-project` | S4 | 进行中 |",
        )
        with self.assertRaisesRegex(ValueError, "unregistered project in state: unknown-project"):
            context("demo", self.root)

    def test_workflow_self_maintenance_is_identified_by_name_and_directory(self):
        self.write_state(
            "S6",
            "| 项目 | 工作目录 | 阶段 | 行状态 |\n|---|---|---|---|\n"
            "| `{}` | `{}` | S6 | COMPLETE |".format(self.root.name, self.root),
        )
        payload = context("demo", self.root)
        self.assertIn("AGENTS.md", payload["required"])
        self.assertNotIn("config/projects/index.json", payload["required"])
        self.assertNotIn("workflow/extensions/dual-baseline-test.md", payload["required"])

    def test_workspace_name_alone_does_not_bypass_project_registration(self):
        self.write_state(
            "S6",
            "| 项目 | 工作目录 | 阶段 | 行状态 |\n|---|---|---|---|\n"
            "| `{}` | `projects/other` | S6 | COMPLETE |".format(self.root.name),
        )
        with self.assertRaisesRegex(ValueError, "unregistered project"):
            context("demo", self.root)

    def test_json_project_names_follow_same_normalization(self):
        (self.task / "state.json").write_text(
            json.dumps({"stage": "S4", "projects": [{"project": "`project-worker`"}]}),
            encoding="utf-8",
        )
        self.assertIn("config/projects/project-worker.json", context("demo", self.root)["required"])

    def test_missing_project_table_after_s1_is_actionable(self):
        self.write_state("S4", "")
        with self.assertRaisesRegex(ValueError, "state has no project rows after S1"):
            context("demo", self.root)

    def run_cli(self, *arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(["--workspace", str(self.root), *arguments])
        return code, json.loads(stdout.getvalue() or stderr.getvalue())

    def test_delivery_public_interfaces_report_unverified_current_and_stale(self):
        self.write_state("S6", "| 项目 | 阶段 | 行状态 |\n|---|---|---|\n| project-worker | S6 | 已完成 |")
        before = {p.name: p.read_bytes() for p in self.task.iterdir()}
        payload = context("demo", self.root)
        self.assertEqual(payload["delivery"]["status"], "UNVERIFIED")
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.task.iterdir()})
        self.assertEqual(self.run_cli("delivery-check", "demo")[0], 2)

        (self.task / "delivery.md").write_text("# Delivery\n- 交付状态: CURRENT\n", encoding="utf-8")
        code, payload = self.run_cli("delivery-record", "demo")
        self.assertEqual((code, payload["status"]), (0, "CURRENT"))
        self.assertEqual(self.run_cli("delivery-check", "demo")[0], 0)
        self.assertEqual(context("demo", self.root)["delivery"]["status"], "CURRENT")

        (self.task / "verify.md").write_text("new verification evidence\n", encoding="utf-8")
        code, payload = self.run_cli("delivery-check", "demo")
        self.assertEqual((code, payload["status"]), (2, "STALE"))
        code, payload = self.run_cli("context", "demo")
        self.assertEqual(code, 0)
        self.assertEqual(payload["delivery"]["status"], "STALE")

    def test_delivery_record_rejects_rework_and_invalid_task_id(self):
        self.write_state("S4", "| 项目 | 阶段 | 行状态 |\n|---|---|---|\n| project-worker | S4 | 进行中 |")
        (self.task / "delivery.md").write_text("- 交付状态: CURRENT\n", encoding="utf-8")
        code, payload = self.run_cli("delivery-record", "demo")
        self.assertEqual(code, 1)
        self.assertIn("S5 or S6", payload["error"])
        self.assertFalse((self.task / "delivery-snapshot.json").exists())
        self.assertEqual(self.run_cli("delivery-check", "../outside")[0], 1)

    def test_default_route_skips_blocked_waiting_and_completed_projects(self):
        self.write_state(
            "S3",
            "| 项目 | 阶段 | 行状态 |\n|---|---|---|\n"
            "| project-worker | S3 | BLOCKED（等待修复） |\n"
            "| project-api | S4 | 进行中 |\n"
            "| project-report | S5 | 等待闸口C |",
        )
        payload = context("demo", self.root)
        self.assertEqual((payload["stage"], payload["project"], payload["runnable"]), ("S4", "project-api", True))
        self.assertIn("workflow/stages/S4/SKILL.md", payload["required"])
        self.assertIn("work/demo/analysis.md", payload["required"])
        self.assertNotIn("config/projects/project-worker.json", payload["required"])
        self.assertNotIn("workflow/stages/S3/SKILL.md", payload["required"])
        code, selected = self.run_cli("context", "demo", "--project", "project-worker")
        self.assertEqual(code, 0)
        self.assertEqual((selected["stage"], selected["route_status"]), ("S3", "BLOCKED"))

    def test_earliest_executable_stage_wins_over_table_order(self):
        self.write_state(
            "S3", "| 项目 | 阶段 | 行状态 |\n|---|---|---|\n"
            "| project-api | S4 | 进行中 |\n| project-worker | S3 | 完成本地实现，待验证 |",
        )
        payload = context("demo", self.root)
        self.assertEqual((payload["stage"], payload["project"]), ("S3", "project-worker"))

    def test_history_cannot_override_current_phase_or_status(self):
        path = self.write_state("S3", "| 项目 | 阶段 | 行状态 |\n|---|---|---|\n| project-worker | S3 | 进行中 |")
        with path.open("a", encoding="utf-8") as handle:
            handle.write("\n## 历史记录\n- 环节: S6\n- 状态: 已完成\n")
        parsed = parse_state(path)
        self.assertEqual((parsed["环节"], parsed["状态"]), ("S3", "进行中"))
        payload = context("demo", self.root)
        self.assertEqual((payload["stage"], payload["lifecycle"]["state"]), ("S3", "ACTIVE"))

    def test_partial_requirement_completion_is_not_a_terminal_state(self):
        state = self.write_state("S1", "")
        state.write_text(state.read_text(encoding="utf-8").replace("- 状态: 进行中", "- 状态: 完成影响分析待S2"), encoding="utf-8")
        self.assertTrue(context("demo", self.root)["runnable"])

    def test_completed_readonly_dependency_is_not_repeated_while_implementation_waits(self):
        self.write_state("S4", "| 项目 | 阶段 | 行状态 |\n|---|---|---|\n"
                         "| project-api | S4 | 只读验证完成 |\n"
                         "| project-worker | S4 | 等待人工联测 |")
        payload = context("demo", self.root)
        self.assertEqual(payload["route_status"], "WAITING")
        self.assertFalse(payload["runnable"])
        readonly = context("demo", self.root, "project-api")
        self.assertEqual(readonly["route_status"], "COMPLETE")
        self.assertFalse(readonly["runnable"])

    def test_no_executable_project_exposes_waiting_without_an_execution_skill(self):
        for status, expected in (("BLOCKED", "BLOCKED"), ("等待闸口C", "WAITING")):
            self.write_state("S4", "| 项目 | 阶段 | 行状态 |\n|---|---|---|\n"
                             "| project-worker | S4 | {} |\n| project-api | S5 | 等待闸口C |".format(status))
            payload = context("demo", self.root)
            self.assertEqual(payload["route_status"], expected)
            self.assertIsNone(payload["project"])
            self.assertIsNone(payload["stage"])
            self.assertEqual(payload["required"], ["work/demo/state.md"])
            self.assertFalse(payload["runnable"])

    def test_completed_archive_keeps_all_project_cleanup_context(self):
        self.write_state("S6", "| 项目 | 阶段 | 行状态 |\n|---|---|---|\n"
                         "| project-worker | S6 | 已完成 |\n| project-api | S6 | COMPLETE |")
        payload = context("demo", self.root)
        self.assertEqual((payload["stage"], payload["project"], payload["route_status"]), ("S6", None, "COMPLETE"))
        self.assertFalse(payload["runnable"])
        self.assertIn("workflow/extensions/dual-baseline-test.md", payload["required"])
        self.assertIn("config/projects/project-api.json", payload["required"])
        self.assertIn("config/projects/project-worker.json", payload["required"])

    def test_explicit_archive_does_not_reopen_a_legacy_free_text_project_status(self):
        state = self.write_state("S6", "| 项目 | 阶段 | 行状态 |\n|---|---|---|\n"
                                 "| project-worker | S6 | master/dev 均已合入，工作树已清理 |")
        state.write_text(state.read_text(encoding="utf-8").replace("- 状态: 进行中", "- 状态: ARCHIVED，归档完成"), encoding="utf-8")
        self.assertFalse(context("demo", self.root)["runnable"])

    def test_one_project_cannot_archive_while_another_is_still_blocked_in_s4(self):
        self.write_state("S4", "| 项目 | 阶段 | 行状态 |\n|---|---|---|\n"
                         "| project-worker | S6 | 进行中 |\n| project-api | S4 | BLOCKED |")
        self.assertFalse(context("demo", self.root)["runnable"])
        self.assertFalse(context("demo", self.root, "project-worker")["runnable"])

    def test_s2_remains_requirement_level_and_project_selector_is_exact(self):
        self.write_state("S2", "| 项目 | 阶段 | 行状态 |\n|---|---|---|\n"
                         "| project-worker | S2 | 进行中 |\n| project-api | S2 | 进行中 |")
        payload = context("demo", self.root)
        self.assertIsNone(payload["project"])
        self.assertIn("config/projects/project-worker.json", payload["required"])
        self.assertIn("config/projects/project-api.json", payload["required"])
        with self.assertRaisesRegex(ValueError, "requirement-level"):
            context("demo", self.root, "project-worker")
        self.write_state("S3", "| 项目 | 阶段 | 行状态 |\n|---|---|---|\n| project-worker | S3 | 进行中 |")
        for name in ("project", "../project-worker", "project-worker/other"):
            with self.assertRaisesRegex(ValueError, "not declared"):
                context("demo", self.root, name)

    def record_metrics(self, project=None, stage=None, **overrides):
        arguments = dict(task_id="demo", root=self.root, stage=stage, outcome="PASS",
                         input_tokens=None, cached_input_tokens=None, output_tokens=None,
                         reasoning_tokens=None, total_tokens=None, token_source=None,
                         rework_count=0, accepted_units=1, rework_units=0, note="fixture",
                         auto_tokens=False, project=project)
        arguments.update(overrides)
        return record_stage_metrics(**arguments)

    def two_active_projects(self):
        self.write_state("S3", "| 项目 | 阶段 | 行状态 |\n|---|---|---|\n"
                         "| project-worker | S3 | 进行中 |\n| project-report | S3 | 进行中 |")
        return ("project-worker", "project-report")

    def test_metrics_default_target_follows_context_and_wrong_stage_is_rejected(self):
        self.write_state("S3", "| 项目 | 阶段 | 行状态 |\n|---|---|---|\n"
                         "| project-worker | S3 | BLOCKED |\n| project-api | S4 | 进行中 |")
        with self.assertRaisesRegex(ValueError, "match an executable"):
            start_stage_metrics("demo", self.root, "S3", None)
        started = start_stage_metrics("demo", self.root, None, None)
        self.assertEqual((started["stage"], started["project"]), ("S4", "project-api"))
        recorded = self.record_metrics()
        self.assertEqual((recorded["stage"], recorded["project"]), ("S4", "project-api"))
        self.assertIn("- 等待秒数：`NOT_AVAILABLE`", (self.task / "metrics.md").read_text(encoding="utf-8"))

    def test_parallel_project_timers_have_unique_attempts_and_cross_process_appends(self):
        names = self.two_active_projects()
        with ThreadPoolExecutor(max_workers=2) as executor:
            started = list(executor.map(lambda name: start_stage_metrics("demo", self.root, None, None, name), names))
        self.assertEqual({item["attempt"] for item in started}, {1, 2})
        self.assertEqual(len(list((self.task / "scratch/metrics").glob("*-active.json"))), 2)
        with self.assertRaisesRegex(ValueError, "specify --project"):
            self.record_metrics()
        script = (
            "from pathlib import Path; import sys; from workflow.workflowctl import record_stage_metrics; "
            "record_stage_metrics('demo',Path(sys.argv[1]),None,'PASS',None,None,None,None,None,None,0,1,0,'parallel',"
            "auto_tokens=False,project=sys.argv[2])"
        )
        processes = [subprocess.Popen([sys.executable, "-B", "-X", "utf8", "-c", script, str(self.root), name],
                                      cwd=SOURCE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
                     for name in names]
        for process in processes:
            stdout, stderr = process.communicate(timeout=20)
            self.assertEqual(process.returncode, 0, stdout + stderr)
        content = (self.task / "metrics.md").read_text(encoding="utf-8")
        self.assertEqual(content.count("## S3 · 尝试"), 2)
        for name in names:
            self.assertIn("- 项目：`" + name + "`", content)
        self.assertFalse(list((self.task / "scratch/metrics").glob("*-active.json")))

    def test_metrics_cannot_close_another_project_and_can_finish_after_state_changes(self):
        names = self.two_active_projects()
        start_stage_metrics("demo", self.root, None, None, names[0])
        with self.assertRaisesRegex(ValueError, "no active metrics marker"):
            self.record_metrics(names[1])
        self.write_state("S4", "| 项目 | 阶段 | 行状态 |\n|---|---|---|\n"
                         "| project-worker | S4 | 进行中 |\n| project-report | S4 | BLOCKED |")
        with self.assertRaisesRegex(ValueError, "no active metrics marker"):
            self.record_metrics(names[0])
        recorded = self.record_metrics(names[0], "S3")
        self.assertEqual((recorded["stage"], recorded["project"]), ("S3", names[0]))

    def test_single_project_s6_metrics_can_close_after_completion(self):
        table = "| 项目 | 阶段 | 行状态 |\n|---|---|---|\n| project-worker | S6 | {} |"
        self.write_state("S6", table.format("进行中"))
        start_stage_metrics("demo", self.root, None, None)
        self.write_state("S6", table.format("已完成"))
        with self.assertRaisesRegex(ValueError, "executable"):
            start_stage_metrics("demo", self.root, None, None)
        self.assertEqual(self.record_metrics()["project"], "project-worker")

    def test_legacy_unscoped_multi_project_marker_closes_without_guessing_ownership(self):
        self.two_active_projects()
        marker = self.task / "scratch/metrics/S3-active.json"
        marker.parent.mkdir(parents=True)
        marker.write_text(json.dumps({"schema_version": 1, "stage": "S3", "attempt": 1,
                                      "started_at": "2026-09-06T00:00:00+08:00"}), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "unfinished"):
            start_stage_metrics("demo", self.root, None, None, "project-worker")
        recorded = self.record_metrics(stage="S3")
        self.assertIsNone(recorded["project"])
        self.assertFalse(marker.exists())

    def test_waiting_seconds_bounds_preserve_active_marker_on_failure(self):
        self.write_state("S3", "| 项目 | 阶段 | 行状态 |\n|---|---|---|\n| project-worker | S3 | 进行中 |")
        start_stage_metrics("demo", self.root, None, "2026-09-06T00:00:00+08:00")
        with patch("workflow.workflowctl._metric_now", return_value="2026-09-06T00:00:10+08:00"):
            with self.assertRaisesRegex(ValueError, "waiting_seconds"):
                self.record_metrics(waiting_seconds=11)
            recorded = self.record_metrics(waiting_seconds=4)
        self.assertEqual((recorded["elapsed_seconds"], recorded["waiting_seconds"]), (10, 4))
        self.assertIn("- 等待秒数：`4`", (self.task / "metrics.md").read_text(encoding="utf-8"))

    def test_overlapping_projects_sharing_a_session_do_not_duplicate_auto_tokens(self):
        names = self.two_active_projects()
        with patch("workflow.workflowctl.current_codex_session_ids", return_value=["same-session"]):
            for name in names:
                start_stage_metrics("demo", self.root, None, None, name)
        with patch("workflow.workflowctl.collect_runtime_usage") as collector:
            for name in names:
                recorded = self.record_metrics(name, auto_tokens=True)
                self.assertIn("overlapping project timers", recorded["token_source"])
                self.assertIsNone(recorded["tokens"]["total_tokens"])
            collector.assert_not_called()

    def test_backfill_preserves_concurrent_event_append_and_section_boundaries(self):
        document = self.task / "metrics.md"
        document.write_text("## S3 · 尝试 1\n\n- 开始：`2026-09-06T00:00:00+08:00`\n"
                            "- 结束：`2026-09-06T00:00:10+08:00`\n- Token 来源：`NOT_AVAILABLE`\n"
                            "- Token：`NOT_AVAILABLE`\n\n## 返工事件 existing\n\n- 原因：原事件\n", encoding="utf-8")
        self.assertNotIn("返工事件", next(METRIC_SECTION_RE.finditer(document.read_text(encoding="utf-8"))).group(0))
        def collect_with_new_event(*args, **kwargs):
            with metrics_lock(self.task):
                document.write_text(document.read_text(encoding="utf-8") + "\n## 返工事件 concurrent\n\n- 原因：并发追加\n", encoding="utf-8")
            return {"available": True, "source": "fixture", "event_count": 1,
                    "input_tokens": 10, "cached_input_tokens": 0, "output_tokens": 2,
                    "reasoning_tokens": 0, "total_tokens": 12}
        with patch("workflow.workflowctl.collect_runtime_usage", side_effect=collect_with_new_event):
            with self.assertRaisesRegex(ValueError, "changed during backfill"):
                backfill_stage_metrics("demo", self.root, ["S3"], ["fixture-session"], self.root)
        content = document.read_text(encoding="utf-8")
        self.assertIn("返工事件 concurrent", content)
        self.assertIn("- Token：`NOT_AVAILABLE`", content)


if __name__ == "__main__":
    unittest.main()
