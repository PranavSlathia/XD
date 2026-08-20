"""Cheap, deterministic Name Asset screening.

This module deliberately has no backlink or authority input.  Its score is a
within-lane triage priority, never a valuation and never a compensating score.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import cast

import wordninja

from dh.lanes.types import NameSubtype

MODEL_VERSION = "name-screen-v1"
CORE_TLDS = frozenset({"com", "net", "org", "co", "io", "ai"})
VOWELS = frozenset("aeiou")
NEGATIVE_TERMS = frozenset(
    {"casino", "crack", "fraud", "hack", "malware", "pharma", "porn", "scam", "warez"}
)
COMMERCIAL_TERMS = frozenset(
    {
        "ad",
        "auto",
        "bank",
        "book",
        "care",
        "cloud",
        "design",
        "digital",
        "finance",
        "flow",
        "food",
        "fund",
        "garden",
        "health",
        "home",
        "host",
        "insurance",
        "lab",
        "legal",
        "loan",
        "market",
        "media",
        "pay",
        "shop",
        "studio",
        "travel",
        "works",
    }
)
SERVICE_TERMS = frozenset(
    {
        "accountant",
        "cleaner",
        "dentist",
        "electrician",
        "lawyer",
        "locksmith",
        "moving",
        "painter",
        "plumber",
        "realtor",
        "roofing",
    }
)
GEO_TERMS = frozenset(
    {
        "austin",
        "boston",
        "chicago",
        "dallas",
        "delhi",
        "dubai",
        "london",
        "miami",
        "mumbai",
        "nyc",
        "paris",
        "pune",
        "sydney",
        "tokyo",
        "toronto",
    }
)


@dataclass(frozen=True, slots=True)
class NameScreenResult:
    domain: str
    screen_passed: bool
    subtype: NameSubtype | None
    score: float
    tokens: tuple[str, ...]
    reasons: tuple[str, ...]
    failures: tuple[str, ...]
    model_version: str = MODEL_VERSION


def _language_costs() -> dict[str, float]:
    raw = getattr(wordninja.DEFAULT_LANGUAGE_MODEL, "_wordcost", {})
    if not isinstance(raw, dict):
        return {}
    return cast(dict[str, float], raw)


def _known_word(token: str) -> bool:
    cost = _language_costs().get(token)
    return cost is not None and cost <= 15.5


def _longest_run(value: str, *, vowels: bool) -> int:
    longest = current = 0
    for char in value:
        matches = char in VOWELS
        if matches == vowels:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def _pronounceable(value: str) -> bool:
    if not 4 <= len(value) <= 11 or not value.isalpha():
        return False
    if "q" in value and "qu" not in value:
        return False
    if _longest_run(value, vowels=True) >= 4 or _longest_run(value, vowels=False) >= 4:
        return False
    ratio = sum(char in VOWELS for char in value) / len(value)
    return 0.25 <= ratio <= 0.65


def _parse(domain: str) -> tuple[str, str] | None:
    normalized = domain.strip().lower().rstrip(".")
    if normalized.count(".") != 1:
        return None
    label, tld = normalized.rsplit(".", 1)
    if tld not in CORE_TLDS or not label or len(label) > 24:
        return None
    if not re.fullmatch(r"[a-z0-9-]+", label) or label.startswith("-") or label.endswith("-"):
        return None
    return label, tld


def screen_name(domain: str, *, minimum_score: float = 65.0) -> NameScreenResult:
    parsed = _parse(domain)
    if parsed is None:
        return NameScreenResult(domain, False, None, 0.0, (), (), ("unsupported domain shape",))
    label, _tld = parsed
    if "-" in label:
        return NameScreenResult(domain, False, None, 20.0, (), (), ("hyphenated name",))
    negative = sorted(term for term in NEGATIVE_TERMS if term in label)
    if negative:
        return NameScreenResult(
            domain,
            False,
            None,
            0.0,
            (),
            (),
            (f"negative or abuse term: {negative[0]}",),
        )

    subtype: NameSubtype | None = None
    reasons: list[str] = []
    failures: list[str] = []
    tokens: tuple[str, ...] = ()
    score = 0.0

    if label.isdigit():
        subtype = NameSubtype.NUMERIC
        score = 82.0 if 2 <= len(label) <= 4 else 45.0
        reasons.append("short numeric pattern")
    elif label.isalpha() and 2 <= len(label) <= 4:
        if _known_word(label) and len(label) >= 4:
            subtype = NameSubtype.DICTIONARY
            score = 84.0
            reasons.append("short known word")
        else:
            subtype = NameSubtype.ACRONYM
            score = 82.0 if len(label) <= 3 else 67.0
            reasons.append("short acronym-length string")
    elif label.isalpha():
        raw_split = cast(
            list[str], wordninja.split(label)  # pyright: ignore[reportUnknownMemberType]
        )
        split: tuple[str, ...] = tuple(part.lower() for part in raw_split)
        tokens = split
        known = tuple(token for token in split if len(token) >= 2 and _known_word(token))
        if len(split) == 1 and known:
            subtype = NameSubtype.DICTIONARY
            cost = _language_costs().get(label, 15.5)
            score = max(68.0, min(92.0, 97.0 - cost * 1.5))
            reasons.append("recognized dictionary word")
        elif (
            len(split) == 2 and all(len(token) >= 3 for token in split) and len(known) == len(split)
        ):
            if (split[0] in GEO_TERMS and split[1] in SERVICE_TERMS) or (
                split[1] in GEO_TERMS and split[0] in SERVICE_TERMS
            ):
                subtype = NameSubtype.GEO_SERVICE
                score = 76.0
                reasons.append("clear geography and service pairing")
            else:
                subtype = NameSubtype.COMPOUND
                commercial_hits = sum(token in COMMERCIAL_TERMS for token in split)
                score = 64.0 + commercial_hits * 7.0
                if len(label) <= 12:
                    score += 3.0
                reasons.append("two recognized words with natural segmentation")
                if commercial_hits:
                    reasons.append("contains a commercially useful concept")
        elif len(split) <= 2 and all(len(token) >= 3 for token in split) and _pronounceable(label):
            subtype = NameSubtype.BRANDABLE
            score = 69.0 if len(label) <= 8 else 65.0
            reasons.append("short pronounceable invented word")
        else:
            failures.append("weak tokenization or pronunciation")

    if subtype is None:
        failures.append("no supported Name Asset subtype")
    if score < minimum_score:
        failures.append("below subtype screening floor")
    passed = subtype is not None and score >= minimum_score and not failures
    return NameScreenResult(
        domain=domain,
        screen_passed=passed,
        subtype=subtype,
        score=round(score, 2),
        tokens=tokens,
        reasons=tuple(reasons),
        failures=tuple(dict.fromkeys(failures)),
    )
