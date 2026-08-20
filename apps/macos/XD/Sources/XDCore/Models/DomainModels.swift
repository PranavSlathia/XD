import Foundation

public enum AssetLane: String, Codable, CaseIterable, Sendable {
    case name
    case authority

    public var title: String {
        switch self {
        case .name: "Name Asset"
        case .authority: "Authority Asset"
        }
    }
}

public enum ReviewState: String, Codable, CaseIterable, Sendable {
    case ready
    case research
    case reject
}

public enum GateState: String, Codable, Sendable {
    case pass
    case fail
    case pending
}

public struct LaneAssessment: Codable, Identifiable, Equatable, Sendable {
    public var id: String { "\(lane.rawValue):\(configVersion)" }
    public let lane: AssetLane
    public let nameSubtype: String?
    public let state: String
    public let screenPassed: Bool
    public let laneScore: Double?
    public let modelVersion: String
    public let configVersion: Int
    public let computedAt: Date
    public let signals: [String: JSONValue]
    public let reasons: [String]
    public let missingEvidence: [String]
}

public struct GateResult: Codable, Identifiable, Equatable, Sendable {
    public var id: String { "\(lane):\(gateKey)" }
    public let lane: String
    public let gateKey: String
    public let state: GateState
    public let fatal: Bool
    public let details: String?
    public let evidenceRefs: [String]
    public let evaluatedAt: Date
}

public struct Dossier: Codable, Identifiable, Equatable, Sendable {
    public var id: String { lane.rawValue }
    public let lane: AssetLane
    public let status: String
    public let generatedAt: Date
    public let thesis: String?
    public let buyerThesis: [String: JSONValue]
    public let comparableSales: [[String: JSONValue]]
    public let risks: [String]
    public let evidenceSummary: [String: JSONValue]
}

public struct CandidateSummary: Codable, Identifiable, Equatable, Sendable {
    public let id: Int
    public let domain: String
    public let lanes: [AssetLane]
    public let hybrid: Bool
    public let nameSubtype: String?
    public let nameScore: Double?
    public let authorityScore: Double?
    public let reviewState: ReviewState
    public let lifecycleState: String
    public let currentStatus: String?
    public let availabilityConfidence: String?
    public let promotedAt: Date?
    public let lastObserved: Date
    public let dossierUpdatedAt: Date?

    public var laneLabel: String {
        if hybrid { return "Hybrid" }
        return lanes.first?.title ?? "Research"
    }
}

public struct CandidatePage: Codable, Equatable, Sendable {
    public let items: [CandidateSummary]
    public let nextCursor: String?
}

public struct LinkEvidence: Codable, Identifiable, Equatable, Sendable {
    public var id: String { "\(sourceURL)|\(targetURL)" }
    public let sourceURL: String
    public let sourceDomain: String
    public let targetURL: String
    public let anchorText: String?
    public let contextText: String?
    public let semanticLocation: String?
    public let relFlags: [String]
    public let isEditorial: Bool?
    public let currentlyLive: Bool?
    public let lastSeen: Date
}

public struct RegistrarQuote: Codable, Identifiable, Equatable, Sendable {
    public var id: String { "\(registrar ?? "unknown"):\(observedAt.timeIntervalSince1970)" }
    public let registrar: String?
    public let availabilityStatus: String?
    public let priceClass: String?
    public let quotePriceMicros: Int?
    public let quoteCurrency: String
    public let observedAt: Date
    public let expiresAt: Date?

    public var displayPrice: String {
        guard let quotePriceMicros else { return "Quote pending" }
        let amount = Double(quotePriceMicros) / 1_000_000
        return amount.formatted(.currency(code: quoteCurrency))
    }
}

public struct CandidateReview: Codable, Identifiable, Equatable, Sendable {
    public let id: Int
    public let decision: ReviewState
    public let reason: String?
    public let notes: String?
    public let decidedAt: Date
    public let deviceId: Int?
}

public struct CandidateDetail: Codable, Identifiable, Equatable, Sendable {
    public let id: Int
    public let domain: String
    public let lanes: [AssetLane]
    public let hybrid: Bool
    public let nameSubtype: String?
    public let nameScore: Double?
    public let authorityScore: Double?
    public let reviewState: ReviewState
    public let lifecycleState: String
    public let currentStatus: String?
    public let availabilityConfidence: String?
    public let promotedAt: Date?
    public let lastObserved: Date
    public let dossierUpdatedAt: Date?
    public let assessments: [LaneAssessment]
    public let gates: [GateResult]
    public let dossiers: [Dossier]
    public let links: [LinkEvidence]
    public let quotes: [RegistrarQuote]
    public let reviews: [CandidateReview]

    public var summary: CandidateSummary {
        CandidateSummary(
            id: id,
            domain: domain,
            lanes: lanes,
            hybrid: hybrid,
            nameSubtype: nameSubtype,
            nameScore: nameScore,
            authorityScore: authorityScore,
            reviewState: reviewState,
            lifecycleState: lifecycleState,
            currentStatus: currentStatus,
            availabilityConfidence: availabilityConfidence,
            promotedAt: promotedAt,
            lastObserved: lastObserved,
            dossierUpdatedAt: dossierUpdatedAt
        )
    }

    public var latestQuote: RegistrarQuote? { quotes.first }
    public var failedGates: [GateResult] { gates.filter { $0.state == .fail } }
    public var pendingGates: [GateResult] { gates.filter { $0.state == .pending } }
    public var canBecomeReady: Bool {
        !lanes.isEmpty && failedGates.isEmpty && pendingGates.isEmpty
    }
}

public struct TodaySnapshot: Codable, Equatable, Sendable {
    public let generatedAt: Date
    public let systemHealth: String
    public let unreadEvents: Int
    public let mostUrgentDomain: String?
    public let candidates: [CandidateSummary]
}

public struct EventItem: Codable, Identifiable, Equatable, Sendable {
    public let id: Int
    public let candidateId: Int?
    public let eventType: String
    public let payload: [String: JSONValue]
    public let createdAt: Date
    public let configVersion: Int?
    public let read: Bool

    public var domain: String? { payload["domain"]?.stringValue }
}

public struct ReviewRequest: Codable, Equatable, Sendable {
    public let decision: ReviewState
    public let reason: String?
    public let notes: String?

    public init(decision: ReviewState, reason: String? = nil, notes: String? = nil) {
        self.decision = decision
        self.reason = reason
        self.notes = notes
    }
}

public struct PairingRequest: Codable, Equatable, Sendable {
    public let code: String
    public let deviceName: String
}

public struct PairingResult: Codable, Equatable, Sendable {
    public let deviceId: Int
    public let deviceName: String
    public let token: String
}

