"""Versioned contracts. Artifacts contain declarative data, never executable code."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Target(StrictModel):
    kind: Literal["role", "label", "text", "css"]
    value: str = Field(min_length=1, max_length=500)
    role: str | None = None
    frame: str | None = None

    @model_validator(mode="after")
    def role_required(self):
        if self.kind == "role" and not self.role:
            raise ValueError("role targets require a role")
        return self


class Value(StrictModel):
    parameter: str | None = None
    literal: str | None = None

    @model_validator(mode="after")
    def exactly_one(self):
        if (self.parameter is None) == (self.literal is None):
            raise ValueError("provide exactly one of parameter or literal")
        return self

    def resolve(self, inputs: dict[str, str]) -> str:
        return inputs[self.parameter] if self.parameter is not None else self.literal


class Condition(StrictModel):
    target: Target
    test: Literal["visible", "text_equals"] = "visible"
    value: Value | None = None

    @model_validator(mode="after")
    def requires_value(self):
        if self.test == "text_equals" and self.value is None:
            raise ValueError("text_equals requires a value")
        return self


class Step(StrictModel):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    action: Literal["click", "fill", "extract", "assert"]
    target: Target
    value: Value | None = None
    output: str | None = None
    postcondition: Condition | None = None
    timeout_ms: int = Field(default=4000, ge=100, le=30000)

    @model_validator(mode="after")
    def action_fields(self):
        if self.action == "fill" and self.value is None:
            raise ValueError("fill requires a value")
        if self.action == "extract" and not self.output:
            raise ValueError("extract requires an output")
        if self.action == "assert" and self.value is None:
            raise ValueError("assert requires an expected value")
        if self.action not in ("fill", "assert") and self.value is not None:
            raise ValueError("value is only valid for fill/assert")
        if self.action != "extract" and self.output is not None:
            raise ValueError("output is only valid for extract")
        return self


class FieldSpec(StrictModel):
    type: Literal["string", "decimal", "currency"] = "string"
    pattern: str | None = None
    sensitive: bool = True


class OutcomeRule(StrictModel):
    code: str = Field(pattern=r"^[A-Z_]{1,64}$")
    target: Target
    category: Literal["business", "failure", "human", "retry"]
    recovery: Target | None = None

    @model_validator(mode="after")
    def recovery_required(self):
        if self.category == "retry" and self.recovery is None:
            raise ValueError("retry rules require an explicit recovery control")
        return self


class Capability(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    name: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    version: str = Field(default="1.0.0", pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    description: str
    vendor: str = "mockbank"
    app_version: str = "1"
    entry_path: str = "/"
    provenance: Literal["hand_authored", "live_llm", "test_fixture"]
    inputs: dict[str, FieldSpec]
    outputs: dict[str, FieldSpec]
    steps: list[Step] = Field(min_length=1, max_length=60)
    success: list[Condition] = Field(min_length=1)
    outcomes: list[OutcomeRule] = Field(default_factory=list)

    @model_validator(mode="after")
    def references(self):
        if len({s.id for s in self.steps}) != len(self.steps):
            raise ValueError("step ids must be unique")
        values = [s.value for s in self.steps]
        values += [c.value for c in self.success]
        values += [s.postcondition.value for s in self.steps if s.postcondition]
        for value in values:
            if value and value.parameter and value.parameter not in self.inputs:
                raise ValueError("unknown input parameter")
        extracted = [s.output for s in self.steps if s.action == "extract"]
        if set(extracted) != set(self.outputs) or len(extracted) != len(set(extracted)):
            raise ValueError("each declared output must be extracted exactly once")
        return self


class RunResult(StrictModel):
    run_id: str
    status: Literal["success", "business_outcome", "failure", "awaiting_human"]
    code: str
    outputs: dict[str, str] = Field(default_factory=dict)
    step_id: str | None = None
    expected: str | None = None
    observed: str | None = None
    llm_calls: int = 0
    evidence_dir: str
