import SwiftUI

@MainActor
struct CandidateDetailView: View {
    @Environment(XDStore.self) private var store
    @Environment(InstrumentTheme.self) private var theme
    @State private var reviewSheet: ReviewState?
    @State private var rawEvidenceExpanded = false
    @State private var sharedGatesExpanded = false

    var body: some View {
        Group {
            if let detail = store.selectedDetail {
                detailBody(detail)
            } else if store.connection == .unpaired {
                PairingRequiredView()
            } else {
                ContentUnavailableView(
                    "Select a candidate",
                    systemImage: "scope",
                    description: Text("Choose a domain to review its independent lane evidence.")
                )
                .foregroundStyle(theme.secondaryLabel)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .background(theme.canvas)
        .sheet(item: $reviewSheet) { decision in
            ReviewDecisionSheet(decision: decision)
                .environment(store)
                .environment(theme)
        }
    }

    private func detailBody(_ detail: CandidateDetail) -> some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 0) {
                header(detail)
                Divider().overlay(theme.line)
                lanePanels(detail)
                    .padding(.horizontal, 28)
                    .padding(.vertical, 20)
                Text("NO COMPENSATING SCORE")
                    .font(theme.mono(10, weight: .medium))
                    .foregroundStyle(theme.tertiaryLabel)
                    .frame(maxWidth: .infinity)
                    .padding(.bottom, 14)
                evidenceRows(detail)
                    .padding(.horizontal, 28)
                    .padding(.bottom, 28)
            }
        }
        .safeAreaInset(edge: .bottom, spacing: 0) {
            decisionBar(detail)
        }
        .background(theme.canvas)
    }

    private func header(_ detail: CandidateDetail) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(alignment: .firstTextBaseline, spacing: 12) {
                Text(detail.domain)
                    .font(.system(size: 32, weight: .semibold))
                    .foregroundStyle(theme.label)
                    .lineLimit(1)
                    .minimumScaleFactor(0.65)
                Text(detail.summary.laneLabel.uppercased())
                    .font(theme.mono(10, weight: .semibold))
                    .foregroundStyle(detail.hybrid ? theme.amber : theme.secondaryLabel)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 4)
                    .overlay { RoundedRectangle(cornerRadius: 3).stroke(theme.amber.opacity(0.55)) }
                Spacer()
                Button { Task { await store.selectCandidate(detail.id) } } label: {
                    Image(systemName: "arrow.clockwise")
                }
                .buttonStyle(.plain)
                .foregroundStyle(theme.secondaryLabel)
                .accessibilityLabel("Refresh candidate")
            }
            HStack(spacing: 10) {
                Text(detail.lifecycleState.replacingOccurrences(of: "_", with: " ").capitalized)
                Text("·")
                Text("Observed \(XDFormat.shortDate.string(from: detail.lastObserved))")
                if let promotedAt = detail.promotedAt {
                    Text("·")
                    Text("Lane entry \(XDFormat.time.string(from: promotedAt))")
                }
            }
            .font(theme.mono(11))
            .foregroundStyle(theme.secondaryLabel)

            HStack(spacing: 8) {
                Text("Recommended action:")
                    .foregroundStyle(theme.secondaryLabel)
                Text(detail.canBecomeReady ? "READY" : "RESEARCH")
                    .font(theme.mono(14, weight: .semibold))
                    .foregroundStyle(detail.canBecomeReady ? theme.green : theme.amber)
            }
        }
        .padding(.horizontal, 28)
        .padding(.vertical, 24)
    }

    private func lanePanels(_ detail: CandidateDetail) -> some View {
        HStack(alignment: .top, spacing: 14) {
            if let name = detail.assessments.first(where: { $0.lane == .name }) {
                LaneAssessmentPanel(
                    assessment: name,
                    dossier: detail.dossiers.first(where: { $0.lane == .name }),
                    links: []
                )
            }
            if let authority = detail.assessments.first(where: { $0.lane == .authority }) {
                LaneAssessmentPanel(
                    assessment: authority,
                    dossier: detail.dossiers.first(where: { $0.lane == .authority }),
                    links: detail.links
                )
            }
        }
    }

    private func evidenceRows(_ detail: CandidateDetail) -> some View {
        VStack(spacing: 0) {
            DisclosureGroup(isExpanded: $sharedGatesExpanded) {
                VStack(spacing: 0) {
                    ForEach(detail.gates.filter { $0.lane == "shared" }) { gate in
                        gateRow(gate)
                    }
                }
                .padding(.bottom, 8)
            } label: {
                evidenceLabel(
                    symbol: "shield",
                    title: "Shared Gates",
                    value: sharedGateSummary(detail),
                    color: detail.failedGates.isEmpty && detail.pendingGates.isEmpty ? theme.green : theme.amber
                )
            }
            .tint(theme.secondaryLabel)

            Divider().overlay(theme.line)
            evidenceLabel(
                symbol: "creditcard",
                title: "Registrar Quote (\(detail.latestQuote?.priceClass?.capitalized ?? "Pending"))",
                value: quoteSummary(detail.latestQuote),
                color: detail.latestQuote?.priceClass == "normal" ? theme.label : theme.amber
            )
            Divider().overlay(theme.line)
            evidenceLabel(
                symbol: "flag",
                title: "Red Flags",
                value: riskSummary(detail),
                color: detail.failedGates.isEmpty ? theme.green : theme.red
            )
            Divider().overlay(theme.line)
            DisclosureGroup(isExpanded: $rawEvidenceExpanded) {
                RawEvidenceView(detail: detail)
                    .padding(.bottom, 12)
            } label: {
                evidenceLabel(
                    symbol: "doc.text",
                    title: "Raw Evidence",
                    value: rawEvidenceExpanded ? "Expanded" : "Collapsed",
                    color: theme.secondaryLabel
                )
            }
            .tint(theme.secondaryLabel)
            Divider().overlay(theme.line)
        }
    }

    private func evidenceLabel(
        symbol: String,
        title: String,
        value: String,
        color: Color
    ) -> some View {
        HStack(spacing: 14) {
            Image(systemName: symbol)
                .font(.system(size: 16))
                .foregroundStyle(theme.secondaryLabel)
                .frame(width: 22)
            Text(title)
                .foregroundStyle(theme.secondaryLabel)
            Spacer()
            Text(value)
                .font(theme.mono(11, weight: .medium))
                .foregroundStyle(color)
                .lineLimit(1)
        }
        .frame(minHeight: 48)
        .contentShape(Rectangle())
    }

    private func gateRow(_ gate: GateResult) -> some View {
        HStack(spacing: 10) {
            Image(systemName: gate.state == .pass ? "checkmark.circle.fill" : gate.state == .fail ? "xmark.octagon.fill" : "clock.fill")
                .foregroundStyle(theme.stateColor(gate.state))
            Text(XDFormat.title(for: gate.gateKey))
                .foregroundStyle(theme.label)
            Spacer()
            Text(gate.state.rawValue.uppercased())
                .font(theme.mono(10, weight: .semibold))
                .foregroundStyle(theme.stateColor(gate.state))
        }
        .padding(.leading, 36)
        .padding(.trailing, 18)
        .frame(height: 36)
    }

    private func decisionBar(_ detail: CandidateDetail) -> some View {
        HStack(spacing: 12) {
            Button("REJECT") { reviewSheet = .reject }
                .buttonStyle(InstrumentButtonStyle(tone: .destructive))
                .keyboardShortcut(.delete, modifiers: [.command, .shift])
            Button("RESEARCH") { reviewSheet = .research }
                .buttonStyle(InstrumentButtonStyle())
                .keyboardShortcut("r", modifiers: [.command, .option])
            Button("READY") { Task { await store.submitReview(.ready) } }
                .buttonStyle(InstrumentButtonStyle(tone: .primary))
                .keyboardShortcut(.return, modifiers: .command)
                .disabled(!detail.canBecomeReady || !store.canMutate || store.isMutating)
        }
        .padding(.horizontal, 28)
        .padding(.vertical, 16)
        .background(theme.sidebar)
        .overlay(alignment: .top) { Rectangle().fill(theme.line).frame(height: 1) }
        .disabled(!store.canMutate || store.isMutating)
    }

    private func sharedGateSummary(_ detail: CandidateDetail) -> String {
        let shared = detail.gates.filter { $0.lane == "shared" }
        if shared.contains(where: { $0.state == .fail }) { return "Failed" }
        if shared.contains(where: { $0.state == .pending }) { return "Evidence pending" }
        return "All gates passed"
    }

    private func quoteSummary(_ quote: RegistrarQuote?) -> String {
        guard let quote else { return "Authoritative quote pending" }
        let registrar = quote.registrar?.capitalized ?? "Registrar"
        return "Standard registration · \(quote.displayPrice) · \(registrar)"
    }

    private func riskSummary(_ detail: CandidateDetail) -> String {
        let risks = detail.dossiers.flatMap(\.risks)
        if !detail.failedGates.isEmpty { return "\(detail.failedGates.count) failed gate(s)" }
        return risks.isEmpty ? "None" : risks.joined(separator: ", ")
    }
}

