"""The only module that talks to a model provider.

One request per message or image, with the output constrained to a JSON schema
(structured outputs), so the reply is always parseable. Server-side fallbacks
re-run a request on another model if the first one declines; a reply that
still is not a normal completion comes back as a marker the validators reject.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import anthropic

from extraction.usage import CallUsage

MODEL = "claude-opus-5"
EFFORT = "low"  # classification and copying out numbers; deep reasoning is not needed
MAX_TOKENS = 4000
FALLBACK_BETA = "server-side-fallback-2026-07-01"
ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


class MissingApiKey(RuntimeError):
    pass


def load_env_file(path: Path = ENV_FILE) -> None:
    """Read KEY=VALUE lines into the environment without overriding real variables."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


class AnthropicJsonModel:
    def __init__(self, model: str = MODEL, effort: str = EFFORT) -> None:
        load_env_file()
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise MissingApiKey("ANTHROPIC_API_KEY is not set (environment or code/.env); use --offline to skip")
        self.model, self.effort = model, effort
        self._client = anthropic.Anthropic()

    def extract(self, system: str, content, schema: dict, purpose: str) -> tuple[dict, CallUsage]:
        response = self._client.beta.messages.create(
            model=self.model,
            max_tokens=MAX_TOKENS,
            betas=[FALLBACK_BETA],
            fallbacks="default",
            system=system,
            messages=[{"role": "user", "content": content}],
            output_config={"effort": self.effort, "format": {"type": "json_schema", "schema": schema}},
        )
        usage = CallUsage(purpose, response.model, response.usage.input_tokens, response.usage.output_tokens)
        if response.stop_reason != "end_turn":
            return {"_rejected": str(response.stop_reason)}, usage
        text = next((block.text for block in response.content if block.type == "text"), "")
        try:
            return json.loads(text), usage
        except json.JSONDecodeError:
            return {"_rejected": "invalid_json"}, usage
