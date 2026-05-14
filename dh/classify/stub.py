"""Stub classifier — deterministic canned output for tests + dry-run spike."""
from __future__ import annotations

from dh.classify.base import (
    ClassifierClient,
    WaybackClassification,
    WaybackClassifierInput,
)


class StubClassifier(ClassifierClient):
    transport = "stub"
    prompt_version = "stub-v0"
    classifier_version = "0.0.0"
    model_used = "stub"

    async def classify_wayback_history(
        self, input_: WaybackClassifierInput
    ) -> WaybackClassification:
        # Deterministic toy heuristic so tests can assert against it without an LLM.
        domain = input_.domain.lower()
        if any(needle in domain for needle in ("casino", "porn", "viagra", "rx")):
            label = "spam_history"
            confidence = 0.95
        elif not input_.snapshots:
            label = "clean"
            confidence = 0.3
        else:
            label = "clean"
            confidence = 0.8

        return WaybackClassification(
            classification=label,
            confidence=confidence,
            reasoning="stub classifier — deterministic heuristic on domain string + snapshot presence",
            model_used=self.model_used,
            prompt_version=self.prompt_version,
            cost_micros=0,
        )
