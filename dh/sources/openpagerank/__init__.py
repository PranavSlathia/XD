"""DomCop Open PageRank — domain-level CC-derived PageRank (0–10), free.

https://www.domcop.com/openpagerank/

Used by spike + a2 worker to filter out candidates that have no real inbound
authority on the domain itself (independent of who's linking TO them from
GitHub). High-star README mention ≠ high inbound-link weight on the target.
"""

from dh.sources.openpagerank.client import (
    OPRBatchResult,
    OPRResult,
    fetch_open_pagerank,
)

__all__ = ["OPRResult", "OPRBatchResult", "fetch_open_pagerank"]
