import json

import pytest

from cua.discovery.loop import discover
from cua.discovery.providers import Decision
from cua.execution.runtime import run_replay

pytestmark = pytest.mark.browser


class FixturePlanner:
    """Deterministic test double, explicitly not a genuine LLM discovery run."""

    live = False
    name = "test_fixture"

    def __init__(self):
        self.index = 0

    def decide(self, goal, contract, observation, history):
        assert "steps" not in contract
        # Resolve refs from each live observation, not stored browser element IDs.
        actions = [
            ("fill", "Member ID", "label", "member_id", None),
            ("click", "Search", "role", None, None),
            ("click", "Open member", "role", None, None),
            ("click", "View accounts", "role", None, None),
            ("assert", "Member ID", "css", "member_id", None),
            ("extract", "Member ID", "css", None, "member_id"),
            ("extract", "Savings balance", "css", None, "balance"),
            ("extract", "Currency", "css", None, "currency"),
        ]
        if self.index == len(actions):
            return Decision(
                action="finish", element_ref=None, input_parameter=None, output_name=None
            )
        action, name, kind, parameter, output = actions[self.index]
        self.index += 1
        element = next(
            x
            for x in observation["elements"]
            if x["target"]["kind"] == kind
            and (x["field"] == name if kind == "css" else x["target"]["value"] == name)
        )
        if action == "fill":
            assert element["filled"] is False
        if self.index == 2:
            field = next(e for e in observation["elements"] if e["target"]["kind"] == "label")
            assert field["filled"] is True
            assert history[-1]["input_parameter"] == "member_id"
            assert "10001" not in json.dumps(observation)
        return Decision(
            action=action, element_ref=element["ref"], input_parameter=parameter, output_name=output
        )


@pytest.mark.parametrize("mistake", ["focus_click", "missing_parameter"])
def test_discovery_corrects_invalid_input_proposal(capability, policy, lab, tmp_path, mistake):
    class FocusFirstPlanner(FixturePlanner):
        rejected = False

        def decide(self, goal, contract, observation, history):
            if not self.rejected:
                self.rejected = True
                field = next(e for e in observation["elements"] if e["target"]["kind"] == "label")
                assert field["allowed_actions"] == ["fill"]
                return Decision(
                    action="click" if mistake == "focus_click" else "fill",
                    element_ref=field["ref"],
                    input_parameter=None,
                    output_name=None,
                )
            assert any(
                h.get("code") in ("ACTION_NOT_OFFERED", "UNKNOWN_PARAMETER") and not h["completed"]
                for h in history
            )
            return super().decide(goal, contract, observation, history)

    artifact, result = discover(
        capability,
        {"member_id": "10001"},
        policy,
        FocusFirstPlanner(),
        target=lab.url,
        goal="Read savings",
        evidence_root=tmp_path,
    )
    assert result.status == "success", result
    assert result.llm_calls == 10
    assert len(artifact.steps) == 8
    assert artifact.steps[0].action == "fill"


def test_discovery_rejects_blocked_controls_with_bounded_correction(
    capability, policy, lab, tmp_path
):
    class BlockedPlanner(FixturePlanner):
        def decide(self, goal, contract, observation, history):
            control = next(
                e
                for e in observation["elements"]
                if e["target"]["value"] == "Open scenario controls"
            )
            assert control["allowed_actions"] == []
            return Decision(
                action="click", element_ref=control["ref"], input_parameter=None, output_name=None
            )

    artifact, result = discover(
        capability,
        {"member_id": "10001"},
        policy,
        BlockedPlanner(),
        target=lab.url,
        goal="Read savings",
        evidence_root=tmp_path,
    )
    assert artifact is None
    assert result.code == "PROPOSAL_REJECTION_LIMIT"
    assert result.llm_calls == policy.max_retries + 1
    assert result.step_id is None  # No disallowed proposal was executed.


