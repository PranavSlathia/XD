import Foundation
import Observation

public enum AppSection: String, CaseIterable, Identifiable, Sendable {
    case today
    case nameAssets
    case authorityAssets
    case hybrids
    case watchlist
    case runs
    case portfolio
    case settings

    public var id: String { rawValue }

    public var title: String {
        switch self {
        case .today: "Today"
        case .nameAssets: "Name Assets"
        case .authorityAssets: "Authority Assets"
        case .hybrids: "Hybrids"
        case .watchlist: "Watchlist"
        case .runs: "Runs"
        case .portfolio: "Portfolio"
        case .settings: "Settings"
        }
    }

    public var symbol: String {
        switch self {
        case .today: "tray.full"
        case .nameAssets: "textformat.abc"
        case .authorityAssets: "link"
        case .hybrids: "square.3.layers.3d"
        case .watchlist: "eye"
        case .runs: "play"
        case .portfolio: "briefcase"
        case .settings: "gearshape"
        }
    }

    public var laneQuery: String? {
        switch self {
        case .nameAssets: "name"
        case .authorityAssets: "authority"
        case .hybrids: "hybrid"
        default: nil
        }
    }
}

public enum ConnectionState: Equatable, Sendable {
    case connecting
    case online
    case offline(String)
    case unpaired

    public var label: String {
        switch self {
        case .connecting: "Connecting"
        case .online: "Private link online"
        case .offline: "Offline cache"
        case .unpaired: "Pair this Mac"
        }
    }
}

public struct DraftChange: Identifiable, Equatable, Sendable {
    public let id: String
    public let before: String
    public let after: String
    public let effect: String
}

@MainActor
@Observable
public final class XDStore {
    public var selectedSection: AppSection = .today
    public var selectedCandidateID: Int?
    public var today: TodaySnapshot?
    public var candidates: [CandidateSummary] = []
    public var selectedDetail: CandidateDetail?
    public var events: [EventItem] = []
    public var runs: [EngineRun] = []
    public var workers: [WorkerHeartbeat] = []
    public var configVersions: [ConfigVersion] = []
    public var configDraft = ConfigDraft(version: nil)
    public var devices: [DeviceCredential] = []
    public var portfolio: [PortfolioOutcome] = []
    public var recentJobs: [OperatorJob] = []
    public var connection: ConnectionState = .connecting
    public var isStale = false
    public var cacheDate: Date?
    public var isLoading = false
    public var isMutating = false
    public var errorMessage: String?
    public var successMessage: String?
    public var searchText = ""
    public var serverAddress: String {
        didSet { defaults.set(serverAddress, forKey: Keys.serverAddress) }
    }
    public var deviceName: String {
        didSet { defaults.set(deviceName, forKey: Keys.deviceName) }
    }
    public var pairingCode = ""
    public var notificationPermission = false
    public var openWhenAttentionRequired: Bool {
        didSet { defaults.set(openWhenAttentionRequired, forKey: Keys.openForAttention) }
    }

    public let notifications: NotificationService
    public let loginItems: LoginItemController

    private let client: XDClient
    private let tokenStore: SecureTokenStore
    private let cache: CacheRepository
    private let defaults: UserDefaults
    private let isDemo: Bool
    private var token: String?
    private var eventTask: Task<Void, Never>?
    private var syncTask: Task<Void, Never>?

    public init(
        client: XDClient,
        tokenStore: SecureTokenStore,
        cache: CacheRepository,
        notifications: NotificationService? = nil,
        loginItems: LoginItemController? = nil,
        defaults: UserDefaults = .standard,
        demo: Bool = false
    ) {
        self.client = client
        self.tokenStore = tokenStore
        self.cache = cache
        self.notifications = notifications ?? NotificationService()
        self.loginItems = loginItems ?? LoginItemController()
        self.defaults = defaults
        isDemo = demo
        serverAddress = defaults.string(forKey: Keys.serverAddress)
            ?? "https://prsnl.tail625ab9.ts.net"
        deviceName = defaults.string(forKey: Keys.deviceName)
            ?? Host.current().localizedName
            ?? "Mac"
        openWhenAttentionRequired = defaults.object(forKey: Keys.openForAttention) as? Bool ?? true
        token = demo ? "preview-token" : try? tokenStore.load()
        if demo {
            today = XDFixtures.today
            candidates = XDFixtures.candidates
            selectedCandidateID = XDFixtures.detail.id
            selectedDetail = XDFixtures.detail
            runs = XDFixtures.runs
            configVersions = [.preview()]
            configDraft = ConfigDraft(version: .preview())
            connection = .online
        }
    }

