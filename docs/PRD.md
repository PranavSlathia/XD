# Domain Hunter — Product Requirements Document

> v0.1 · 2026-05-14 · Personal use tool. Single operator. Tailscale-only.

---

## 1. Problem

Existing expired-domain tools (SpamZilla $49/mo, DomCop $49-199/mo, ExpiredDomains.net, CatchDoms) all consume the same handful of *post-expiry* registrar feeds. They miss high-authority domains that don't yet show on expiring lists — domains that authority sources (academia, patents, popular GitHub repos) link to but that have quietly gone dead. They also lack:

- LLM-driven content-history classification (was this domain ever spam / adult / casino / parked?)
- Forward-looking distress signals (cert decay, content decay, redirect history)
- Comp-based valuation against historical sales

Operator needs a self-hosted tool that surfaces ~20-50 *worth-buying* expired-domain candidates per day, scored and enriched, with all the standard ExpiredDomains.net-equivalent filters plus the novel inverse-authority-graph signals.

---

## 2. Goal

> **Produce a daily ranked shortlist of 20-50 expired/available domains worth manually acquiring**, for a single operator, with enough context per candidate to make a buy/skip decision in <30 seconds.

Non-goals (out of scope):
- Automated acquisition (operator buys manually via GoDaddy / Porkbun / Namecheap / SnapNames / DropCatch).
- Listing / sale / outbound — handled by a separate flipper tool.
- Drop-catching at the registry level (impossible at our scale).
- Workflow B brandable speculation — explicitly deferred.
- Multi-user / SaaS — single-operator only for v1.

---

## 3. Users & access

- **One user**: the operator. Authenticated by virtue of being on Tailscale.
- **Access**: Tailscale-only web dashboard at `domain-hunter.taildxxxxx.ts.net`.
- **No public internet exposure.**

---

## 4. Functional requirements

### 4.1 Ingestion

**Phase 1 (build now): A2 only.** A3 and A4 require spikes before commitment (see § 8).

| Source | Phase | Description | Cadence | Tooling |
|---|---|---|---|---|
| **A2 — GitHub README / docs dead-link miner** | **1** | Discover external URLs in README, docs/, wiki for repos with ≥500 stars. | Daily incremental, weekly full re-scan | GHArchive on BigQuery to find repos with new PushEvents → GitHub Contents/Trees API with ETag-conditional `GET` → regex URLs from text. Sparse / partial clone (`git clone --filter=blob:none --depth=1`) only when Contents API misses a path. |
| **A3 — Academic citation URL miner** | **2 (spike required)** | OpenAlex provides authority/citation *scoring* (work IDs, primary_location). Actual URL mining requires CrossRef references (where present), PubMed Central OA/JATS full text, or licensed OA PDFs. Spike must demonstrate non-trivial yield before commitment. | Quarterly | CrossRef Public Data File + PMC OA bulk + OpenAlex (scoring layer) |
| **A4 — Google Patents prior-art URL miner** | **2 (spike required)** | Source table: `patents-public-data.patents.publications` (not `google_patents_research.publications`). Useful fields: `claims_localized`, `description_localized`, **`citation.npl_text`** (Non-Patent Literature). NPL text is where prior-art URLs typically live. Run BigQuery dry-run (`maximum_bytes_billed`) before any full scan. | Quarterly | BigQuery + REGEXP_EXTRACT_ALL on npl_text/description_localized |
| **CZDS daily zone files** | **4 (blocked on approval)** | Daily delete diff per TLD. Application submitted day 1; approvals take 3–10 business days per TLD. Without CZDS or RDAP EPP status, Phase 1 cannot reliably populate `pending_delete` / `expiring_soon` status (see § 4.2). | Daily | `pip install czds-api` (acidvegas) |

**A2 cost / volume controls:**

