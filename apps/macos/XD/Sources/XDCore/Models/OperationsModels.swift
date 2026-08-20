import Foundation

public enum JobKind: String, Codable, CaseIterable, Identifiable, Sendable {
    case inventoryScan = "inventory_scan"
    case contentCrawl = "content_crawl"
    case availabilityRefresh = "availability_refresh"
    case backlinkValidate = "backlink_validate"
    case waybackRefresh = "wayback_refresh"
    case recomputeAssessments = "recompute_assessments"
    case generateDossier = "generate_dossier"

    public var id: String { rawValue }

    public var title: String {
        switch self {
        case .inventoryScan: "Inventory scan"
        case .contentCrawl: "Content crawl"
        case .availabilityRefresh: "Availability refresh"
        case .backlinkValidate: "Backlink validation"
        case .waybackRefresh: "Wayback refresh"
        case .recomputeAssessments: "Recompute assessments"
        case .generateDossier: "Generate dossier"
        }
    }

    public var needsCandidate: Bool {
        self == .backlinkValidate || self == .generateDossier
    }

    public var needsSeed: Bool { self == .contentCrawl }
}

public struct JobRequest: Codable, Equatable, Sendable {
    public let kind: JobKind
    public let payload: [String: JSONValue]
    public let idempotencyKey: String
}

public struct OperatorJob: Codable, Identifiable, Equatable, Sendable {
    public let id: String
    public let kind: JobKind
    public let state: String
    public let payload: [String: JSONValue]
    public let idempotencyKey: String
    public let configVersion: Int
    public let createdAt: Date
    public let startedAt: Date?
    public let finishedAt: Date?
    public let claimedBy: String?
    public let result: [String: JSONValue]?
    public let error: String?
}

public struct WorkerHeartbeat: Codable, Identifiable, Equatable, Sendable {
    public var id: String { workerName }
    public let workerName: String
    public let state: String
    public let jobId: String?
    public let observedAt: Date
    public let details: [String: JSONValue]
}

public struct EngineRun: Codable, Identifiable, Equatable, Sendable {
    public let id: String
    public let kind: String
    public let source: String
    public let state: String
    public let startedAt: Date
    public let finishedAt: Date?
    public let metrics: [String: JSONValue]
    public let error: String?
}

public struct ConfigVersion: Codable, Identifiable, Equatable, Sendable {
    public var id: Int { version }
    public let version: Int
    public let createdAt: Date
    public let parentVersion: Int?
    public let config: [String: JSONValue]
    public let notes: String?
    public let isActive: Bool
    public let activatedAt: Date?
    public let diff: [String: ConfigChange]
}

public struct ConfigChange: Codable, Equatable, Sendable {
    public let before: JSONValue?
    public let after: JSONValue?
}

public struct ConfigCreateRequest: Codable, Equatable, Sendable {
    public let config: [String: JSONValue]
    public let notes: String?
}

public struct DeviceCredential: Codable, Identifiable, Equatable, Sendable {
    public let id: Int
    public let deviceName: String
    public let createdAt: Date
    public let lastSeenAt: Date?
    public let revokedAt: Date?
}

public struct PortfolioOutcome: Codable, Identifiable, Equatable, Sendable {
    public let id: Int
    public let candidateId: Int
    public let outcome: String
    public let occurredAt: Date
    public let amountMicros: Int?
    public let currency: String?
    public let notes: String?
}

public struct PortfolioOutcomeRequest: Codable, Equatable, Sendable {
    public let outcome: String
    public let amountMicros: Int?
    public let currency: String?
    public let notes: String?
}

public struct ConfigDraft: Equatable, Sendable {
    public var monthlyBudgetUSD: Int
    public var nameScreenMinimum: Double
    public var nameCandidateLimit: Int
    public var crawlerMaxPages: Int
    public var crawlerDelaySeconds: Double

    public init(version: ConfigVersion?) {
        let root = version?.config ?? [:]
        let paid = root["paid_enrichment"]?.objectValue ?? [:]
        let name = root["name"]?.objectValue ?? [:]
        let crawler = root["crawler"]?.objectValue ?? [:]
        monthlyBudgetUSD = (paid["monthly_budget_micros"]?.intValue ?? 25_000_000) / 1_000_000
        nameScreenMinimum = name["screen_min_score"]?.numberValue ?? 65
        nameCandidateLimit = name["inventory_candidate_limit"]?.intValue ?? 1_000
        crawlerMaxPages = crawler["max_pages_per_seed"]?.intValue ?? 25
        crawlerDelaySeconds = crawler["minimum_delay_seconds"]?.numberValue ?? 1
    }

    public func applying(to source: [String: JSONValue]) -> [String: JSONValue] {
        var result = source
        var paid = result["paid_enrichment"]?.objectValue ?? [:]
        var name = result["name"]?.objectValue ?? [:]
        var crawler = result["crawler"]?.objectValue ?? [:]
        paid["monthly_budget_micros"] = .number(Double(monthlyBudgetUSD * 1_000_000))
        name["screen_min_score"] = .number(nameScreenMinimum)
        name["inventory_candidate_limit"] = .number(Double(nameCandidateLimit))
        crawler["max_pages_per_seed"] = .number(Double(crawlerMaxPages))
        crawler["minimum_delay_seconds"] = .number(crawlerDelaySeconds)
        result["paid_enrichment"] = .object(paid)
        result["name"] = .object(name)
        result["crawler"] = .object(crawler)
        return result
    }
}

