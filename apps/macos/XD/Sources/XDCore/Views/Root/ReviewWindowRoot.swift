import SwiftUI

@MainActor
public struct ReviewWindowRoot: View {
    @Environment(XDStore.self) private var store
    @Environment(InstrumentTheme.self) private var theme
    @State private var columnVisibility: NavigationSplitViewVisibility = .all
    @State private var commandPaletteOpen = false

    public init() {}

    public var body: some View {
        @Bindable var store = store

        NavigationSplitView(columnVisibility: $columnVisibility) {
            SidebarView()
                .navigationSplitViewColumnWidth(min: 176, ideal: 200, max: 225)
        } content: {
            switch store.selectedSection {
            case .runs:
                RunListView()
            case .portfolio:
                PortfolioListView()
            case .settings:
                SettingsIndexView()
            default:
                CandidateListView()
            }
        } detail: {
            switch store.selectedSection {
            case .runs:
                OperationsDetailView()
            case .portfolio:
                PortfolioDetailView()
            case .settings:
                EngineSettingsView()
            default:
                CandidateDetailView()
            }
        }
        .navigationSplitViewStyle(.balanced)
        .background(theme.canvas)
        .tint(theme.amber)
        .preferredColorScheme(.dark)
        .overlay(alignment: .top) {
            if store.isStale {
                StaleBanner()
                    .padding(.top, 8)
            }
        }
        .overlay {
            Button("Open command palette") { commandPaletteOpen = true }
                .keyboardShortcut("k", modifiers: .command)
                .frame(width: 1, height: 1)
                .opacity(0.001)
                .accessibilityHidden(true)
        }
        .sheet(isPresented: $commandPaletteOpen) {
            CommandPaletteView(isPresented: $commandPaletteOpen)
                .environment(store)
                .environment(theme)
        }
        .alert(
            "XD",
            isPresented: Binding(
                get: { store.errorMessage != nil || store.successMessage != nil },
                set: { if !$0 { store.clearMessages() } }
            )
        ) {
            Button("OK") { store.clearMessages() }
        } message: {
            Text(store.errorMessage ?? store.successMessage ?? "")
        }
        .frame(minWidth: 1_080, minHeight: 700)
    }
}

private struct StaleBanner: View {
    @Environment(XDStore.self) private var store
    @Environment(InstrumentTheme.self) private var theme

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: "wifi.slash")
            Text("OFFLINE CACHE")
                .font(theme.mono(11, weight: .semibold))
            if let cacheDate = store.cacheDate {
                Text("Updated \(cacheDate.formatted(.relative(presentation: .named)))")
                    .foregroundStyle(theme.secondaryLabel)
            }
            Text("Mutations disabled")
                .foregroundStyle(theme.amber)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 7)
        .background(theme.raised)
        .overlay { RoundedRectangle(cornerRadius: 4).stroke(theme.amber.opacity(0.45)) }
        .clipShape(RoundedRectangle(cornerRadius: 4))
        .shadow(color: .black.opacity(0.28), radius: 10, y: 4)
    }
}

private struct CommandPaletteView: View {
    @Environment(XDStore.self) private var store
    @Environment(InstrumentTheme.self) private var theme
    @Binding var isPresented: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text("COMMANDS")
                .font(theme.mono(12, weight: .semibold))
                .foregroundStyle(theme.amber)
                .padding(18)
            Divider().overlay(theme.line)
            command("Open Today", symbol: "tray.full", shortcut: "⌘1") {
                Task { await store.loadSection(.today) }
            }
            command("Refresh evidence", symbol: "arrow.clockwise", shortcut: "⌘R") {
                Task { await store.refresh() }
            }
            command("Mark Research", symbol: "scope", shortcut: "⌥⌘R", enabled: store.canMutate) {
                Task { await store.submitReview(.research) }
            }
            command("Mark Ready", symbol: "checkmark", shortcut: "⌘↩", enabled: store.selectedDetail?.canBecomeReady == true && store.canMutate) {
                Task { await store.submitReview(.ready) }
            }
            command("Open Runs", symbol: "play", shortcut: "⌘6") {
                Task { await store.loadSection(.runs) }
            }
        }
        .frame(width: 440)
        .background(theme.canvas)
    }

    private func command(
        _ title: String,
        symbol: String,
        shortcut: String,
        enabled: Bool = true,
        action: @escaping () -> Void
    ) -> some View {
        Button {
            action()
            isPresented = false
        } label: {
            HStack(spacing: 12) {
                Image(systemName: symbol).frame(width: 20)
                Text(title)
                Spacer()
                Text(shortcut)
                    .font(theme.mono(11))
                    .foregroundStyle(theme.tertiaryLabel)
            }
            .padding(.horizontal, 18)
            .frame(height: 44)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .disabled(!enabled)
    }
}
