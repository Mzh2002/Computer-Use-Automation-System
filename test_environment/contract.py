"""Reviewed MockBank task contract and development fixture; no provider dependency."""

from cua.core.schemas import Capability, Condition, FieldSpec, OutcomeRule, Step, Target, Value

FRAME = 'iframe[title="Account panel"]'


def role(name, role="heading", frame=None):
    return Target(kind="role", value=name, role=role, frame=frame)


def cell(name, frame=FRAME):
    return Target(kind="css", value=f'tr:has(> th:text-is("{name}")) > td', frame=frame)


def development_capability() -> Capability:
    """Explicitly hand-authored. Discovery uses only its contract, never these steps."""
    return Capability(
        name="read-savings",
        description="Read a member's savings balance through the UI.",
        provenance="hand_authored",
        inputs={"member_id": FieldSpec(pattern=r"[0-9]{5}")},
        outputs={
            "member_id": FieldSpec(pattern=r"[0-9]{5}"),
            "balance": FieldSpec(type="decimal"),
            "currency": FieldSpec(type="currency"),
        },
        steps=[
            Step(
                id="enter-member",
                action="fill",
                target=Target(kind="label", value="Member ID"),
                value=Value(parameter="member_id"),
            ),
            Step(id="search", action="click", target=role("Search", "button")),
            Step(id="open-member", action="click", target=role("Open member", "link")),
            Step(id="open-accounts", action="click", target=role("View accounts", "link")),
            Step(
                id="verify-member",
                action="assert",
                target=cell("Member ID"),
                value=Value(parameter="member_id"),
            ),
            Step(id="read-member", action="extract", target=cell("Member ID"), output="member_id"),
            Step(
                id="read-balance",
                action="extract",
                target=cell("Savings balance"),
                output="balance",
            ),
            Step(id="read-currency", action="extract", target=cell("Currency"), output="currency"),
        ],
        success=[
            Condition(target=role("Account summary", frame=FRAME)),
            Condition(
                target=cell("Member ID"), test="text_equals", value=Value(parameter="member_id")
            ),
        ],
        outcomes=[
            OutcomeRule(
                code="MEMBER_NOT_FOUND", category="business", target=role("Member not found")
            ),
            OutcomeRule(
                code="INVALID_MEMBER_ID", category="business", target=role("Invalid member ID")
            ),
            OutcomeRule(
                code="PERMISSION_DENIED",
                category="failure",
                target=role("Permission denied", frame=FRAME),
            ),
            OutcomeRule(
                code="APPLICATION_ERROR",
                category="failure",
                target=role("Application error", frame=FRAME),
            ),
            OutcomeRule(
                code="SESSION_EXPIRED",
                category="human",
                target=role("Session expired", frame=FRAME),
            ),
            OutcomeRule(
                code="OPERATOR_REVIEW_REQUIRED",
                category="human",
                target=role("Operator review required", frame=FRAME),
            ),
            OutcomeRule(
                code="TRANSIENT_LOAD",
                category="retry",
                target=role("Temporary service interruption", frame=FRAME),
                recovery=role("Retry load", "link", FRAME),
            ),
        ],
    )
