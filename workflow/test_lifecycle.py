import unittest

from workflow.lifecycle import read_lifecycle


class LifecycleTests(unittest.TestCase):
    def test_implementation_complete_is_still_active(self):
        self.assertEqual(read_lifecycle("- 环节: S3\n- 状态: 完成本地实现，待验证\n")["state"], "ACTIVE")

    def test_archival_does_not_prove_runtime_or_cleanup(self):
        result = read_lifecycle("- 环节: S6\n- 状态: 完成\n")
        self.assertEqual(result["state"], "ARCHIVED")
        for field in ("merge", "deployment", "cleanup", "acceptance"):
            self.assertEqual(result[field], "UNKNOWN")

    def test_cancelled_is_distinct(self):
        self.assertEqual(read_lifecycle("- 环节: S6\n- 状态: 已作废（已回滚）\n")["state"], "CANCELLED")

    def test_s6_can_still_be_blocked_or_waiting(self):
        for status, expected in (("BLOCKED（归档检查失败）", "BLOCKED"), ("等待人工验收", "WAITING")):
            self.assertEqual(read_lifecycle("- 环节: S6\n- 状态: " + status + "\n")["state"], expected)
        self.assertEqual(read_lifecycle("- 环节: S6\n## 当前状态摘要\n- 生命周期: BLOCKED\n")["state"], "BLOCKED")

    def test_only_current_section_is_read(self):
        text = "- 环节: S6\n- 状态: 已归档\n## 当前状态摘要\n- 生命周期: ARCHIVED\n- 清理: COMPLETE\n- 状态依据: [后续清理](state.md#清理补充)\n## 旧记录\n- 清理: PENDING\n"
        result = read_lifecycle(text)
        self.assertEqual(result["cleanup"], "COMPLETE")
        self.assertEqual(result["source"], "explicit")

    def test_duplicate_section_and_invalid_enum_do_not_promote(self):
        text = "- 环节: S3\n- 状态: 实现完成\n## 当前状态摘要\n- 生命周期: ARCHIVED\n"
        self.assertEqual(read_lifecycle(text)["state"], "ACTIVE")
        self.assertTrue(read_lifecycle(text)["issues"])
        self.assertEqual(read_lifecycle(text + "## 当前状态摘要\n- 生命周期: ARCHIVED\n")["source"], "legacy")

    def test_evidence_required_for_positive_independent_claims(self):
        text = "- 环节: S6\n## 当前状态摘要\n- 生命周期: ARCHIVED\n- 人工验收: PASS\n- 部署: VERIFIED\n"
        result = read_lifecycle(text)
        self.assertEqual(result["acceptance"], "UNKNOWN")
        self.assertEqual(result["deployment"], "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
