"""Trusted policy lives outside the model and the recorded capability."""

import json
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

from pydantic import Field

from cua.core.schemas import StrictModel


class PolicyViolation(Exception):
    pass


class Policy(StrictModel):
    origins: list[str]
    routes: list[str]
    actions: list[str] = Field(default_factory=lambda: ["click", "fill", "extract", "assert"])
    click_names: list[str]
    fill_names: list[str]
    human_control_names: list[str] = Field(default_factory=list)
    max_steps: int = Field(default=30, ge=1, le=60)
    max_seconds: int = Field(default=120, ge=1, le=600)
    max_retries: int = Field(default=2, ge=0, le=5)

    @classmethod
    def load(cls, path: Path):
        return cls.model_validate_json(path.read_text(encoding="utf-8"))

    def check_url(self, url: str):
        parsed = urlsplit(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if parsed.username or parsed.password or origin not in self.origins:
            raise PolicyViolation("ORIGIN_BLOCKED")
        path = unquote(parsed.path or "/")
        if "\\" in path or any(x in (".", "..") for x in path.split("/")):
            raise PolicyViolation("ROUTE_BLOCKED")
        if not any(re.fullmatch(pattern, path) for pattern in self.routes):
            raise PolicyViolation("ROUTE_BLOCKED")

    def check_action(self, action: str, name: str):
        if action not in self.actions:
            raise PolicyViolation("ACTION_BLOCKED")
        if action == "click" and name not in self.click_names:
            raise PolicyViolation("CONTROL_BLOCKED")
        if action == "fill" and name not in self.fill_names:
            raise PolicyViolation("CONTROL_BLOCKED")

    def save(self, path: Path):
        path.write_text(json.dumps(self.model_dump(), indent=2), encoding="utf-8")
