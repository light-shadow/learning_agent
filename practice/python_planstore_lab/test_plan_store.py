"""PlanStore Lab 的确定性测试。"""

import unittest

from plan_store import (
    Evidence,
    EvidenceKind,
    Plan,
    PlanError,
    PlanStep,
    PlanStore,
    RevisionRequest,
    StepStatus,
    all_steps_completed_contract,
    criterion_step_verifier,
)


def make_plan() -> Plan:
    """构造会话过期修复任务的最小计划。"""
    return Plan(
        goal="修复会话过期边界",
        constraints=["仅修改会话过期判断"],
        steps=[
            PlanStep("s1", "确认实现位置", [], ["source_located"]),
            PlanStep("s2", "复现目标失败", ["s1"], ["target_failure_reproduced"]),
            PlanStep("s3", "完成最小修复", ["s2"], ["allowed_diff_created"]),
            PlanStep(
                "s4",
                "完成分层验证",
                ["s3"],
                ["target_passed", "boundary_passed", "regression_passed"],
            ),
            PlanStep("s5", "写交付说明", ["s4"], ["delivery_written"]),
        ],
    )


def make_evidence(
    evidence_id: str,
    step_id: str,
    criterion: str,
    *,
    version: int = 0,
    kind: EvidenceKind = EvidenceKind.INSPECTION,
) -> Evidence:
    """构造模拟 Runtime 产生的已通过证据。"""
    return Evidence(
        id=evidence_id,
        step_id=step_id,
        tool_call_id=f"call-{evidence_id}",
        artifact_version=version,
        kind=kind,
        payload={"criterion": criterion, "passed": True},
    )