    public var baseURL: URL? {
        guard let url = URL(string: serverAddress),
              let scheme = url.scheme?.lowercased(),
              scheme == "https" || (isDemo && scheme == "http")
        else { return nil }
        return url
    }

    public var canMutate: Bool {
        connection == .online && token != nil && !isStale
    }

    public var needsAttention: Bool {
        !(today?.candidates.isEmpty ?? true)
    }

    public var unreadCount: Int { today?.unreadEvents ?? 0 }
    public var urgentDomain: String? { today?.mostUrgentDomain }
    public var systemHealthy: Bool { today?.systemHealth == "healthy" && connection == .online }
    public var activeConfig: ConfigVersion? { configVersions.first(where: \.isActive) }

    public var filteredCandidates: [CandidateSummary] {
        guard !searchText.isEmpty else { return candidates }
        return candidates.filter { $0.domain.localizedCaseInsensitiveContains(searchText) }
    }

    public var configChanges: [DraftChange] {
        let source = activeConfig.map(ConfigDraft.init) ?? ConfigDraft(version: nil)
        var changes: [DraftChange] = []
        func add(_ id: String, _ before: String, _ after: String, _ effect: String) {
            if before != after { changes.append(.init(id: id, before: before, after: after, effect: effect)) }
        }
        add(
            "Paid enrichment cap",
            "$\(source.monthlyBudgetUSD)/month",
            "$\(configDraft.monthlyBudgetUSD)/month",
            "Hard stop for paid evidence; exhaustion leaves evidence pending."
        )
        add(
            "Name screen minimum",
            source.nameScreenMinimum.formatted(.number.precision(.fractionLength(0...1))),
            configDraft.nameScreenMinimum.formatted(.number.precision(.fractionLength(0...1))),
            configDraft.nameScreenMinimum > source.nameScreenMinimum
                ? "Fewer names enter enrichment; precision should rise."
                : "More names enter enrichment; provider and review load may rise."
        )
        add(
            "Name candidate limit",
            String(source.nameCandidateLimit),
            String(configDraft.nameCandidateLimit),
            "Changes the bounded expensive-enrichment pool, not full-feed screening."
        )
        add(
            "Pages per seed",
            String(source.crawlerMaxPages),
            String(configDraft.crawlerMaxPages),
            "Changes maximum crawl work per allowlisted seed."
        )
        add(
            "Crawl delay",
            "\(source.crawlerDelaySeconds)s",
            "\(configDraft.crawlerDelaySeconds)s",
            configDraft.crawlerDelaySeconds >= source.crawlerDelaySeconds
                ? "Reduces request pressure and crawl throughput."
                : "Increases throughput and source pressure."
        )
        return changes
    }

    public func bootstrap() async {
        if isDemo {
            notificationPermission = await notifications.requestAuthorization()
            return
        }
        loadCachedToday()
        token = try? tokenStore.load()
        guard token != nil else {
            connection = .unpaired
            return
        }
        await refresh()
        notificationPermission = await notifications.requestAuthorization()
        startEventStream()
        startSyncLoop()
    }

    public func refresh() async {
        guard let baseURL, let token else {
            connection = token == nil ? .unpaired : .offline("Invalid private server URL")
            return
        }
        isLoading = true
        connection = .connecting
        defer { isLoading = false }
        do {
            async let todayRequest = client.fetchToday(baseURL, token)
            async let candidatesRequest = client.fetchCandidates(
                baseURL,
                token,
                CandidateQuery(lane: selectedSection.laneQuery, state: stateForSection)
            )
            let (newToday, page) = try await (todayRequest, candidatesRequest)
            today = newToday
            candidates = selectedSection == .today ? newToday.candidates : page.items
            connection = .online
            isStale = false
            cacheDate = nil
            try? cache.save(newToday, key: Keys.todayCache)
            try? cache.save(page, key: cacheKey(for: selectedSection))
            if selectedCandidateID == nil {
                selectedCandidateID = candidates.first?.id
            }
            if let selectedCandidateID {
                await selectCandidate(selectedCandidateID)
            }
        } catch {
            handleConnectionError(error)
            loadCachedPage(for: selectedSection)
        }
    }

