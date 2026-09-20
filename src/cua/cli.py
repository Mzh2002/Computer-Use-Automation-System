"""Commands for the local lab, live discovery, and deterministic invocation."""

import json
import os
from pathlib import Path
from typing import Annotated

import typer

from cua.core.schemas import Capability
from cua.execution.policy import Policy
from cua.execution.runtime import run_replay
from test_environment import DEFAULT_POLICY
from test_environment.commands import demo, export_example, sandbox_app
from test_environment.contract import development_capability

app = typer.Typer(
    pretty_exceptions_show_locals=False,
    help="Discover UI capabilities and replay them without a model.",
    no_args_is_help=True,
)
app.add_typer(sandbox_app, name="sandbox")
app.command()(demo)
app.command("export-example")(export_example)


def print_result(result):
    typer.echo(result.model_dump_json(indent=2))


def inputs_file(path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise typer.BadParameter("Inputs must be a JSON object.")
    return data


def handler(headed):
    if headed:
        from cua.execution.handoff import terminal_handoff

        return terminal_handoff
    return None


@app.command()
def replay(
    artifact: Path,
    inputs: Annotated[Path, typer.Option(exists=True)],
    policy: Path = DEFAULT_POLICY,
    target: str = "http://127.0.0.1:8000",
    headed: bool = False,
    slow_mo: int = 0,
    evidence: Path = Path("evidence/runs"),
):
    """Invoke a saved capability. No provider client is imported or called."""
    cap = Capability.model_validate_json(artifact.read_text(encoding="utf-8"))
    result = run_replay(
        cap,
        inputs_file(inputs),
        Policy.load(policy),
        target=target,
        evidence_root=evidence,
        headed=headed,
        slow_mo=slow_mo,
        human=handler(headed),
    )
    print_result(result)
    raise typer.Exit(
        0 if result.status == "success" else 2 if result.status == "business_outcome" else 1
    )


@app.command()
def discover(
    goal: Annotated[str, typer.Option()],
    inputs: Annotated[Path, typer.Option(exists=True)],
    target: str = "http://127.0.0.1:8000",
    policy: Path = DEFAULT_POLICY,
    out: Path = Path("capabilities/read-savings.json"),
    model: str = "",
    headed: bool = False,
    slow_mo: int = 0,
    evidence: Path = Path("evidence/runs"),
):
    """Run a real LLM against the UI, then verify its artifact in a fresh replay."""
    from cua.discovery.loop import discover as run_discovery
    from cua.discovery.providers import OpenAIPlanner

    try:
        planner = OpenAIPlanner(model or None)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    if out.exists():
        raise typer.BadParameter("Output exists; use a new --out path to preserve version history.")
    params = inputs_file(inputs)
    trusted_policy = Policy.load(policy)
    artifact, result = run_discovery(
        development_capability(),
        params,
        trusted_policy,
        planner,
        target=target,
        goal=goal,
        evidence_root=evidence,
        headed=headed,
        slow_mo=slow_mo,
        human=handler(headed),
    )
    print_result(result)
    if artifact is None:
        typer.echo(
            f"No artifact saved to {out.resolve()}: discovery stopped with {result.code} "
            f"at {result.step_id or 'initialization/completion'}. "
            f"Details: {Path(result.evidence_dir).resolve() / 'result.json'}",
            err=True,
        )
        raise typer.Exit(1)
    verified = run_replay(
        artifact,
        params,
        trusted_policy,
        target=target,
        evidence_root=evidence,
        headed=headed,
        human=handler(headed),
    )
    typer.echo("Fresh-session verification replay:")
    print_result(verified)
    if verified.status != "success":
        typer.echo("Artifact was not published because fresh-session verification failed.")
        raise typer.Exit(1)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(artifact.model_dump_json(indent=2), encoding="utf-8")
    # Also colocate the exact artifact with the discovery evidence.
    (Path(result.evidence_dir) / "capability.json").write_text(
        artifact.model_dump_json(indent=2), encoding="utf-8"
    )
    typer.echo(f"Saved verified capability: {out.resolve()}")


@app.command()
def doctor():
    """Check configuration without printing credentials or making model requests."""
    import importlib.metadata

    typer.echo(f"Playwright: {importlib.metadata.version('playwright')}")
    typer.echo(f"OPENAI_API_KEY configured: {bool(os.environ.get('OPENAI_API_KEY'))}")
    typer.echo(f"OPENAI_MODEL configured: {bool(os.environ.get('OPENAI_MODEL'))}")
    typer.echo(
        "Replay needs no model credentials. Install browser: uv run playwright install chromium"
    )


if __name__ == "__main__":
    app()
