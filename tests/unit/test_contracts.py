import pytest
from pydantic import ValidationError

from cua.core.schemas import Capability, FieldSpec, Value
from cua.execution.policy import Policy, PolicyViolation
from cua.execution.runtime import validate_fields
from test_environment import DEFAULT_POLICY


def test_artifact_roundtrip_and_bad_reference(capability):
    assert Capability.model_validate_json(capability.model_dump_json()) == capability
    bad = capability.model_dump()
    bad["steps"][0]["value"]["parameter"] = "undefined"
    with pytest.raises(ValidationError):
        Capability.model_validate(bad)


def test_duplicate_output_and_missing_success_rejected(capability):
    bad = capability.model_dump()
    bad["steps"][-1]["output"] = "balance"
    with pytest.raises(ValidationError):
        Capability.model_validate(bad)
    bad = capability.model_dump()
    bad["success"] = []
    with pytest.raises(ValidationError):
        Capability.model_validate(bad)


def test_parameter_literal_exclusive():
    with pytest.raises(ValidationError):
        Value(parameter="member_id", literal="10001")


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/",
        "http://127.0.0.1:8000.evil.example/",
        "http://user:secret@127.0.0.1:8000/",
        "http://127.0.0.1:8000/close-account",
        "http://127.0.0.1:8000/lab",
        "http://127.0.0.1:8000/%2e%2e/accounts",
        "javascript:alert(1)",
        "file:///C:/private.txt",
    ],
)
def test_policy_rejects_escape_routes(url):
    policy = Policy.load(DEFAULT_POLICY)
    with pytest.raises(PolicyViolation):
        policy.check_url(url)


def test_money_and_types():
    spec = {"balance": FieldSpec(type="decimal")}
    validate_fields({"balance": "842.19"}, spec)
    for value in ["NaN", "Infinity", "8e4", "842.199", 842.19]:
        with pytest.raises(ValueError):
            validate_fields({"balance": value}, spec)
