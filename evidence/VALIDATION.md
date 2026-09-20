# Implementation validation

Validated in this Windows workspace on 2026-09-14 with Python 3.12.14, Playwright 1.62.0,
and its installed Chromium browser.

| Check | Result |
| --- | --- |
| `uv run pytest -q` (equivalent venv Python invocation used) | **34 passed**, 44.25 seconds |
| `uv run ruff check .` (equivalent venv invocation used) | Passed |
| `uv run ruff format --check .` | Source files formatted with Ruff |
| `cua demo --repeat 10 --evidence evidence/sample-replay` | **13/13 passed** |
| Installed `cua` command / doctor | Working; no model key/model configured |

The 13 replay checks consist of ten consecutive successful fresh-session balance lookups,
one expected not-found result, one successful transient recovery and one expected permission
denial. Each successful result was checked against the synthetic fixture's known balance.
See [the original demo summary](sample-replay/demo-summary.json) and its referenced run directories.

The suite covers live Chromium interaction, parameterized outputs, no model calls on replay,
network restrictions and actual redirect rejection, business/operational errors, bounded recovery,
member-identity verification, control-transfer state transitions, preserved session cookies,
redacted manual-control events, premature resume, native confirmation blocking, and typed recording.
The real provider SDK's Structured Outputs request/response path is tested with a mock HTTP
transport. Browser recording tests use an explicitly labeled deterministic planner double.

## Remaining external validation

Update: the live discovery and replay item below was completed on 2026-09-19; see
[LIVE_VALIDATION.md](LIVE_VALIDATION.md). The original validation record above is retained.

- Configure `OPENAI_API_KEY` and `OPENAI_MODEL`, run `cua discover`, and retain its real model
  discovery evidence plus a replay with the second member. No live LLM run is claimed here.
- Follow the README's headed handoff demonstration to perform the takeover personally. Automated
  tests operate the same real browser through a simulated operator; they do not claim a person
  participated in validation.

No public repository was created and no submission email was sent.
