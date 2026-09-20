# MockBank test environment

This package contains the synthetic application and everything specific to exercising it.
It is separate from the automation engine in `src/cua/` and the assertions in `tests/`.

| Location | Purpose |
| --- | --- |
| `app.py` | MockBank pages, SQLite seed data and injected failure scenarios |
| `server.py` | Starts/stops an isolated loopback server for demos and tests |
| `commands.py` | Implements `cua sandbox`, `cua demo` and `cua export-example` |
| `contract.py` | Defines the savings task's inputs, outputs, checkpoints and example steps |
| `config/local.json` | Trusted route, control and action policy for MockBank |
| `fixtures/inputs/` | Synthetic valid, invalid and unknown member inputs |
| `fixtures/capabilities/` | Bundled hand-authored replay example |
| `__init__.py` | Resolves bundled asset paths independently of the working directory |

From the repository root, run the self-contained demo:

```powershell
uv run cua demo --headed --slow-mo 250
```

Or keep the environment running in one terminal:

```powershell
uv run cua sandbox reset
uv run cua sandbox serve
```

Open <http://127.0.0.1:8000> or replay in a second terminal:

```powershell
uv run cua replay test_environment/fixtures/capabilities/example-read-savings.json `
  --inputs test_environment/fixtures/inputs/member-10002.json --headed
```

Change the next run's scenario with `uv run cua sandbox scenario session-expired`, or use
<http://127.0.0.1:8000/lab>. Restore the normal scenario with `uv run cua sandbox scenario normal`.
The runtime database stays in ignored `.runtime/`, not among the fixtures. `CUA_SANDBOX_DB`
can override its location. The demo and automated tests use temporary databases.

Generated discovery artifacts go into the repository's `capabilities/` directory. The bundled
fixture is hand-authored and is not evidence of a real LLM discovery run.
