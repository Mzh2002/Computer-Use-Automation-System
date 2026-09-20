"""LLM-selected UI actions become reviewed, parameterized replay data."""

import json
from pathlib import Path
from urllib.parse import urljoin

from cua.core.evidence import Evidence
from cua.core.schemas import Capability, Condition, Step, Value
from cua.execution.policy import Policy, PolicyViolation
from cua.execution.runtime import Execution, StopRun, make_result, validate_fields
from cua.surfaces.playwright import BrowserSurface, SurfaceError


def discover(
    contract: Capability,
    inputs: dict[str, str],
    policy: Policy,
    planner,
    *,
    target: str,
    goal: str,
    evidence_root=Path("evidence/runs"),
    headed=False,
    slow_mo=0,
    human=None,
):
    mode = "live_discovery" if planner.live else "test_fixture_discovery"
    evidence = Evidence(evidence_root, mode)
    evidence.event(
        "capability_bound", capability=contract.name, capability_version=contract.version
    )
    execution = None
    artifact = None
    calls = 0
    rejected_proposals = 0
    try:
        try:
            validate_fields(inputs, contract.inputs)
        except ValueError as exc:
            raise StopRun("INPUT_VALIDATION_FAILED", "business_outcome") from exc
        history = []
        steps = []
        signatures = {}
        # The supplied development steps are excluded: the model must discover the path.
        model_contract = contract.model_dump(exclude={"steps", "provenance", "outcomes"})
        with BrowserSurface(policy, evidence, headed=headed, slow_mo=slow_mo) as surface:
            execution = Execution(contract, inputs, policy, surface, evidence, human)
            try:
                surface.navigate(urljoin(target, contract.entry_path))
                while True:
                    execution.budget()
                    if calls >= policy.max_steps:
                        raise StopRun("MODEL_STEP_LIMIT")
                    while execution.outcomes():
                        execution.budget()
                    observation = surface.observe()
                    calls += 1
                    evidence.event("model_requested", provider=planner.name, model_call=calls)
                    decision = planner.decide(goal, model_contract, observation, history)
                    execution.budget()
                    evidence.event("model_decided", action=decision.action, model_call=calls)
                    if decision.action == "finish":
                        execution.verify()
                        if not steps:
                            raise StopRun("EMPTY_RECORDING")
                        artifact = contract.model_copy(
                            update={
                                "steps": steps,
                                "provenance": "live_llm" if planner.live else "test_fixture",
                            }
                        )
                        artifact = Capability.model_validate_json(artifact.model_dump_json())
                        # No invocation data may leak through a dynamic locator or label.
                        serialized = artifact.model_dump_json()
                        if any(value and value in serialized for value in inputs.values()):
                            raise StopRun("ARTIFACT_CONTAINS_INVOCATION_DATA")
                        break
                    if decision.element_ref not in surface.catalog:
                        raise StopRun("UNKNOWN_ELEMENT_REFERENCE")
                    chosen = surface.catalog[decision.element_ref]
                    selected = next(
                        x for x in observation["elements"] if x["ref"] == decision.element_ref
                    )
                    rejection = None
                    if decision.action not in selected["allowed_actions"]:
                        rejection = "ACTION_NOT_OFFERED"
                    elif decision.action in ("fill", "assert") and (
                        decision.input_parameter not in contract.inputs
                    ):
                        rejection = "UNKNOWN_PARAMETER"
                    elif decision.action == "extract":
                        if decision.output_name not in contract.outputs:
                            rejection = "UNKNOWN_OUTPUT"
                        elif decision.output_name in execution.outputs:
                            rejection = "DUPLICATE_OUTPUT"
                    if rejection:
                        rejected_proposals += 1
                        evidence.event(
                            "proposal_rejected",
                            code=rejection,
                            action=decision.action,
                            attempt=rejected_proposals,
                        )
                        if rejected_proposals > policy.max_retries:
                            raise StopRun("PROPOSAL_REJECTION_LIMIT")
                        history.append(
                            {
                                "action": decision.action,
                                "target": chosen.model_dump(),
                                "completed": False,
                                "code": rejection,
                                "allowed_actions": selected["allowed_actions"],
                                "input_parameters": list(contract.inputs),
                                "remaining_outputs": [
                                    name
                                    for name in contract.outputs
                                    if name not in execution.outputs
                                ],
                            }
                        )
                        continue
                    value = None
                    if decision.action in ("fill", "assert"):
                        value = Value(parameter=decision.input_parameter)
                    step = Step(
                        id=f"step-{len(steps) + 1}",
                        action=decision.action,
                        target=chosen,
                        value=value,
                        output=decision.output_name if decision.action == "extract" else None,
                    )
                    signature = step.model_dump(exclude={"id"})
                    key = json.dumps(signature, sort_keys=True)
                    signatures[key] = signatures.get(key, 0) + 1
                    if signatures[key] > 2:
                        execution.handoff("REPEATED_ACTION", Condition(target=chosen))
                        signatures[key] = 0
                    execution.step(step)
                    if step.action == "click":
                        while execution.outcomes():
                            execution.budget()
                        # A successful click is followed by a concrete, observed checkpoint.
                        after = surface.observe()
                        headings = [
                            x
                            for x in after["elements"]
                            if x["target"]["kind"] == "role" and x["target"]["role"] == "heading"
                        ]
                        if headings:
                            target_heading = surface.catalog[headings[-1]["ref"]]
                            if surface.visible(target_heading):
                                step.postcondition = Condition(target=target_heading)
                    steps.append(step)
                    history.append(
                        {
                            "action": step.action,
                            "target": step.target.model_dump(),
                            "output": step.output,
                            "input_parameter": step.value.parameter if step.value else None,
                            "completed": True,
                        }
                    )
            except Exception:
                artifact = None
                evidence.snapshot(surface, "failure")
                raise
        result = make_result(evidence, execution, llm_calls=calls)
    except StopRun as exc:
        result = make_result(evidence, execution, status=exc.status, code=exc.code, llm_calls=calls)
    except (SurfaceError, PolicyViolation) as exc:
        result = make_result(evidence, execution, status="failure", code=str(exc), llm_calls=calls)
    except Exception as exc:
        evidence.event("runtime_error", code=type(exc).__name__)
        result = make_result(
            evidence, execution, status="failure", code="DISCOVERY_ERROR", llm_calls=calls
        )
    evidence.finish(result)
    return artifact, result