private struct LaneAssessmentPanel: View {
    @Environment(InstrumentTheme.self) private var theme
    let assessment: LaneAssessment
    let dossier: Dossier?
    let links: [LinkEvidence]

    var body: some View {
        InstrumentPanel {
            VStack(alignment: .leading, spacing: 0) {
                HStack {
                    Text("\(assessment.lane.title.uppercased()) · \(assessment.state.uppercased())")
                        .font(theme.mono(12, weight: .semibold))
                        .foregroundStyle(theme.laneColor(assessment.lane))
                    Spacer()
                    Image(systemName: assessment.missingEvidence.isEmpty ? "checkmark" : "clock")
                        .foregroundStyle(assessment.missingEvidence.isEmpty ? theme.green : theme.amber)
                }
                .padding(16)
                Divider().overlay(theme.line)

                if assessment.lane == .name {
                    metric("Subtype", assessment.nameSubtype.map { XDFormat.title(for: $0) } ?? "Unclassified")
                    metric("Name quality", scoreLabel(assessment.laneScore))
                    metric("Comparable sales", dossier?.comparableSales.isEmpty == false ? "Recorded" : "Pending")
                    metric("Buyer thesis", dossier?.buyerThesis.isEmpty == false ? "Complete" : "Pending")
                } else {
                    let independent = Set(links.map(\.sourceDomain)).count
                    let live = links.filter { $0.currentlyLive == true }.count
                    metric("Independent sources", String(independent))
                    metric("Currently live", String(live))
                    metric("Editorial placement", links.allSatisfy { $0.isEditorial == true } ? "Verified" : "Review")
                    metric("Topical context", dossier?.status == "complete" ? "Consistent" : "Pending")
                }

                Divider().overlay(theme.line)
                Text(dossier?.thesis ?? assessment.reasons.first ?? "Evidence collection in progress.")
                    .font(.system(size: 12))
                    .foregroundStyle(theme.secondaryLabel)
                    .lineLimit(3)
                    .padding(16)
                    .frame(minHeight: 76, alignment: .topLeading)
            }
        }
        .frame(maxWidth: .infinity)
    }

