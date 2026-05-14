"""Normalization functions per PRD §4.5.

Each function clips its input to a defined range and returns 0-100.
Pure, deterministic, no IO — easy to unit-test once the data shape lands.

These are stubs with the math sketched; implement + test in Phase 1.
"""
from __future__ import annotations

import math

SAT = 10**6   # authority saturation (PRD §4.5)


def normalize_max_source_authority(max_signal: float) -> float:
    """log10-scaled, saturates at 10^6."""
    return min(math.log10(max(max_signal, 0) + 1) / math.log10(SAT), 1.0) * 100


def normalize_source_diversity(distinct_sources: int) -> float:
    """Capped — 5 sources is full credit."""
    return min(distinct_sources / 5, 1.0) * 100


def normalize_referring_domains(count: int) -> float:
    return min(count / 50, 1.0) * 100


def normalize_open_pagerank(opr: float) -> float:
    return max(0.0, min(opr, 10.0)) / 10 * 100


def normalize_age(years: float) -> float:
    return min(math.log(max(years, 0) + 1) / math.log(20), 1.0) * 100
