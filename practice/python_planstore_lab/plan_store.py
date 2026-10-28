"""可验证 Planning 的最小 Python 实战实现。"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, Iterable, List, Mapping, Optional, Sequence


class StepStatus(str, Enum):
    """计划步骤的生命周期状态。"""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"
    FAILED = "failed"


class EvidenceKind(str, Enum):
    """证据的来源类型。"""

    INSPECTION = "inspection"
    TEST = "test"
    DIFF = "diff"
    DELIVERY = "delivery"


class PlanError(RuntimeError):
    """携带稳定错误码的计划规则异常。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Evidence:
    """一次真实工具结果形成的、可引用的事实。"""

    id: str
    step_id: str
    tool_call_id: str
    artifact_version: int
    kind: EvidenceKind
    payload: Mapping[str, object]


@dataclass
class PlanStep:
    """带依赖和验收标准的可执行子目标。"""

    id: str
    objective: str
    depends_on: List[str]
    success_criteria: List[str]
    status: StepStatus = StepStatus.PENDING
    evidence_ids: List[str] = field(default_factory=list)
    last_error: Optional[str] = None


@dataclass
class Plan:
    """任务的当前计划快照。"""

    goal: str
    constraints: List[str]
    steps: List[PlanStep]
    version: int = 1
    revision_count: int = 0
    max_revisions: int = 3


@dataclass(frozen=True)
class RevisionRequest:
    """模型提交的、带版本和证据依据的结构性计划变更申请。"""

    expected_version: int
    reason: str
    evidence_ids: List[str]
    replace_step_id: str
    replacement: PlanStep


StepVerifier = Callable[[PlanStep, Sequence[Evidence]], bool]
CompletionContract = Callable[["PlanStore"], bool]