- Use GHArchive's BigQuery `events` table to identify repos with recent activity (PushEvent / CreateEvent in last 7 days). Only fetch those.
- Use the GitHub REST `repos/{owner}/{repo}/contents/{path}` endpoint with `If-None-Match` ETag headers — returns 304 unchanged → near-zero quota cost on repeat runs.
- **Per-repo budget caps (first-pass cost — ETags don't help here):**
  - max files scanned per repo: 50
  - max markdown files per repo: 30
  - max clone size (sparse clone fallback): 50 MB
  - **skip archived repos** unless explicitly whitelisted
  - **skip vendored / generated paths**: `vendor/`, `node_modules/`, `dist/`, `build/`, `*.min.*`, `third_party/`
- Sparse-clone (`--filter=blob:none --depth=1 --sparse`) only when Contents API misses more than 5 candidate paths.
- Cap raw URLs extracted per day at 50k; if exceeded, raise star threshold dynamically next day.

**A2 path / context safety filter (hard reject before any URL becomes a candidate):**

GitHub dead-link mining surfaces *operational* URLs as often as editorial ones. Registering an operational URL is a supply-chain-attack surface — we will not do it. Every extracted URL is tagged with a `source_context_type` (see § 12 data model). Hard-reject URLs whose context is operational; only `editorial` / `homepage` / `docs_reference` URLs become candidates.

| Context | Action |
|---|---|
| URL appears in `setup.py`, `pyproject.toml`, `requirements*.txt`, `Pipfile`, `poetry.lock` | **REJECT** — Python dependency |
| URL appears in `package.json`, `package-lock.json`, `yarn.lock`, `pnpm-lock.yaml` | **REJECT** — Node dependency |
| URL appears in `Gemfile*`, `composer.*`, `Cargo.*`, `go.mod`, `go.sum`, `Podfile*`, `Package.swift` | **REJECT** — package manager |
| URL appears in `Dockerfile`, `docker-compose*.y*ml`, `Containerfile` | **REJECT** — image dependency |
| URL appears in `.github/workflows/*`, `.gitlab-ci.yml`, `.circleci/*`, `Jenkinsfile`, `azure-pipelines.yml`, `*.tf` | **REJECT** — CI/CD or IaC dependency |
| Path or filename contains `install`, `bootstrap`, `setup-`, `entrypoint`, `update`, `heartbeat`, `auth`, `sso`, `webhook`, `callback`, `health` | **REJECT** — operational endpoint |
| URL appears in `SECURITY.md`, `CONTRIBUTING.md` under "report a vulnerability" or "security contact" | **REJECT** — security surface |
| URL is inside a fenced markdown code block (` ```...``` `) | **REJECT** by default — code blocks are 90%+ operational |
| URL is the target of an HTML `<script src>` / `<link href>` / `<img src>` extracted from rendered docs | **REJECT** — asset host |
| URL path contains `/api/`, `/oauth`, `/auth/`, `/.well-known/`, `/webhook`, `/cdn/`, `/track`, `/pixel`, `/check-update` | **REJECT** — runtime endpoint |
| URL is in `README.md` prose (not code block) AND looks like a project homepage / blog / paper / "see also" reference | **ACCEPT** as `editorial` |
| URL is in `docs/**/*.md` prose | **ACCEPT** as `docs_reference` |
| URL is the repo's declared homepage in `package.json` / `setup.cfg` / GitHub repo settings | **ACCEPT** as `homepage` |
| Anything else | tag as `unknown` and exclude from Phase 1 digest (keep in DB for later review) |

The classifier runs deterministically on path + surrounding markdown context. Borderline cases (`unknown`) can be human-spot-checked from the dashboard but never auto-promoted to the digest.

### 4.2 Availability check — RDAP-first

ICANN's RDAP-Phase-2 deadline (28 January 2025) made RDAP the **definitive** gTLD registration-data source; WHOIS is legacy. Our waterfall starts with RDAP.

> ⚠️ **DNS NXDOMAIN is NOT availability evidence.** A registered domain can have zero DNS records (parked, hold, intentionally null). NXDOMAIN is *only* a liveness hint that the candidate is worth a paid availability check — it never sets `current_status` to `available` on its own. Authoritative availability must come from RDAP (or a registrar availability API). Code MUST refuse to mark a candidate `available` based solely on a DNS lookup.

| Order | Method | Cost | Role |
|---|---|---|---|
| 1 | **`dnspython` NXDOMAIN check** | Free | **Liveness hint only.** NXDOMAIN ⇒ worth paying for RDAP. NS-records-present ⇒ probably registered, deprioritise RDAP cost. Never sets authoritative status. |
| 2 | **RDAP via IANA bootstrap registry** | Free | **Authoritative.** Registration status + EPP status codes (`pendingDelete`, `redemptionPeriod`, `clientHold`, `serverHold`, `autoRenewPeriod`). Use `httpx-rdap` or the `rdap` Python client. IANA's bootstrap registry (`https://data.iana.org/rdap/dns.json`) tells us which RDAP server to query per TLD. |
| 3 | **WhoisJSON** | 1,000 req/mo free recurring | Fallback authoritative source for TLDs not yet on RDAP. Confirmed coverage of .io/.ai/.info/.biz/.xyz/.shop. Official `whoisjson` Python client. |
| 4 | **WhoisFreaks Domain Availability** | 500 free credits then ~$0.001/check; up to 100 domains/req | Bulk fallback once WhoisJSON free tier exhausted. |
| 5 | **`python-whois`** (legacy) | Free | Last-resort fallback for ccTLDs without RDAP/WhoisJSON coverage. ⚠️ pip name is `python-whois`, NOT `whois`. |

**`availability_confidence` enum** (stored alongside `current_status`):
- `authoritative` — RDAP / WhoisJSON / WhoisFreaks returned an unambiguous status
- `probable` — One source says available but another disagrees, or only a legacy WHOIS source responded
- `unknown` — Pipeline could not get a definitive answer (rate limit, network error, unsupported TLD)
- `conflicting` — Two sources disagree (e.g. RDAP says available, WhoisJSON says registered) — never goes to digest

Status field on candidate (derived from RDAP EPP status codes when available):
`unknown` / `registered` / `available` / `pending_delete` / `redemption_period` / `expiring_soon` / `client_hold` / `server_hold`.

> **`pending_delete` / `expiring_soon` require either CZDS or RDAP EPP status.** Without CZDS (Phase 4) AND when RDAP doesn't expose EPP status for a given TLD, Phase 1 can mark only `available` vs `registered`. Candidates with `unknown` deletion timing go to the dashboard watchlist, NOT the daily digest.

> **Only candidates with `availability_confidence = authoritative` AND `current_status ∈ {available, pending_delete, redemption_period, expiring_soon}` are eligible for the daily digest.**

### 4.3 Wayback / archive-history analysis

For every available candidate, pull Wayback Machine CDX history and analyze for content quality and spam history.

**Required signals:**
- **First capture date**, **last capture date**, **total captures count**
- **Capture density timeline** — bursts of activity vs sparse
- **Content-type transitions** — real-content → parked → 404 transitions
- **Spam history detection**:
  - Was the domain ever hosting adult / casino / pharma content?
  - Did it host PBN-style auto-generated content?
  - Did it have Chinese / Russian spam content (common hijack signal)?
- **Redirect history** — did it 301/302 to other domains historically? Which?
- **Language history** — did the domain switch languages (often hijack indicator)
- **Final-content classification** — what did the site look like before it died?

**Tooling:**
- Wayback CDX API (free): `https://web.archive.org/cdx/search/cdx` — call directly from Python (~30 lines, no third-party CLI needed; `waybackurls` is unlicensed and references a dead Common Crawl index — skipped per IMPLEMENTATION_NOTES.md).
- Cheap-metadata pass first: capture density, span (first→last), parking-template detector via HTML hash signatures. **Run before any LLM call.**
- **Claude Haiku classifier** runs only on candidates that already pass cheap filters (positive availability + positive metadata score). Prompt: given N representative snapshots (HTML or screenshot) → classify content history as `clean` / `spam_history` / `adult_history` / `redirect_history` / `pbn_history` / `mixed` with confidence.
- Hard daily cap: ≤ N classifications per day (default 200) enforced by Redis-backed counter — never blow through budget.
- Cache classifications by `(domain, cdx_hash)` — re-classify only if Wayback shows new captures.

### 4.4 ExpiredDomains.net-equivalent filter set

Every candidate gets these scored metrics (the standard domainer filter set):

| Metric | Source |
|---|---|
| Domain length (chars) | computed |
| TLD | computed |
| Domain age (years since first registration) | WHOIS / Wayback first-seen |
| Wayback first-seen / last-seen / count | CDX |
| Language (current and historical) | Claude on snapshot content |
| Has hosted adult / casino / pharma | Wayback classifier |
| Has been redirected (currently or historically) | Wayback + live probe |
| **Open PageRank** (0-10) | DomCop free API |
| **Backlink count estimate** | Common Crawl Web Graph |
| **Referring domains count** | Common Crawl |
| **Inbound source authority score** | from A2/A3/A4 — repo stars / paper citations / patent count |
| IP / hosting country (last known) | Wayback + reverse DNS |
| Pending delete / available / registered status | Section 4.2 |
| Reputation flags (Bluecoat / X-Force / Talos / Google Safe Browsing) | `threatexpress/domainhunter` modules |
| Trademark risk score | **Local USPTO trademark bulk-data index** (ingest the USPTO trademark daily-XML dumps from `data.uspto.gov/bulkdata/`) for exact + fuzzy mark search. TSDR API used only as enrichment when a candidate matches a serial/registration number. ⚠️ TESS was retired in 2023; do not reference it. |

### 4.5 Scoring

Composite score on 0–100 scale, computed from above metrics.

**Normalization rules** (each input clipped to its defined range, then linearly scaled to 0–100):

| Input | Raw range → 0-100 scaling |
|---|---|
| `max_source_authority` | log10(max_signal + 1) ÷ log10(SAT) × 100, where `max_signal` = MAX over all mentions of (repo_stars OR paper_citations OR patent_forward_cites); SAT (saturation) = 10⁶. **Max, not sum** — prevents trash domains mentioned by many tiny sources from inflating. |
| `source_diversity_bonus` | min(distinct_sources / 5, 1.0) × 100, **capped** — three or more independent corroborating sources matters; beyond 5 adds nothing. |
| `referring_domains_score` | min(referring_domains / 50, 1.0) × 100 — 50+ unique referring domains = full credit |
| `open_pagerank_score` | (Open PageRank − 0) ÷ 10 × 100 |
| `wayback_clean_score` | classifier output: `clean`=100, `mixed`=50, others=0 |
| `age_score` | min(ln(years_since_first_cap + 1) / ln(20), 1.0) × 100 — 20-year-old = full credit |
| `spam_penalty` | classifier output: 100 if any `*_history` flag, 0 otherwise |
| `tm_risk_penalty` | 100 × P(TM-conflict) from USPTO-bulk fuzzy match (Levenshtein + Claude similarity), 0–1 → ×100 |
| `reputation_penalty` | 100 if Bluecoat/X-Force/Talos/Umbrella flags Malicious or Suspicious, else 50 if Mixed/Uncategorised, else 0 |

**Composite weights (initial; tunable from dashboard):**

```
score =   0.25 * max_source_authority
        + 0.10 * source_diversity_bonus      # capped
        + 0.20 * referring_domains_score
        + 0.15 * open_pagerank_score
        + 0.10 * wayback_clean_score
        + 0.10 * age_score
        - 0.10 * spam_penalty
        - 0.10 * tm_risk_penalty
        - 0.10 * reputation_penalty
```

Composite is then clipped to [0, 100]. Weights live in a `scoring_weights` table so re-runs are reproducible and tunable without code change.

**Hard filters (auto-reject regardless of score):**
- TM exact match in USPTO bulk index → reject
- Wayback shows adult/casino/pharma at any historical point → reject (untouchable)
- Google Safe Browsing flagged → reject
- `available` status check returned `registered` (not actually available) → reject for current run, recheck weekly

### 4.6 Output

Three output surfaces, all driven by the same `candidates` table:

**1. Web dashboard (Tailscale-only)**
- Sortable / filterable candidate table (date, score, all metrics)
- Detail view per candidate with all metrics, Wayback timeline, score breakdown, raw inbound link list, screenshots of historical captures
- Actions: mark as `bought`, `passed`, `watching`
- Filter saved-views (e.g., "score >70, no spam history, .com only")

**2. Daily Discord digest**
- Top **5–10 high-confidence buyable candidates** pushed via Discord webhook at 09:00 IST daily (was 20–50 — tightened per § 9)
- "High-confidence buyable" requires ALL of:
  - `availability_confidence = 'authoritative'`
  - `current_status ∈ {available, pending_delete, redemption_period, expiring_soon}`
  - `composite_score ≥ 70`
  - No hard-filter triggered
  - **If a `registrar_quotes` row exists for the candidate within the last 14 days, `quote_price_micros < PREMIUM_CEILING_MICROS`** (default $200 = 200_000_000). Premium-quoted candidates go to a separate "Premium watch" channel in the dashboard, not the daily digest.
- Rich embeds: domain name, score, top 3 reasons (highest-weight metrics), latest quote price (if known), Wayback timeline link, link to dashboard detail page
- One message per digest, paginated if >10 candidates

**3. CSV / JSON export**
- "Download today's shortlist" button → CSV
- API endpoint: `GET /api/candidates?date=YYYY-MM-DD&min_score=70` → JSON
- Useful for spreadsheet workflow + future flipper-tool integration

---

## 5. Non-functional requirements

| Requirement | Target |
|---|---|
| Daily raw URL discovery (A2) | ≤ 50k / day (hard cap; if exceeded, raise star threshold next day) |
| Daily candidates passing cheap filters | ≤ 500 / day (advance to enrichment) |
| Daily candidates Claude-classified | ≤ 200 / day (Redis-counter enforced) |
| Daily high-confidence purchasable | **5–10 / day** (target for Discord digest; see § 9) |
| Dashboard latency | <500ms for paginated candidate list |
| Wayback classification unit cost | <$0.005/domain (Claude Haiku, prompt-cached) |
| Monthly API budget cap | **$50–100/mo total** (see hard spend controls below) |
| Uptime | Best-effort; ingestion jobs idempotent and resumable |
| Data retention | Indefinite (single-operator, no privacy concerns) |
| Reproducibility | All ingestion + scoring runs logged with input snapshot and scoring-weights version |

**Hard spend controls (enforced in code, not just documented):**

| Control | Mechanism |
|---|---|
| BigQuery cost cap | Every query sets `maximum_bytes_billed` to a per-job limit (default 10 GB ≈ $0.05). Larger scans require explicit env flag override. |
| Claude / LLM daily cap | Redis token-bucket: `llm_calls_today` counter, hard-fail at 200 calls/day. |
| Paid availability cap | Per-day counter on `whoisjson_calls` (1k/mo ÷ 30) and `whoisfreaks_calls` (budget-derived). Exceed → tier-down to RDAP + DNS only. |
| Common Crawl egress | Stay in `us-east-1`; track GB/month via S3 CloudWatch. Hard cap 100 GB/mo. |
| Classification gating | LLM never invoked unless candidate already passed availability + cheap metadata filters. |

The $50–100/mo budget is achievable **only** because cheap filters gate every paid step. Without the gating, the same pipeline costs ~$250–330/mo (see RESEARCH.md § 7 — that figure assumes 1k LLM classifications/day with no gating).

---

## 6. Tech stack

| Layer | Choice | Why |
|---|---|---|
| Language | **Python 3.12** | Every open-source repo we're stitching is Python; matches operator skill |
| API framework | **FastAPI** | Async, OpenAPI-native, well-known |
| Frontend | **SvelteKit** (or Next.js) | Modern, lightweight, single-operator UI doesn't need React ecosystem heft. Tailscale-only so no SSR complexity. |
| Database | **Postgres 16 + pgvector** | Already running on Dell; embeddings for similarity / comp valuation in future |
| Job scheduler | **APScheduler** + cron in Docker | Simple; no Airflow overhead for personal scale |
| Queue | **Redis** | For Claude API rate-limited tasks |
| LLM | **Claude Haiku** (scoring) + **Claude Sonnet** (top-5% rescore) | Haiku at firehose, Sonnet on shortlist. Prompt-caching aggressively. |
| Embeddings | **Voyage-3** or **OpenAI text-embedding-3-large** | For future comp-based valuation |
| Liveness | **`httpx`** async (deadfinder skipped — Crystal sidecar overkill for our volume) | Fast batch HTTP checks |
| Availability waterfall | **`dnspython` → RDAP (`httpx-rdap` / `rdap`) → WhoisJSON → WhoisFreaks → `python-whois`** | RDAP-first per ICANN Jan 2025; WHOIS as legacy. See § 4.2. |
| Wayback | **CDX API** called directly via `httpx` (~30 LoC) | `waybackurls` skipped — unlicensed + dead CC index reference |
| Reputation | **`threatexpress/domainhunter`** 4 functions vendored under BSD-3 (attribution required) | Bluecoat / X-Force / Talos / Umbrella |
| Trademark | **USPTO trademark bulk-data daily XML** ingested locally (Postgres) + TSDR API for serial-level enrichment | TESS is retired (2023) — do NOT reference TESS in code or docs |
| Common Crawl | **DuckDB** over Parquet snapshots | Memory-mapped, doesn't blow RAM |
| Deployment | **Docker Compose** on Dell | Same pattern as other services |
| Notifications | **Discord webhook** | Free, zero auth, rich embeds |

---

## 7. Out-of-scope (explicit)

These are deliberately excluded from v1:

- ❌ Workflow B brandable generation
- ❌ Acquisition automation (no auto-backorder, no snipe bot)
- ❌ Sedo / Afternic / Dan listing automation
- ❌ Outbound buyer email automation
- ❌ Multi-user / auth / billing / SaaS
- ❌ CZDS pipeline until approval received
- ❌ Mobile app
- ❌ Public-facing UI / landing page

---

## 8. Phases

### Phase 0 — Foundations (Week 1)
- [ ] CZDS applications submitted day 1 (.com, .net, .org, .info, .biz, .xyz, .shop)
- [ ] USPTO trademark bulk daily-XML download cron set up (data.uspto.gov/bulkdata/)
- [ ] Postgres 16 + pgvector container running on Dell
- [ ] Repo scaffolded: `~/projects/domain-hunter` with FastAPI + SvelteKit + Docker Compose
- [ ] Schema applied (see § 12 data model)
- [ ] Discord webhook configured + smoke-tested
- [ ] Hard spend controls wired before any pipeline runs

### Phase 0.5 — A2 yield spike (Week 1, before dashboard build)

**Gate: validate the A2 hypothesis on real data before building the rest of the system.**

Sample 500–1,000 high-star repos (≥ 5k stars to start, biased toward older repos where dead links are most likely). Run a minimum-viable A2 pipeline end-to-end:

- [ ] Sample 500–1,000 repos from GHArchive, biased toward age + star count
- [ ] Extract URLs only from `README.md` / `README.rst` and `docs/**/*.md` markdown **prose** (skip code blocks)
- [ ] Apply the § 4.1 path/context safety filter — drop anything classified as operational
- [ ] Normalise to **registrable domain** (eTLD+1 via `tldextract`, dropping path/subdomain noise; use Public Suffix List)
- [ ] Run liveness probe (`httpx` async) + RDAP availability waterfall (§ 4.2)
- [ ] Manually review **top 50** by candidate `max_source_authority`
- [ ] Write `docs/spikes/a2-yield.md` with measured numbers:

| Spike metric | Target |
|---|---|
| URLs extracted per repo (median) | (record actual) |
| `editorial / homepage / docs_reference` fraction after path classifier | ≥ 60% — if lower, classifier needs tuning |
| % of registrable domains responding NXDOMAIN | (record actual) |
| **% of NXDOMAIN → actually available per RDAP** | (record actual — this is the headline yield) |
| `tm_rejection_rate` on top-50 manual review | ≤ 30% |
| `spam_history_rate` on top-50 (Wayback spot-check) | ≤ 30% |
| **Buyable + interesting domains in top 50 (operator judgment)** | ≥ 3 |
| Total Phase 0.5 spend | < $10 |

**Decision gate:**
- ≥ 3 buyable+interesting in top 50 AND projected daily yield ≥ 1 buyable / day → proceed to Phase 1 build
- < 3 buyable in top 50 → A2 hypothesis weakened. Iterate path classifier, raise star floor, or pivot Phase 1 to a different methodology (A14 awesome-list pruning, HN front page, or wait for CZDS approval) before building dashboard.

### Phase 1 — A2 GitHub miner + RDAP + cheap Wayback metadata (Weeks 2-3)
**Scope tightened: A2 only. A3 and A4 are spikes, not Phase 1 deliverables.**
- [ ] GHArchive BigQuery integration (with `maximum_bytes_billed` per query); identify repos ≥500 stars with recent PushEvents
- [ ] GitHub Contents API integration with ETag-conditional GETs; sparse-clone fallback
- [ ] README/docs/wiki URL extractor with regex + filter
- [ ] `httpx` async liveness probe
- [ ] RDAP-first availability waterfall (§ 4.2)
- [ ] Wayback CDX cheap-metadata pass: capture count, span, parking-template detector — no LLM yet
- [ ] LLM classifier ONLY on candidates that pass cheap filters (Redis daily-cap enforced)
- [ ] Composite scorer with normalization (§ 4.5)
- [ ] Hard-filter pipeline
- [ ] Dashboard candidate list view with manual `bought` / `passed` / `watching` actions
- [ ] Discord digest cron at 09:00 IST

**Phase 1 exit criteria (MEASURABLE — replaces the "subjectively reasonable" gate):**

| Gate | Threshold |
|---|---|
| Daily digest size | 5–10 candidates per day, sustained over 14 days |
| `purchasable_rate` | ≥ 80% of digest candidates are actually currently purchasable on first manual check |
| `liveness_false_positive_rate` | ≤ 5% of "available" candidates are actually registered |
| `tm_rejection_rate` | ≤ 10% of digest candidates have TM exact-match on USPTO bulk (after our screen) |
| `wayback_clean_rate` | ≥ 70% of digest candidates classified `clean` or `mixed` |
| `cost_per_accepted_candidate` | < $0.50 (total monthly cost ÷ accepted candidates) |
| Operator decision | ≥ 1 actual purchase from digest within 21 days |

If any gate fails after 14 days, the phase is iterated, not exited.

### Phase 1.5 — Spikes (parallel to Phase 1; can launch immediately)

These two run as time-boxed spikes (≤3 days each). Exit = a 1-page memo committed to `docs/spikes/<name>.md` with concrete yield numbers.

- [ ] **A3 spike (academic URL miner)**: pick 1k papers from CrossRef + 1k from PMC OA. Extract reference URLs. Report: % of papers with extractable URLs, % URLs that 404, false-positive rate, total URL volume projected at full scale. Decision gate: ≥ 50 URLs / 1k papers worth checking, else defer indefinitely.
- [ ] **A4 spike (patents NPL miner)**: BigQuery dry-run on `patents-public-data.patents.publications.citation.npl_text` for 10k publications, with `maximum_bytes_billed=1GB`. Report: bytes scanned, $ cost, URL yield, true-prior-art-vs-citation distribution. Decision gate: < $5/quarter projected cost AND ≥ 100 URLs / 10k publications.

### Phase 2 — Enrichment depth (Week 4-5)
- [ ] Common Crawl Web Graph DuckDB lookups → referring-domains count + Open PageRank
- [ ] USPTO bulk TM exact + Levenshtein fuzzy index
- [ ] Reputation lookups (Bluecoat / X-Force / Talos / Umbrella — vendored)
- [ ] Reputation hard-filter integration
- [ ] If A3 spike passed: integrate CrossRef + PMC pipeline
- [ ] If A4 spike passed: integrate patents pipeline

### Phase 3 — CZDS once approved
- [ ] CZDS daily zone-file download (approved TLDs)
- [ ] Daily diff → `pending_delete` / `expiring_soon` status populated
- [ ] Cross-reference deletes with our A2 candidates → priority boost when shortlist matches today's drops

### Phase 4 — Tunable scoring + dashboard polish
- [ ] Dashboard score-weight sliders backed by `scoring_weights` table (versioned)
- [ ] Save filters as named views
- [ ] CSV/JSON export endpoint
- [ ] Outcome feedback loop: `outcomes` table → simple lift analysis per signal → suggested weight changes

---

## 9. Success metrics

Quality over volume. **Primary metric is "watchlist", not "purchasable" — buyable inventory is rarer than dead-link discovery.** A2-only Phase 1 will find many dead URLs but far fewer truly available, clean, non-TM, resale-worthy domains.

| Metric | Target | Phase |
|---|---|---|
| **High-confidence watchlist candidates / day** | **5–10** | Phase 1 |
| **Buyable (digest-eligible) candidates / week** | **1–3** | Phase 1 |
| `watchlist_quality_rate` (operator manual review) | ≥ 60% rated "worth tracking" | Phase 1 |
| `purchasable_rate` (of digest) | ≥ 80% currently purchasable on manual check | Phase 1 |
| `liveness_false_positive_rate` | ≤ 5% | Phase 1 |
| `tm_rejection_rate` (post-screen, manual check) | ≤ 10% | Phase 1 |
| `wayback_clean_rate` | ≥ 70% of digest classified `clean` or `mixed` | Phase 1 |
| `cost_per_accepted_candidate` | < $0.50 | Phase 1 |
| Total monthly cost | < $100 | All phases |
| Operator review time | < 15 min/day | All phases |
| Actual buy cadence | ≥ 1 buy / 2 weeks | Phase 2+ |

---

## 10. Open questions

- [ ] Should we ingest `awesome-*` GitHub lists (A14) as a Phase 1 bonus? GitHub issue #1810 has 6,642 pre-identified dead links — near-zero effort.
- [ ] Hosting country / IP for the enricher — does running RDAP / DNS from a residential IP hit rate-limit walls? (Tailscale exit-node on a cheap VPS as fallback?)
- [ ] Do we add HN front-page mining (A7) to Phase 1? <$1 BigQuery, trivial.
- [x] **De-duplication policy when same domain appears across A2/A3/A4**: collapse to a single `candidates` row with multiple `source_mentions`. Authority computed as **max(source_authority) + capped source_diversity_bonus** (max alone loses corroboration signal; sum lets trash inflate; max + capped bonus is the right shape). See § 4.5.
- [ ] RDAP rate-limit policy per registry — do we need per-registry backoff or a single global limiter?

---

## 11. References

See `RESEARCH.md` for full methodology research and `IMPLEMENTATION_NOTES.md` for the open-source repo + WHOIS API audit. See `CZDS_APPLICATIONS.md` for the approved-purpose-statement template.

---

## 12. Data model (Postgres)

Core + evidence-trail tables. Evidence tables let us reproduce any score and audit any decision.

```sql
-- Core
CREATE TABLE sources (
    id           SERIAL PRIMARY KEY,
    kind         TEXT NOT NULL,          -- 'github_readme' | 'crossref_ref' | 'pmc_jats' | 'patent_npl' | 'czds_drop'
    source_uri   TEXT NOT NULL,          -- e.g. 'github:owner/repo' | 'doi:10.xxx/yyy' | 'patent:US12345678'
    authority    NUMERIC,                -- e.g. github stars, paper citations, patent forward-cite count
    first_seen   TIMESTAMPTZ DEFAULT now(),
    UNIQUE(kind, source_uri)
);

CREATE TABLE candidates (
    id                      SERIAL PRIMARY KEY,
    domain                  TEXT UNIQUE NOT NULL,
    first_observed          TIMESTAMPTZ DEFAULT now(),
    last_observed           TIMESTAMPTZ DEFAULT now(),
    current_status          TEXT,            -- 'unknown' | 'registered' | 'available' | 'pending_delete' | ...
    availability_confidence TEXT,            -- 'authoritative' | 'probable' | 'unknown' | 'conflicting'
    composite_score         NUMERIC,
    score_version           INT REFERENCES scoring_weights(version),
    hard_filtered           BOOLEAN DEFAULT false,
    hard_filter_reason      TEXT             -- see outcome_pass_reason values
);

CREATE TABLE source_mentions (
    id                  SERIAL PRIMARY KEY,
    candidate_id        INT REFERENCES candidates(id) ON DELETE CASCADE,
    source_id           INT REFERENCES sources(id),

    -- Provenance: WHERE we found the citation (raw, never normalized)
    source_url          TEXT,                -- e.g. 'https://github.com/foo/bar/blob/main/README.md' or 'doi:10.1234/abc#ref-12'
    source_url_hash     BYTEA,               -- sha256(source_url); for dedup + fast lookup on long URLs

    -- Citation: WHAT was cited (raw URL, preserved even after the candidate is domain-normalized)
    -- This is critical for the "why did this domain surface?" answer in the dashboard.
    cited_url           TEXT,                -- e.g. 'http://example.com/2009/some/deep/path?q=1' (full URL)
    cited_url_hash      BYTEA,               -- sha256(cited_url); for dedup

    context_type        TEXT,                -- 'editorial' | 'homepage' | 'docs_reference' | 'dependency'
                                             -- | 'api_endpoint' | 'asset_host' | 'security_surface'
                                             -- | 'ci_dependency' | 'unknown'
    context_snippet     TEXT,                -- short prose snippet around the URL for debugging

    observed_at         TIMESTAMPTZ DEFAULT now(),

    UNIQUE(source_url_hash, cited_url_hash)  -- same target URL cited from the same source file = one mention
);
CREATE INDEX ON source_mentions (candidate_id, context_type);
CREATE INDEX ON source_mentions (source_url_hash);
CREATE INDEX ON source_mentions (cited_url_hash);
-- Storing raw cited_url lets the dashboard answer "why this domain?" with the actual link,
-- not just the registrable-domain abstraction.

-- Evidence trail (per-check raw observations)
CREATE TABLE rdap_snapshots (
    id              SERIAL PRIMARY KEY,
    candidate_id    INT REFERENCES candidates(id) ON DELETE CASCADE,
    observed_at     TIMESTAMPTZ DEFAULT now(),
    rdap_server     TEXT,
    epp_statuses    TEXT[],
    expiry_date     DATE,
    registrar       TEXT,
    raw_response    JSONB
);

CREATE TABLE availability_checks (
    id            SERIAL PRIMARY KEY,
    candidate_id  INT REFERENCES candidates(id) ON DELETE CASCADE,
    observed_at   TIMESTAMPTZ DEFAULT now(),
    source        TEXT,                  -- 'rdap' | 'whoisjson' | 'whoisfreaks' | 'python-whois' | 'dns'
    status        TEXT,                  -- 'available' | 'registered' | ...
    is_authoritative BOOLEAN,            -- false for DNS / python-whois ccTLD legacy; true for RDAP/WhoisJSON/WhoisFreaks
    cost_micros   BIGINT DEFAULT 0,      -- microUSD (1 cent = 10,000 micros). RDAP/DNS = 0; paid calls ~100–1,000 micros.
    raw_response  JSONB
);

CREATE TABLE http_observations (
    id              SERIAL PRIMARY KEY,
    candidate_id    INT REFERENCES candidates(id) ON DELETE CASCADE,
    observed_at     TIMESTAMPTZ DEFAULT now(),
    status_code     INT,
    final_url       TEXT,
    is_parked       BOOLEAN,
    ns_signal       TEXT                 -- 'sedo' | 'bodis' | 'parkingcrew' | NULL
);

CREATE TABLE wayback_snapshots (
    id            SERIAL PRIMARY KEY,
    candidate_id  INT REFERENCES candidates(id) ON DELETE CASCADE,
    observed_at   TIMESTAMPTZ DEFAULT now(),
    first_capture DATE,
    last_capture  DATE,
    capture_count INT,
    cdx_summary   JSONB
);

CREATE TABLE classification_runs (
    id                  SERIAL PRIMARY KEY,
    candidate_id        INT REFERENCES candidates(id) ON DELETE CASCADE,
    observed_at         TIMESTAMPTZ DEFAULT now(),
    prompt_version      TEXT NOT NULL,    -- e.g. 'wayback-v3' — bumped when prompt template changes
    model_used          TEXT NOT NULL,    -- 'claude-haiku-4-5-20251001' | ...
    classifier_version  TEXT,             -- bumped when scoring logic / post-processing changes
    snapshot_ids        TEXT[],           -- CDX urlkeys + timestamps chosen as input
    classification      TEXT,             -- 'clean' | 'spam_history' | ...
    confidence          NUMERIC,
    cost_micros         BIGINT DEFAULT 0, -- microUSD; Haiku call ~3,000–10,000 micros per classification
    cache_key           TEXT NOT NULL,    -- = sha256(domain || prompt_version || model_used || classifier_version || sorted(snapshot_ids))
    raw_response        JSONB
);
CREATE INDEX ON classification_runs (cache_key);
-- Cache invalidates if ANY of: domain content (new snapshots), prompt template, model, classifier logic, or chosen-snapshot set changes.

CREATE TABLE scoring_weights (
    version       INT PRIMARY KEY,
    created_at    TIMESTAMPTZ DEFAULT now(),
    weights_json  JSONB NOT NULL,        -- {source_authority: 0.30, ...}
    notes         TEXT
);

-- Registrar quotes: a domain can be 'available' but premium-priced.
-- Tracked separately from availability_checks because (a) price changes over time,
-- (b) different registrars quote differently, (c) the operator's "should I buy?"
-- depends on the *quote price*, not on whether we paid 0.001¢ to ask.
CREATE TABLE registrar_quotes (
    id                       SERIAL PRIMARY KEY,
    candidate_id             INT REFERENCES candidates(id) ON DELETE CASCADE,
    observed_at              TIMESTAMPTZ DEFAULT now(),
    registrar                TEXT,         -- 'porkbun' | 'namecheap' | 'godaddy' | 'sav' | 'dynadot'
    is_premium               BOOLEAN,      -- registrar flagged as premium / aftermarket-listed
    quote_price_micros       BIGINT,       -- microUSD; e.g. $11 = 11_000_000
    renewal_price_micros     BIGINT,       -- annual renewal cost (matters for .ai $150-200/yr)
    quote_currency           TEXT DEFAULT 'USD',
    api_cost_micros          BIGINT DEFAULT 0,  -- our cost to make the lookup (separate from quote_price)
    raw_response             JSONB
);
CREATE INDEX ON registrar_quotes (candidate_id, observed_at DESC);

-- Digest gate: only surface candidates whose latest quote_price_micros < configured ceiling
-- (default $200 = 200_000_000 micros). Above that → 'premium_quote' pass_reason, watchlist only.

-- Provenance: per-source legal / ToS / robots memory.
-- Pre-populated row per source kind. Update last_verified_at when re-checked.
CREATE TABLE source_terms (
    kind                   TEXT PRIMARY KEY,    -- matches sources.kind
    license                TEXT,                -- 'CC0-1.0' | 'OGL-v3' | 'public-domain' | 'CC-BY-4.0' | 'custom'
    redistribution_allowed BOOLEAN,             -- can we share derivatives publicly?
    attribution_required   BOOLEAN,
    rate_limit_notes       TEXT,
    robots_policy          TEXT,                -- relevant robots.txt / API-policy snippet
    terms_url              TEXT,
    last_verified_at       DATE,
    notes                  TEXT                 -- free-form: legal scope, non-commercial caveats
);

-- Pre-populated rows (insert at migration):
--
-- ('github_readme',    'mixed (per-repo licenses)', true, true,
--   'REST 5k/hr authenticated, 60/hr anon; GraphQL 5k/hr',
--   'robots.txt allows; GHArchive is CC-BY-4.0; cloned content carries upstream license',
--   'https://docs.github.com/en/site-policy/github-terms/github-terms-of-service',
--   CURRENT_DATE,
--   'Use Contents API + ETags before clone. Respect 403/429 by exponential backoff.')
--
-- ('wayback_cdx',      'archive.org Terms of Use', false, true,
--   'No published RPS; observed ~5 req/s OK; respect Retry-After',
--   'IA explicitly permits research; do not scrape full-content snapshots in bulk',
--   'https://archive.org/about/terms.php',
--   CURRENT_DATE,
--   'Use CDX index for metadata; only fetch snapshots for the ones we classify.')
--
-- ('crossref_ref',     'CC0-1.0 (metadata)', true, false,
--   'Polite Pool: 50 req/s with mailto in User-Agent; otherwise public-pool ~1-5 req/s',
--   'No robots restriction; Public Data File is the bulk source',
--   'https://www.crossref.org/documentation/retrieve-metadata/rest-api/',
--   CURRENT_DATE,
--   'Always identify with mailto for Polite Pool.')
--
-- ('pmc_jats',         'NIH public-domain / variable per-article', true, false,
--   'OAI-PMH polite use; bulk packaged FTP at ftp.ncbi.nlm.nih.gov/pub/pmc/',
--   'PMC OA subset is for research/text-mining; respect commercial-use license tags per article',
--   'https://www.ncbi.nlm.nih.gov/pmc/about/copyright/',
--   CURRENT_DATE,
--   'Filter article-level license; PMC OA Commercial vs NonCommercial subsets differ.')
--
-- ('patent_npl',       'public-domain (USPTO/EPO/WIPO)', true, false,
--   'BigQuery: respect maximum_bytes_billed; no external scraping',
--   'patents-public-data is Google Cloud public dataset, research-friendly',
--   'https://cloud.google.com/blog/topics/public-datasets/google-patents-public-datasets-connecting-public-paid-and-private-patent-data',
--   CURRENT_DATE,
--   'USPTO data is US-public-domain; Google enrichment columns have BQ ToS restrictions.')
--
-- ('czds_drop',        'ICANN CZDS Terms — research only', false, true,
--   'Daily download per TLD; no real-time API',
--   'CZDS forbids redistribution; data internal-use only',
--   'https://czds.icann.org/terms-and-conditions',
--   CURRENT_DATE,
--   'Never share raw zone data. Aggregates / counts only externally if ever needed.')

CREATE TABLE outcomes (
    id                   SERIAL PRIMARY KEY,
    candidate_id         INT REFERENCES candidates(id) ON DELETE CASCADE,
    decided_at           TIMESTAMPTZ DEFAULT now(),
    decision             TEXT,           -- 'bought' | 'passed' | 'watching' | 'needs_manual_review' | 'lost_to_other'
    pass_reason          TEXT,           -- when decision='passed' or 'needs_manual_review': see enum below
    notes                TEXT,
    acquisition_cost_usd NUMERIC,
    acquisition_channel  TEXT            -- 'godaddy_auction' | 'snapnames' | 'porkbun_handreg' | ...
);
-- decision enum:
--   'bought'              — operator acquired the domain
--   'passed'              — operator rejected (pass_reason explains why)
--   'watching'            — keep monitoring (e.g. expiring_soon but not yet droppable)
--   'needs_manual_review' — automated pipeline gave ambiguous signal; flagged for human-only judgment
--   'lost_to_other'       — operator tried to acquire but lost (auction, drop-catcher)

-- pass_reason enum (also used for candidates.hard_filter_reason):
--   'tm_risk'             — USPTO bulk match flagged
--   'spam_history'        — Wayback classifier flagged adult/casino/pharma/PBN
--   'not_available'       — RDAP says registered after we shortlisted
--   'low_resale'          — operator judgment: unlikely buyer market
--   'too_expensive'       — auction or backorder price > budget
--   'premium_quote'       — registrar quote exceeds configured premium ceiling
--   'security_sensitive'  — A2 path classifier deemed operational dependency
--   'weak_authority'      — only one tiny source, doesn't pass diversity floor
--   'reputation_flag'     — Bluecoat / X-Force / Talos / Umbrella flagged
--   'classifier_ambiguous'— Wayback classifier returned low confidence or 'mixed'
--   'conflicting_signal'  — sources disagree on a critical metric; needs human eyes

-- Indexes
CREATE INDEX ON candidates (composite_score DESC) WHERE NOT hard_filtered;
CREATE INDEX ON candidates (current_status);
CREATE INDEX ON source_mentions (candidate_id);
CREATE INDEX ON availability_checks (candidate_id, observed_at DESC);
CREATE INDEX ON classification_runs (candidate_id, observed_at DESC);
```

All paid-API observations carry `cost_micros` (microUSD; many calls are below 1¢ so cents-precision is insufficient). Monthly spend:

```sql
SELECT
    DATE_TRUNC('month', observed_at) AS month,
    SUM(cost_micros)::float / 1e6     AS usd
FROM (
    SELECT observed_at, cost_micros FROM availability_checks
    UNION ALL
    SELECT observed_at, cost_micros FROM classification_runs
) AS x
GROUP BY 1
ORDER BY 1 DESC;
```
