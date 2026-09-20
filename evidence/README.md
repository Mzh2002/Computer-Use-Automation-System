# Evidence

Live model discovery has now produced `capabilities/read-savings.json` and passed verification
plus a replay with another member. See [live validation](LIVE_VALIDATION.md) for the run links.

`uv run cua demo` and individual runs write to ignored `evidence/runs/` directories. Each run
contains `events.jsonl`, a redacted `result.json`, and structural DOM snapshots when appropriate.
Successful CLI discovery also writes its exact generated capability into its run directory.

## Supplied replay evidence

`sample-replay/demo-summary.json` records 13 passing browser checks: ten consecutive normal
replays, a not-found result, a transient recovery, and a permission-denial result. Each referenced
run directory contains its original redacted logs/results, with DOM structure for exceptional
outcomes. `sample-replay/example-capability.json` is the exact hand-authored fixture used.
All runs made zero model calls; this evidence demonstrates replay only.

`test_environment/fixtures/capabilities/example-read-savings.json` is hand-authored. Offline recording tests use a clearly
labeled test planner. Neither is presented as genuine LLM discovery.

Before submission, run live discovery with your model key, replay its artifact with another member,
and copy only reviewed synthetic evidence into a tracked directory here. Include an error run and
a manual headed handoff demonstration. No publication or email is performed by the implementation.
