import Foundation
import XCTest
@testable import XDCore

final class XDCoreTests: XCTestCase {
    func testHybridRequiresBothIndependentLanes() {
        XCTAssertEqual(Set(XDFixtures.detail.lanes), Set([.name, .authority]))
        XCTAssertTrue(XDFixtures.detail.hybrid)
        XCTAssertEqual(XDFixtures.detail.assessments.count, 2)
    }

    func testReadyRequiresEveryGateToPass() throws {
        XCTAssertTrue(XDFixtures.detail.canBecomeReady)

        let encoded = try APICodec.encoder().encode(XDFixtures.detail)
        var object = try XCTUnwrap(
            JSONSerialization.jsonObject(with: encoded) as? [String: Any]
        )
        var gates = try XCTUnwrap(object["gates"] as? [[String: Any]])
        gates[0]["state"] = "pending"
        object["gates"] = gates
        let changed = try JSONSerialization.data(withJSONObject: object)
        let pending = try APICodec.decoder().decode(CandidateDetail.self, from: changed)

        XCTAssertFalse(pending.canBecomeReady)
        XCTAssertEqual(pending.pendingGates.count, 1)
    }

    func testConfigurationDraftPreservesUneditedSections() {
        let version = ConfigVersion.preview()
        var draft = ConfigDraft(version: version)
        draft.monthlyBudgetUSD = 40
        let updated = draft.applying(to: version.config)

        XCTAssertEqual(
            updated["authority"],
            version.config["authority"],
            "typed draft must not rewrite unrelated authority settings"
        )
        XCTAssertEqual(
            updated["paid_enrichment"]?.objectValue?["monthly_budget_micros"]?.intValue,
            40_000_000
        )
    }

    func testOnlyTypedReadOnlyResearchJobsExist() {
        XCTAssertEqual(JobKind.allCases.count, 7)
        let forbidden = ["shell", "command", "docker", "purchase", "register", "bid", "backorder"]
        for kind in JobKind.allCases {
            XCTAssertFalse(forbidden.contains(where: kind.rawValue.contains))
        }
    }

    func testSnakeCaseCandidatePayloadDecodes() throws {
        let payload = """
        {
          "id": 9,
          "domain": "example.com",
          "lanes": ["name"],
          "hybrid": false,
          "name_subtype": "dictionary",
          "name_score": 91.0,
          "authority_score": null,
          "review_state": "research",
          "lifecycle_state": "available",
          "current_status": "available",
          "availability_confidence": "registrar",
          "promoted_at": "2026-08-21T09:00:00Z",
          "last_observed": "2026-08-21T09:01:00.125Z",
          "dossier_updated_at": null
        }
        """
        let value = try APICodec.decoder().decode(
            CandidateSummary.self,
            from: Data(payload.utf8)
        )
        XCTAssertEqual(value.nameSubtype, "dictionary")
        XCTAssertEqual(value.lanes, [.name])
        XCTAssertFalse(value.hybrid)
    }
}

