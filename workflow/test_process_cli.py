import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SOURCE = Path(__file__).resolve().parent.parent


class ProcessCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.task = self.root / "work/demo"
        self.task.mkdir(parents=True)
        (self.task / "state.md").write_text("- 环节: S4\n- 状态: 进行中\n\n| 项目 | 阶段 | 行状态 |\n|---|---|---|\n| demo | S4 | 进行中 |\n", encoding="utf-8")
        self.command = [sys.executable, "-B", "-X", "utf8", str(SOURCE / "workflow/workflowctl.py"), "--workspace", str(self.root)]
        self.event_args = ["rework-record", "demo", "--event-id", "RW-001", "--type", "defect", "--loop", "L1", "--project", "demo", "--from-stage", "S4", "--to-stage", "S3", "--occurred-at", "NOT_AVAILABLE", "--reason", "测试响应边界错误", "--acceptance", "AC1", "--evidence", "verify.md#失败"]

    def run_cli(self, args):
        result = subprocess.run(self.command + args, capture_output=True, text=True, encoding="utf-8", timeout=20)
        return result.returncode, json.loads(result.stdout or result.stderr)

    def test_record_check_idempotence_and_declared_project(self):
        code, result = self.run_cli(self.event_args)
        self.assertEqual((code, result["status"]), (0, "RECORDED"))
        original = (self.task / "metrics.md").read_bytes()
        code, result = self.run_cli(self.event_args)
        self.assertEqual((code, result["status"]), (0, "ALREADY_RECORDED"))
        self.assertEqual(original, (self.task / "metrics.md").read_bytes())
        code, result = self.run_cli(["rework-check", "demo"])
        self.assertEqual((code, result["event_count"], result["l1_count"]), (0, 1, 1))
        wrong = list(self.event_args)
        wrong[wrong.index("--project") + 1] = "unrelated"
        code, result = self.run_cli(wrong)
        self.assertEqual(code, 1)
        self.assertIn("not declared", result["error"])
        self.assertEqual(original, (self.task / "metrics.md").read_bytes())

    def test_invalid_ledger_is_reported_and_not_counted(self):
        (self.task / "metrics.md").write_text("## 返工事件 bad\n- 类型: defect\n", encoding="utf-8")
        code, result = self.run_cli(["rework-check", "demo"])
        self.assertEqual((code, result["status"], result["event_count"]), (2, "INVALID", 0))

    def test_parallel_event_writers_keep_both_records(self):
        second = list(self.event_args)
        second[second.index("--event-id") + 1] = "RW-002"
        processes = [subprocess.Popen(self.command + args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8") for args in (self.event_args, second)]
        for process in processes:
            out, err = process.communicate(timeout=20)
            self.assertEqual(process.returncode, 0, out + err)
        self.assertEqual(self.run_cli(["rework-check", "demo"])[1]["event_count"], 2)


if __name__ == "__main__":
    unittest.main()
