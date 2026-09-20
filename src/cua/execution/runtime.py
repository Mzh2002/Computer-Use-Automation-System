"""Shared execution, outcome handling and control-transfer state machine."""

import re
import time
from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from pathlib import Path

from cua.core.evidence import Evidence
from cua.core.schemas import Capability, Condition, FieldSpec, RunResult, Step
from cua.execution.policy import Policy, PolicyViolation
from cua.surfaces.playwright import BrowserSurface, SurfaceError


class StopRun(Exception):
    def __init__(self, code: str, status="failure"):
        self.code = code
        self.status = status
        super().__init__(code)


def validate_fields(values: dict[str, str], specs: dict[str, FieldSpec]):
    if set(values) != set(specs):
        raise ValueError("FIELD_SET_MISMATCH")
    for key, spec in specs.items():
        value = values[key]
        if not isinstance(value, str):
            raise ValueError("FIELD_TYPE_MISMATCH")
        if spec.pattern and not re.fullmatch(spec.pattern, value):
            raise ValueError("FIELD_PATTERN_MISMATCH")
        if spec.type == "decimal":
            try:
                if not Decimal(value).is_finite() or not re.fullmatch(r"-?[0-9]+\.[0-9]{2}", value):
                    raise ValueError("INVALID_DECIMAL")
            except InvalidOperation as exc:
                raise ValueError("INVALID_DECIMAL") from exc
        if spec.type == "currency" and not re.fullmatch(r"[A-Z]{3}", value):
            raise ValueError("INVALID_CURRENCY")


# A handler operates the same BrowserSurface and signals ready; it never restarts it.
HumanHandler = Callable[[BrowserSurface, str], bool]


class Execution:
    def __init__(
        self,
        capability: Capability,
        inputs: dict[str, str],
        policy: Policy,
        surface: BrowserSurface,
        evidence: Evidence,
        human: HumanHandler | None = None,
    ):
        self.capability = capability
        self.inputs = inputs
        self.policy = policy
        self.surface = surface
        self.evidence = evidence
        self.human = human
        self.outputs: dict[str, str] = {}
        self.current_step: str | None = None
        self.deadline = time.monotonic() + policy.max_seconds
        self.retries = 0
        self.interventions = 0
        self.action_count = 0

    def budget(self):
        if time.monotonic() > self.deadline:
            raise StopRun("RUN_TIMEOUT")
        if self.action_count >= self.policy.max_steps:
            raise StopRun("STEP_BUDGET_EXCEEDED")

    def handoff(self, reason: str, resume: Condition | None = None):
        self.interventions += 1
        if self.interventions > 3:
            raise StopRun("INTERVENTION_LIMIT")
        self.surface.set_owner("PAUSED")
        self.evidence.event("intervention_requested", code=reason, step_id=self.current_step)
        self.evidence.snapshot(self.surface, "before-handoff")
        if self.human is None:
            # No misleading live-session claim: a headless unattended run terminates here.
            raise StopRun("HUMAN_REQUIRED")
        started = time.monotonic()
        self.surface.set_owner("HUMAN")
        if not self.human(self.surface, reason):
            raise StopRun("HUMAN_ABORTED")
        self.surface.page.wait_for_timeout(50)  # Flush manual browser events before changing owner.
        self.surface.set_owner("VALIDATING")
        self.surface.assert_allowed()
        if any(
            rule.category == "human" and self.surface.visible(rule.target)
            for rule in self.capability.outcomes
        ):
            raise StopRun("RESUME_NOT_READY")
        if any(
            frame.locator('dialog[open], [role="dialog"]').count()
            for frame in self.surface.page.frames
        ):
            raise StopRun("RESUME_NOT_READY")
        if resume:
            try:
                self.surface.check(resume, self.inputs)
            except SurfaceError as exc:
                raise StopRun("RESUME_CHECKPOINT_FAILED") from exc
        self.evidence.snapshot(self.surface, "after-handoff")
        self.evidence.event("resume_validated", checkpoint="passed", step_id=self.current_step)
        self.surface.set_owner("AUTOMATION")
        # Operator time is excluded; the terminal handler has its own five-minute budget.
        self.deadline += time.monotonic() - started

    def outcomes(self, resume: Condition | None = None):
        self.surface.assert_allowed()
        for rule in self.capability.outcomes:
            if not self.surface.visible(rule.target):
                continue
            self.evidence.event("outcome_detected", code=rule.code, step_id=self.current_step)
            if rule.category == "business":
                raise StopRun(rule.code, "business_outcome")
            if rule.category == "failure":
                raise StopRun(rule.code)
            if rule.category == "human":
                self.handoff(rule.code, resume)
                return True
            if rule.category == "retry":
                if self.retries >= self.policy.max_retries:
                    raise StopRun("RETRY_EXHAUSTED")
                self.retries += 1
                self.budget()
                self.action_count += 1
                self.evidence.event("recovery_attempt", attempt=self.retries, code=rule.code)
                self.surface.execute(Step(id="recovery", action="click", target=rule.recovery), {})
                return True
        # Unknown HTML dialogs are never clicked through automatically.
        for frame in self.surface.page.frames:
            if frame.locator('dialog[open], [role="dialog"]').count():
                self.handoff("UNEXPECTED_DIALOG", resume)
                return True
        return False

    def step(self, step: Step):
        self.current_step = step.id
        self.budget()
        resume = Condition(target=step.target)
        while self.outcomes(resume):
            self.budget()
        reasons = {
            "click": "advance_workflow",
            "fill": "bind_input_parameter",
            "extract": "read_declared_output",
            "assert": "verify_checkpoint",
        }
        self.evidence.event(
            "step_started", step_id=step.id, action=step.action, reason=reasons[step.action]
        )
        self.action_count += 1
        try:
            value = self.surface.execute(step, self.inputs)
        except SurfaceError as exc:
            if self.outcomes(resume):
                self.budget()
                self.action_count += 1
                value = self.surface.execute(step, self.inputs)
            elif exc.code in ("TARGET_TIMEOUT", "AMBIGUOUS_TARGET"):
                self.handoff(exc.code, resume)
                self.budget()
                self.action_count += 1
                value = self.surface.execute(step, self.inputs)
            else:
                raise
        if step.output:
            self.outputs[step.output] = value
        if step.postcondition:
            try:
                self.surface.check(step.postcondition, self.inputs)
            except SurfaceError:
                if not self.outcomes(step.postcondition):
                    raise
                self.surface.check(step.postcondition, self.inputs)
        self.evidence.event("step_completed", step_id=step.id, action=step.action)

    def verify(self):
        if time.monotonic() > self.deadline:
            raise StopRun("RUN_TIMEOUT")
        while self.outcomes():
            self.budget()
        for condition in self.capability.success:
            self.surface.check(condition, self.inputs)
        try:
            validate_fields(self.outputs, self.capability.outputs)
        except ValueError as exc:
            raise StopRun("OUTPUT_VALIDATION_FAILED") from exc
        self.evidence.event("success_verified", checkpoint="passed")


