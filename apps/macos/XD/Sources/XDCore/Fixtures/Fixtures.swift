import Foundation

public enum XDFixtures {
    private static let now = Date(timeIntervalSince1970: 1_787_283_840)

    public static let candidates: [CandidateSummary] = [
        CandidateSummary(
            id: 101,
            domain: "NorthlineLab.com",
            lanes: [.name, .authority],
            hybrid: true,
            nameSubtype: "natural_compound",
            nameScore: 88,
            authorityScore: 91,
            reviewState: .research,
            lifecycleState: "expired",
            currentStatus: "available",
            availabilityConfidence: "registrar",
            promotedAt: now.addingTimeInterval(-360),
            lastObserved: now.addingTimeInterval(-360),
            dossierUpdatedAt: now.addingTimeInterval(-360)
        ),
        CandidateSummary(
            id: 102,
            domain: "SummitVector.io",
            lanes: [.name, .authority],
            hybrid: true,
            nameSubtype: "natural_compound",
            nameScore: 84,
            authorityScore: 86,
            reviewState: .research,
            lifecycleState: "expired",
            currentStatus: "available",
            availabilityConfidence: "registrar",
            promotedAt: now.addingTimeInterval(-1_620),
            lastObserved: now.addingTimeInterval(-1_620),
            dossierUpdatedAt: now.addingTimeInterval(-1_620)
        ),
        CandidateSummary(
            id: 103,
            domain: "HarborSignal.net",
            lanes: [.name, .authority],
            hybrid: true,
            nameSubtype: "natural_compound",
            nameScore: 79,
            authorityScore: 82,
            reviewState: .research,
            lifecycleState: "expired",
            currentStatus: "available",
            availabilityConfidence: "registrar",
            promotedAt: now.addingTimeInterval(-3_300),
            lastObserved: now.addingTimeInterval(-3_300),
            dossierUpdatedAt: now.addingTimeInterval(-3_300)
        ),
    ]

    public static let today = TodaySnapshot(
        generatedAt: now,
        systemHealth: "healthy",
        unreadEvents: 3,
        mostUrgentDomain: "NorthlineLab.com",
        candidates: candidates
    )

    public static let detail = CandidateDetail(
        id: candidates[0].id,
        domain: candidates[0].domain,
        lanes: candidates[0].lanes,
        hybrid: true,
        nameSubtype: candidates[0].nameSubtype,
        nameScore: candidates[0].nameScore,
        authorityScore: candidates[0].authorityScore,
        reviewState: .research,
        lifecycleState: "expired",
        currentStatus: "available",
        availabilityConfidence: "registrar",
        promotedAt: candidates[0].promotedAt,
        lastObserved: now.addingTimeInterval(-360),
        dossierUpdatedAt: now,
        assessments: [
            LaneAssessment(
                lane: .name,
                nameSubtype: "natural_compound",
                state: "qualified",
                screenPassed: true,
                laneScore: 88,
                modelVersion: "name-screen-v1",
                configVersion: 1,
                computedAt: now,
                signals: [
                    "commercial_fit": .string("strong"),
                    "exact_match": .string("NorthlineLab.com"),
                    "trademark_check": .string("Clear"),
                    "search_interest": .string("Consistent"),
                    "type_in_potential": .string("Strong"),
                    "name_quality": .string("High"),
                ],
                reasons: ["Natural commercial compound", "Easy to pronounce"],
                missingEvidence: []
            ),
            LaneAssessment(
                lane: .authority,
                nameSubtype: nil,
                state: "qualified",
                screenPassed: true,
                laneScore: 91,
                modelVersion: "authority-rubric-v1",
                configVersion: 1,
                computedAt: now,
                signals: [
                    "verified_sources": .number(14),
                    "referring_domains": .number(142),
                    "backlinks": .number(631),
                    "domain_rank": .number(32),
                    "page_rank": .number(29),
                    "anchor_diversity": .string("Good"),
                    "spam_score": .string("1%"),
                    "archive_history": .string("Clean"),
                ],
                reasons: ["Independent editorial citations", "Topically consistent"],
                missingEvidence: []
            ),
        ],
        gates: [
            gate("availability_authoritative"),
            gate("standard_registration_price"),
            gate("rights_clear"),
            gate("reputation_clean"),
            gate("history_clean"),
            gate("buyer_or_use_thesis"),
            gate("name_quality", lane: "name"),
            gate("comparable_sales", lane: "name"),
            gate("verified_referring_pages", lane: "authority"),
            gate("authority_rubric", lane: "authority"),
        ],
        dossiers: [
            Dossier(
                lane: .name,
                status: "complete",
                generatedAt: now,
                thesis: "A crisp commercial compound suited to laboratory software, research infrastructure, and technical services.",
                buyerThesis: ["categories": .array([.string("lab software"), .string("research tools")])],
                comparableSales: [["domain": .string("NorthLab.com"), "price": .number(8_500)]],
                risks: [],
                evidenceSummary: ["type_in_potential": .string("strong")]
            ),
            Dossier(
                lane: .authority,
                status: "complete",
                generatedAt: now,
                thesis: "Fourteen independent editorial source pages remain topically aligned; twelve are currently live.",
                buyerThesis: ["use": .string("legitimate technical publishing")],
                comparableSales: [],
                risks: [],
                evidenceSummary: ["verified_sources": .number(14), "live_sources": .number(12)]
            ),
        ],
        links: (1...14).map { index in
            LinkEvidence(
                sourceURL: "https://research.example.edu/resources/\(index)",
                sourceDomain: index.isMultiple(of: 2) ? "research.example.edu" : "journal.example.org",
                targetURL: "https://NorthlineLab.com/guide",
                anchorText: index.isMultiple(of: 3) ? "Northline laboratory guide" : "technical reference",
                contextText: "Independent editorial reference in a maintained resources page.",
                semanticLocation: "article",
                relFlags: [],
                isEditorial: true,
                currentlyLive: index <= 12,
                lastSeen: now.addingTimeInterval(Double(-index * 300))
            )
        },
        quotes: [
            RegistrarQuote(
                registrar: "porkbun",
                availabilityStatus: "available",
                priceClass: "normal",
                quotePriceMicros: 12_500_000,
                quoteCurrency: "USD",
                observedAt: now,
                expiresAt: now.addingTimeInterval(900)
            )
        ],
        reviews: []
    )

    public static let runs: [EngineRun] = [
        EngineRun(
            id: "discovery:52",
            kind: "discovery",
            source: "dropcatch",
            state: "success",
            startedAt: now.addingTimeInterval(-3_600),
            finishedAt: now.addingTimeInterval(-3_240),
            metrics: ["observations": .number(103_441), "promoted": .number(3)],
            error: nil
        ),
        EngineRun(
            id: "crawl:88",
            kind: "crawl",
            source: "seed:12",
            state: "success",
            startedAt: now.addingTimeInterval(-7_200),
            finishedAt: now.addingTimeInterval(-6_900),
            metrics: ["pages_fetched": .number(25), "links_observed": .number(422)],
            error: nil
        ),
    ]

    private static func gate(_ key: String, lane: String = "shared") -> GateResult {
        GateResult(
            lane: lane,
            gateKey: key,
            state: .pass,
            fatal: false,
            details: "Verified evidence",
            evidenceRefs: [],
            evaluatedAt: now
        )
    }
}
