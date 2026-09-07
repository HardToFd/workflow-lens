import tempfile
import unittest
from pathlib import Path

from workflow.rework import check_rework, read_rework, record_rework, validate_event


class ReworkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "work/demo").mkdir(parents=True)
        self.event = dict(id="RW-001", type="defect", loop="L1", project="demo", from_stage="S4", to_stage="S3", occurred_at="2026-09-04T10:11:29Z", reason="原响应构造边界导致隔离合同测试失败", acceptance="AC1", evidence="verify.md#尝试-1")

    def test_event_id_is_idempotent_and_preserves_original_bytes(self):
        path = self.root / "work/demo/metrics.md"
        before = b"# original\r\n\r\n- Token: NOT_AVAILABLE\r\n"
        path.write_bytes(before)
        self.assertEqual(record_rework("demo", self.root, self.event)["status"], "RECORDED")
        after = path.read_bytes()
        self.assertTrue(after.startswith(before))
        self.assertEqual(record_rework("demo", self.root, self.event)["status"], "ALREADY_RECORDED")
        self.assertEqual(path.read_bytes(), after)
        result = check_rework("demo", self.root)
        self.assertEqual(result["event_count"], 1)
        self.assertEqual(result["l1_count"], 1)
        self.assertEqual(result["events"][0]["occurred_at"], "2026-09-04T18:11:29+08:00")

    def test_conflicting_id_refuses_write(self):
        record_rework("demo", self.root, self.event)
        with self.assertRaisesRegex(ValueError, "different content"):
            record_rework("demo", self.root, dict(self.event, reason="different"))

    def test_markdown_code_in_free_text_survives_idempotent_round_trip(self):
        for index, reason in enumerate(("`payload.user_id` was missing", "`payload.user_id`")):
            event = dict(self.event, id="RW-" + str(index), reason=reason, acceptance="`AC1`", evidence="`verify.md`")
            record_rework("demo", self.root, event)
            self.assertEqual(record_rework("demo", self.root, event)["status"], "ALREADY_RECORDED")
            self.assertEqual(check_rework("demo", self.root)["events"][index]["reason"], reason)

    def test_scope_baseline_and_environment_are_not_l1(self):
        for kind in ("scope_change", "baseline_adaptation", "environment", "workflow_migration"):
            with self.assertRaisesRegex(ValueError, "L1 requires"):
                validate_event(dict(self.event, type=kind))
            record_rework("demo", self.root, dict(self.event, id=kind, type=kind, loop="NONE"))
        result = check_rework("demo", self.root)
        self.assertEqual(result["event_count"], 4)
        self.assertEqual(result["l1_count"], 0)

    def test_legacy_counts_are_never_summed(self):
        result = read_rework("## S3 · 尝试 2\n- 返工次数：`4`\n## S4 · 尝试 3\n- 返工次数：`4`\n")
        self.assertEqual(result["legacy_records"], 2)
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(result["event_count"], 0)

    def test_malformed_or_conflicting_duplicate_is_excluded(self):
        record_rework("demo", self.root, self.event)
        text = (self.root / "work/demo/metrics.md").read_text(encoding="utf-8")
        text += text[text.index("## 返工事件"):].replace("原响应构造边界", "另一个原因")
        result = read_rework(text)
        self.assertEqual(result["status"], "INVALID")
        self.assertEqual(result["event_count"], 0)

    def test_rejects_multiline_fields_and_timezone_free_timestamp(self):
        with self.assertRaises(ValueError):
            validate_event(dict(self.event, reason="x\n## spoof"))
        with self.assertRaises(ValueError):
            validate_event(dict(self.event, occurred_at="2026-09-04T18:11:29"))


if __name__ == "__main__":
    unittest.main()
