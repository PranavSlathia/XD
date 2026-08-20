import SwiftUI

@MainActor
struct CandidateListView: View {
    @Environment(XDStore.self) private var store
    @Environment(InstrumentTheme.self) private var theme
    @State private var searchVisible = false

    var body: some View {
        @Bindable var store = store

        VStack(spacing: 0) {
            header
            Divider().overlay(theme.line)
            if searchVisible {
                HStack(spacing: 8) {
                    Image(systemName: "magnifyingglass")
                        .foregroundStyle(theme.secondaryLabel)
                    TextField("Search domains", text: $store.searchText)
                        .textFieldStyle(.plain)
                }
                .padding(.horizontal, 16)
                .frame(height: 42)
                .background(theme.panel)
                Divider().overlay(theme.line)
            }
            if store.filteredCandidates.isEmpty {
                ContentUnavailableView(
                    "No candidates",
                    systemImage: "tray",
                    description: Text("Zero is correct when no domain clears the lane screen.")
                )
                .foregroundStyle(theme.secondaryLabel)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                List(selection: $store.selectedCandidateID) {
                    ForEach(store.filteredCandidates) { candidate in
                        CandidateRow(candidate: candidate, selected: candidate.id == store.selectedCandidateID)
                            .tag(candidate.id)
                            .listRowInsets(.init())
                            .listRowSeparator(.hidden)
                            .listRowBackground(Color.clear)
                    }
                }
                .listStyle(.plain)
                .scrollContentBackground(.hidden)
                .environment(\.defaultMinListRowHeight, 1)
            }
        }
        .background(theme.canvas)
        .navigationSplitViewColumnWidth(min: 290, ideal: 350, max: 430)
        .onChange(of: store.selectedCandidateID) { _, id in
            if let id { Task { await store.selectCandidate(id) } }
        }
    }

    private var header: some View {
        HStack(alignment: .top) {
            VStack(alignment: .leading, spacing: 5) {
                Text(store.selectedSection.title.uppercased())
                    .font(.system(size: 20, weight: .semibold))
                    .foregroundStyle(theme.label)
                Text("\(store.filteredCandidates.count) NEED ATTENTION")
                    .font(theme.mono(11, weight: .semibold))
                    .foregroundStyle(theme.amber)
            }
            Spacer()
            Button { searchVisible.toggle() } label: {
                Image(systemName: searchVisible ? "xmark" : "magnifyingglass")
            }
            .buttonStyle(.plain)
            .foregroundStyle(theme.secondaryLabel)
            .accessibilityLabel(searchVisible ? "Close search" : "Search candidates")
            Button { Task { await store.loadCandidatePage() } } label: {
                Image(systemName: "arrow.clockwise")
            }
            .buttonStyle(.plain)
            .foregroundStyle(theme.secondaryLabel)
            .keyboardShortcut("r", modifiers: .command)
            .accessibilityLabel("Refresh candidates")
        }
        .padding(.horizontal, 22)
        .padding(.vertical, 18)
        .frame(minHeight: 78)
    }
}

private struct CandidateRow: View {
    @Environment(InstrumentTheme.self) private var theme
    let candidate: CandidateSummary
    let selected: Bool

    var body: some View {
        HStack(alignment: .top, spacing: 14) {
            Circle()
                .fill(theme.amber)
                .frame(width: 8, height: 8)
                .padding(.top, 8)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 8) {
                Text(candidate.domain)
                    .font(.system(size: 16, weight: .semibold))
                    .foregroundStyle(theme.label)
                    .lineLimit(1)
                HStack {
                    Text(candidate.lifecycleState.replacingOccurrences(of: "_", with: " ").capitalized)
                    Spacer()
                    Text(XDFormat.time.string(from: candidate.lastObserved))
                }
                .font(theme.mono(11))
                .foregroundStyle(theme.secondaryLabel)
            }
            Spacer(minLength: 4)
            Text(candidate.laneLabel.uppercased())
                .font(theme.mono(10, weight: .semibold))
                .foregroundStyle(candidate.hybrid ? theme.amber : candidate.lanes.first.map(theme.laneColor) ?? theme.secondaryLabel)
                .padding(.horizontal, 7)
                .padding(.vertical, 4)
                .overlay { RoundedRectangle(cornerRadius: 3).stroke(theme.line) }
        }
        .padding(.horizontal, 18)
        .padding(.vertical, 16)
        .frame(minHeight: 104)
        .background(selected ? theme.selected : theme.canvas)
        .overlay(alignment: .bottom) { Rectangle().fill(theme.line).frame(height: 1) }
        .contentShape(Rectangle())
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(candidate.domain), \(candidate.laneLabel), \(candidate.reviewState.rawValue)")
    }
}
