"""GitHub-source modules — A2 ingestion + path/context classifier."""

from dh.sources.github.context import ContextType, classify_url_context

__all__ = ["ContextType", "classify_url_context"]