class PlanStore:
    """计划状态的唯一写入者：负责门禁、证据校验和原子修订。"""

    _CURRENT_VERSION_EVIDENCE_KINDS = {
        EvidenceKind.TEST,
        EvidenceKind.DIFF,
    }

    def __init__(
        self,
        plan: Plan,
        step_verifier: StepVerifier,
        completion_contract: CompletionContract,
    ) -> None:
        """创建 PlanStore，并校验初始计划的依赖图。"""
        self.plan = deepcopy(plan)
        self._step_verifier = step_verifier
        self._completion_contract = completion_contract
        self._evidences: Dict[str, Evidence] = {}
        self._current_code_version = 0
        self._validate_plan(self.plan)

    @property
    def current_code_version(self) -> int:
        """返回当前代码版本，用于判断测试和 diff 证据是否新鲜。"""
        return self._current_code_version

    def ready_step_ids(self) -> List[str]:
        """返回所有前置步骤均已完成、允许开始的步骤 ID。"""
        return [
            step.id
            for step in self.plan.steps
            if step.status == StepStatus.PENDING
            and self._all_dependencies_completed(step)
        ]

    def start(self, step_id: str) -> None:
        """仅在步骤待执行且全部依赖完成时，将步骤置为执行中。"""
        step = self._require_step(step_id)
        if step.status != StepStatus.PENDING or not self._all_dependencies_completed(step):
            raise PlanError(
                "PLAN_STEP_NOT_READY",
                f"步骤 {step_id} 尚未就绪，不能开始。",
            )
        step.status = StepStatus.IN_PROGRESS

    def mark_code_changed(self) -> int:
        """在 Runtime 成功写入源码后递增代码版本，并返回新版本号。"""
        self._current_code_version += 1
        return self._current_code_version

    def block(self, step_id: str, reason: str) -> None:
        """将执行中的步骤标记为阻塞，并保留等待人工或外部条件处理的原因。"""
        step = self._require_step(step_id)
        if step.status != StepStatus.IN_PROGRESS:
            raise PlanError(
                "PLAN_STEP_NOT_IN_PROGRESS",
                f"步骤 {step_id} 不在执行中，不能标记为阻塞。",
            )
        if not reason.strip():
            raise PlanError(
                "PLAN_BLOCK_REQUIRES_REASON",
                "阻塞步骤时必须记录具体原因。",
            )
        step.status = StepStatus.BLOCKED
        step.last_error = reason

    def record_evidence(self, evidence: Evidence) -> None:
        """登记 Runtime 产生的真实证据，禁止重复 ID 和未知步骤。"""
        self._require_step(evidence.step_id)
        if evidence.id in self._evidences:
            raise PlanError("PLAN_DUPLICATE_EVIDENCE", f"证据 {evidence.id} 已存在。")
        self._evidences[evidence.id] = evidence

    def complete(self, step_id: str, evidence_ids: Iterable[str]) -> None:
        """校验步骤证据后，将执行中的步骤置为已完成。"""
        step = self._require_step(step_id)
        evidence_ids = list(evidence_ids)
        if step.status != StepStatus.IN_PROGRESS:
            raise PlanError(
                "PLAN_STEP_NOT_IN_PROGRESS",
                f"步骤 {step_id} 不在执行中，不能完成。",
            )
        if not evidence_ids:
            raise PlanError(
                "PLAN_COMPLETION_REQUIRES_EVIDENCE",
                f"步骤 {step_id} 完成时必须引用证据。",
            )

        evidences = [self._require_evidence(evidence_id) for evidence_id in evidence_ids]
        for evidence in evidences:
            if evidence.step_id != step_id:
                raise PlanError(
                    "PLAN_EVIDENCE_STEP_MISMATCH",
                    f"证据 {evidence.id} 不属于步骤 {step_id}。",
                )
            if (
                evidence.kind in self._CURRENT_VERSION_EVIDENCE_KINDS
                and evidence.artifact_version != self._current_code_version
            ):
                raise PlanError(
                    "PLAN_EVIDENCE_STALE",
                    f"证据 {evidence.id} 来自代码版本 {evidence.artifact_version}，"
                    f"当前版本为 {self._current_code_version}。",
                )

        if not self._step_verifier(step, evidences):
            raise PlanError(
                "PLAN_COMPLETION_REJECTED",
                f"步骤 {step_id} 的证据不满足验收标准。",
            )

        step.evidence_ids = evidence_ids
        step.status = StepStatus.COMPLETED

    def revise(self, request: RevisionRequest) -> None:
        """在候选副本上替换步骤并重连下游依赖，全部校验通过才提交。"""
        if request.expected_version != self.plan.version:
            raise PlanError(
                "PLAN_VERSION_CONFLICT",
                f"请求版本 {request.expected_version} 与当前版本 {self.plan.version} 不一致。",
            )
        if not request.reason.strip():
            raise PlanError("PLAN_REVISION_REQUIRES_REASON", "修订必须说明原因。")
        if not request.evidence_ids:
            raise PlanError("PLAN_REVISION_REQUIRES_EVIDENCE", "修订必须引用证据。")
        if self.plan.revision_count >= self.plan.max_revisions:
            raise PlanError("PLAN_MAX_REVISIONS_EXCEEDED", "已超过计划修订上限。")
        for evidence_id in request.evidence_ids:
            self._require_evidence(evidence_id)

        candidate = deepcopy(self.plan)
        old_step = self._find_step(candidate, request.replace_step_id)
        if self._has_step(candidate, request.replacement.id):
            raise PlanError(
                "PLAN_DUPLICATE_STEP_ID",
                f"替代步骤 ID {request.replacement.id} 已存在。",
            )

        old_step.status = StepStatus.SKIPPED
        candidate.steps.append(deepcopy(request.replacement))
        for step in candidate.steps:
            step.depends_on = [
                request.replacement.id if dependency == old_step.id else dependency
                for dependency in step.depends_on
            ]

        self._validate_plan(candidate)
        candidate.version += 1
        candidate.revision_count += 1
        self.plan = candidate

    def can_deliver(self) -> bool:
        """调用任务级完成契约，判断当前计划是否可以交付。"""
        return self._completion_contract(self)

    def evidence(self, evidence_id: str) -> Evidence:
        """按 ID 返回已登记证据，供完成契约和测试检查。"""
        return self._require_evidence(evidence_id)

    def _all_dependencies_completed(self, step: PlanStep) -> bool:
        """判断一个步骤的所有前置是否均为 COMPLETED。"""
        return all(
            self._require_step(dependency).status == StepStatus.COMPLETED
            for dependency in step.depends_on
        )

    def _require_step(self, step_id: str) -> PlanStep:
        """返回存在的当前计划步骤，不存在时抛出稳定错误码。"""
        return self._find_step(self.plan, step_id)

    @staticmethod
    def _find_step(plan: Plan, step_id: str) -> PlanStep:
        """在指定计划中查找步骤，不存在时拒绝操作。"""
        for step in plan.steps:
            if step.id == step_id:
                return step
        raise PlanError("PLAN_UNKNOWN_STEP", f"不存在步骤 {step_id}。")

    @staticmethod
    def _has_step(plan: Plan, step_id: str) -> bool:
        """判断指定计划是否已包含某个步骤 ID。"""
        return any(step.id == step_id for step in plan.steps)

    def _require_evidence(self, evidence_id: str) -> Evidence:
        """返回已登记证据，不存在时拒绝引用。"""
        try:
            return self._evidences[evidence_id]
        except KeyError as error:
            raise PlanError(
                "PLAN_UNKNOWN_EVIDENCE",
                f"不存在证据 {evidence_id}。",
            ) from error

    @staticmethod
    def _validate_plan(plan: Plan) -> None:
        """校验步骤 ID 唯一、依赖存在且依赖图无环。"""
        step_ids = [step.id for step in plan.steps]
        if len(step_ids) != len(set(step_ids)):
            raise PlanError("PLAN_DUPLICATE_STEP_ID", "计划中存在重复步骤 ID。")

        known_ids = set(step_ids)
        for step in plan.steps:
            for dependency in step.depends_on:
                if dependency not in known_ids:
                    raise PlanError(
                        "PLAN_UNKNOWN_DEPENDENCY",
                        f"步骤 {step.id} 依赖不存在的步骤 {dependency}。",
                    )

        graph = {step.id: step.depends_on for step in plan.steps}
        visiting = set()
        visited = set()

        def visit(step_id: str) -> None:
            """深度优先遍历依赖图，发现回边时报告环。"""
            if step_id in visiting:
                raise PlanError("PLAN_DEPENDENCY_CYCLE", "计划依赖图存在环。")
            if step_id in visited:
                return
            visiting.add(step_id)
            for dependency in graph[step_id]:
                visit(dependency)
            visiting.remove(step_id)
            visited.add(step_id)

        for step_id in graph:
            visit(step_id)


def criterion_step_verifier(step: PlanStep, evidences: Sequence[Evidence]) -> bool:
    """要求步骤的每项成功标准都被至少一份 passed 证据覆盖。"""
    proven_criteria = {
        str(evidence.payload.get("criterion"))
        for evidence in evidences
        if evidence.payload.get("passed") is True
    }
    return set(step.success_criteria).issubset(proven_criteria)


def all_steps_completed_contract(store: PlanStore) -> bool:
    """示例任务级完成契约：所有步骤完成且至少发生过一次代码变更。"""
    return (
        store.current_code_version > 0
        and all(step.status == StepStatus.COMPLETED for step in store.plan.steps)
    )

