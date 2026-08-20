import SwiftUI

@MainActor
struct SettingsIndexView: View {
    @Environment(XDStore.self) private var store
    @Environment(InstrumentTheme.self) private var theme

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                VStack(alignment: .leading, spacing: 5) {
                    Text("SETTINGS")
                        .font(.system(size: 18, weight: .semibold))
                    Text("VERSIONED CONTROLS")
                        .font(theme.mono(11, weight: .semibold))
                        .foregroundStyle(theme.amber)
                }
                Spacer()
            }
            .padding(.horizontal, 22)
            .frame(height: 78)
            Divider().overlay(theme.line)
            VStack(spacing: 0) {
                indexRow("Private connection", symbol: "lock.shield", value: store.connection.label)
                indexRow("Engine configuration", symbol: "slider.horizontal.3", value: store.activeConfig.map { "v\($0.version)" } ?? "Pending")
                indexRow("Paired devices", symbol: "laptopcomputer.and.iphone", value: String(store.devices.filter { $0.revokedAt == nil }.count))
                indexRow("Notifications", symbol: "bell", value: store.notificationPermission ? "Allowed" : "Not allowed")
            }
            Spacer()
        }
        .foregroundStyle(theme.label)
        .background(theme.canvas)
        .navigationSplitViewColumnWidth(min: 290, ideal: 370, max: 450)
    }

    private func indexRow(_ title: String, symbol: String, value: String) -> some View {
        HStack(spacing: 12) {
            Image(systemName: symbol)
                .foregroundStyle(theme.secondaryLabel)
                .frame(width: 22)
            Text(title)
            Spacer()
            Text(value)
                .font(theme.mono(10))
                .foregroundStyle(theme.secondaryLabel)
        }
        .padding(.horizontal, 18)
        .frame(height: 52)
        .overlay(alignment: .bottom) { Rectangle().fill(theme.line).frame(height: 1) }
    }
}

@MainActor
struct EngineSettingsView: View {
    @Environment(XDStore.self) private var store
    @Environment(InstrumentTheme.self) private var theme
    @State private var showDiff = false
    @State private var notes = ""
    @State private var launchAtLogin = false
    @State private var loginItemError: String?

