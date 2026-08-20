import SwiftUI

@MainActor
struct PortfolioListView: View {
    @Environment(XDStore.self) private var store
    @Environment(InstrumentTheme.self) private var theme

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                VStack(alignment: .leading, spacing: 5) {
                    Text("PORTFOLIO")
                        .font(.system(size: 18, weight: .semibold))
                    Text("\(store.portfolio.count) OUTCOMES")
                        .font(theme.mono(11, weight: .semibold))
                        .foregroundStyle(theme.amber)
                }
                Spacer()
            }
            .padding(.horizontal, 22)
            .frame(height: 78)
            Divider().overlay(theme.line)
            List(store.portfolio) { outcome in
                VStack(alignment: .leading, spacing: 6) {
                    HStack {
                        Text("Candidate #\(outcome.candidateId)")
                            .font(.system(size: 14, weight: .semibold))
                        Spacer()
                        Text(outcome.outcome.uppercased())
                            .font(theme.mono(10, weight: .semibold))
                            .foregroundStyle(theme.green)
                    }
                    Text(XDFormat.shortDate.string(from: outcome.occurredAt))
                        .font(theme.mono(10))
                        .foregroundStyle(theme.secondaryLabel)
                }
                .padding(.vertical, 12)
                .listRowBackground(theme.canvas)
            }
            .listStyle(.plain)
            .scrollContentBackground(.hidden)
        }
        .foregroundStyle(theme.label)
        .background(theme.canvas)
        .navigationSplitViewColumnWidth(min: 290, ideal: 370, max: 450)
    }
}

@MainActor
struct PortfolioDetailView: View {
    @Environment(XDStore.self) private var store
    @Environment(InstrumentTheme.self) private var theme
    @State private var outcome = "acquired"
    @State private var notes = ""
    private let outcomes = ["acquired", "lost", "inquiry", "sold", "renewed", "abandoned"]

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                Text("COMMERCIAL OUTCOMES")
                    .font(.system(size: 24, weight: .semibold))
                Text("Record what happened outside XD so its gates can be calibrated against reality. This form cannot register, bid on, or sell a domain.")
                    .foregroundStyle(theme.secondaryLabel)
                    .frame(maxWidth: 620, alignment: .leading)
                InstrumentPanel {
                    VStack(alignment: .leading, spacing: 16) {
                        Picker("Outcome", selection: $outcome) {
                            ForEach(outcomes, id: \.self) { Text($0.capitalized).tag($0) }
                        }
                        TextEditor(text: $notes)
                            .scrollContentBackground(.hidden)
                            .padding(8)
                            .frame(height: 110)
                            .background(theme.raised)
                            .overlay { RoundedRectangle(cornerRadius: 4).stroke(theme.line) }
                        Button("RECORD OUTCOME") {
                            Task {
                                await store.recordOutcome(outcome, notes: notes.isEmpty ? nil : notes)
                                notes = ""
                            }
                        }
                        .buttonStyle(InstrumentButtonStyle(tone: .primary))
                        .disabled(!store.canMutate || store.selectedCandidateID == nil)
                    }
                    .padding(18)
                }
                Text("Select a candidate in Today or an asset lane before recording its outcome.")
                    .font(theme.mono(10))
                    .foregroundStyle(theme.tertiaryLabel)
            }
            .padding(28)
        }
        .foregroundStyle(theme.label)
        .background(theme.canvas)
    }
}

