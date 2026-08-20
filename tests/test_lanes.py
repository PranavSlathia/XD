from __future__ import annotations

from dh.lanes.authority import AuthorityLink, AuthorityScreenInput, screen_authority
from dh.lanes.gates import GateEvidence, evaluate_readiness
from dh.lanes.name import screen_name
from dh.lanes.types import GateState, Lane, NameSubtype


def test_strong_zero_backlink_name_passes_without_authority_input() -> None:
    result = screen_name("brightmarket.com")

    assert result.screen_passed is True
    assert result.subtype is NameSubtype.COMPOUND
    assert "backlink" not in " ".join((*result.reasons, *result.failures)).lower()


def test_gibberish_cannot_become_name_asset() -> None:
    assert screen_name("ruiyecs.com").screen_passed is False
    assert screen_name("pxylzx.com").screen_passed is False


def test_core_name_subtypes_are_separate() -> None:
    assert screen_name("garden.com").subtype is NameSubtype.DICTIONARY
    assert screen_name("abc.com").subtype is NameSubtype.ACRONYM
    assert screen_name("247.com").subtype is NameSubtype.NUMERIC
    assert screen_name("austinplumber.com").subtype is NameSubtype.GEO_SERVICE


def test_authority_prefilter_does_not_claim_readiness() -> None:
    result = screen_authority(
        AuthorityScreenInput(
            domain="plainname.org",
            referring_domains=120,
            open_pagerank=5.1,
        )
    )

    assert result.screen_passed is True
    assert "direct referring-page validation" in result.missing_evidence
    assert "authority rubric calibration" in result.missing_evidence


def test_direct_editorial_link_can_enter_authority_research() -> None:
    result = screen_authority(
        AuthorityScreenInput(
            domain="plainname.org",
            observed_links=(
                AuthorityLink(
                    source_domain="example.edu",
                    source_url="https://example.edu/resources",
                    live=True,
                    editorial=True,
                    followable=True,
                    relevant=True,
                ),
            ),
        )
    )

    assert result.screen_passed is True
    assert result.verified_independent_domains == 1
    assert result.relevant_independent_domains == 1


def test_irrelevant_link_can_enter_research_but_not_pass_topical_evidence() -> None:
    result = screen_authority(
        AuthorityScreenInput(
            domain="plainname.org",
            observed_links=(
                AuthorityLink(
                    source_domain="irrelevant.example",
                    source_url="https://irrelevant.example/resources",
                    live=True,
                    editorial=True,
                    followable=True,
                    relevant=False,
                ),
                AuthorityLink(
                    source_domain="plainname.org",
                    source_url="https://www.plainname.org/archive",
                    live=True,
                    editorial=True,
                    followable=True,
                    relevant=True,
                    independent=False,
                ),
            ),
        )
    )

    assert result.screen_passed is True
    assert result.verified_independent_domains == 1
    assert result.relevant_independent_domains == 0
    assert "topical relevance validation" in result.missing_evidence


def test_ready_can_come_from_either_lane_without_compensation() -> None:
    gates = [
        *(
            GateEvidence("shared", key, GateState.PASSED)
            for key in (
                "availability_authoritative",
                "standard_registration_price",
                "rights_clear",
                "reputation_clean",
                "history_clean",
                "buyer_thesis",
            )
        ),
        GateEvidence("name", "name_quality", GateState.PASSED),
        GateEvidence("name", "domain_specific_comps", GateState.PASSED),
        GateEvidence("authority", "verified_referring_pages", GateState.PENDING),
        GateEvidence("authority", "authority_rubric", GateState.PENDING),
    ]

    result = evaluate_readiness({Lane.NAME, Lane.AUTHORITY}, gates)

    assert result.ready is True
    assert result.ready_lanes == (Lane.NAME,)


def test_fatal_shared_failure_blocks_all_lanes() -> None:
    result = evaluate_readiness(
        {Lane.NAME},
        [GateEvidence("shared", "rights_clear", GateState.FAIL, fatal=True)],
    )

    assert result.ready is False
    assert result.fatal_failures == ("shared:rights_clear",)
