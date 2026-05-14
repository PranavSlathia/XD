"""Classifier abstraction layer.

Domain Hunter must remain decoupled from any specific LLM transport so we can
swap implementations (Codex CLI subprocess ↔ Anthropic API ↔ OpenAI API ↔ stub)
without touching workers or scoring code.

Use `make_classifier()` to get the configured implementation.
"""
from __future__ import annotations

from dh.classify.base import (
    ClassifierClient,
    WaybackClassification,
    WaybackClassifierInput,
)
from dh.classify.factory import make_classifier

__all__ = [
    "ClassifierClient",
    "WaybackClassification",
    "WaybackClassifierInput",
    "make_classifier",
]