    public func loadSection(_ section: AppSection) async {
        selectedSection = section
        searchText = ""
        switch section {
        case .runs:
            await loadRuns()
        case .portfolio:
            await loadPortfolio()
        case .settings:
            await loadSettingsData()
        default:
            await loadCandidatePage()
        }
    }

    public func loadCandidatePage() async {
        guard let baseURL, let token, canMutate || connection == .online else {
            loadCachedPage(for: selectedSection)
            return
        }
        isLoading = true
        defer { isLoading = false }
        do {
            let page = try await client.fetchCandidates(
                baseURL,
                token,
                CandidateQuery(lane: selectedSection.laneQuery, state: stateForSection)
            )
            candidates = selectedSection == .today ? today?.candidates ?? page.items : page.items
            try? cache.save(page, key: cacheKey(for: selectedSection))
            if !candidates.contains(where: { $0.id == selectedCandidateID }) {
                selectedCandidateID = candidates.first?.id
            }
            if let selectedCandidateID { await selectCandidate(selectedCandidateID) }
        } catch {
            handleConnectionError(error)
            loadCachedPage(for: selectedSection)
        }
    }

    public func selectCandidate(_ id: Int) async {
        selectedCandidateID = id
        guard let baseURL, let token, connection == .online else {
            loadCachedDetail(id)
            return
        }
        do {
            let detail = try await client.fetchCandidate(baseURL, token, id)
            selectedDetail = detail
            try? cache.save(detail, key: "candidate:\(id)")
            await markEventsRead(candidateID: id)
        } catch {
            errorMessage = error.localizedDescription
            loadCachedDetail(id)
        }
    }

