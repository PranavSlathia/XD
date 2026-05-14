"""ClassifierClient ABC + the Pydantic schemas every implementation must honor.

Why an ABC?
  - The PRD picks Codex CLI as the primary transport, but the cost/concurrency
    profile of a subprocess call is poor at scale. If Phase 0.5 yield is good
    enough that we want to run thousands of classifications/day, we will swap
    to a direct API. This interface keeps the swap to a one-file change.
  - Tests use the StubClassifier — no LLM needed.
"""
from __future__ import annotations

import abc
import hashlib
from typing import Literal

from pydantic import BaseModel, Field

WaybackClassLabel = Literal[
    "clean", "spam_history", "adult_history", "redirect_history", "pbn_history", "mixed"
]


class WaybackSnapshotRef(BaseModel):
    """A single Wayback CDX entry — minimal data needed for classification."""
    urlkey: str
    timestamp: str   # YYYYMMDDHHMMSS
    original: str
    mimetype: str | None = None
    statuscode: int | None = None
    digest: str | None = None


class WaybackClassifierInput(BaseModel):
    """Everything the classifier needs to classify one candidate's history."""
    domain: str
    snapshots: list[WaybackSnapshotRef]
    snapshot_html_samples: list[str] = Field(default_factory=list)


class WaybackClassification(BaseModel):
    """Output schema — pinned because cache_key includes the schema-version."""
    classification: WaybackClassLabel
    confidence: float = Field(ge=0, le=1)
    reasoning: str
    model_used: str
    prompt_version: str
    cost_micros: int = Field(ge=0, description="microUSD spent on this call")


def compute_cache_key(
    domain: str,
    prompt_version: str,
    model_used: str,
    classifier_version: str,
    snapshot_ids: list[str],
) -> str:
    """Stable cache key. Mirrors PRD §12 classification_runs.cache_key.

    cache invalidates if ANY of: domain, prompt template, model, classifier logic,
    OR the chosen snapshot set changes.
    """
    payload = "||".join(
        [domain, prompt_version, model_used, classifier_version, *sorted(snapshot_ids)]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ClassifierClient(abc.ABC):
    """Common interface across all classifier implementations.

    Concrete subclasses:
      - CodexCliClassifier   — subprocess to `codex exec`
      - AnthropicApiClassifier — direct Anthropic API (future)
      - OpenAIApiClassifier  — direct OpenAI API (future)
      - StubClassifier       — for tests
    """

    transport: str = "abstract"

    @abc.abstractmethod
    async def classify_wayback_history(
        self, input_: WaybackClassifierInput
    ) -> WaybackClassification:
        """Classify a domain's Wayback-archive content history.

        MUST be deterministic w.r.t. (domain, prompt_version, model_used,
        classifier_version, snapshot_ids).  Implementations are responsible
        for filling `cost_micros` honestly.
        """
        ...

    # Room for future methods on this ABC without breaking impls:
    #   classify_brandability(...)
    #   classify_tm_similarity(...)
    # Add as @abc.abstractmethod when ready; until then, leave off this base.
