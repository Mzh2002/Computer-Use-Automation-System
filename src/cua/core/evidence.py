"""Persist an allowlisted event contract, not raw pages or model transcripts."""

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4


class Evidence:
    def __init__(self, root: Path, mode: str):
        self.run_id = uuid4().hex
        self.directory = root / self.run_id
        self.directory.mkdir(parents=True)
        self.event("run_started", mode=mode)

    def event(self, event: str, **fields):
        # Callers pass enum-like metadata only. User text, arguments, model rationale,
        # exception messages, URLs, extracted values and secrets are intentionally absent.
        allowed = {
            "control",
            "reason",
            "capability",
            "capability_version",
            "mode",
            "step_id",
            "action",
            "code",
            "status",
            "owner",
            "attempt",
            "provider",
            "model_call",
            "tag",
            "input_type",
            "checkpoint",
            "count",
        }
        payload = {key: value for key, value in fields.items() if key in allowed}
        payload.update(event=event, time=datetime.now(UTC).isoformat(), run_id=self.run_id)
        with (self.directory / "events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload) + "\n")

    def snapshot(self, surface, label: str):
        # Structural DOM evidence: no text, values, URLs, or arbitrary attributes.
        name = re.sub(r"[^a-zA-Z0-9_-]", "_", label)[:64]
        try:
            state = surface.structural_snapshot()
        except Exception:
            state = {"unavailable": True}
        (self.directory / f"{name}.json").write_text(json.dumps(state, indent=2), encoding="utf-8")

    def finish(self, result):
        self.event("run_finished", status=result.status, code=result.code)
        saved = result.model_dump()
        saved["outputs"] = {key: "[REDACTED]" for key in result.outputs}
        (self.directory / "result.json").write_text(json.dumps(saved, indent=2), encoding="utf-8")
