# XD — Domain Hunter Engine and macOS App PRD

> **Current product source of truth** · approved 2026-08-21
>
> This document supersedes the product assumptions in `docs/PRD.md` and the
> single-funnel design in `docs/ALWAYS_ON_PIPELINE.md`. Those files remain as
> historical records. Existing APIs and Vulture remain supported throughout the
> migration and parity period.

## Summary

XD is an always-on domain discovery system for two independently valuable assets:

1. **Name Assets** — commercially strong names that may have zero backlinks.
2. **Authority Assets** — domains supported by legitimate, high-quality referring
   pages, even when the name itself is unremarkable.
3. **Hybrids** — domains that independently pass both lanes. Hybrids rank first,
   but are not required.

There is no compensating overall score. Backlinks cannot rescue a bad Name Asset,
and zero backlinks cannot hurt a good Name Asset.

The mature target is **2–3 acquisition-ready dossiers per week across either
lane**. This is a quality target, not a quota: returning zero is correct when
nothing qualifies.

XD only surfaces domains currently obtainable for an ordinary, non-premium
registration fee. It never bids, backorders, purchases, or spends money.

## Product rules and success criteria

- Initial TLDs: `.com`, `.net`, `.org`, `.co`, `.io`, and `.ai`.
- Auctions, premium listings, aftermarket purchases, and registration execution
  are out of scope.
- GitHub discovery is permanently retired. Historical GitHub evidence remains in
  the database for audit.
- Candidate states:
  - **Research:** evidence is incomplete, availability is pending, or the domain
    is being watched through expiry.
  - **Ready:** every required shared and lane-specific gate has passed.
  - **Reject:** terminal, append-only decision with a recorded reason. A rejected
    candidate returns only through an explicit reopen action.
- Fatal trademark, impersonation, toxic-history, premium-price, or availability
  failures can never be overridden into Ready.
- Ready requires authoritative availability, a current standard-price quote,
  complete lane evidence, clean history/rights/reputation checks, a legitimate
  buyer or use thesis, and no critical unknowns.
- Commercial outcomes—acquired externally, lost, contacted, sold, renewed, or
  abandoned—are recorded for calibration.

## Engine

### Independent assessments

Every discovered domain receives zero, one, or two assessments: `name` and
`authority`. A domain is a Hybrid only when both independently qualify.
Lifecycle, human review, and lane assessment states remain separate.

```text
Discovery → Normalization → Lane screening → Evidence collection
          → Hard gates → Dossier → Human decision
```

Raw observations are not candidates. A domain becomes a candidate only after it
passes the inexpensive first-stage screen for at least one lane.

### Name Asset lane

The Name lane evaluates the complete expiry inventory before any OpenPageRank
intersection. It classifies and scores categories independently:

- dictionary words;
- natural compounds and commercial phrases;
- brandables;
- acronyms;
- numeric domains; and
- geo-service names.

Deterministic, inexpensive checks run first: length, tokenization, word quality,
pronunciation, spelling ambiguity, semantic coherence, commercial applicability,
negative meanings, and subtype rules.

Only the best subset receives expensive enrichment: search demand and advertiser
intent, domain-specific comparable sales, plausible end-user categories/examples,
trademark and former-brand checks, and a human-readable name thesis.

Backlinks and OpenPageRank are excluded from Name qualification. A language model
may explain evidence or propose buyer ideas, but cannot promote a domain or bypass
a failed gate.

A Name dossier explains why the name is memorable and commercially useful, the
subtype it passed, realistic buyer categories, comparable sales (or the explicit
`comps unavailable` blocker), and risks such as spelling confusion, trademark
proximity, or narrow demand.

### Authority Asset lane

Backlinks are the primary signal, especially verified links from independent,
reputable referring domains. Provider metrics are prefilters only. Ready requires
directly verified referring pages recording:

- source URL and domain;
- anchor text and surrounding context;
- editorial versus technical/sitewide placement;
- `rel` attributes and link type;
- current HTTP/link status;
- first-seen, last-seen, and current-live status;
- source topic and relevance;
- source independence; and
- historical site topic and ownership changes.

The rubric favours legitimate editorial citations, topical consistency, source
diversity, and durable referring pages. It rejects manipulated anchors, obvious
link networks, spam history, former-brand impersonation risk, and technically
generated links.

No fixed authority threshold is initially treated as truth. Thresholds become
active only after evaluation against a labelled review set; they remain versioned
and reversible.

### Discovery priorities

Content-based discovery is ordered as follows:

1. Old resource, recommendation, and useful-links pages.
2. Government, education, association, and nonprofit PDFs.
3. Member, vendor, conference, and association directories, with strict
   former-brand safeguards.
4. Newsletter, RSS, podcast-show-note, and publisher archives.
5. Wikimedia dead-link annotations.
6. Common Crawl dangling-target and historical-link-graph changes.
7. GDELT front-page graph as a supporting stream.
8. Distress monitoring: live site → stale site → parking → DNS loss → pending
   deletion.