    var body: some View {
        @Bindable var store = store

        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                Text("PRIVATE SETTINGS")
                    .font(.system(size: 24, weight: .semibold))

                section("CONNECTION") {
                    VStack(alignment: .leading, spacing: 14) {
                        TextField("Private server URL", text: $store.serverAddress)
                            .textFieldStyle(.roundedBorder)
                        TextField("Device name", text: $store.deviceName)
                            .textFieldStyle(.roundedBorder)
                        if store.connection == .unpaired {
                            SecureField("One-time pairing code", text: $store.pairingCode)
                                .textFieldStyle(.roundedBorder)
                            Button("PAIR THIS MAC") { Task { await store.pair() } }
                                .buttonStyle(InstrumentButtonStyle(tone: .primary))
                                .disabled(store.isMutating)
                        } else {
                            HStack {
                                StatusLamp(
                                    color: store.connection == .online ? theme.green : theme.amber,
                                    label: store.connection.label
                                )
                                Spacer()
                                Button("Forget local credential") { store.forgetLocalCredential() }
                                    .buttonStyle(.plain)
                                    .foregroundStyle(theme.red)
                            }
                        }
                        Text("The raw device token is stored in macOS Keychain. The server stores only its hash.")
                            .font(theme.mono(10))
                            .foregroundStyle(theme.tertiaryLabel)
                    }
                }

                section("APP BEHAVIOR") {
                    VStack(alignment: .leading, spacing: 14) {
                        Toggle("Launch quietly at login", isOn: $launchAtLogin)
                        Toggle("Open the review window when attention is required", isOn: $store.openWhenAttentionRequired)
                        HStack {
                            Text("Local notifications")
                            Spacer()
                            Text(store.notificationPermission ? "ALLOWED" : "NOT ALLOWED")
                                .font(theme.mono(10, weight: .semibold))
                                .foregroundStyle(store.notificationPermission ? theme.green : theme.amber)
                        }
                        if let loginItemError {
                            Text(loginItemError)
                                .font(.system(size: 11))
                                .foregroundStyle(theme.amber)
                        }
                    }
                }

                section("ENGINE DRAFT") {
                    VStack(alignment: .leading, spacing: 16) {
                        Stepper(
                            "Paid enrichment cap: $\(store.configDraft.monthlyBudgetUSD)/month",
                            value: Binding(
                                get: { store.configDraft.monthlyBudgetUSD },
                                set: { store.configDraft.monthlyBudgetUSD = $0 }
                            ),
                            in: 0...1_000,
                            step: 5
                        )
                        VStack(alignment: .leading, spacing: 6) {
                            Text("Name screen minimum: \(store.configDraft.nameScreenMinimum.formatted(.number.precision(.fractionLength(0...1))))")
                            Slider(
                                value: Binding(
                                    get: { store.configDraft.nameScreenMinimum },
                                    set: { store.configDraft.nameScreenMinimum = $0 }
                                ),
                                in: 0...100,
                                step: 1
                            )
                        }
                        Stepper(
                            "Name enrichment pool: \(store.configDraft.nameCandidateLimit)",
                            value: Binding(
                                get: { store.configDraft.nameCandidateLimit },
                                set: { store.configDraft.nameCandidateLimit = $0 }
                            ),
                            in: 1...10_000,
                            step: 100
                        )
                        Stepper(
                            "Maximum pages per seed: \(store.configDraft.crawlerMaxPages)",
                            value: Binding(
                                get: { store.configDraft.crawlerMaxPages },
                                set: { store.configDraft.crawlerMaxPages = $0 }
                            ),
                            in: 1...250
                        )
                        Stepper(
                            "Minimum crawl delay: \(store.configDraft.crawlerDelaySeconds.formatted(.number.precision(.fractionLength(1)))) seconds",
                            value: Binding(
                                get: { store.configDraft.crawlerDelaySeconds },
                                set: { store.configDraft.crawlerDelaySeconds = $0 }
                            ),
                            in: 0.25...30,
                            step: 0.25
                        )
                        Button("PREVIEW TYPED DIFF") { showDiff = true }
                            .buttonStyle(InstrumentButtonStyle(tone: .primary))
                            .disabled(store.activeConfig == nil || store.configChanges.isEmpty || !store.canMutate)
                    }
                }

                section("VERSION HISTORY") {
                    VStack(spacing: 0) {
                        ForEach(store.configVersions) { version in
                            HStack(spacing: 12) {
                                Text("v\(version.version)")
                                    .font(theme.mono(12, weight: .semibold))
                                Text(version.notes ?? "No notes")
                                    .foregroundStyle(theme.secondaryLabel)
                                    .lineLimit(1)
                                Spacer()
                                if version.isActive {
                                    Text("ACTIVE")
                                        .font(theme.mono(10, weight: .semibold))
                                        .foregroundStyle(theme.green)
                                } else {
                                    Button(version.version < (store.activeConfig?.version ?? 0) ? "Rollback" : "Activate") {
                                        Task { await store.activateConfig(version: version.version) }
                                    }
                                    .buttonStyle(.plain)
                                    .foregroundStyle(theme.amber)
                                    .disabled(!store.canMutate)
                                }
                            }
                            .frame(height: 42)
                            Divider().overlay(theme.line)
                        }
                    }
                }

                section("PAIRED DEVICES") {
                    VStack(spacing: 0) {
                        if store.devices.isEmpty {
                            Text("No device list loaded.")
                                .foregroundStyle(theme.secondaryLabel)
                                .frame(maxWidth: .infinity, alignment: .leading)
                        }
                        ForEach(store.devices) { device in
                            HStack {
                                VStack(alignment: .leading, spacing: 3) {
                                    Text(device.deviceName)
                                    Text(device.revokedAt == nil ? "Active" : "Revoked")
                                        .font(theme.mono(9))
                                        .foregroundStyle(device.revokedAt == nil ? theme.green : theme.red)
                                }
                                Spacer()
                                if device.revokedAt == nil {
                                    Button("Revoke") { Task { await store.revokeDevice(device.id) } }
                                        .buttonStyle(.plain)
                                        .foregroundStyle(theme.red)
                                }
                            }
                            .frame(height: 44)
                            Divider().overlay(theme.line)
                        }
                    }
                }
            }
            .padding(28)
            .frame(maxWidth: 760, alignment: .leading)
        }
        .foregroundStyle(theme.label)
        .background(theme.canvas)
        .sheet(isPresented: $showDiff) {
            ConfigDiffSheet(isPresented: $showDiff, notes: $notes)
                .environment(store)
                .environment(theme)
        }
        .task {
            launchAtLogin = store.loginItems.isEnabled
            if store.configVersions.isEmpty { await store.loadSettingsData() }
        }
        .onChange(of: launchAtLogin) { _, value in
            do {
                try store.loginItems.setEnabled(value)
                loginItemError = nil
            } catch {
                loginItemError = "Login launch needs a signed app bundle: \(error.localizedDescription)"
                launchAtLogin = store.loginItems.isEnabled
            }
        }
    }

    private func section<Content: View>(
        _ title: String,
        @ViewBuilder content: () -> Content
    ) -> some View {
        VStack(alignment: .leading, spacing: 9) {
            Text(title)
                .font(theme.mono(11, weight: .semibold))
                .foregroundStyle(theme.secondaryLabel)
            InstrumentPanel {
                content()
                    .padding(18)
            }
        }
    }
}