@pytest.mark.parametrize("finish_early", [False, True])
def test_cli_saves_verified_artifact_or_explains_missing_file(
    monkeypatch, policy, lab, tmp_path, finish_early
):
    from typer.testing import CliRunner

    from cua.cli import app
    from cua.discovery import providers

    class Planner(FixturePlanner):
        def decide(self, *args):
            if finish_early:
                return Decision(
                    action="finish", element_ref=None, input_parameter=None, output_name=None
                )
            return super().decide(*args)

    monkeypatch.setattr(providers, "OpenAIPlanner", lambda model: Planner())
    input_path = tmp_path / "input.json"
    input_path.write_text('{"member_id": "10001"}')
    policy_path = tmp_path / "policy.json"
    policy.save(policy_path)
    destination = tmp_path / "capabilities" / "read-savings.json"
    response = CliRunner().invoke(
        app,
        [
            "discover",
            "--goal",
            "Read savings",
            "--inputs",
            str(input_path),
            "--target",
            lab.url,
            "--policy",
            str(policy_path),
            "--out",
            str(destination),
            "--evidence",
            str(tmp_path / "evidence"),
        ],
    )
    if finish_early:
        assert response.exit_code == 1
        assert not destination.exists()
        assert "No artifact saved" in response.output
        assert "TARGET_TIMEOUT" in response.output
    else:
        assert response.exit_code == 0, response.output
        assert destination.is_file()
        assert json.loads(destination.read_text())["provenance"] == "test_fixture"
        assert "Fresh-session verification replay" in response.output
        assert "Saved verified capability" in response.output
    assert str(destination.resolve()) in response.output


def test_record_then_replay_different_input(capability, policy, lab, tmp_path):
    artifact, result = discover(
        capability,
        {"member_id": "10001"},
        policy,
        FixturePlanner(),
        target=lab.url,
        goal="Read member savings",
        evidence_root=tmp_path,
    )
    assert result.status == "success", result
    assert artifact.provenance == "test_fixture"
    assert "10001" not in artifact.model_dump_json()
    assert result.llm_calls == 9
    assert any(s.postcondition for s in artifact.steps)
    replay = run_replay(
        artifact, {"member_id": "10002"}, policy, target=lab.url, evidence_root=tmp_path
    )
    assert replay.status == "success", replay
    assert replay.outputs["balance"] == "842.19"
    assert replay.llm_calls == 0


def test_model_cannot_claim_false_success(capability, policy, lab, tmp_path):
    class PrematurePlanner(FixturePlanner):
        def decide(self, *args):
            return Decision(
                action="finish", element_ref=None, input_parameter=None, output_name=None
            )

    artifact, result = discover(
        capability,
        {"member_id": "10001"},
        policy,
        PrematurePlanner(),
        target=lab.url,
        goal="Done",
        evidence_root=tmp_path,
    )
    assert artifact is None
    assert result.status == "failure"
    assert result.outputs == {}


def test_discovery_handoff_does_not_record_exception_page(capability, policy, lab, tmp_path):
    from test_environment.app import scenario
    from test_environment.contract import FRAME

    scenario("session-expired", lab.database)

    def operator(surface, reason):
        surface.page.frame_locator(FRAME).get_by_role("button", name="Restore demo session").click()
        return True

    artifact, result = discover(
        capability,
        {"member_id": "10001"},
        policy,
        FixturePlanner(),
        target=lab.url,
        goal="Read savings",
        evidence_root=tmp_path,
        human=operator,
    )
    assert result.status == "success", result
    assert all(
        step.postcondition is None or step.postcondition.target.value != "Session expired"
        for step in artifact.steps
    )
    scenario("normal", lab.database)
    replay = run_replay(
        artifact, {"member_id": "10002"}, policy, target=lab.url, evidence_root=tmp_path
    )
    assert replay.status == "success", replay


def test_provider_structured_request(monkeypatch):
    """Exercise the real SDK serializer/parser against a mock HTTP endpoint, no API spend."""
    import httpx
    from openai import OpenAI

    from cua.discovery.providers import OpenAIPlanner

    seen = []

    def respond(request):
        body = json.loads(request.content)
        seen.append(body)
        decision = {
            "action": "finish",
            "element_ref": None,
            "input_parameter": None,
            "output_name": None,
        }
        return httpx.Response(
            200,
            json={
                "id": "resp_test",
                "object": "response",
                "created_at": 0,
                "status": "completed",
                "model": "test-model",
                "error": None,
                "incomplete_details": None,
                "output": [
                    {
                        "id": "msg_test",
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [
                            {"type": "output_text", "text": json.dumps(decision), "annotations": []}
                        ],
                    }
                ],
            },
        )

    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-test-key")
    planner = OpenAIPlanner("test-model")
    planner.client = OpenAI(
        api_key="synthetic-test-key",
        http_client=httpx.Client(transport=httpx.MockTransport(respond)),
    )
    assert planner.decide("Test goal", {}, {"elements": []}, []).action == "finish"
    assert seen[0]["store"] is False
    assert seen[0]["text"]["format"]["type"] == "json_schema"
    assert seen[0]["text"]["format"]["strict"] is True
