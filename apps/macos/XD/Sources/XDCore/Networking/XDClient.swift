import Foundation

public struct CandidateQuery: Sendable {
    public var lane: String?
    public var state: ReviewState?
    public var search: String?
    public var cursor: String?
    public var limit: Int

    public init(
        lane: String? = nil,
        state: ReviewState? = nil,
        search: String? = nil,
        cursor: String? = nil,
        limit: Int = 100
    ) {
        self.lane = lane
        self.state = state
        self.search = search
        self.cursor = cursor
        self.limit = limit
    }
}

public enum XDClientError: LocalizedError, Equatable, Sendable {
    case invalidBaseURL
    case unauthorized
    case conflict(String)
    case server(status: Int, message: String)
    case invalidResponse

    public var errorDescription: String? {
        switch self {
        case .invalidBaseURL: "The private server URL is invalid."
        case .unauthorized: "This Mac is not paired, or its credential was revoked."
        case let .conflict(message): message
        case let .server(status, message): "Server error \(status): \(message)"
        case .invalidResponse: "The server returned an unreadable response."
        }
    }
}

public struct XDClient: Sendable {
    public var fetchToday: @Sendable (URL, String) async throws -> TodaySnapshot
    public var fetchCandidates: @Sendable (URL, String, CandidateQuery) async throws -> CandidatePage
    public var fetchCandidate: @Sendable (URL, String, Int) async throws -> CandidateDetail
    public var reviewCandidate: @Sendable (URL, String, Int, ReviewRequest) async throws -> CandidateReview
    public var markEventRead: @Sendable (URL, String, Int) async throws -> EventItem
    public var eventStream: @Sendable (URL, String, Int) -> AsyncThrowingStream<EventItem, Error>
    public var fetchRuns: @Sendable (URL, String) async throws -> [EngineRun]
    public var fetchWorkers: @Sendable (URL, String) async throws -> [WorkerHeartbeat]
    public var createJob: @Sendable (URL, String, JobRequest) async throws -> OperatorJob
    public var fetchJob: @Sendable (URL, String, String) async throws -> OperatorJob
    public var fetchConfigs: @Sendable (URL, String) async throws -> [ConfigVersion]
    public var createConfig: @Sendable (URL, String, ConfigCreateRequest) async throws -> ConfigVersion
    public var activateConfig: @Sendable (URL, String, Int) async throws -> ConfigVersion
    public var pairDevice: @Sendable (URL, PairingRequest) async throws -> PairingResult
    public var fetchDevices: @Sendable (URL, String) async throws -> [DeviceCredential]
    public var revokeDevice: @Sendable (URL, String, Int) async throws -> Void
    public var fetchPortfolio: @Sendable (URL, String) async throws -> [PortfolioOutcome]
    public var createOutcome: @Sendable (URL, String, Int, PortfolioOutcomeRequest) async throws -> PortfolioOutcome

