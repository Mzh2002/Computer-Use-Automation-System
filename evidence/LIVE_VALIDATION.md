# Live discovery validation — 2026-09-19

The missing-file report was traced to discovery run `3aed4f45a17e48d4a049c74ae72f68c2`:
its first proposed click stopped with `CONTROL_BLOCKED`. No capability had been saved because
discovery had not succeeded. An earlier successful run was a replay of the development fixture.

Discovery now observes permitted actions and populated-input state, includes successful parameter
bindings in history, and provides bounded feedback for invalid proposals before they execute.
The original execution policy is still enforced. The CLI explicitly explains failures to save
and prints the absolute path when it saves a verified artifact.

Using the existing model configuration against an isolated synthetic MockBank instance:

| Run | Result | Model calls |
| --- | --- | --- |
| [Live discovery](runs/e1ec3546775842d381659bb0288e2dab/result.json) | Success, member 10001 | 9 |
| [Fresh-session verification](runs/613d07531cb34586b7d721b2f0f3221b/result.json) | Success | 0 |
| [Second-member replay](runs/d911660e61ef4095ab2d0629ca0b012d/result.json) | Success, member 10002, expected synthetic balance | 0 |

The generated artifact is [`capabilities/read-savings.json`](../capabilities/read-savings.json),
with `provenance: live_llm`. It was written only after verification passed. Each run directory
contains redacted results and events; the discovery directory also contains the exact capability.
The run directories are ignored by Git, so curate them before submission if sharing this evidence.

Validation: nine discovery/end-to-end tests and 30 unit/integration tests passed; Ruff lint and
format checks passed. New regression coverage includes invalid proposal correction, populated
field observations without exposing values, and CLI success/failure artifact behavior.