    private func metric(_ label: String, _ value: String) -> some View {
        HStack {
            Text(label).foregroundStyle(theme.secondaryLabel)
            Spacer()
            Text(value)
                .font(theme.mono(11, weight: .medium))
                .foregroundStyle(theme.green)
        }
        .padding(.horizontal, 16)
        .frame(height: 39)
    }

    private func scoreLabel(_ score: Double?) -> String {
        guard let score else { return "Pending" }
        if score >= 85 { return "High" }
        if score >= 70 { return "Qualified" }
        return "Research"
    }
}

private struct RawEvidenceView: View {
    @Environment(InstrumentTheme.self) private var theme
    let detail: CandidateDetail

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            if detail.links.isEmpty {
                Text("No referring-page observations recorded for this candidate.")
                    .foregroundStyle(theme.secondaryLabel)
            } else {
                ForEach(detail.links.prefix(20)) { link in
                    HStack(alignment: .top, spacing: 10) {
                        Image(systemName: link.currentlyLive == true ? "link.circle.fill" : "link.circle")
                            .foregroundStyle(link.currentlyLive == true ? theme.green : theme.amber)
                        VStack(alignment: .leading, spacing: 3) {
                            Text(link.sourceDomain)
                                .font(.system(size: 12, weight: .semibold))
                                .foregroundStyle(theme.label)
                            Text(link.anchorText ?? "No anchor text")
                                .font(theme.mono(10))
                                .foregroundStyle(theme.secondaryLabel)
                            if let context = link.contextText {
                                Text(context)
                                    .font(.system(size: 11))
                                    .foregroundStyle(theme.tertiaryLabel)
                                    .lineLimit(2)
                            }
                        }
                        Spacer()
                        Text(link.isEditorial == true ? "EDITORIAL" : "REVIEW")
                            .font(theme.mono(9, weight: .semibold))
                            .foregroundStyle(link.isEditorial == true ? theme.green : theme.amber)
                    }
                    .padding(.vertical, 6)
                    Divider().overlay(theme.line)
                }
            }
        }
        .padding(.leading, 36)
        .padding(.trailing, 18)
    }
}

private struct ReviewDecisionSheet: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(XDStore.self) private var store
    @Environment(InstrumentTheme.self) private var theme
    let decision: ReviewState
    @State private var reason = ""
    @State private var notes = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text(decision == .reject ? "REJECT CANDIDATE" : "KEEP IN RESEARCH")
                .font(theme.mono(14, weight: .semibold))
                .foregroundStyle(decision == .reject ? theme.red : theme.amber)
            if decision == .reject {
                TextField("Required reason", text: $reason)
                    .textFieldStyle(.roundedBorder)
            }
            TextEditor(text: $notes)
                .font(.system(size: 13))
                .scrollContentBackground(.hidden)
                .padding(8)
                .background(theme.panel)
                .overlay { RoundedRectangle(cornerRadius: 4).stroke(theme.line) }
                .frame(height: 120)
            HStack {
                Button("Cancel") { dismiss() }
                    .buttonStyle(InstrumentButtonStyle())
                Button(decision == .reject ? "Reject" : "Save Research") {
                    Task {
                        await store.submitReview(
                            decision,
                            reason: reason.isEmpty ? nil : reason,
                            notes: notes.isEmpty ? nil : notes
                        )
                        dismiss()
                    }
                }
                .buttonStyle(InstrumentButtonStyle(tone: decision == .reject ? .destructive : .primary))
                .disabled(decision == .reject && reason.trimmingCharacters(in: .whitespaces).isEmpty)
            }
        }
        .padding(22)
        .frame(width: 470)
        .background(theme.canvas)
    }
}

private struct PairingRequiredView: View {
    @Environment(InstrumentTheme.self) private var theme

    var body: some View {
        ContentUnavailableView {
            Label("Pair this Mac", systemImage: "lock.shield")
        } description: {
            Text("Open Settings and enter a one-time code generated on the Dell server.")
        }
        .foregroundStyle(theme.secondaryLabel)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

extension ReviewState: Identifiable {
    public var id: String { rawValue }
}
