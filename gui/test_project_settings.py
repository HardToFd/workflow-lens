"""Project settings persistence against isolated registries and the real CLI router."""

import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gui.server import ApiError, WorkflowWorkspace
from workflow.workflowctl import _project_context_files
from workflow.delivery import SNAPSHOT, record_delivery


class ProjectSettingsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="workflow-project-settings-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "workspace"
        self.root.mkdir()
        (self.root / "AGENTS.md").write_text("# fixture\n", encoding="utf-8")
        (self.root / "prds").mkdir()
        (self.root / "config" / "projects" / "custom").mkdir(parents=True)
        self.repo("demo")
        self.index_path = self.root / "config/projects/index.json"
        self.detail_path = self.root / "config/projects/custom/demo-settings.json"
        self.markdown_path = self.root / "config/projects.md"
        self.data = {
            "schema_version": 1, "name": "demo", "path": "repos/demo/",
            "conventions": ["AGENTS.md"], "verification": ["python -m unittest"],
            "branch_model": {"base": "origin/main", "feature": "feature/<id>", "delivery_target": "main", "custom": "preserve"},
            "extensions": [], "change_tracking": {"required": True, "document_path": "docs/<id>.md"},
            "request_form_generation": {"required": True, "custom": "preserve"},
            "approval_policy": {"R0": "auto", "R1": "gate_b", "R2": "gate_b", "R3": "gate_b"},
            "custom": {"nested": [1, 2]}, "read_only": False,
        }
        self.write_json(self.detail_path, self.data)
        self.index = {"schema_version": 1, "custom": "preserve", "projects": [
            {"name": "demo", "path": "repos/demo/", "signals": ["demo signal"], "detail": "config/projects/custom/demo-settings.json", "custom": "preserve"}
        ]}
        self.write_json(self.index_path, self.index)
        self.markdown_path.write_text(
            "# projects\n\n## demo\n\n- 路径: `repos/demo/`\n- 规范文件: `OLD.md`\n"
            "- 验证命令: `old-command`\n- 分支模型: stale markdown\n- 流程扩展: 无\n\n<!-- sentinel -->\n",
            encoding="utf-8",
        )
        (self.root / "config/skills.md").write_text("# skills\n", encoding="utf-8")
        (self.root / "config/capabilities.md").write_text("# capabilities\n\n## 当前运行设置\n\n- 运行档位偏好: 自动检测\n", encoding="utf-8")
        self.app = WorkflowWorkspace(self.root)
        # Skill discovery is unrelated to project persistence and must not inspect the user's home.
        self.addCleanup(patch.stopall)
        patch.object(self.app, "_skills_snapshot", return_value=([], [], 0, 0)).start()
        patch.object(self.app, "_prepare_skills", side_effect=lambda content, rows: (content, [])).start()

    def repo(self, name):
        path = self.root / "repos" / name
        path.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(path)], check=True, capture_output=True)
        return path

    @staticmethod
    def write_json(path, data):
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def assert_status(self, status, action):
        with self.assertRaises(ApiError) as raised:
            action()
        self.assertEqual(status, raised.exception.status)

    def test_save_updates_cli_authority_and_preserves_hidden_fields(self):
        payload = self.app.settings()
        row = payload["projects"]["rows"][0]
        self.assertEqual(["python -m unittest"], row["commands"])
        self.assertIn("origin/main", row["branch_model"])
        row.update(commands=["git diff --check", "python -m unittest discover"], branch_model="从 `origin/release` 拉 `fix/<需求id>`;MR 合入 `release`")
        saved = self.app.save_settings(payload)
        selected = _project_context_files(self.root, {"projects": [{"project": "demo"}]}, "S4")
        self.assertEqual(["config/projects/custom/demo-settings.json"], selected)
        cli_data = json.loads((self.root / selected[0]).read_text(encoding="utf-8"))
        self.assertEqual(row["commands"], cli_data["verification"])
        self.assertEqual("origin/release", cli_data["branch_model"]["base"])
        for key in ("change_tracking", "request_form_generation", "approval_policy", "read_only", "custom"):
            self.assertEqual(self.data[key], cli_data[key])
        self.assertEqual("preserve", cli_data["branch_model"]["custom"])
        self.assertEqual(self.index, json.loads(self.index_path.read_text(encoding="utf-8")))
        markdown = self.markdown_path.read_text(encoding="utf-8")
        self.assertIn("python -m unittest discover", markdown)
        self.assertIn("origin/release", markdown)
        self.assertIn("<!-- sentinel -->", markdown)
        self.assertEqual(row["commands"], saved["projects"]["rows"][0]["commands"])

    def test_new_project_is_registered_for_cli(self):
        repo = self.repo("imported")
        payload = self.app.settings()
        row = self.app.inspect_project(str(repo))
        row["branch_model"] = "从 `origin/main` 拉 `feature/<需求id>`，MR 合入 `main`"
        payload["projects"]["rows"].append(row)
        self.app.save_settings(payload)
        selected = _project_context_files(self.root, {"projects": [{"project": "imported"}]}, "S4")
        self.assertEqual(["config/projects/imported.json"], selected)
        data = json.loads((self.root / selected[0]).read_text(encoding="utf-8"))
        self.assertTrue(data["change_tracking"]["required"])
        self.assertEqual("gate_b", data["approval_policy"]["R3"])
        index = json.loads(self.index_path.read_text(encoding="utf-8"))
        self.assertEqual(["imported"], index["projects"][1]["signals"])

    def test_readonly_external_source_is_preserved_when_editing_other_project(self):
        legacy = copy.deepcopy(self.data)
        legacy.update(name="legacy", path="../legacy/", read_only=True)
        legacy["branch_model"].update(feature="disabled", delivery_target="demo/main")
        legacy_path = self.root / "config/projects/legacy.json"
        self.write_json(legacy_path, legacy)
        self.index["projects"].append({"name": "legacy", "path": "../legacy/", "signals": ["legacy"], "detail": "config/projects/legacy.json"})
        self.write_json(self.index_path, self.index)
        original = legacy_path.read_bytes()
        payload = self.app.settings()
        payload["projects"]["rows"][0]["commands"] = ["new-command"]
        self.app.save_settings(payload)
        self.assertEqual(original, legacy_path.read_bytes())
        payload = self.app.settings()
        payload["projects"]["rows"][1]["path"] = "../different/"
        self.assert_status(400, lambda: self.app.save_settings(payload))

    def test_stale_detail_or_index_revision_is_rejected(self):
        for path in (self.detail_path, self.index_path, self.markdown_path):
            payload = self.app.settings()
            path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            changed = path.read_bytes()
            self.assert_status(409, lambda: self.app.save_settings(payload))
            self.assertEqual(changed, path.read_bytes())

    def test_unchanged_index_is_guarded_during_save(self):
        payload = self.app.settings()
        payload["projects"]["rows"][0]["commands"] = ["new-command"]
        original = self.app._prepare_capabilities
        def change_index(content, mode):
            self.index_path.write_text(self.index_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            return original(content, mode)
        before = self.detail_path.read_bytes()
        with patch.object(self.app, "_prepare_capabilities", side_effect=change_index):
            self.assert_status(409, lambda: self.app.save_settings(payload))
        self.assertEqual(before, self.detail_path.read_bytes())

    def test_failed_markdown_write_rolls_back_json_and_new_registration(self):
        self.repo("imported")
        payload = self.app.settings()
        payload["projects"]["rows"][0]["commands"] = ["new-command"]
        payload["projects"]["rows"].append({"name": "imported", "path": "repos/imported/", "specifications": "无", "commands": ["git diff --check"], "branch_model": "从 `origin/main` 拉 `feature/<需求id>`;MR 合入 `main`"})
        before = {path: path.read_bytes() for path in (self.index_path, self.detail_path, self.markdown_path)}
        original = self.app._atomic_write
        def fail_markdown(path, content):
            if path == self.markdown_path:
                raise OSError("simulated failure")
            return original(path, content)
        with patch.object(self.app, "_atomic_write", side_effect=fail_markdown):
            with self.assertRaises(OSError):
                self.app.save_settings(payload)
        self.assertEqual(before, {path: path.read_bytes() for path in before})
        self.assertFalse((self.root / "config/projects/imported.json").exists())

    def test_unmappable_branch_and_unsafe_detail_are_rejected(self):
        payload = self.app.settings()
        payload["projects"]["rows"][0]["branch_model"] = "main only"
        self.assert_status(400, lambda: self.app.save_settings(payload))
        self.index["projects"][0]["detail"] = "config/projects/../../AGENTS.md"
        self.write_json(self.index_path, self.index)
        self.assert_status(400, self.app.settings)

    def test_dual_baseline_cannot_deliver_to_dev(self):
        self.data["branch_model"].update(base="origin/master", delivery_target="master")
        self.data["extensions"] = ["dual-baseline-test"]
        self.data["dual_baseline"] = {"test_base": "origin/dev", "test_branch": "test/<id>", "integration": "manual dev validation"}
        self.write_json(self.detail_path, self.data)
        payload = self.app.settings()
        payload["projects"]["rows"][0]["branch_model"] = payload["projects"]["rows"][0]["branch_model"].replace("MR 合入 `master`", "MR 合入 `dev`")
        before = self.detail_path.read_bytes()
        self.assert_status(400, lambda: self.app.save_settings(payload))
        self.assertEqual(before, self.detail_path.read_bytes())

    def test_unregistered_markdown_section_is_preserved(self):
        note = "\n## legacy-not-registered\n\n- 路径: `legacy/`\n- 规范文件: `README.md`\n- 验证命令: `git diff --check`\n- 分支模型: legacy\n\nUSER-OWNED-MIGRATION-NOTE\n"
        self.markdown_path.write_text(self.markdown_path.read_text(encoding="utf-8") + note, encoding="utf-8")
        payload = self.app.settings()
        payload["projects"]["rows"][0]["commands"] = ["updated-command"]
        self.app.save_settings(payload)
        self.assertIn(note, self.markdown_path.read_text(encoding="utf-8"))

    def test_no_index_keeps_markdown_save_compatibility(self):
        self.index_path.unlink()
        payload = self.app.settings()
        self.assertEqual(["old-command"], payload["projects"]["rows"][0]["commands"])
        payload["projects"]["rows"][0]["commands"] = ["compat-command"]
        before = self.detail_path.read_bytes()
        self.app.save_settings(payload)
        self.assertIn("compat-command", self.markdown_path.read_text(encoding="utf-8"))
        self.assertEqual(before, self.detail_path.read_bytes())
        self.assertFalse(self.index_path.exists())


class DeliveryApprovalTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="workflow-gui-delivery-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "AGENTS.md").write_text("# fixture\n", encoding="utf-8")
        (self.root / "prds").mkdir()
        self.task = self.root / "work/demo-task"
        self.task.mkdir(parents=True)
        self.state_path = self.task / "state.md"
        self.state_path.write_text(
            "# state\n- 环节: S5\n- 状态: 等待闸口\n\n"
            "| 项目 | 工作目录 | 分支 | 联测分支 | 联测状态 | 阶段 | 回修轮次 | MR/PR | 闸口C | 行状态 |\n"
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |\n"
            "| a | /a | feature/a | test/a | PASS | S5 | 0 | !1 | 等待中 | 等待闸口C |\n"
            "| b | /b | feature/b | test/b | PASS | S5 | 0 | !2 | 等待中 | 等待闸口C |\n",
            encoding="utf-8",
        )
        for name in ("plan.md", "impl-log.md", "verify.md"):
            (self.task / name).write_text("# reviewed evidence\n", encoding="utf-8")
        self.delivery_path = self.task / "delivery.md"
        self.delivery_path.write_text("# delivery\n\n- 交付状态: CURRENT\n", encoding="utf-8")
        self.app = WorkflowWorkspace(self.root)

    def record(self):
        parsed = self.app.parse_state(self.state_path.read_text(encoding="utf-8"))
        return record_delivery("demo-task", self.root, {"环节": parsed["top"]["phase"], "projects": parsed["projects"]})

    def approve(self, project="a"):
        return self.app.approve_gate("demo-task", {"gate": "C", "project": project, "result": "已合并", "quote": "已合并，可归档"})

    def assert_rejected(self):
        state_before = self.state_path.read_bytes()
        with self.assertRaises(ApiError) as raised:
            self.approve()
        self.assertEqual(409, raised.exception.status)
        self.assertEqual(state_before, self.state_path.read_bytes())

    def test_absent_unverified_and_stale_delivery_block_gate_c(self):
        self.assert_rejected()
        content = self.delivery_path.read_bytes()
        self.delivery_path.unlink()
        self.assert_rejected()
        self.delivery_path.write_bytes(content)
        self.record()
        (self.task / "plan.md").write_text("# changed scope\n", encoding="utf-8")
        self.assert_rejected()

    def test_current_bundle_supports_consecutive_project_approvals(self):
        self.assertEqual("CURRENT", self.record()["status"])
        before = json.loads((self.task / SNAPSHOT).read_text(encoding="utf-8"))
        first = self.approve("a")
        self.assertEqual("CURRENT", first["delivery"]["status"])
        self.assertEqual("S5", first["top"]["phase"])
        second = self.approve("b")
        self.assertEqual("CURRENT", second["delivery"]["status"])
        self.assertEqual("S6", second["top"]["phase"])
        after = json.loads((self.task / SNAPSHOT).read_text(encoding="utf-8"))
        self.assertEqual(before["inputs"], after["inputs"])
        self.assertEqual(before["projects"], after["projects"])
        self.assertEqual(before["delivery_projects"], after["delivery_projects"])
        self.assertNotEqual(before["artifacts"]["delivery.md"], after["artifacts"]["delivery.md"])

    def test_stale_artifact_has_readonly_warning_and_detail_status(self):
        content = self.delivery_path.read_bytes()
        self.assertTrue(self.app.read_artifact("demo-task", "delivery.md")["content"].startswith("> 交付材料 UNVERIFIED"))
        self.record()
        (self.task / "verify.md").write_text("# changed verification\n", encoding="utf-8")
        self.assertEqual("STALE", self.app.task_detail("demo-task")["delivery"]["status"])
        self.assertTrue(self.app.read_artifact("demo-task", "delivery.md")["content"].startswith("> 交付材料 STALE"))
        self.assertEqual(content, self.delivery_path.read_bytes())

    def test_input_changed_after_current_check_is_not_resigned(self):
        self.record()
        before = (self.task / SNAPSHOT).read_bytes()
        original = self.app._gate_record_change
        def change_input(path, heading, lines):
            result = original(path, heading, lines)
            (self.task / "plan.md").write_text("# concurrent change\n", encoding="utf-8")
            return result
        with patch.object(self.app, "_gate_record_change", side_effect=change_input):
            self.assert_rejected()
        self.assertEqual(before, (self.task / SNAPSHOT).read_bytes())
        self.assertEqual("STALE", self.app.task_detail("demo-task")["delivery"]["status"])


if __name__ == "__main__":
    unittest.main()