    public static func live(session: URLSession = .shared) -> XDClient {
        let transport = APITransport(session: session)
        return XDClient(
            fetchToday: { baseURL, token in
                try await transport.get(baseURL, path: "/api/v1/today", token: token)
            },
            fetchCandidates: { baseURL, token, query in
                var values: [URLQueryItem] = [.init(name: "limit", value: String(query.limit))]
                if let lane = query.lane { values.append(.init(name: "lane", value: lane)) }
                if let state = query.state { values.append(.init(name: "state", value: state.rawValue)) }
                if let search = query.search, !search.isEmpty {
                    values.append(.init(name: "search", value: search))
                }
                if let cursor = query.cursor { values.append(.init(name: "cursor", value: cursor)) }
                return try await transport.get(
                    baseURL,
                    path: "/api/v1/candidates",
                    token: token,
                    query: values
                )
            },
            fetchCandidate: { baseURL, token, id in
                try await transport.get(baseURL, path: "/api/v1/candidates/\(id)", token: token)
            },
            reviewCandidate: { baseURL, token, id, body in
                try await transport.send(
                    baseURL,
                    path: "/api/v1/candidates/\(id)/reviews",
                    method: "POST",
                    token: token,
                    body: body
                )
            },
            markEventRead: { baseURL, token, id in
                try await transport.send(
                    baseURL,
                    path: "/api/v1/events/\(id)/read",
                    method: "POST",
                    token: token,
                    body: EmptyBody()
                )
            },
            eventStream: { baseURL, token, after in
                transport.events(baseURL, token: token, after: after)
            },
            fetchRuns: { baseURL, token in
                try await transport.get(baseURL, path: "/api/v1/runs", token: token)
            },
            fetchWorkers: { baseURL, token in
                try await transport.get(baseURL, path: "/api/v1/workers", token: token)
            },
            createJob: { baseURL, token, request in
                try await transport.send(
                    baseURL,
                    path: "/api/v1/jobs",
                    method: "POST",
                    token: token,
                    body: request
                )
            },
            fetchJob: { baseURL, token, id in
                try await transport.get(baseURL, path: "/api/v1/jobs/\(id)", token: token)
            },
            fetchConfigs: { baseURL, token in
                try await transport.get(baseURL, path: "/api/v1/config/versions", token: token)
            },
            createConfig: { baseURL, token, request in
                try await transport.send(
                    baseURL,
                    path: "/api/v1/config/versions",
                    method: "POST",
                    token: token,
                    body: request
                )
            },
            activateConfig: { baseURL, token, version in
                try await transport.send(
                    baseURL,
                    path: "/api/v1/config/versions/\(version)/activate",
                    method: "POST",
                    token: token,
                    body: EmptyBody()
                )
            },
            pairDevice: { baseURL, request in
                try await transport.send(
                    baseURL,
                    path: "/api/v1/pairing/complete",
                    method: "POST",
                    token: nil,
                    body: request
                )
            },
            fetchDevices: { baseURL, token in
                try await transport.get(baseURL, path: "/api/v1/devices", token: token)
            },
            revokeDevice: { baseURL, token, id in
                try await transport.sendWithoutResponse(
                    baseURL,
                    path: "/api/v1/devices/\(id)",
                    method: "DELETE",
                    token: token
                )
            },
            fetchPortfolio: { baseURL, token in
                try await transport.get(baseURL, path: "/api/v1/portfolio", token: token)
            },
            createOutcome: { baseURL, token, candidateID, request in
                try await transport.send(
                    baseURL,
                    path: "/api/v1/candidates/\(candidateID)/outcomes",
                    method: "POST",
                    token: token,
                    body: request
                )
            }
        )
    }

