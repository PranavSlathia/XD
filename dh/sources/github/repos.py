"""Shared Pydantic models for the GitHub source layer."""
from __future__ import annotations

from pydantic import BaseModel, Field


class Repo(BaseModel):
    """One repo identified for ingestion."""

    owner: str
    name: str
    stars: int
    archived: bool = False
    default_branch: str = "main"

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.name}"


class ExtractedUrl(BaseModel):
    """One URL extracted from a repo file."""

    repo: Repo
    file_path: str               # e.g. 'README.md' or 'docs/intro.md'
    url: str
    context_type: str            # value of ContextType enum (string for JSON-friendliness)
    surrounding: str = Field(default="", description="few lines around the URL")


class RepoFile(BaseModel):
    """Markdown file fetched from a repo (Contents API)."""

    repo: Repo
    path: str
    text: str
    etag: str | None = None
