"""Codex CLI classifier — subprocess to `codex exec` with structured JSON output.

This is intentionally a thin shim. If the classifier becomes a bottleneck we
swap the file with `dh.classify.anthropic` / `dh.classify.openai` and nothing
else in the codebase changes.

NOTE: implementation is a stub — fill in after Phase 0.5 confirms volume.
"""
from __future__ import annotations

from dh.classify.base import (
    ClassifierClient,
    WaybackClassification,
    WaybackClassifierInput,
)


class CodexCliClassifier(ClassifierClient):
    """Subprocess-based classifier using the `codex exec` CLI."""

    transport = "codex_cli"
    prompt_version = "wayback-v0"          # bump when prompt changes
    classifier_version = "0.1.0"
    model_used = "gpt-5"                   # informational; actual model is whatever codex chooses

    async def classify_wayback_history(
        self, input_: WaybackClassifierInput
    ) -> WaybackClassification:
        # TODO: implement after Phase 0.5 yield spike proves the pipeline shape.
        #   - Render prompt from promptfoo/wayback_v0.md
        #   - Pass response_format JSON Schema (derived from WaybackClassification)
        #   - asyncio.create_subprocess_exec(
        #         settings.codex_bin, "exec", "--quiet", "--json", ...
        #     )
        #   - Read stdout, parse, validate via Pydantic
        #   - Set cost_micros from a fixed share-of-subscription estimate
        raise NotImplementedError(
            "CodexCliClassifier is a stub. Implement after Phase 0.5 yield spike."
        )
