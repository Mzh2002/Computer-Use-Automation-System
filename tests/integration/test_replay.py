import json
import socket
from pathlib import Path

import pytest

from cua.core.evidence import Evidence
from cua.core.schemas import Step
from cua.execution.policy import PolicyViolation
from cua.execution.runtime import run_replay
from cua.surfaces.playwright import BrowserSurface
from test_environment.app import scenario
from test_environment.contract import FRAME, role

pytestmark = pytest.mark.browser


def invoke(capability, policy, lab, tmp_path, member_id="10002", **kwargs):
    return run_replay(
        capability,
        {"member_id": member_id},
        policy,
        target=lab.url,
        evidence_root=tmp_path / "runs",
        **kwargs,
    )


@pytest.mark.parametrize("member_id,balance", [("10001", "1250.50"), ("10002", "842.19")])
def test_parameterized_replay_without_provider(
    capability, policy, lab, tmp_path, monkeypatch, member_id, balance
):
    import openai

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    def forbidden(*args, **kwargs):
        pytest.fail("Replay attempted to initialize a model client")

    monkeypatch.setattr(openai, "OpenAI", forbidden)
    original_connect = socket.socket.connect

    def local_only(self, address):
        if isinstance(address, tuple) and address[0] not in ("127.0.0.1", "::1"):
            pytest.fail("Replay attempted external Python network access")
        return original_connect(self, address)

    monkeypatch.setattr(socket.socket, "connect", local_only)
    result = invoke(capability, policy, lab, tmp_path, member_id)
    assert result.status == "success", result
    assert result.outputs == {"member_id": member_id, "balance": balance, "currency": "USD"}
    assert result.llm_calls == 0
    persisted = "".join(p.read_text() for p in Path(result.evidence_dir).glob("*.json*"))
    for value in (member_id, balance, "Sample Member"):
        assert value not in persisted


@pytest.mark.parametrize(
    "mode,code",
    [
        ("permission-denied", "PERMISSION_DENIED"),
        ("app-error", "APPLICATION_ERROR"),
        ("wrong-member", "CHECKPOINT_MISMATCH"),
        ("ambiguous", "HUMAN_REQUIRED"),
    ],
)
def test_explicit_failures(capability, policy, lab, tmp_path, mode, code):
    scenario(mode, lab.database)
    result = invoke(capability, policy, lab, tmp_path)
    assert result.status == "failure", result
    assert result.code == code, result
    assert result.outputs == {}
    assert (Path(result.evidence_dir) / "failure.json").exists()


@pytest.mark.parametrize(
    "member_id,code", [("99999", "MEMBER_NOT_FOUND"), ("bad", "INPUT_VALIDATION_FAILED")]
)
def test_business_outcomes(capability, policy, lab, tmp_path, member_id, code):
    result = invoke(capability, policy, lab, tmp_path, member_id)
    assert result.status == "business_outcome"
    assert result.code == code


@pytest.mark.parametrize("mode", ["slow", "transient"])
def test_recoverable_load(capability, policy, lab, tmp_path, mode):
    scenario(mode, lab.database)
    result = invoke(capability, policy, lab, tmp_path)
    assert result.status == "success", result
    events = (Path(result.evidence_dir) / "events.jsonl").read_text()
    if mode == "transient":
        assert '"recovery_attempt"' in events


@pytest.mark.parametrize("mode", ["unexpected-dialog", "session-expired"])
def test_same_session_handoff(capability, policy, lab, tmp_path, mode):
    scenario(mode, lab.database)
    seen = []

    def simulated_operator(surface, reason):
        # Real browser interactions exercise the seam; this is not human evidence.
        assert surface.owner == "HUMAN"
        page = surface.page
        context = surface.context
        panel = page.frame_locator(FRAME)
        if mode == "unexpected-dialog":
            panel.get_by_role("button", name="Acknowledge notice").click()
        else:
            panel.get_by_role("button", name="Restore demo session").click()
        panel.get_by_role("heading", name="Account summary").wait_for()
        if mode == "session-expired":
            assert any(
                cookie["name"] == "demo_session" and cookie["value"] == "restored"
                for cookie in context.cookies()
            )
        assert page is surface.page and context is surface.context
        seen.append(reason)
        return True

    result = invoke(capability, policy, lab, tmp_path, human=simulated_operator)
    assert result.status == "success", result
    assert seen
    events = [
        json.loads(line)
        for line in (Path(result.evidence_dir) / "events.jsonl").read_text().splitlines()
    ]
    assert [e["owner"] for e in events if e["event"] == "ownership_changed"] == [
        "PAUSED",
        "HUMAN",
        "VALIDATING",
        "AUTOMATION",
    ]
    assert any(e["event"] == "human_action" for e in events)
    assert any(e.get("control") in policy.human_control_names for e in events)


def test_premature_resume_fails(capability, policy, lab, tmp_path):
    scenario("unexpected-dialog", lab.database)
    result = invoke(capability, policy, lab, tmp_path, human=lambda surface, reason: True)
    assert result.code == "RESUME_NOT_READY"
    assert not result.outputs


def test_risky_action_and_network_escape_blocked(policy, lab, tmp_path):
    with BrowserSurface(policy, Evidence(tmp_path / "risk", "test")) as surface:
        surface.navigate(lab.url + "/workspace?member_id=10001")
        step = Step(id="bad-click", action="click", target=role("Close account", "button", FRAME))
        with pytest.raises(PolicyViolation):
            surface.execute(step, {})
        assert "/workspace" in surface.page.url
        with pytest.raises(PolicyViolation):
            surface.navigate("https://example.com/")


def test_blocked_request_does_not_reach_external_server(policy, lab, tmp_path):
    with BrowserSurface(policy, Evidence(tmp_path / "network", "test")) as surface:
        surface.navigate(lab.url)
        response = surface.page.evaluate("""async () => {
          try { await fetch('https://example.com/'); return 'escaped'; }
          catch { return 'blocked'; }
        }""")
        assert response == "blocked"
        with pytest.raises(PolicyViolation):
            surface.assert_allowed()


def test_retry_budget_exhaustion(capability, policy, lab, tmp_path):
    scenario("transient", lab.database)
    policy.max_retries = 0
    result = invoke(capability, policy, lab, tmp_path)
    assert result.code == "RETRY_EXHAUSTED"
    assert result.outputs == {}


def test_native_confirmation_canceled_and_stops(policy, lab, tmp_path):
    with BrowserSurface(policy, Evidence(tmp_path / "native", "test")) as surface:
        surface.navigate(lab.url)
        assert surface.page.evaluate("confirm('Synthetic unexpected confirmation')") is False
        with pytest.raises(PolicyViolation, match="NATIVE_DIALOG_BLOCKED"):
            surface.assert_allowed()


def test_actual_redirect_blocked(policy, lab, tmp_path):
    from fastapi.responses import RedirectResponse

    def redirect():
        return RedirectResponse("https://example.com/")

    lab.server.config.app.add_api_route("/redirect-test", redirect)
    policy.routes.append("/redirect-test")
    with BrowserSurface(policy, Evidence(tmp_path / "redirect", "test")) as surface:
        with pytest.raises(PolicyViolation, match="ORIGIN_BLOCKED"):
            surface.navigate(lab.url + "/redirect-test")
