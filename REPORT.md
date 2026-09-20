# Architecture

The system is a synchronous CLI runtime and a separate local MockBank web application. Discovery
uses a genuine model adapter to select one typed action from a live browser observation. The
executor enforces trusted policy before acting, records what actually ran, and verifies the task's
success conditions. Replay imports neither the planner nor its provider client. A small disposable
server wrapper supports tests and `cua demo`; no queue, cluster or production service is required.

Source is grouped by responsibility: `cua.core` holds shared schemas/evidence, `cua.discovery`
holds the discovery loop/provider, `cua.execution` holds replay/policy/handoff, and `cua.surfaces`
holds browser control. The separately packaged `test_environment` owns MockBank, its server,
task contract, demo commands, policy and synthetic fixtures. Tests remain in `tests/`.

MockBank provides search → member detail → account workspace, including a table-based account
panel in an iframe. It deliberately lacks test IDs. SQLite and developer-only controls let us
inject repeatable outcomes. Automation uses rendered UI controls and text extraction; it never
reads the database or calls business APIs. The task is read-only but includes a forbidden Close
account control to exercise policy. The real provider integration has now completed discovery,
fresh-session verification, and a second-member replay; see `evidence/LIVE_VALIDATION.md`.

# Artifact schema

The capability contract has a schema version, capability version, vendor/application version,
provenance, entry path, typed inputs/outputs, ordered steps, success predicates, and outcome rules.
Each step identifies an action and a target with optional frame scope, parameter reference,
extraction name, observed postcondition and timeout. Pydantic rejects unknown fields, missing
references, duplicate steps/outputs and capabilities without success criteria. Monetary outputs
are validated fixed-point strings, never binary floats.

Artifacts are declarative JSON, not generated Python or raw transcripts. A model chooses an
ephemeral reference in the current observation; recording resolves it to a stable typed target.
Fill/assert actions bind explicit input keys, and outputs have a caller-facing schema. Discovery
uses the reviewed task contract without receiving the development fixture's steps. It publishes
only after successful discovery and a fresh-session replay. The supplied fixture is marked
`hand_authored`, offline planner artifacts `test_fixture`, genuine model recordings `live_llm`.

# Determinism & error handling

Replay selects no actions with an LLM. It executes a fixed sequence plus explicitly declared,
bounded recovery rules. Browser timing is handled through visibility/actionability waits, strict
single-target checks and final member-identity/success assertions. Locators use labels, exact
role/name matches, or a scoped table relationship such as the cell beside a Savings balance
header. Raw coordinates and positional frame guessing are avoided. Ambiguous controls stop.

The result distinguishes successful typed outputs, expected business outcomes (unknown member,
invalid input), and operational failures. Recognized transient pages have an explicit safe Retry
load control with a run-wide retry budget. Permission/app failures stop; unknown conditions and
session expiry can request intervention. Arbitrary failed clicks are not blindly retried. A
resumed attempt must pass a checkpoint first. Member identity is independently checked before
success; the model cannot simply announce that a task succeeded. Same inputs only imply same
outputs when the underlying application state is unchanged; determinism describes the execution
policy, not immutable bank data.

# Heterogeneity & multi-tenant

The `Surface` protocol separates perception, targeting, action and checkpoints from the recorded
flow. The implemented browser adapter supports one level of named/titled iframes and table-relative
targets. Nested or unnamed frames fail explicitly. A desktop adapter would add accessibility
control paths and application/window identity; a visual adapter would need bounded image matching
with deterministic ambiguity handling. Those are design seams, not claimed implementations.

Base URLs and allowlists live in trusted deployment configuration, separate from a vendor/version
capability. A version marker gates the sample app. A production extension would keep reviewed
tenant/version-specific locator overrides separately, resolve them before execution, validate
target uniqueness and checkpoints, and require qualification runs before promoting a version.
Tenant branding should not be embedded in the shared workflow. No actual tenant registry,
distributed execution or automatic version migration is implemented.

# Escalation & handoff

Ownership transitions are AUTOMATION → PAUSED → HUMAN → VALIDATING → AUTOMATION. The runner logs
an intervention reason and current step, captures a structural snapshot, and stops issuing actions.
In headed mode a terminal reader thread accepts resume/abort while the main thread continues
dispatching Playwright events. The human operates the exact existing browser/context, including
its cookies and iframe. Redacted interaction events and before/after structure are retained.

Resume requires cleared blockers, allowed locations and the next step's checkpoint. Early resume,
operator abort, timeout or repeated interventions stop safely. Operator time is excluded from
the automation budget but bounded independently to five minutes. Headless runs without an operator
handler terminate with HUMAN_REQUIRED and close the browser; there is no misleading queued live
session. Tests simulate an operator through actual UI interactions, checking object identity,
cookies, ownership order and action evidence. The manual demo exercises the human terminal path.

# Safety

Trusted policy is independent of model output and capability provenance. It allowlists exact
origins, route patterns, action types and actual control names. Navigation and context-level
network interception cover subresources. Browser-initiated requests are forwarded with automatic
redirects disabled; all server redirects are inspected and blocked before the browser can follow
them. This is a deliberate compatibility cut, including for allowlisted redirect destinations.
It does not bypass the UI or expose a business API to the agent. Service workers, downloads and popups are
disabled or blocked. Automatic requests are read-only GETs. Only human-owned synthetic session
restoration permits POST; financial changes are blocked. Unknown native JS confirmations are
canceled and stop execution; the live handoff demonstration uses HTML dialogs.

Persisted events contain controlled metadata, not invocation values, UI text, secrets, provider
errors or model transcripts. Failure evidence is a text/attribute-free DOM tree. Output values
are returned to the caller but redacted in saved results. Discovery sends the goal and UI control
descriptions to the provider and requests `store=False`; this does not replace provider retention
controls. The implementation is qualified only for the synthetic app. A malicious real application
can disguise control meaning, and a human can act outside the automation's click policy. Production
use needs application-specific action contracts, authenticated operator access, approved data
handling, and an isolated desktop/network boundary. The sample does not claim financial compliance.

# Cuts

The working scope is one read-only task contract on one synthetic web surface. Native desktop
control, visual/OCR locators, nested frames, tenant orchestration, remote operator consoles,
distributed leases, artifact signing/approval and autonomous write recovery are not implemented.
Structural failure snapshots are less informative than carefully redacted screenshots but avoid
accidentally persisting regulated fields. The current provider adapter and discovery machinery can
be tested offline; a genuine model run still requires external API access. Live discovery and its
fresh-session verification replay have now succeeded. Next are a second tenant variant and stronger policy
contracts if the project expands. The solution deliberately spends its complexity on the typed
artifact, execution contract, error taxonomy and real control-transfer seam.