def make_result(evidence, execution=None, *, status="success", code="OK", llm_calls=0):
    return RunResult(
        run_id=evidence.run_id,
        status=status,
        code=code,
        outputs=execution.outputs if execution and status == "success" else {},
        step_id=execution.current_step if execution else None,
        expected="declared action and checkpoint" if status != "success" else None,
        observed=code if status != "success" else None,
        llm_calls=llm_calls,
        evidence_dir=str(evidence.directory),
    )


def run_replay(
    capability: Capability,
    inputs: dict[str, str],
    policy: Policy,
    *,
    target: str,
    evidence_root=Path("evidence/runs"),
    headed=False,
    slow_mo=0,
    human: HumanHandler | None = None,
) -> RunResult:
    evidence = Evidence(evidence_root, "replay")
    evidence.event(
        "capability_bound", capability=capability.name, capability_version=capability.version
    )
    execution = None
    try:
        try:
            validate_fields(inputs, capability.inputs)
        except ValueError as exc:
            raise StopRun("INPUT_VALIDATION_FAILED", "business_outcome") from exc
        if capability.vendor != "mockbank" or capability.app_version != "1":
            raise StopRun("APP_VERSION_MISMATCH")
        if len(capability.steps) > policy.max_steps:
            raise StopRun("STEP_BUDGET_EXCEEDED")
        with BrowserSurface(policy, evidence, headed=headed, slow_mo=slow_mo) as surface:
            execution = Execution(capability, inputs, policy, surface, evidence, human)
            try:
                from urllib.parse import urljoin

                surface.navigate(urljoin(target, capability.entry_path))
                for step in capability.steps:
                    execution.step(step)
                execution.verify()
            except Exception:
                evidence.snapshot(surface, "failure")
                raise
        result = make_result(evidence, execution)
    except StopRun as exc:
        result = make_result(evidence, execution, status=exc.status, code=exc.code)
    except (PolicyViolation, SurfaceError) as exc:
        code = str(exc) if isinstance(exc, PolicyViolation) else exc.code
        result = make_result(evidence, execution, status="failure", code=code)
    except Exception as exc:
        # Raw Playwright/provider errors can contain page text or credentials.
        evidence.event("runtime_error", code=type(exc).__name__)
        result = make_result(evidence, execution, status="failure", code="RUNTIME_ERROR")
    evidence.finish(result)
    return result