    public static let preview = XDClient(
        fetchToday: { _, _ in XDFixtures.today },
        fetchCandidates: { _, _, _ in CandidatePage(items: XDFixtures.candidates, nextCursor: nil) },
        fetchCandidate: { _, _, id in
            guard id == XDFixtures.detail.id else {
                var detail = XDFixtures.detail
                return CandidateDetail(
                    id: id,
                    domain: XDFixtures.candidates.first(where: { $0.id == id })?.domain ?? detail.domain,
                    lanes: detail.lanes,
                    hybrid: detail.hybrid,
                    nameSubtype: detail.nameSubtype,
                    nameScore: detail.nameScore,
                    authorityScore: detail.authorityScore,
                    reviewState: detail.reviewState,
                    lifecycleState: detail.lifecycleState,
                    currentStatus: detail.currentStatus,
                    availabilityConfidence: detail.availabilityConfidence,
                    promotedAt: detail.promotedAt,
                    lastObserved: detail.lastObserved,
                    dossierUpdatedAt: detail.dossierUpdatedAt,
                    assessments: detail.assessments,
                    gates: detail.gates,
                    dossiers: detail.dossiers,
                    links: detail.links,
                    quotes: detail.quotes,
                    reviews: detail.reviews
                )
            }
            return XDFixtures.detail
        },
        reviewCandidate: { _, _, _, request in
            CandidateReview(
                id: Int.random(in: 1...10_000),
                decision: request.decision,
                reason: request.reason,
                notes: request.notes,
                decidedAt: Date(),
                deviceId: 1
            )
        },
        markEventRead: { _, _, id in
            EventItem(
                id: id,
                candidateId: nil,
                eventType: "candidate.read",
                payload: [:],
                createdAt: Date(),
                configVersion: 1,
                read: true
            )
        },
        eventStream: { _, _, _ in AsyncThrowingStream { $0.finish() } },
        fetchRuns: { _, _ in XDFixtures.runs },
        fetchWorkers: { _, _ in [] },
        createJob: { _, _, request in
            OperatorJob(
                id: UUID().uuidString,
                kind: request.kind,
                state: "queued",
                payload: request.payload,
                idempotencyKey: request.idempotencyKey,
                configVersion: 1,
                createdAt: Date(),
                startedAt: nil,
                finishedAt: nil,
                claimedBy: nil,
                result: nil,
                error: nil
            )
        },
        fetchJob: { _, _, id in
            OperatorJob(
                id: id,
                kind: .inventoryScan,
                state: "success",
                payload: [:],
                idempotencyKey: "preview",
                configVersion: 1,
                createdAt: Date(),
                startedAt: Date(),
                finishedAt: Date(),
                claimedBy: "preview",
                result: [:],
                error: nil
            )
        },
        fetchConfigs: { _, _ in [.preview] },
        createConfig: { _, _, request in .preview(config: request.config, version: 2) },
        activateConfig: { _, _, version in .preview(version: version) },
        pairDevice: { _, request in
            PairingResult(deviceId: 1, deviceName: request.deviceName, token: "preview-token")
        },
        fetchDevices: { _, _ in [] },
        revokeDevice: { _, _, _ in },
        fetchPortfolio: { _, _ in [] },
        createOutcome: { _, _, candidateID, request in
            PortfolioOutcome(
                id: 1,
                candidateId: candidateID,
                outcome: request.outcome,
                occurredAt: Date(),
                amountMicros: request.amountMicros,
                currency: request.currency,
                notes: request.notes
            )
        }
    )
}

private struct EmptyBody: Codable, Sendable {}

private struct APIErrorBody: Decodable {
    let detail: JSONValue?
}