9. Paid outbound-link indexes later, once source economics are understood.

Common Crawl graph processing runs off the Dell server; only compact evidence is
imported. Technical and editorial edges coexist in the graph, so direct
referring-page validation remains mandatory. See
[Common Crawl Web Graphs](https://commoncrawl.org/web-graphs).

Drop feeds remain a secondary watch stream. Content-link discovery is the main
route for overlooked domains still available at registration fee.

### Availability and pricing

XD has a lifecycle adapter for each core TLD. RDAP and DNS alone never prove
availability. Before Ready, XD must:

- check authoritative registrar availability;
- obtain a current registration quote;
- classify it as normal, premium, auction, unavailable, or unknown;
- store registrar, currency, price, and check time; and
- keep conflicting or stale results in Research.

There is no purchase or registration API.

### Providers and budgets

Interchangeable interfaces cover backlink intelligence, search-demand evidence,
comparable sales, and registrar availability/pricing.

DataForSEO is the pilot backlink/search provider, with a configurable hard
default cap of **$25/month**. Reaching the cap stops paid enrichment and keeps the
evidence pending; missing evidence is never converted to zero. See
[DataForSEO backlink pricing](https://dataforseo.com/pricing/backlinks/backlinks)
and its [pricing update](https://dataforseo.com/update/pricing-update-in-dataforseo-apis).

Ahrefs can later support outbound-linked-domain discovery through its
[linked-domains interface](https://docs.ahrefs.com/en/api/reference/site-explorer/get-linkeddomains).

Comparable sales should come from a licensed provider. If reliable comps cannot
be obtained automatically, XD creates a manual evidence task and blocks the Name
lane from Ready.

## Backend contracts

### API v1

Existing endpoints remain during migration. API v1 adds:

- `GET /api/v1/today`
- `GET /api/v1/candidates?lane=&state=&search=&cursor=`
- `GET /api/v1/candidates/{id}`
- `POST /api/v1/candidates/{id}/reviews`
- `GET /api/v1/events?after=` (Server-Sent Events; supports `Last-Event-ID`)
- `POST /api/v1/events/{id}/read`
- `GET /api/v1/runs`
- `GET /api/v1/workers`
- `POST /api/v1/jobs`
- `GET /api/v1/jobs/{id}`
- `GET /api/v1/config/versions`
- `POST /api/v1/config/versions`
- `POST /api/v1/config/versions/{id}/activate`
- device pairing and credential revocation endpoints.

Reviews accept `ready`, `research`, or `reject`, plus reason and notes. The
server rejects Ready while any required gate is pending or failed.

### Data model

The durable model includes:

- independent lane assessments (`name | authority`) and Name subtype;
- lifecycle state independent of review state;
- versioned gate results (`pass | fail | pending`);
- source pages and detailed link observations;
- crawl seeds and runs;
- authoritative availability quotes;
- candidate events and global read receipts;
- typed operator jobs and worker heartbeats;
- per-device credentials;
- versioned engine configurations; and
- append-only reviews, reopen actions, and commercial outcomes.

Every assessment and run records the configuration version that produced it.
Existing evidence and historical candidates are backfilled, never deleted.

### Jobs and events

Jobs use a PostgreSQL-backed queue—never a generic shell endpoint or Docker
socket. Supported job types are:

- inventory scan;
- content crawl;
- availability refresh;
- backlink validation;
- Wayback refresh;
- assessment recomputation; and
- dossier generation.

States are `queued`, `running`, `success`, `partial`, or `failed`. Each job has an
idempotency key and database lock; a duplicate active job returns `409`.

Candidate, job, configuration, and decision changes write to an append-only event
stream. SSE catch-up lets either Mac recover missed events.

## XD macOS app

### Shape

XD is a universal SwiftUI macOS 14+ app in `apps/macos/XD`, distributed
personally to the Mac Mini and MacBook. It includes a menu-bar utility, a full
review window, quiet launch at login, automatic reconnection, and no window at
launch unless attention is required.

Full Xcode is a development prerequisite; command-line tools alone cannot provide
the final signed/installable build.

### Experience

The visual anchor is a **functional hardware instrument**: compact readouts,
clear physical-control character, restrained colour, and tactile feedback
inspired by well-designed electronic tools. It must not use generic neon, glass,
gradient-heavy, or fake-scanning aesthetics.

Three evidence-based visual directions using real hardware references are created
before implementation; one becomes the design system.

Primary navigation:

- Today
- Name Assets
- Authority Assets
- Hybrids
- Watchlist
- Runs
- Portfolio
- Settings

Today is the default and contains only genuine attention items. Reviews use a
three-column `NavigationSplitView`: filtered list, domain summary, then evidence
detail. The first detail level shows thesis, lane, red flags, gate status,
availability, and next action; raw evidence is one level deeper. See
[Apple NavigationSplitView](https://developer.apple.com/documentation/swiftui/navigationsplitview).

Review controls are Ready, Research, and Reject. Mouse targets remain obvious;
keyboard shortcuts and a command palette cover frequent actions.

### Menu bar and notifications

The menu bar shows system health, unread candidate-event count, the most urgent
domain, and Open Today. Candidate events—not raw observations—can notify for lane
entry, gate gained/lost, dossier completion, availability change, and review or
outcome change.

Both Macs receive events. Reading or handling one marks it read globally.
Notifications are generated locally by the login app; APNs is unnecessary. See
[Apple UserNotifications](https://developer.apple.com/documentation/usernotifications).

### Settings and safe controls

Settings expose versioned controls through draft → typed diff/effect preview →
activation, with one-click rollback and audit history.

Trigger buttons map only to typed backend jobs. The app cannot execute arbitrary
commands, access Docker, register a domain, or spend money.

The server is authoritative. SwiftData is an offline cache; when disconnected,
XD labels cached data as stale and disables mutations.

### Private connectivity and authentication

`dh-api` stays bound to `127.0.0.1`. Tailscale Serve exposes it privately at
`https://prsnl.tail625ab9.ts.net`, proxying to port 8007. Funnel, Cloudflare, and
public listeners are forbidden. See [Tailscale Serve](https://tailscale.com/docs/features/tailscale-serve).

Access requires tailnet ACL permission and a separate per-device token. Server
storage contains only token hashes; the raw token lives in macOS Keychain.
One-time server-generated pairing codes, device revocation, and audit records are
required.

## Operations and rollout

- Add one low-concurrency content/operator worker and later remove Vulture,
  keeping steady container count approximately flat.
- Apply explicit CPU and memory limits. Full graph analysis runs off-Dell.
- Crawling uses allowlisted seeds, verified terms, robots compliance, rate
  limits, no JavaScript, page/byte/type caps, ETag caching, and idempotent
  observations.
- Prevent SSRF by allowing only public IPs and re-resolving every redirect;
  loopback, private, link-local, and metadata targets are rejected.
- Keep cached list responses below 500 ms.
- Keep additional steady RAM below 400 MB.
- Throttle new work when its contribution pushes the Dell 15-minute load toward
  3.0.

Delivery phases:

1. Commit this durable PRD and point historical documents here.
2. Add migrations, authentication/pairing, jobs/events, config versions,
   heartbeats, and API v1 while preserving Vulture and old APIs.
3. Ship full-inventory Name evaluation and core-six registrar adapters.
4. Ship content discovery, detailed link observations, authority validation,
   DataForSEO, distress watching, and off-Dell graph jobs.
5. Complete the three-option hardware-instrument visual checkpoint.
6. Build and install XD on both Macs with login launch, notifications, review
   flows, and safe controls.
7. Run a four-week engine pilot and at least 14 days of XD/Vulture parity.
8. Retire Vulture only after event, notification, review, and recovery parity;
   then update Dell deployment and recovery documentation.

Swift-only changes use path-filtered macOS CI and must not trigger Dell
deployment.

## Acceptance plan

- A strong zero-backlink name can become a Ready Name Asset.
- Gibberish with strong provider authority cannot qualify as a Name Asset.
- An unremarkable clean domain with genuinely strong referring pages can qualify
  as an Authority Asset.
- Hybrid requires both assessments to pass independently.
- Premium, auction, unavailable, trademark-conflicting, impersonating, or
  toxic-history domains can never become Ready.
- Test subtype classification, lifecycle rules, normal-price detection, provider
  caps, source independence, link context, and gate versioning.
- Test migration/backfill without deleting historical evidence.
- Test job idempotency/locking/partial failure/retry and config rollback.
- Test pairing, per-device revocation, SSE catch-up, and two-device read sync.
- Test SSRF, redirect re-resolution, crawl limits, robots, and hostile documents.
- Test menu status, Today, review flows, keyboard/mouse use, offline stale state,
  notifications, and blocked Ready actions.
- Candidate events should reach both online Macs in approximately five seconds.
- The complete system has no purchase, bid, auction, backorder, or
  arbitrary-command endpoint.
- Track Ready yield per 100,000 observations, source yield, provider cost per
  dossier, rejection reasons, acquisitions, sales, and renewals.
- Treat 2–3 Ready dossiers per week as a mature quality objective, never a reason
  to lower gates or fabricate candidates.

## Assumptions and defaults

- Engine and client remain in the `XD` repository.
- Dell remains authoritative; both Macs are clients.
- English-language commercial discovery is the initial market.
- Paid enrichment defaults to a versioned $25 monthly hard cap.
- There is no lane quota.
- Authority Assets are for legitimate site builders; XD makes no promise that
  rankings or link value transfer. Expired-domain abuse remains disallowed under
  [Google's spam policy](https://developers.google.com/search/docs/essentials/spam-policies#expired-domain-abuse).

