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
from dh.config import settings
from dh.logging import log
from dh.spend import LLM_CALLS_KEY, get_default_cap


class CodexCliClassifier(ClassifierClient):
    """Subprocess-based classifier using the `codex exec` CLI."""

    transport = "codex_cli"
    prompt_version = "wayback-v0"          # bump when prompt changes
    classifier_version = "0.1.0"
    model_used = "gpt-5"                   # informational; actual model is whatever codex chooses

    async def classify_wayback_history(
        self, input_: WaybackClassifierInput
    ) -> WaybackClassification:
        # Hard daily cap: tier-down deterministically when budget is exhausted.
        _, exceeded = await get_default_cap().incr_and_check(
            LLM_CALLS_KEY, settings.llm_daily_call_cap
        )
        if exceeded:
            log.warning("classify.codex.tier_down", reason="llm_daily_cap")
            return WaybackClassification(
                classification="mixed",
                confidence=0.0,
                reasoning="llm daily cap exceeded; deterministic skip",
                model_used=self.model_used,
                prompt_version=self.prompt_version,
                cost_micros=0,
            )
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
