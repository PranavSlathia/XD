import SwiftData
import SwiftUI
import XDCore

@main
@MainActor
struct XDApp: App {
    @State private var store: XDStore
    @State private var theme: InstrumentTheme

    init() {
        let demo = ProcessInfo.processInfo.arguments.contains("--demo")
        let schema = Schema([CacheRecord.self])
        let configuration = ModelConfiguration(
            "XDCache",
            schema: schema,
            isStoredInMemoryOnly: demo
        )
        let container: ModelContainer
        do {
            container = try ModelContainer(for: schema, configurations: [configuration])
        } catch {
            fatalError("Unable to create XD offline cache: \(error)")
        }
        let notifications = NotificationService()
        let store = XDStore(
            client: demo ? .preview : .live(),
            tokenStore: demo ? .memory(initial: "preview-token") : .keychain,
            cache: CacheRepository(container: container),
            notifications: notifications,
            demo: demo
        )
        let theme = InstrumentTheme()
        _store = State(initialValue: store)
        _theme = State(initialValue: theme)

        notifications.onOpenEvent = { eventID, candidateID in
            Task { @MainActor in
                if let candidateID { await store.selectCandidate(candidateID) }
                await store.markEventsRead(candidateID: candidateID)
                WindowManager.shared.open(store: store, theme: theme)
                _ = eventID
            }
        }

        Task { @MainActor in
            await store.bootstrap()
            if demo || (store.openWhenAttentionRequired && store.needsAttention) {
                WindowManager.shared.open(store: store, theme: theme)
            }
        }
    }

    var body: some Scene {
        MenuBarExtra {
            MenuBarView {
                WindowManager.shared.open(store: store, theme: theme)
            }
            .environment(store)
            .environment(theme)
        } label: {
            Label(
                store.unreadCount > 0 ? "XD \(store.unreadCount)" : "XD",
                systemImage: store.systemHealthy ? "scope" : "exclamationmark.triangle"
            )
        }
        .menuBarExtraStyle(.window)

        Settings {
            MacSettingsView()
                .environment(store)
                .environment(theme)
                .preferredColorScheme(.dark)
        }
    }
}

