import AppKit
import SwiftUI
import XDCore

@MainActor
struct MenuBarView: View {
    @Environment(XDStore.self) private var store
    @Environment(InstrumentTheme.self) private var theme
    let openWindow: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 10) {
                StatusIndicator(healthy: store.systemHealthy)
                VStack(alignment: .leading, spacing: 3) {
                    Text("XD")
                        .font(.system(size: 15, weight: .semibold))
                    Text(store.connection.label)
                        .font(.system(size: 11))
                        .foregroundStyle(theme.secondaryLabel)
                }
                Spacer()
                if store.unreadCount > 0 {
                    Text(String(store.unreadCount))
                        .font(theme.mono(12, weight: .semibold))
                        .foregroundStyle(theme.amber)
                }
            }
            .padding(14)

            Divider().overlay(theme.line)

            if let urgent = store.urgentDomain {
                VStack(alignment: .leading, spacing: 5) {
                    Text("MOST URGENT")
                        .font(theme.mono(9, weight: .semibold))
                        .foregroundStyle(theme.secondaryLabel)
                    Text(urgent)
                        .font(.system(size: 14, weight: .semibold))
                        .lineLimit(1)
                }
                .padding(14)
            } else {
                Text("No candidate needs attention.")
                    .font(.system(size: 12))
                    .foregroundStyle(theme.secondaryLabel)
                    .padding(14)
            }

            Divider().overlay(theme.line)

            Button {
                store.selectedSection = .today
                openWindow()
            } label: {
                Label("Open Today", systemImage: "tray.full")
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, 14)
                    .frame(height: 40)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)

            Button {
                Task { await store.markEventsRead() }
            } label: {
                Label("Mark events read", systemImage: "checkmark.circle")
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, 14)
                    .frame(height: 40)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .disabled(store.unreadCount == 0 || !store.canMutate)

            SettingsLink {
                Label("Settings", systemImage: "gearshape")
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, 14)
                    .frame(height: 40)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)

            Divider().overlay(theme.line)

            Button("Quit XD") { NSApp.terminate(nil) }
                .buttonStyle(.plain)
                .foregroundStyle(theme.secondaryLabel)
                .padding(14)
        }
        .frame(width: 300)
        .foregroundStyle(theme.label)
        .background(theme.canvas)
    }
}

private struct StatusIndicator: View {
    @Environment(InstrumentTheme.self) private var theme
    let healthy: Bool

    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: 4)
                .stroke(healthy ? theme.green : theme.amber, lineWidth: 1)
            Circle()
                .fill(healthy ? theme.green : theme.amber)
                .frame(width: 6, height: 6)
        }
        .frame(width: 25, height: 25)
        .accessibilityLabel(healthy ? "System healthy" : "System needs attention")
    }
}

