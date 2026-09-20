"""Synthetic MockBank environment and its bundled test fixtures."""

from pathlib import Path

ENVIRONMENT_ROOT = Path(__file__).resolve().parent
DEFAULT_POLICY = ENVIRONMENT_ROOT / "config" / "local.json"
EXAMPLE_CAPABILITY = ENVIRONMENT_ROOT / "fixtures" / "capabilities" / "example-read-savings.json"
INPUTS_DIRECTORY = ENVIRONMENT_ROOT / "fixtures" / "inputs"