class PlanStoreTest(unittest.TestCase):
    """验证 Planning 的依赖、证据和修订门禁。"""

    def setUp(self) -> None:
        """为每个用例创建隔离的 PlanStore。"""
        self.store = PlanStore(
            make_plan(),
            criterion_step_verifier,
            all_steps_completed_contract,
        )

    def complete_step(self, step_id: str, *evidences: Evidence) -> None:
        """登记证据并完成一个已就绪步骤，减少测试重复代码。"""
        self.store.start(step_id)
        for evidence in evidences:
            self.store.record_evidence(evidence)
        self.store.complete(step_id, [evidence.id for evidence in evidences])

    def complete_s1_and_s2(self) -> None:
        """完成定位和复现步骤，为修订或修改步骤准备前置条件。"""
        self.complete_step(
            "s1",
            make_evidence("e1", "s1", "source_located"),
        )
        self.complete_step(
            "s2",
            make_evidence(
                "e2",
                "s2",
                "target_failure_reproduced",
                kind=EvidenceKind.TEST,
            ),
        )

    def test_start_rejects_unfinished_dependency(self) -> None:
        """前置未完成时，开始下游步骤必须被拒绝。"""
        with self.assertRaisesRegex(PlanError, "尚未就绪") as error:
            self.store.start("s2")
        self.assertEqual("PLAN_STEP_NOT_READY", error.exception.code)

    def test_complete_rejects_missing_evidence(self) -> None:
        """模型没有引用证据时，步骤不能完成。"""
        self.store.start("s1")
        with self.assertRaises(PlanError) as error:
            self.store.complete("s1", [])
        self.assertEqual("PLAN_COMPLETION_REQUIRES_EVIDENCE", error.exception.code)

    def test_block_records_reason_and_keeps_downstream_step_not_ready(self) -> None:
        """步骤被阻塞后必须保留原因，且不能满足下游依赖。"""
        self.complete_s1_and_s2()
        self.store.start("s3")
        self.store.block("s3", "等待人工批准修改会话策略")

        blocked_step = self.store.plan.steps[2]
        self.assertEqual(StepStatus.BLOCKED, blocked_step.status)
        self.assertEqual("等待人工批准修改会话策略", blocked_step.last_error)
        self.assertNotIn("s4", self.store.ready_step_ids())
        with self.assertRaises(PlanError) as error:
            self.store.start("s4")
        self.assertEqual("PLAN_STEP_NOT_READY", error.exception.code)

    def test_complete_rejects_other_steps_evidence(self) -> None:
        """引用其他步骤证据时，归属校验必须失败。"""
        self.store.start("s1")
        foreign = make_evidence("e-foreign", "s2", "source_located")
        self.store.record_evidence(foreign)
        with self.assertRaises(PlanError) as error:
            self.store.complete("s1", ["e-foreign"])
        self.assertEqual("PLAN_EVIDENCE_STEP_MISMATCH", error.exception.code)

    def test_complete_rejects_stale_test_evidence(self) -> None:
        """代码变化后，旧版本测试证据不能完成当前步骤。"""
        self.complete_s1_and_s2()
        self.store.start("s3")
        self.store.mark_code_changed()
        self.store.record_evidence(
            make_evidence(
                "e3-old",
                "s3",
                "allowed_diff_created",
                version=0,
                kind=EvidenceKind.DIFF,
            )
        )
        with self.assertRaises(PlanError) as error:
            self.store.complete("s3", ["e3-old"])
        self.assertEqual("PLAN_EVIDENCE_STALE", error.exception.code)

    def test_expected_failure_can_complete_reproduction_step(self) -> None:
        """复现步骤可用明确的失败事实完成，而不是要求 exit code 为零。"""
        self.complete_step(
            "s1",
            make_evidence("e1", "s1", "source_located"),
        )
        self.store.start("s2")
        reproduction = Evidence(
            id="e2",
            step_id="s2",
            tool_call_id="call-e2",
            artifact_version=0,
            kind=EvidenceKind.TEST,
            payload={
                "criterion": "target_failure_reproduced",
                "passed": True,
                "exit_code": 1,
                "expected": True,
                "actual": False,
                "assertion_location": "session_policy_test.py:10",
            },
        )
        self.store.record_evidence(reproduction)
        self.store.complete("s2", ["e2"])
        self.assertEqual(StepStatus.COMPLETED, self.store.plan.steps[1].status)

    def test_revision_replaces_step_and_rewires_downstream_dependency(self) -> None:
        """修订成功后保留旧步骤历史，并将下游依赖改接到替代步骤。"""
        self.complete_s1_and_s2()
        root_cause = make_evidence("e-root", "s2", "target_failure_reproduced")
        self.store.record_evidence(root_cause)
        replacement = PlanStep(
            "s3b",
            "修复到期时刻比较",
            ["s2"],
            ["allowed_diff_created"],
        )
        self.store.revise(
            RevisionRequest(
                expected_version=1,
                reason="源码证据指向到期时刻比较",
                evidence_ids=["e-root"],
                replace_step_id="s3",
                replacement=replacement,
            )
        )
        statuses = {step.id: step.status for step in self.store.plan.steps}
        dependencies = {step.id: step.depends_on for step in self.store.plan.steps}
        self.assertEqual(StepStatus.SKIPPED, statuses["s3"])
        self.assertEqual(["s3b"], dependencies["s4"])
        self.assertEqual(2, self.store.plan.version)

    def test_revision_rejects_version_conflict_without_mutating_plan(self) -> None:
        """基于旧版本修订时，原计划版本和步骤状态必须保持不变。"""
        self.complete_s1_and_s2()
        root_cause = make_evidence("e-root", "s2", "target_failure_reproduced")
        self.store.record_evidence(root_cause)
        before = self.store.plan
        with self.assertRaises(PlanError) as error:
            self.store.revise(
                RevisionRequest(
                    expected_version=2,
                    reason="故意使用错误版本",
                    evidence_ids=["e-root"],
                    replace_step_id="s3",
                    replacement=PlanStep("s3b", "替代步骤", ["s2"], ["allowed_diff_created"]),
                )
            )
        self.assertEqual("PLAN_VERSION_CONFLICT", error.exception.code)
        self.assertEqual(before.version, self.store.plan.version)
        self.assertEqual(StepStatus.PENDING, self.store.plan.steps[2].status)

    def test_revision_rejects_cycle_without_mutating_plan(self) -> None:
        """替代步骤依赖下游步骤形成环时，整次修订必须原子拒绝。"""
        self.complete_s1_and_s2()
        root_cause = make_evidence("e-root", "s2", "target_failure_reproduced")
        self.store.record_evidence(root_cause)
        before_version = self.store.plan.version
        with self.assertRaises(PlanError) as error:
            self.store.revise(
                RevisionRequest(
                    expected_version=1,
                    reason="故意构造依赖环",
                    evidence_ids=["e-root"],
                    replace_step_id="s3",
                    replacement=PlanStep(
                        "s3b",
                        "错误替代步骤",
                        ["s4"],
                        ["allowed_diff_created"],
                    ),
                )
            )
        self.assertEqual("PLAN_DEPENDENCY_CYCLE", error.exception.code)
        self.assertEqual(before_version, self.store.plan.version)
        self.assertEqual(StepStatus.PENDING, self.store.plan.steps[2].status)


if __name__ == "__main__":
    unittest.main(verbosity=2)