private struct ConfigDiffSheet: View {
    @Environment(XDStore.self) private var store
    @Environment(InstrumentTheme.self) private var theme
    @Binding var isPresented: Bool
    @Binding var notes: String

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("CONFIGURATION DIFF")
                .font(theme.mono(14, weight: .semibold))
                .foregroundStyle(theme.amber)
            Text("Creating this version does not activate it. Activation remains a separate audited action.")
                .foregroundStyle(theme.secondaryLabel)
            ScrollView {
                VStack(spacing: 0) {
                    ForEach(store.configChanges) { change in
                        VStack(alignment: .leading, spacing: 7) {
                            HStack {
                                Text(change.id).font(.system(size: 13, weight: .semibold))
                                Spacer()
                                Text("\(change.before) → \(change.after)")
                                    .font(theme.mono(10))
                                    .foregroundStyle(theme.amber)
                            }
                            Text(change.effect)
                                .font(.system(size: 11))
                                .foregroundStyle(theme.secondaryLabel)
                        }
                        .padding(.vertical, 12)
                        Divider().overlay(theme.line)
                    }
                }
            }
            .frame(height: 240)
            TextField("Audit notes", text: $notes)
                .textFieldStyle(.roundedBorder)
            HStack {
                Button("Cancel") { isPresented = false }
                    .buttonStyle(InstrumentButtonStyle())
                Button("CREATE DRAFT VERSION") {
                    Task {
                        await store.createConfigDraft(notes: notes.isEmpty ? nil : notes)
                        notes = ""
                        isPresented = false
                    }
                }
                .buttonStyle(InstrumentButtonStyle(tone: .primary))
                .disabled(store.isMutating)
            }
        }
        .padding(22)
        .frame(width: 600)
        .background(theme.canvas)
    }
}

@MainActor
public struct MacSettingsView: View {
    @Environment(XDStore.self) private var store
    @Environment(InstrumentTheme.self) private var theme

    public init() {}

    public var body: some View {
        EngineSettingsView()
            .environment(store)
            .environment(theme)
            .frame(width: 720, height: 680)
    }
}

