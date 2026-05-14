"""Selects the concrete ClassifierClient implementation from settings.

Use this from workers / spike — never import a concrete impl directly.
"""
from __future__ import annotations

from dh.classify.base import ClassifierClient
from dh.config import settings


def make_classifier() -> ClassifierClient:
    transport = settings.classifier_transport

    if transport == "codex_cli":
        from dh.classify.codex import CodexCliClassifier
        return CodexCliClassifier()

    if transport == "stub":
        from dh.classify.stub import StubClassifier
        return StubClassifier()

    if transport == "anthropic_api":
        raise NotImplementedError(
            "anthropic_api transport reserved; implement dh.classify.anthropic when Codex CLI "
            "proves too slow/expensive."
        )

    if transport == "openai_api":
        raise NotImplementedError(
            "openai_api transport reserved; implement dh.classify.openai when Codex CLI proves "
            "too slow/expensive."
        )

    raise ValueError(f"Unknown classifier_transport: {transport!r}")
