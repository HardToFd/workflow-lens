import tempfile
import unittest
from pathlib import Path

from gui.server import WorkflowWorkspace


class LifecycleApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "AGENTS.md").write_text("# fixture\n", encoding="utf-8")
        (self.root / "prds").mkdir()
        (self.root / "work/demo").mkdir(parents=True)
        self.app = WorkflowWorkspace(self.root)

    def test_list_and_detail_share_lifecycle_without_completion_substring(self):
        (self.root / "work/demo/state.md").write_text("- 环节: S3\n- 状态: 完成本地实现，未验证\n", encoding="utf-8")
        listing = self.app.list_tasks()[0]
        detail = self.app.task_detail("demo")
        self.assertEqual(listing["lifecycle"], detail["lifecycle"])
        self.assertEqual(detail["lifecycle"]["state"], "ACTIVE")

    def test_old_status_header_and_code_formatted_project(self):
        content = "- 环节: S6\n- 状态: 已完成\n\n| 项目 | 阶段 | 状态 |\n|---|---|---|\n| `demo` | S6 | 已完成（无 MR 验收） |\n"
        parsed = self.app.parse_state(content)
        self.assertEqual(parsed["projects"][0]["project"], "demo")
        self.assertEqual(parsed["projects"][0]["row_status"], "已完成（无 MR 验收）")

    def test_history_cannot_supply_missing_top_phase(self):
        (self.root / "work/demo/state.md").write_text("- 状态: 进行中\n\n## 历史记录\n- 环节: S6\n- 状态: 已完成\n", encoding="utf-8")
        listing = self.app.list_tasks()[0]
        self.assertEqual(listing["phase"], "未开始")
        self.assertEqual(listing["lifecycle"]["state"], "ACTIVE")


if __name__ == "__main__":
    unittest.main()