    public func submitReview(
        _ decision: ReviewState,
        reason: String? = nil,
        notes: String? = nil
    ) async {
        guard canMutate, let baseURL, let token, let id = selectedCandidateID else { return }
        isMutating = true
        defer { isMutating = false }
        do {
            _ = try await client.reviewCandidate(
                baseURL,
                token,
                id,
                ReviewRequest(decision: decision, reason: reason, notes: notes)
            )
            successMessage = "\(selectedDetail?.domain ?? "Candidate") marked \(decision.rawValue)."
            await refresh()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    public func pair() async {
        guard let baseURL else {
            errorMessage = XDClientError.invalidBaseURL.localizedDescription
            return
        }
        guard !pairingCode.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            errorMessage = "Enter the one-time pairing code generated on the Dell."
            return
        }
        isMutating = true
        defer { isMutating = false }
        do {
            let result = try await client.pairDevice(
                baseURL,
                PairingRequest(code: pairingCode, deviceName: deviceName)
            )
            try tokenStore.save(result.token)
            token = result.token
            pairingCode = ""
            connection = .connecting
            await refresh()
            notificationPermission = await notifications.requestAuthorization()
            startEventStream()
            startSyncLoop()
            successMessage = "\(result.deviceName) paired. The raw credential is stored in Keychain."
        } catch {
            errorMessage = error.localizedDescription
            connection = .unpaired
        }
    }

    public func forgetLocalCredential() {
        try? tokenStore.remove()
        token = nil
        eventTask?.cancel()
        syncTask?.cancel()
        connection = .unpaired
        isStale = today != nil
    }

    public func loadRuns() async {
        guard let baseURL, let token, connection == .online else { return }
        do {
            async let runRequest = client.fetchRuns(baseURL, token)
            async let workerRequest = client.fetchWorkers(baseURL, token)
            (runs, workers) = try await (runRequest, workerRequest)
        } catch { errorMessage = error.localizedDescription }
    }

    public func triggerJob(
        kind: JobKind,
        candidateID: Int? = nil,
        seedID: Int? = nil,
        batchSize: Int = 10
    ) async {
        guard canMutate, let baseURL, let token else { return }
        var payload: [String: JSONValue] = [:]
        if kind.needsCandidate, let candidateID { payload["candidate_id"] = .number(Double(candidateID)) }
        if kind.needsSeed, let seedID { payload["seed_id"] = .number(Double(seedID)) }
        if [.availabilityRefresh, .waybackRefresh].contains(kind) {
            payload["batch_size"] = .number(Double(batchSize))
        }
        if kind == .recomputeAssessments {
            if let candidateID { payload["candidate_id"] = .number(Double(candidateID)) }
            payload["limit"] = .number(1_000)
        }
        if kind.needsCandidate && candidateID == nil {
            errorMessage = "This job requires a candidate."
            return
        }
        if kind.needsSeed && seedID == nil {
            errorMessage = "A content crawl requires an allowlisted seed ID."
            return
        }
        isMutating = true
        defer { isMutating = false }
        do {
            let key = "mac-\(kind.rawValue)-\(candidateID ?? seedID ?? Int(Date().timeIntervalSince1970))"
            let job = try await client.createJob(
                baseURL,
                token,
                JobRequest(kind: kind, payload: payload, idempotencyKey: key)
            )
            recentJobs.insert(job, at: 0)
            successMessage = "\(kind.title) queued safely."
        } catch { errorMessage = error.localizedDescription }
    }

    public func loadSettingsData() async {
        guard let baseURL, let token, connection == .online else { return }
        do {
            async let configsRequest = client.fetchConfigs(baseURL, token)
            async let devicesRequest = client.fetchDevices(baseURL, token)
            (configVersions, devices) = try await (configsRequest, devicesRequest)
            configDraft = ConfigDraft(version: activeConfig)
        } catch { errorMessage = error.localizedDescription }
    }

    public func createConfigDraft(notes: String?) async {
        guard canMutate, let baseURL, let token, let activeConfig else { return }
        guard !configChanges.isEmpty else {
            errorMessage = "The draft does not change the active configuration."
            return
        }
        isMutating = true
        defer { isMutating = false }
        do {
            let created = try await client.createConfig(
                baseURL,
                token,
                ConfigCreateRequest(config: configDraft.applying(to: activeConfig.config), notes: notes)
            )
            configVersions.insert(created, at: 0)
            successMessage = "Configuration v\(created.version) created as a draft. Review and activate it separately."
        } catch { errorMessage = error.localizedDescription }
    }

    public func activateConfig(version: Int) async {
        guard canMutate, let baseURL, let token else { return }
        isMutating = true
        defer { isMutating = false }
        do {
            _ = try await client.activateConfig(baseURL, token, version)
            await loadSettingsData()
            successMessage = "Configuration v\(version) is active."
        } catch { errorMessage = error.localizedDescription }
    }

    public func revokeDevice(_ id: Int) async {
        guard canMutate, let baseURL, let token else { return }
        do {
            try await client.revokeDevice(baseURL, token, id)
            await loadSettingsData()
        } catch { errorMessage = error.localizedDescription }
    }

    public func loadPortfolio() async {
        guard let baseURL, let token, connection == .online else { return }
        do { portfolio = try await client.fetchPortfolio(baseURL, token) }
        catch { errorMessage = error.localizedDescription }
    }

    public func recordOutcome(
        _ outcome: String,
        amountMicros: Int? = nil,
        currency: String? = nil,
        notes: String? = nil
    ) async {
        guard canMutate, let baseURL, let token, let id = selectedCandidateID else { return }
        do {
            let result = try await client.createOutcome(
                baseURL,
                token,
                id,
                PortfolioOutcomeRequest(
                    outcome: outcome,
                    amountMicros: amountMicros,
                    currency: currency,
                    notes: notes
                )
            )
            portfolio.insert(result, at: 0)
            successMessage = "Portfolio outcome recorded."
        } catch { errorMessage = error.localizedDescription }
    }

    public func markEventsRead(candidateID: Int? = nil) async {
        guard canMutate, let baseURL, let token else { return }
        let pending = events.filter { !$0.read && (candidateID == nil || $0.candidateId == candidateID) }
        for event in pending {
            _ = try? await client.markEventRead(baseURL, token, event.id)
        }
        events = events.map { item in
            guard pending.contains(where: { $0.id == item.id }) else { return item }
            return EventItem(
                id: item.id,
                candidateId: item.candidateId,
                eventType: item.eventType,
                payload: item.payload,
                createdAt: item.createdAt,
                configVersion: item.configVersion,
                read: true
            )
        }
        if candidateID == nil, let today {
            self.today = TodaySnapshot(
                generatedAt: today.generatedAt,
                systemHealth: today.systemHealth,
                unreadEvents: 0,
                mostUrgentDomain: today.mostUrgentDomain,
                candidates: today.candidates
            )
        }
    }

    public func clearMessages() {
        errorMessage = nil
        successMessage = nil
    }

    private var stateForSection: ReviewState? {
        selectedSection == .watchlist ? .research : nil
    }

    private func startEventStream() {
        eventTask?.cancel()
        guard let baseURL, let token, !isDemo else { return }
        let after = defaults.integer(forKey: Keys.lastEventID)
        eventTask = Task { [weak self] in
            guard let self else { return }
            var cursor = after
            while !Task.isCancelled {
                do {
                    for try await event in client.eventStream(baseURL, token, cursor) {
                        if Task.isCancelled { return }
                        cursor = max(cursor, event.id)
                        defaults.set(cursor, forKey: Keys.lastEventID)
                        events.insert(event, at: 0)
                        if events.count > 250 { events.removeLast(events.count - 250) }
                        if !event.read, notifiableEventTypes.contains(event.eventType) {
                            await notifications.post(event)
                        }
                        await refreshAfterEvent(event)
                    }
                } catch is CancellationError {
                    return
                } catch {
                    connection = .offline(error.localizedDescription)
                    isStale = true
                    try? await Task.sleep(for: .seconds(3))
                }
            }
        }
    }

    private func refreshAfterEvent(_ event: EventItem) async {
        guard let baseURL, let token else { return }
        do {
            today = try await client.fetchToday(baseURL, token)
            connection = .online
            isStale = false
            if let candidateID = event.candidateId, candidateID == selectedCandidateID {
                selectedDetail = try await client.fetchCandidate(baseURL, token, candidateID)
            }
        } catch {
            handleConnectionError(error)
        }
    }

    private func handleConnectionError(_ error: Error) {
        if let clientError = error as? XDClientError, clientError == .unauthorized {
            token = nil
            try? tokenStore.remove()
            connection = .unpaired
        } else {
            connection = .offline(error.localizedDescription)
        }
        isStale = today != nil
        errorMessage = error.localizedDescription
    }

    private func loadCachedToday() {
        guard let cached = try? cache.load(TodaySnapshot.self, key: Keys.todayCache) else { return }
        today = cached.0
        candidates = cached.0.candidates
        cacheDate = cached.1
        isStale = true
    }

    private func loadCachedPage(for section: AppSection) {
        guard let cached = try? cache.load(CandidatePage.self, key: cacheKey(for: section)) else {
            if section == .today { candidates = today?.candidates ?? [] }
            return
        }
        candidates = cached.0.items
        cacheDate = cached.1
        isStale = true
    }

    private func loadCachedDetail(_ id: Int) {
        guard let cached = try? cache.load(CandidateDetail.self, key: "candidate:\(id)") else { return }
        selectedDetail = cached.0
        cacheDate = max(cacheDate ?? .distantPast, cached.1)
        isStale = true
    }

    private func cacheKey(for section: AppSection) -> String {
        "candidate-page:\(section.rawValue)"
    }

    private func startSyncLoop() {
        syncTask?.cancel()
        guard let baseURL, let token, !isDemo else { return }
        syncTask = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(10))
                guard !Task.isCancelled, let self else { return }
                do {
                    let snapshot = try await client.fetchToday(baseURL, token)
                    today = snapshot
                    connection = .online
                    isStale = false
                    try? cache.save(snapshot, key: Keys.todayCache)
                } catch is CancellationError {
                    return
                } catch {
                    handleConnectionError(error)
                }
            }
        }
    }

    private var notifiableEventTypes: Set<String> {
        [
            "candidate.promoted",
            "gate.changed",
            "dossier.completed",
            "availability.changed",
            "review.changed",
            "outcome.recorded",
        ]
    }

    private enum Keys {
        static let serverAddress = "xd.server-address"
        static let deviceName = "xd.device-name"
        static let openForAttention = "xd.open-for-attention"
        static let lastEventID = "xd.last-event-id"
        static let todayCache = "today"
    }
}
