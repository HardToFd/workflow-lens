import tempfile
import unittest
from pathlib import Path

from workflow.delivery import check_delivery, record_delivery


class DeliveryFreshnessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.task = self.root / "work" / "demo"
        self.task.mkdir(parents=True)
        self.state = {"环节": "S5", "projects": [{"项目": "api", "分支": "feature/demo@aaa",
                                                "联测分支": "test/demo@bbb"}]}
        for name in ("plan.md", "impl-log.md", "verify.md"):
            (self.task / name).write_text("# verified v2\n", encoding="utf-8")
        (self.task / "delivery.md").write_text("# Delivery\n- 交付状态: CURRENT\n", encoding="utf-8")
        (self.task / "delivery").mkdir()
        self.patch = self.task / "delivery" / "0001.patch"
        self.patch.write_text("reviewed patch v2", encoding="utf-8")

    def test_existing_delivery_needs_review_and_read_has_no_writes(self):
        before = {p.relative_to(self.task): p.read_bytes() for p in self.task.rglob("*") if p.is_file()}
        self.assertEqual(check_delivery("demo", self.root, self.state)["status"], "UNVERIFIED")
        after = {p.relative_to(self.task): p.read_bytes() for p in self.task.rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def test_changed_evidence_or_patch_invalidates_reviewed_bundle(self):
        self.assertEqual(record_delivery("demo", self.root, self.state)["status"], "CURRENT")
        for relative in ("plan.md", "impl-log.md", "verify.md", "delivery.md", "delivery/0001.patch"):
            with self.subTest(file=relative):
                path = self.task / relative
                old = path.read_bytes()
                path.write_bytes(old + b"changed")
                self.assertEqual(check_delivery("demo", self.root, self.state)["status"], "STALE")
                path.write_bytes(old)
        self.assertEqual(check_delivery("demo", self.root, self.state)["status"], "CURRENT")

    def test_rework_and_branch_change_reject_old_delivery(self):
        record_delivery("demo", self.root, self.state)
        self.state["环节"] = "S3"
        self.assertEqual(check_delivery("demo", self.root, self.state)["status"], "STALE")
        with self.assertRaisesRegex(ValueError, "S5 or S6"):
            record_delivery("demo", self.root, self.state)
        self.state["环节"] = "S6"
        self.assertEqual(check_delivery("demo", self.root, self.state)["status"], "CURRENT")
        self.state["projects"][0]["分支"] = "feature/demo@new"
        self.assertEqual(check_delivery("demo", self.root, self.state)["status"], "STALE")

    def test_adding_or_removing_attachment_is_stale_history_is_not_current(self):
        record_delivery("demo", self.root, self.state)
        extra = self.task / "delivery" / "0002.patch"
        extra.write_text("new", encoding="utf-8")
        self.assertEqual(check_delivery("demo", self.root, self.state)["status"], "STALE")
        history = self.task / "delivery" / "history"
        history.mkdir()
        extra.rename(history / extra.name)
        self.assertEqual(check_delivery("demo", self.root, self.state)["status"], "CURRENT")
        self.patch.unlink()
        self.assertEqual(check_delivery("demo", self.root, self.state)["status"], "STALE")

    def test_invalidated_delivery_cannot_be_recorded_without_regeneration(self):
        (self.task / "delivery.md").write_text("- 交付状态: STALE\n", encoding="utf-8")
        self.assertEqual(check_delivery("demo", self.root, self.state)["status"], "STALE")
        with self.assertRaisesRegex(ValueError, "regenerate"):
            record_delivery("demo", self.root, self.state)

    def test_record_preserves_previous_snapshot_and_missing_evidence_fails_closed(self):
        record_delivery("demo", self.root, self.state)
        previous = (self.task / "delivery-snapshot.json").read_bytes()
        (self.task / "plan.md").write_text("new reviewed version", encoding="utf-8")
        record_delivery("demo", self.root, self.state)
        archived = list((self.task / "delivery" / "history").glob("snapshot-*.json"))
        self.assertEqual(len(archived), 1)
        self.assertEqual(archived[0].read_bytes(), previous)
        (self.task / "verify.md").unlink()
        self.assertEqual(check_delivery("demo", self.root, self.state)["status"], "STALE")
        with self.assertRaises(OSError):
            record_delivery("demo", self.root, self.state)

    def test_corrupt_snapshot_and_task_traversal_are_rejected(self):
        (self.task / "delivery-snapshot.json").write_text("[]", encoding="utf-8")
        self.assertEqual(check_delivery("demo", self.root, self.state)["status"], "STALE")
        with self.assertRaises(ValueError):
            check_delivery("../outside", self.root, self.state)

    def test_partial_project_delivery_is_valid_but_does_not_cover_new_project(self):
        self.state = {"环节": "S4", "projects": [
            {"项目": "api", "阶段": "S5", "分支": "feature/api@aaa"},
            {"项目": "worker", "阶段": "S4", "分支": "feature/worker@bbb"},
        ]}
        self.assertEqual(record_delivery("demo", self.root, self.state)["status"], "CURRENT")
        self.state["projects"][0]["阶段"] = "S6"
        self.assertEqual(check_delivery("demo", self.root, self.state)["status"], "CURRENT")
        self.state["projects"][1]["阶段"] = "S5"
        self.assertEqual(check_delivery("demo", self.root, self.state)["status"], "STALE")
        record_delivery("demo", self.root, self.state)
        self.state["projects"][0]["阶段"] = "S3"
        self.assertEqual(check_delivery("demo", self.root, self.state)["status"], "STALE")

    def test_prd_and_analysis_revision_invalidate_even_before_stage_is_updated(self):
        (self.root / "prds").mkdir()
        prd = self.root / "prds" / "demo.md"
        analysis = self.task / "analysis.md"
        prd.write_text("approved scope", encoding="utf-8")
        analysis.write_text("approved acceptance", encoding="utf-8")
        record_delivery("demo", self.root, self.state)
        for path in (prd, analysis):
            original = path.read_bytes()
            path.write_bytes(original + b" new contract")
            self.assertEqual(check_delivery("demo", self.root, self.state)["status"], "STALE")
            path.write_bytes(original)


if __name__ == "__main__":
    unittest.main()