private actor APITransport {
    private let session: URLSession

    init(session: URLSession) {
        self.session = session
    }

    func get<Response: Decodable>(
        _ baseURL: URL,
        path: String,
        token: String,
        query: [URLQueryItem] = []
    ) async throws -> Response {
        let request = try makeRequest(baseURL, path: path, method: "GET", token: token, query: query)
        return try await execute(request)
    }

    func send<Body: Encodable, Response: Decodable>(
        _ baseURL: URL,
        path: String,
        method: String,
        token: String?,
        body: Body
    ) async throws -> Response {
        var request = try makeRequest(baseURL, path: path, method: method, token: token)
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try APICodec.encoder().encode(body)
        return try await execute(request)
    }

    func sendWithoutResponse(
        _ baseURL: URL,
        path: String,
        method: String,
        token: String
    ) async throws {
        let request = try makeRequest(baseURL, path: path, method: method, token: token)
        let (_, response) = try await session.data(for: request)
        try validate(response: response, data: Data())
    }

    nonisolated func events(
        _ baseURL: URL,
        token: String,
        after: Int
    ) -> AsyncThrowingStream<EventItem, Error> {
        AsyncThrowingStream { continuation in
            let task = Task {
                do {
                    var request = try makeRequest(
                        baseURL,
                        path: "/api/v1/events",
                        method: "GET",
                        token: token,
                        query: [.init(name: "after", value: String(after))]
                    )
                    request.setValue(String(after), forHTTPHeaderField: "Last-Event-ID")
                    request.setValue("text/event-stream", forHTTPHeaderField: "Accept")
                    let (bytes, response) = try await session.bytes(for: request)
                    guard let http = response as? HTTPURLResponse else {
                        throw XDClientError.invalidResponse
                    }
                    guard (200..<300).contains(http.statusCode) else {
                        throw http.statusCode == 401
                            ? XDClientError.unauthorized
                            : XDClientError.server(status: http.statusCode, message: "Event stream failed")
                    }
                    var eventData = ""
                    for try await line in bytes.lines {
                        if Task.isCancelled { break }
                        if line.isEmpty {
                            if !eventData.isEmpty {
                                let data = Data(eventData.utf8)
                                continuation.yield(try APICodec.decoder().decode(EventItem.self, from: data))
                            }
                            eventData = ""
                        } else if line.hasPrefix("data:") {
                            eventData += line.dropFirst(5).trimmingCharacters(in: .whitespaces)
                        }
                    }
                    continuation.finish()
                } catch is CancellationError {
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: error)
                }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }

    private nonisolated func makeRequest(
        _ baseURL: URL,
        path: String,
        method: String,
        token: String?,
        query: [URLQueryItem] = []
    ) throws -> URLRequest {
        guard var components = URLComponents(
            url: baseURL.appendingPathComponent(path.trimmingCharacters(in: CharacterSet(charactersIn: "/"))),
            resolvingAgainstBaseURL: false
        ) else { throw XDClientError.invalidBaseURL }
        if !query.isEmpty { components.queryItems = query }
        guard let url = components.url else { throw XDClientError.invalidBaseURL }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.timeoutInterval = method == "GET" ? 20 : 30
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        if let token, !token.isEmpty {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        return request
    }

    private func execute<Response: Decodable>(_ request: URLRequest) async throws -> Response {
        let (data, response) = try await session.data(for: request)
        try validate(response: response, data: data)
        do {
            return try APICodec.decoder().decode(Response.self, from: data)
        } catch {
            throw XDClientError.invalidResponse
        }
    }

    private func validate(response: URLResponse, data: Data) throws {
        guard let http = response as? HTTPURLResponse else {
            throw XDClientError.invalidResponse
        }
        guard (200..<300).contains(http.statusCode) else {
            if http.statusCode == 401 { throw XDClientError.unauthorized }
            let decoded = try? APICodec.decoder().decode(APIErrorBody.self, from: data)
            let message = decoded?.detail.map(String.init(describing:)) ?? HTTPURLResponse.localizedString(forStatusCode: http.statusCode)
            if http.statusCode == 409 { throw XDClientError.conflict(message) }
            throw XDClientError.server(status: http.statusCode, message: message)
        }
    }
}

public extension ConfigVersion {
    static func preview(
        config: [String: JSONValue] = [
            "schema_version": .number(1),
            "core_tlds": .array(["com", "net", "org", "co", "io", "ai"].map(JSONValue.string)),
            "paid_enrichment": .object([
                "provider": .string("dataforseo"),
                "monthly_budget_micros": .number(25_000_000),
                "operation_reserve_micros": .number(100_000),
            ]),
            "name": .object([
                "screen_min_score": .number(65),
                "inventory_candidate_limit": .number(1_000),
            ]),
            "authority": .object([
                "prefilter_min_referring_domains": .number(10),
                "ready_thresholds_enabled": .bool(false),
            ]),
            "crawler": .object([
                "concurrency": .number(2),
                "max_pages_per_seed": .number(25),
                "max_response_bytes": .number(2_000_000),
                "request_timeout_seconds": .number(15),
                "minimum_delay_seconds": .number(1),
            ]),
        ],
        version: Int = 1
    ) -> ConfigVersion {
        ConfigVersion(
            version: version,
            createdAt: Date(),
            parentVersion: version > 1 ? version - 1 : nil,
            config: config,
            notes: "Preview configuration",
            isActive: version == 1,
            activatedAt: version == 1 ? Date() : nil,
            diff: [:]
        )
    }
}

