import SwiftUI

@MainActor
struct SidebarView: View {
    @Environment(XDStore.self) private var store
    @Environment(InstrumentTheme.self) private var theme

    var body: some View {
        @Bindable var store = store

        VStack(spacing: 0) {
            HStack {
                Spacer()
                Text("XD")
                    .font(.system(size: 22, weight: .bold))
                    .foregroundStyle(theme.label)
            }
            .padding(.horizontal, 20)
            .frame(height: 66)

            List(selection: $store.selectedSection) {
                ForEach(AppSection.allCases) { section in
                    sidebarRow(section)
                        .tag(section)
                        .listRowBackground(
                            store.selectedSection == section ? theme.selected : Color.clear
                        )
                        .listRowSeparator(.hidden)
                }
            }
            .listStyle(.sidebar)
            .scrollContentBackground(.hidden)
            .background(theme.sidebar)

            VStack(alignment: .leading, spacing: 9) {
                Divider().overlay(theme.line)
                if let generatedAt = store.today?.generatedAt {
                    Text("\(XDFormat.shortDate.string(from: generatedAt).uppercased())  ·  \(XDFormat.time.string(from: generatedAt))")
                        .font(theme.mono(11))
                        .foregroundStyle(theme.secondaryLabel)
                }
                Text("Always-on research")
                    .foregroundStyle(theme.secondaryLabel)
                StatusLamp(
                    color: store.systemHealthy ? theme.green : theme.amber,
                    label: store.connection == .online ? "Private mode" : store.connection.label
                )
            }
            .padding(20)
        }
        .background(theme.sidebar)
        .onChange(of: store.selectedSection) { _, section in
            Task { await store.loadSection(section) }
        }
    }

    private func sidebarRow(_ section: AppSection) -> some View {
        HStack(spacing: 12) {
            Image(systemName: section.symbol)
                .font(.system(size: 15, weight: .medium))
                .foregroundStyle(store.selectedSection == section ? theme.amber : theme.secondaryLabel)
                .frame(width: 20)
            Text(section.title)
                .font(.system(size: 15))
                .foregroundStyle(theme.label)
            Spacer(minLength: 6)
            if section == .today, store.unreadCount > 0 {
                Text(String(store.unreadCount))
                    .font(theme.mono(12, weight: .semibold))
                    .foregroundStyle(theme.amber)
            }
        }
        .padding(.horizontal, 8)
        .frame(height: 42)
        .contentShape(Rectangle())
        .accessibilityLabel(
            section == .today && store.unreadCount > 0
                ? "Today, \(store.unreadCount) unread events"
                : section.title
        )
    }
}
