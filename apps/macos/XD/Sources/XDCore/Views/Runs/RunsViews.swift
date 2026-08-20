import SwiftUI

@MainActor
struct RunListView: View {
    @Environment(XDStore.self) private var store
    @Environment(InstrumentTheme.self) private var theme

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                VStack(alignment: .leading, spacing: 5) {
                    Text("RUNS")
                        .font(.system(size: 18, weight: .semibold))
                    Text("\(store.runs.count) RECENT")
                        .font(theme.mono(11, weight: .semibold))
                        .foregroundStyle(theme.amber)
                }
                Spacer()
                Button { Task { await store.loadRuns() } } label: {
                    Image(systemName: "arrow.clockwise")
                }
                .buttonStyle(.plain)
            }
            .padding(.horizontal, 22)
            .frame(height: 78)
            Divider().overlay(theme.line)
            List(store.runs) { run in
                VStack(alignment: .leading, spacing: 7) {
                    HStack {
                        Text(run.source)
                            .font(.system(size: 14, weight: .semibold))
                        Spacer()
                        Text(run.state.uppercased())
                            .font(theme.mono(10, weight: .semibold))
                            .foregroundStyle(run.state == "success" ? theme.green : theme.amber)
                    }
                    Text("\(run.kind.uppercased()) · \(XDFormat.shortDate.string(from: run.startedAt)) \(XDFormat.time.string(from: run.startedAt))")
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
struct OperationsDetailView: View {
    @Environment(XDStore.self) private var store
    @Environment(InstrumentTheme.self) private var theme
    @State private var selectedKind: JobKind = .inventoryScan
    @State private var candidateID = ""
    @State private var seedID = ""
    @State private var batchSize = 10

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                VStack(alignment: .leading, spacing: 7) {
                    Text("SAFE OPERATIONS")
                        .font(.system(size: 24, weight: .semibold))
                    Text("Typed jobs only · no shell · no Docker · no registration")
                        .font(theme.mono(11))
                        .foregroundStyle(theme.secondaryLabel)
                }
                InstrumentPanel {
                    VStack(alignment: .leading, spacing: 16) {
                        Picker("Job", selection: $selectedKind) {
                            ForEach(JobKind.allCases) { kind in
                                Text(kind.title).tag(kind)
                            }
                        }
                        if selectedKind.needsCandidate || selectedKind == .recomputeAssessments {
                            TextField("Candidate ID", text: $candidateID)
                                .textFieldStyle(.roundedBorder)
                        }
                        if selectedKind.needsSeed {
                            TextField("Allowlisted seed ID", text: $seedID)
                                .textFieldStyle(.roundedBorder)
                        }
                        if [.availabilityRefresh, .waybackRefresh].contains(selectedKind) {
                            Stepper("Batch size: \(batchSize)", value: $batchSize, in: 1...100)
                        }
                        Button("QUEUE \(selectedKind.title.uppercased())") {
                            Task {
                                await store.triggerJob(
                                    kind: selectedKind,
                                    candidateID: Int(candidateID),
                                    seedID: Int(seedID),
                                    batchSize: batchSize
                                )
                            }
                        }
                        .buttonStyle(InstrumentButtonStyle(tone: .primary))
                        .disabled(!store.canMutate || store.isMutating)
                    }
                    .padding(18)
                }

                sectionTitle("WORKERS")
                InstrumentPanel {
                    VStack(spacing: 0) {
                        if store.workers.isEmpty {
                            Text("No worker heartbeats loaded.")
                                .foregroundStyle(theme.secondaryLabel)
                                .padding(18)
                                .frame(maxWidth: .infinity, alignment: .leading)
                        } else {
                            ForEach(store.workers) { worker in
                                HStack {
                                    StatusLamp(
                                        color: worker.state == "idle" || worker.state == "running" ? theme.green : theme.amber,
                                        label: worker.workerName
                                    )
                                    Spacer()
                                    Text(worker.state.uppercased())
                                        .font(theme.mono(10, weight: .semibold))
                                }
                                .padding(.horizontal, 16)
                                .frame(height: 42)
                                Divider().overlay(theme.line)
                            }
                        }
                    }
                }

                if !store.recentJobs.isEmpty {
                    sectionTitle("QUEUED FROM THIS MAC")
                    InstrumentPanel {
                        VStack(spacing: 0) {
                            ForEach(store.recentJobs) { job in
                                HStack {
                                    Text(job.kind.title)
                                    Spacer()
                                    Text(job.state.uppercased())
                                        .font(theme.mono(10, weight: .semibold))
                                        .foregroundStyle(theme.amber)
                                }
                                .padding(.horizontal, 16)
                                .frame(height: 42)
                                Divider().overlay(theme.line)
                            }
                        }
                    }
                }
            }
            .padding(28)
        }
        .foregroundStyle(theme.label)
        .background(theme.canvas)
    }

    private func sectionTitle(_ value: String) -> some View {
        Text(value)
            .font(theme.mono(11, weight: .semibold))
            .foregroundStyle(theme.secondaryLabel)
    }
}

