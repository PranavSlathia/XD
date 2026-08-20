from __future__ import annotations

from enum import StrEnum


class Lane(StrEnum):
    NAME = "name"
    AUTHORITY = "authority"


class NameSubtype(StrEnum):
    DICTIONARY = "dictionary"
    COMPOUND = "compound"
    BRANDABLE = "brandable"
    ACRONYM = "acronym"
    NUMERIC = "numeric"
    GEO_SERVICE = "geo_service"


class AssessmentState(StrEnum):
    SCREENING = "screening"
    RESEARCH = "research"
    QUALIFIED = "qualified"
    REJECTED = "rejected"


class GateState(StrEnum):
    PASSED = "pass"
    FAIL = "fail"
    PENDING = "pending"


class ReviewState(StrEnum):
    READY = "ready"
    RESEARCH = "research"
    REJECT = "reject"
