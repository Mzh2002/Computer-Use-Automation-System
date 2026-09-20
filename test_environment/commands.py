"""MockBank sandbox and fixture demonstration commands."""

import json
from pathlib import Path
from typing import Annotated

import typer

from cua.execution.policy import Policy
from cua.execution.runtime import run_replay
from test_environment import DEFAULT_POLICY
from test_environment.contract import development_capability

sandbox_app = typer.Typer(help="Local synthetic banking environment.")


@sandbox_app.command("reset")
def sandbox_reset(seed: str = "demo"):
    """Reset the local database to the two synthetic demo members."""
    if seed != "demo":
        raise typer.BadParameter("The only seed is demo.")
    from test_environment.app import db_path, reset

    reset()
    typer.echo(f"Reset synthetic database: {db_path()}")


@sandbox_app.command("scenario")
def sandbox_scenario(name: str):
    """Set the scenario used by the next browser run (use normal to reset)."""
    from test_environment.app import SCENARIOS, scenario

    if name not in SCENARIOS:
        raise typer.BadParameter(f"Choose one of: {', '.join(SCENARIOS)}")
    scenario(name)
    typer.echo(f"Scenario: {name}")


@sandbox_app.command("serve")
def sandbox_serve(host: str = "127.0.0.1", port: int = 8000):
    """Run the local website; intentionally restricted to loopback."""
    if host not in ("127.0.0.1", "localhost"):
        raise typer.BadParameter("The synthetic sandbox binds to loopback only.")
    import uvicorn

    from test_environment.app import create_app

    # Access logs include query inputs, so they are disabled even for the demo.
    uvicorn.run(create_app(), host=host, port=port, access_log=False)


def export_example(out: Path = Path("capabilities/example-read-savings.json")):
    """Write the hand-authored development fixture (this is not LLM discovery)."""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(development_capability().model_dump_json(indent=2), encoding="utf-8")
    typer.echo(f"Hand-authored development fixture: {out}")


def demo(
    headed: bool = False,
    slow_mo: int = 0,
    repeat: Annotated[int, typer.Option(min=1, max=20)] = 1,
    evidence: Path = Path("evidence/runs"),
):
    """Start an isolated lab, replay a fixture through four scenarios, then stop it."""
    import tempfile

    from test_environment.app import scenario
    from test_environment.server import LabServer

    fixture = development_capability()
    results = []
    with tempfile.TemporaryDirectory(prefix="cua-demo-") as directory:
        with LabServer(Path(directory) / "mockbank.sqlite3") as lab:
            trusted_policy = Policy.load(DEFAULT_POLICY)
            trusted_policy.origins = [lab.url]
            cases = [("normal", "10002", "OK")] * repeat + [
                ("normal", "99999", "MEMBER_NOT_FOUND"),
                ("transient", "10002", "OK"),
                ("permission-denied", "10002", "PERMISSION_DENIED"),
            ]
            for mode, member_id, expected_code in cases:
                scenario(mode, lab.database)
                result = run_replay(
                    fixture,
                    {"member_id": member_id},
                    trusted_policy,
                    target=lab.url,
                    evidence_root=evidence,
                    headed=headed,
                    slow_mo=slow_mo,
                )
                typer.echo(result.model_dump_json(indent=2))
                matches = result.code == expected_code
                if expected_code == "OK":
                    matches = matches and result.outputs.get("balance") == "842.19"
                results.append(
                    {
                        "scenario": mode,
                        "expected_code": expected_code,
                        "actual_code": result.code,
                        "passed": matches,
                        "run_id": result.run_id,
                    }
                )
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "demo-summary.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    (evidence / "example-capability.json").write_text(
        fixture.model_dump_json(indent=2), encoding="utf-8"
    )
    passed = sum(item["passed"] for item in results)
    typer.echo(
        f"Demo: {passed}/{len(results)} checks passed. Fixture is hand-authored; no LLM used."
    )
    raise typer.Exit(0 if passed == len(results) else 1)
