# Domain Hunter — Research Dossier

> Consolidated research for a self-hosted expired-domain + brandable-domain discovery / scoring / acquisition pipeline.
> Two passes complete (high-level market + deep methodology). All sources cited inline.
> **Use this as the testing checklist** — each methodology is a candidate pipeline to validate.

---

## 0. Thesis & Scope

### Two parallel income streams, one discovery engine

- **Workflow A — High-authority expired domains.** Domains carrying real backlink authority from credible sources, found *before* they hit anyone's expiring list. Inverse-graph mining.
- **Workflow B — Trend-based brandable speculation.** Predict which brandable .com / .ai / .io will sell well based on emerging trends.

Both pipelines feed the same Postgres + pgvector store and the same scoring layer.

### Scope (confirmed)

**IN SCOPE — what the tool does:**
1. **Ingest** from all upstream sources (CZDS, Common Crawl, GHArchive, OpenAlex, Patents, GDELT, HN, EDGAR, USPTO, WARN, CertStream, CatchDoms baseline, etc.)
2. **Enrich** (liveness, WHOIS, DNS health, Open PageRank, Wayback history, reputation, TM screen)
3. **Score** Workflow A + Workflow B candidates
4. **Output a ranked shortlist** — domains worth buying, with reasoning per candidate

**OUT OF SCOPE — handled separately by the user:**
- Acquisition (manual buy at GoDaddy / Porkbun / Namecheap / SnapNames / DropCatch)
- Listing on Sedo / Afternic / Dan
- Outbound buyer email
- Auction sniping
- Flipping / sale workflow (a separate "flipper" tool)

The tool stops at "here's what to buy this week." Operator handles the rest.

### Hard truth — we are NOT competing with drop-catchers

DropCatch runs 1,200+ ICANN-accredited registrar shells slamming Verisign's EPP endpoint in parallel; SnapNames runs ~300. Single-IP single-server can't win the drop. We surface opportunities; the user buys via existing channels.

---

## 1. Market structure (skip if you've read this)

### Drop moment
- Verisign deletes unrenewed .com 5 days after RGP + 5 days pendingDelete, typically 11:00–14:00 UTC.
- Winners are registrar-shell farms: **DropCatch (1,200+)**, **SnapNames (~300)**, **Pheenix**, **Park.io (.io)**, **GoDaddy**, **Dynadot**, **Sav**.
- We compete on **GoDaddy Expired Auctions / Closeouts** (closeouts bottom at $11), **NameJet/SnapNames pre-release**, and **hand-reg at the actual drop**.

### Aftermarket fees
| Marketplace | Seller commission |
|---|---|
| Afternic (Afternic-nameservered domains) | 15% |
| Sedo | 15% standard / 20% brokered |
| Dan.com (now GoDaddy stack) | 9% (buyer-paid) |
| Atom (ex-Squadhelp) | 30% — curated brandable traffic |
| GoDaddy direct | 15–25% |

Standard portfolio strategy: Afternic for distribution (lands on GoDaddy/Namecheap registrar search), Sedo for international, Dan as primary lander, Atom only for genuinely brandable picks.

### Hard truths on profitability
- Sell-through rate (STR): **1–2% per year** is industry standard for quality .com inventory at end-user prices. (NamePros polls).
- Year 1: roughly break-even on flips. Year 2+: profitable.
- The tool is worth 5–10× the flips. SaaS subscription layer is the moat (SpamZilla / DomCop estimated $1–5M ARR each).

---

## 2. Existing tools — what they do and don't

| Tool | Cost | Strengths | Weaknesses |
|---|---|---|---|
| **ExpiredDomains.net** | Free | Default scrape-and-filter UI, aggregates GoDaddy/Sav/DropCatch/Dynadot | No LLM scoring, no comp-based valuation, no distress signals, no CT data |
| **SpamZilla** | $49/mo | 70+ metrics, spam classifier | Brandability sort useless; spam classifier filters legitimate aged inventory |
| **DomCop** | $49–199/mo | Best filter UI, Majestic/Moz/Ahrefs integrations | Optimised for PBN/SEO use case |
| **NameBio** | $$ | $3B+ historical sales DB, API endpoints | Gated API access for "established businesses" |
| **DropCatch / SnapNames / NameJet** | Per-catch | Discovery surface + pre-release inventory | They catch; we just see what's listed |
| **CatchDoms (RapidAPI / Apify)** | $39/mo Pro | Pre-aggregated 370k expired feed from 18 sources w/ DA/TF/CF/Wayback age + MCP server | Useful **baseline feed** to layer novel pipelines on top of |

---

## 3. Existing open-source repos — what to stitch

| Repo | Stars | License | Use for |
|---|---|---|---|
| `acidvegas/czds` | ~50 | ISC | Daily zone-file pull (preferred over icann/czds-api-client-python) |
| `icann/czds-api-client-python` | official | Apache-2.0 | Backup CZDS client |
| `luigigubello/expired-domain-finder` | small | MIT | **PyPI homepage scanner — extend to NPM/CRAN/Bioconductor/DockerHub** |
| `threatexpress/domainhunter` | ~2.6k | **BSD-3** | Vendor only the 4 reputation-check fns from `domainhunter.py` (Bluecoat L70, X-Force L175, Talos L215, Umbrella L44). Skip its ExpiredDomains.net scraper and McAfee captcha-OCR pathway. |
| `tomnomnom/waybackurls` | ~5k | **NO LICENSE** (treat as all-rights-reserved) — and hardcoded CC-MAIN-2018-22 index is 8 years dead. **Don't depend.** Reimplement CDX call in ~30 lines of Python. |
| `gau` (getallurls) | — | — | Adds AlienVault/CommonCrawl/URLScan sources to waybackurls |
| `CaliDog/certstream-server` + `certstream-python` | 4k / 800 | MIT | Realtime CT log feed |
| `sslmate/certspotter` | ~2k | MPL | Alternative CT monitor with disk-backed state |
| `hahwul/deadfinder` | ~1.5k | MIT | **Crystal v2 now (not Ruby).** Use Docker sidecar `ghcr.io/hahwul/deadfinder:latest` — or skip entirely; pure `httpx` async handles 10k/day. |
| `JustinBeckwith/linkinator` | — | MIT | Liveness validator (JS) |
| `biglocalnews/warn-scraper` | ~150 | MIT | 81k+ pre-built WARN Act layoff notices |
| `dgunning/edgartools` | ~1k | MIT | SEC 8-K bankruptcy parser |
| `EdOverflow/can-i-take-over-xyz` | — | — | Dangling-DNS subdomain reference |
| `projectdiscovery/subfinder` + `httpx` | — | MIT | Fast batch subdomain enumeration + liveness |
| `s0md3v/Photon` | — | — | Fast site crawler (for A2/A6 mining) |
| `mxrch/GHunt` | — | — | GitHub OSINT including org metadata (D5) |
| `short443/BDAC` + `hackerpain/bulkvaluator` | tiny | MIT | GoDaddy bulk appraisal scraping (may break on ToS) |
| `bosszukung/Domain-Name-Prediction` | tiny | — | Reference for ML pricing model — retrain on NameBio |
| **Williams-Media/Exipred-Domain-Finder** | <100 | none | Reference only — re-write needed |
| **Nicoloren/expireddomainsfinder** | tiny | unclear | Skip |

Honourable mentions:
- `acidvegas/czds` is preferred — cleaner reimplementation.
- `lauritzh/dead-domain-discovery` (not a repo, a hosted tool) — interesting reference architecture for CT + DNS + WHOIS cross-reference.

---

## 4. Paid + free APIs to stitch

| API | Cost | Purpose |
|---|---|---|
| **ICANN CZDS** | Free (apply per-TLD, ~2 weeks approval) | Daily zone files for 1,200+ TLDs incl .com, .net, .org. **Mandatory base.** |
| **CatchDoms** | $39/mo Pro | Baseline expired feed |
| **DomainsDB.info** | Free | Cheap bulk availability + WHOIS |
| **WhoisFreaks Domain Availability** | 500 free, ~$0.001/check | Bulk availability up to 100/req, 1500+ TLDs. Fallback for .ai/.io |
| **WhoisXMLAPI** | $0.0009/check | Historical WHOIS (mass-buyer tagging P1) |
| **SecurityTrails** | $$$ | Historical DNS, reverse IP. Only after D13 + D2 prove out |
| **Open PageRank (DomCop)** | Free, unlimited w/ API key | CC-derived PageRank 0–10. **Indispensable.** |
| **Common Crawl S3** | Free + egress (~$30/mo `us-east-1`) | The link graph itself. Query via DuckDB. |
| **BigQuery public datasets** | ~$5/TB scanned | HN, Patents, GDELT, GitHub Archive |
| **OpenAlex S3 snapshot** | Free (~300GB) | Academic citations |
| **CrossRef Public Data File** | Free | Academic supplement |
| **GDELT BigQuery** | Free dataset, query costs only | News outbound URLs |
| **Wayback Machine CDX API** | Free, polite rate | Liveness history, content decay |
| **DNSTwister** | Free | Typosquat / related-domain enumeration |
| **urlscan.io** | Free ~100/day | Snapshot + outbound URL extraction |
| **Estibot** | ~$30/mo | Workflow B appraisals (industry standard) |
| **WhoisJSON** | 1,000 req/mo free recurring; paid scales cheap | Primary availability fallback. Coverage confirmed for .io/.ai/.info/.biz/.xyz/.shop. Official `whoisjson` PyPI client. **Replaces Domainr (deprecated) in our stack.** |
| **Podcast Index API** | Free | A11 podcast RSS mining |
| **USPTO TSDR** | Free w/ key, 60/min | Trademark abandonment + TM screening |
| **SEC EDGAR APIs** | Free, no key | 8-K bankruptcy mining |

---

## 5. Methodologies — full list with verdicts

Legend: 🟢 NOVEL & uncontested | 🟡 partially done | 🔴 fully done | ⚫ legal risk | ⚪ skip

### Workflow A — Authority-graph inverse mining
| # | Method | Verdict | Source/Tooling |
|---|---|---|---|
| A1 | Wikipedia `{{dead link}}` references | 🟡 SpamZilla/Karma filter on Wiki backlinks; nobody filters on *currently flagged dead* | Wikimedia dumps + IABot DB |
| **A2** | **GitHub README + docs dead-link mining** | 🟢 **TOP 5 — uncontested** | GHArchive BQ + `hahwul/deadfinder` |
| **A3** | **Academic citation URLs (CrossRef + PMC OA)** ⚠️ OpenAlex = scorer, not extractor — use CrossRef references + PMC OA/JATS full text for URLs. Spike before commit. | 🟢 **TOP 5 — uncontested** | CrossRef Public Data File + PMC OA bulk + OpenAlex (authority layer) |
| **A4** | **Google Patents prior-art URLs** ⚠️ correct table is `patents-public-data.patents.publications` not `google_patents_research.publications`; field is `citation.npl_text`. Spike + BQ dry-run before commit. | 🟢 **TOP 5 — uncontested** | `patents-public-data.patents.publications` BigQuery |
| A5 | .gov / .gov.uk / .eu outbound | 🟡 sampled by Ahrefs/Majestic; full coverage uncontested | GOV.UK content API, EUR-Lex, GDELT |
| A6 | News-archive outbound mining | 🟡 GDELT-as-source is novel; news-as-backlink is generic | GDELT GKG on BigQuery |
| A7 | HN front-page mining | 🟢 free BigQuery, <$1/query | `bigquery-public-data.hacker_news.full` |
| A8 | ProductHunt graveyard | 🟢 no public API; scrape leaderboards | Wayback + producthunt.com/leaderboard |
| A9 | Reddit top-of-all-time URL mining | 🟢 academic Watchful1 monthly dumps | academictorrents.com |
| A10 | YouTube channel description links | 🟡 anyone can do it; 10k unit/day quota cap | YouTube Data API v3 |
| A11 | Podcast RSS show-notes mining | 🟢 podcastindex.org free | Podcast Index API |
| A12 | Twitter/X archive | ⚫ ToS prohibits redistribution; API unaffordable | Skip |
| A13 | Stack Overflow accepted-answer URLs | 🟢 SO data dump + arXiv 2010.04892 has pre-built broken-link dataset | archive.org SO dump |
| A14 | "awesome-*" GitHub lists | 🟢 sindresorhus issue #1810 already lists 6,642/47,941 dead — **free pre-computed** | GitHub issue |
| A15 | DMOZ / Curlie legacy | ⚪ strip-mined 2017–2019 | Skip |

### Workflow A — Predictive distress mining
| # | Method | Verdict | Source/Tooling |
|---|---|---|---|
| **D1** | **CT-log dead-cert detection** | 🟢 **TOP 5 — uncontested** | crt.sh Postgres mirror + certstream |
| D2 | DNS health / parking-NS transitions | 🟡 SpamZilla flags parking; not transitions | Daily zone-file NS snapshot |
| **D3** | **Wayback content-decay classifier (Claude vision)** | 🟢 **TOP 5 — uncontested** | CDX API + Claude Haiku |
| D4 | HN/PH/IH "shutting down" classifier | 🟢 trivial RSS + regex + Claude | HN dataset + RSS |
| D5 | GitHub org abandonment | 🟢 uncontested | GHArchive + org `blog` URL |
| D6 | App Store / Play removal | 🟡 Sensor Tower owns it; cost > value | Scrape iTunes Lookup |
| D7 | Crunchbase / failory shutdown | 🔴 startups.rip, failory.com, failedstartups.io publish | Consume their lists |
| D8 | SEC EDGAR 8-K bankruptcy | 🟢 zero domainers do this | `dgunning/edgartools` |
| D9 | USPTO trademark abandonment | 🟢 uncontested | TSDR XML feed |
| D10 | State Sec-of-State lapse | 🟡 per-state slog | CA/DE/NY/TX scrapable |
| D11 | WARN Act layoff mining | 🟢 `biglocalnews/warn-scraper` ready; ~30% mortality in 24mo | warn-scraper |
| D12 | YC mortality | 🔴 startups.rip + Jared Heyman publish | Consume |
| D13 | Reverse-IP shared-hosting graveyards | 🟢 uncontested, tiny TAM | ViewDNS / HackerTarget free tier |

### OSINT angles
| # | Method | Verdict | Source/Tooling |
|---|---|---|---|
| O1 | CT-log subdomain inventory of dead parents | 🟢 creative; mild TM tail risk | crt.sh |
| O2 | Bug bounty disclosed reports | ⚪ low signal | Skip |
| **O3** | **NPM/PyPI/RubyGems orphan homepage URLs** | 🟢 validated by security research; **stay on homepage side, never email** | `luigigubello/expired-domain-finder` |
| O4 | DockerHub/Quay orphan image homepages | 🟢 trivial | DockerHub API `full_description` |
| O5 | CRAN/Bioconductor academic packages | 🟢 stacks with A3 | CRAN `URL:` field |
| O6 | OpenAlex institution mining | ⚪ narrow path to monetisation | Skip |

### Workflow B — Trend-based brandable
| # | Method | Verdict | Source/Tooling |
|---|---|---|---|
| T1 | Claude brandable generator from trend seeds | 🟡 Squadhelp does manually, no public LLM pipeline at scale | Claude API |
| T2 | GitHub topics velocity | 🟢 single sources obvious, combined pipeline is the moat | GitHub Search API |
| T3 | arXiv keyword velocity | 🟢 | arXiv OAI-PMH |
| T4 | YC batch keyword mining | 🟢 | YC public batch lists |
| T5 | NameBio comps velocity | 🔴 everyone uses it | NameBio API |
| T6 | Google Trends rising | 🟡 obvious but useful in stack | pytrends |
| T7 | Reddit subreddit growth | 🟢 | Pushshift academic dumps |
| T8 | TikTok hashtag velocity | 🟡 ToS check needed | TikTok Creative Center |
| T9 | X trending topics historical | ⚫ ToS | Skip |
| **T10** | **301-redirect-chain capture** | 🟢 **TOP 5 — your BBC method generalised, automated** | CC WAT + DuckDB |

### Portfolio plays
| # | Method | Verdict | Source/Tooling |
|---|---|---|---|
| P1 | Mass-buyer expiry watching | 🟢 tag HugeDomains/BuyDomains/Mike Mann portfolios via WHOIS history | WhoisXMLAPI |
| P2 | Cross-registrar expiring-list arb | 🟡 pros do this privately | Aggregate registrar feeds |
| P3 | Drop-list cross-registrar diff | ⚪ infrastructure-constrained | Skip |

---

## 6. The TOP 5 uncontested edges

> If we ship only these five we have a real moat.

### 1. 🥇 GitHub README + docs dead-link mining (A2)
- **Why uncontested:** security researchers proved the attack value (ReversingLabs/JFrog PyPI/NPM papers); no domainer has packaged it for flipping. A 50k-star repo's external link is higher real authority than 80% of Ahrefs editorial signals.
- **Stack:** GHArchive BigQuery → repos >500 stars → shallow clone → regex external URLs from README*/docs/wiki → `hahwul/deadfinder` liveness → WHOIS check → score by `stars × url_frequency`.
- **Cost:** ~$5/mo BigQuery.
- **Starter repo:** `luigigubello/expired-domain-finder` (PyPI homepage version) — fork, extend to NPM/CRAN/Bioconductor/DockerHub.

### 2. 🥈 Google Patents prior-art URL mining (A4) — *requires spike before commit*
- **Why uncontested:** patent + domainer Venn diagram is empty. Patent prior-art URLs are extreme-trust (USPTO/EPO refs survive forever); link-rot is ~50%+ for citations >10 years old.
- **Stack (corrected):** Use BigQuery table **`patents-public-data.patents.publications`** (NOT `google_patents_research.publications`, which lacks the relevant fields). Useful columns: `claims_localized`, `description_localized`, and **`citation.npl_text`** (Non-Patent Literature) — NPL is where prior-art URLs typically live, not the claims. Example:
  ```sql
  SELECT REGEXP_EXTRACT_ALL(c.npl_text, r'https?://[^\s)\]"]+') AS urls
  FROM `patents-public-data.patents.publications`,
       UNNEST(citation) AS c
  WHERE c.npl_text IS NOT NULL
  ```
- **Always run with `maximum_bytes_billed` set** before any full scan (patents corpus is large).
- **Cost:** must be validated by spike before commitment. PRD § 8 Phase 1.5 defines the gate.

### 3. 🥉 Academic citation URL mining (A3) — *requires spike before commit*
- ⚠️ **Correction from earlier draft:** OpenAlex's `referenced_works` is OpenAlex *work IDs*, not arbitrary cited URLs. Its `primary_location` / `locations.landing_page_url` is where each paper itself lives, not URLs cited *within* it. So OpenAlex is an authority/citation **scorer** in this stack, not the URL **extractor**.
- **For actual URL extraction:**
  - **CrossRef references** — present for ~50% of Crossref-deposited records, accessible via the Crossref Public Data File or the `/works/{doi}` API.
  - **PubMed Central OA / JATS full text** — full XML of OA papers, has every external link.
  - Licensed OA PDFs (Unpaywall) — secondary.
- **Cost:** S3 egress + PMC bulk; must be validated by spike. PRD § 8 Phase 1.5 defines the gate.

### 4. Wayback content-decay classifier with Claude vision (D3)
- **Why uncontested:** cost was prohibitive pre-LLM; now Haiku does it at ~$0.001/classification. Forward-looking 30–90 day drop predictor.
- **Stack:** CDX API → capture sequence → Claude classifies real → parking → 404 transitions.
- **Cost:** $50–100/mo at 1k candidates/day.

### 5. 301-redirect-chain capture (T10)
- **Why uncontested:** Ahrefs has the data, doesn't expose the query. Generalises your manual BBC/Ahrefs method.
- **Stack:** Common Crawl WAT redirect graph → DuckDB → monitor expiry of redirecting nodes → capture authority-passing domains cheap.
- **Cost:** Common Crawl S3 egress only.

### Honourable mentions
- **A14** awesome-list pruning (free pre-computed list in GitHub issue #1810)
- **D8** SEC 8-K bankruptcy signal (`dgunning/edgartools`)
- **D11** WARN Act → company death (`biglocalnews/warn-scraper`)

---

## 7. Unified architecture

```
┌── INGESTION (Dell cron) ─────────────────────────────────────────────┐
│ CZDS daily zone diffs ─┐                                              │
│ Common Crawl WAT monthly ─┤                                           │
│ GHArchive BigQuery hourly ┤                                           │
│ Wikipedia dump monthly    ┤                                           │
│ OpenAlex S3 quarterly     ┼─→ raw_links (source, target, ctx)         │
│ GDELT GKG daily           ┤                                           │
│ HN BigQuery daily         ┤                                           │
│ Patents BQ quarterly      ┤                                           │
│ EDGAR 8-K daily           ┤                                           │
│ WARN-scraper daily        ┤                                           │
│ USPTO TSDR daily          ┤                                           │
│ Certstream realtime       ┤                                           │
│ CatchDoms daily (baseline)┘                                           │
└────────────────────────────────────────────────────────────────────────┘
                          ↓
┌── ENRICHMENT ──────────────────────────────────────────────────────────┐
│ Liveness probe (deadfinder/httpx, async)                               │
│ Availability waterfall: DNS NXDOMAIN → RDAP → WhoisJSON → WhoisFreaks  │
│   → python-whois (legacy fallback). See PRD § 4.2.                     │
│ DNS health (parking-NS classifier)                                     │
│ Open PageRank lookup                                                   │
│ Wayback CDX history (capture density, parking transitions)             │
│ Reputation (domainhunter modules: Bluecoat/X-Force/Talos)              │
└────────────────────────────────────────────────────────────────────────┘
                          ↓
┌── SCORING ─────────────────────────────────────────────────────────────┐
│ Workflow A: f(source_authority, n_inbound_sources, wayback_age,         │
│              openpagerank, reputation_clean)                            │
│ Workflow B: f(brandability_llm, trend_velocity, namebio_comps,          │
│              pron_ease, length, vowel_ratio)                            │
│ Embed candidate + context → pgvector for similarity dedup               │
│ Comp-based valuation: kNN over NameBio embeddings → predicted price    │
└────────────────────────────────────────────────────────────────────────┘
                          ↓
┌── WORKFLOW B GENERATOR (parallel) ────────────────────────────────────┐
│ Trend signals: GitHub topics, arXiv keyword, YC batch, pytrends,       │
│ Reddit growth, NameBio velocity                                        │
│  → Claude prompt: "given seed verticals X, generate 200 brandable .com │
│    /.ai/.io candidates with rationale"                                 │
│  → WhoisFreaks bulk availability                                       │
│  → USPTO trademark bulk index + TSDR enrichment + EUIPO TMView         │
│     (TESS was retired 2023; do not reference it)                       │
│  → score → shortlist                                                   │
└────────────────────────────────────────────────────────────────────────┘
                          ↓
┌── SHORTLIST (only output this tool produces) ──────────────────────────┐
│ Candidate table → ranked shortlist → Discord digest + dashboard + CSV  │
│                                                                         │
│ ⚠️ EVERYTHING BELOW IS EXPLICITLY OUT OF SCOPE (see PRD § 7).           │
│ The operator handles all of these manually or via a separate flipper.  │
│   • Hand-reg (Porkbun/Namecheap API)                                   │
│   • Backorder (DropCatch/SnapNames where worth it)                     │
│   • GoDaddy auction snipe bot (final-60s, budget-capped)               │
│   • List to Sedo/Afternic/Dan via APIs                                 │
│   • Outbound email (Claude-personalised, sent via Postmark/SES)        │
│ These are not built by Domain Hunter. Listed only for context.         │
└────────────────────────────────────────────────────────────────────────┘
```

**Reference budget (research estimate at 1k candidates/day, no gating):** ~$250–330/mo. PRD § 5 enforces a tighter ~$50–100/mo cap by **gating every paid step behind cheap filters** (DNS → RDAP → metadata pass → LLM only on top survivors).
- CatchDoms Pro $39
- Estibot ~$30
- BigQuery ~$10–20
- S3 egress ~$30
- WhoisFreaks ~$30
- WhoisXMLAPI historical ~$20
- Claude API ~$80–150
- Postmark/SES ~$10
- (Dell handles compute, no hosting cost)

---

## 8. Honest economics

### Workflow A (high-authority expired)
- Hand-reg / closeout: $11–12 per acquisition
- GoDaddy expired auction win: $12–500 median
- SnapNames/NameJet backorder: $69–79 if won, $0 if not
- DropCatch backorder: ~$59 if uncontested, auction if contested
- Renewal: $9–15/yr per .com
- Sales hit rate: 1–2%/yr STR for quality inventory
- Average sale: $1.5–4k
- Year 1 net: roughly break-even

### Workflow B (trend brandable)
- Hand-reg: $11/yr per .com, $14/yr per .net, $25+/yr per .io, $150–200/yr per .ai
- **.ai renewal cost is a portfolio killer** — pick spots, don't bulk
- Average sale on Atom: $2k typical, $33k top-seller average (13 sales / $440k)
- Sell-through: ~0.3–1% on curated marketplaces

### Critical economic lesson
> **The tool is worth more than the flips.** SpamZilla/DomCop are estimated $1–5M ARR each with worse tech. Monetise:
> 1. Direct flips (cash flow, dogfooding)
> 2. $99/mo "weekly top-50 shortlist" PDF service
> 3. $49–99/mo SaaS competing with SpamZilla/DomCop
> 4. API white-label to Atom/Sedo/Afternic
> 5. Free public "top picks today" SEO surface w/ DropCatch/SnapNames affiliate links

---

## 9. Legal / risk landscape

- **UDRP:** WIPO 6,168 cases in 2024, >95% transfer to complainant. USPTO trademark bulk-data index (TESS was retired in 2023) + EUIPO TMView pre-screen is **mandatory**.
- **ACPA (US):** statutory damages up to $100k/domain for bad-faith TM registration.
- **Google "Expired Domain Abuse" policy (March 2024):** killed the PBN/aged-for-SEO market. ODYS launched $499 DDAAS specifically because of this. **Do not build around SEO/PBN resale.**
- **Prior content traps:** Wayback shows if domain was previously adult/casino/pharma → untouchable for editorial resale.
- **Manual penalties don't show in tools.** Build a "redacted in Google" detector: search `site:domain.com` — zero pages indexed despite Wayback showing thousands = suspicious.
- **O3 (NPM/PyPI homepage):** legal to register; ethical only if package is truly dead. **Maintainer-email domain registration is illegal in most jurisdictions (CFAA / Computer Misuse Act).** Stay on homepage side.
- **Common Crawl / OpenAlex / GDELT / GHArchive / SEC / USPTO / WARN:** all public domain or CC-licenced.
- **X / Twitter archive:** ToS prohibits redistribution. Skip.
- **NYT/FT archive scraping:** ToS violation. Use GDELT's pre-extracted URLs instead.

---

## 10. Profitable categories in 2026

| Category | Verdict | Notes |
|---|---|---|
| Brandable .com (4–9 chars, pronounceable) | ✅ King | $2k avg, top sales $33k+ |
| Two-word .com (startup-y) | ✅ Sweet spot | $2k–25k typical, under-tooled |
| Aged domains for PBN/SEO | ❌ **DEAD** | Google March 2024 policy |
| .ai speculation | ⚠️ Past peak | $150–200/yr renewals destroy economics |
| .io speculation | ⚠️ Past peak | Better than .ai, still careful |
| Geographic / category killers | ✅ Slow but real | $2–10k to SMBs |
| Trend keywords (agent, vibe, forge, GLP-1) | ✅ Hot now | Pick spots |

---

## 11. Failure modes to watch

The dominant risk across every novel methodology is **low signal-to-noise**, not legality. Most dead links are dead because the owner forgot to renew a worthless domain. **The scoring stage is the only thing that separates gold from sewage** — invest there before scaling ingestion.

Specific traps:
- Drop-catching infrastructure fantasy → won't work.
- Bulk-buying .ai → renewal costs eat you.
- Skipping USPTO TM pre-screen → one UDRP = $1,500 + the domain.
- Buying domains with prior adult/casino/pharma Wayback content.
- Trusting "great backlink profile" tools — manual penalties are invisible.
- Funding 500-domain portfolio month 1 — renewal costs are silent killers.
- Believing $20k/mo year-one stories — NamePros poll data: 1–2% STR.

---

## 12. Testing checklist (per methodology)

For each row in section 5, validate in this order:
1. **Can we ingest at all?** API key? Rate limits? Volume per day?
2. **Is the signal real?** Pull 100 candidates → manually rate quality.
3. **Does scoring separate gold from noise?** Top 10 by score should be obvious wins.
4. **Cost per candidate** at production scale?
5. **Hit rate** on TM screen / Google penalty / prior content traps?
6. **Time-to-acquisition** — how long before our shortlist domains hit drop?
7. **Resale signal** — list 5 best on Sedo/Afternic and measure inbound inquiries in 90 days.

Pipelines that score 6/7 graduate to production. The rest get a writeup in `/docs/experiments/<methodology>-result.md`.

---

## 13. Sources

### Pass 1 — market structure & profitability
- Indie Hackers: self-hosting agents real costs
- NamePros: sell-through rate analysis (~1–2%/yr)
- NamePros: portfolio size vs STR poll
- NamePros: holding costs silent portfolio killer
- DomainDetails KB: expired domain auctions comparison
- DomainDetails KB: domain aftermarket platforms compared
- NameJet/SnapNames merger (PRWeb)
- ICANN CZDS portal (https://czds.icann.org/)
- Namesilo: CZDS zone files for market research
- acidvegas/czds on GitHub
- NameBio API documentation
- Common Crawl backlinks gist (retlehs)
- Wayback CDX Server README
- certificate.transparency.dev monitors
- Morgan Linton: Atom top-seller $439k
- Google Search Central: March 2024 core update + spam policies
- GigaLaw: UDRP decisions 2024 stats
- ODYS DDAAS announcement
- Niche Pursuits: Sedo vs Afternic 2026

### Pass 2 — novel methodologies
- SpamZilla — buy expired domains
- Karma.Domains — expired domains with Wikipedia backlinks
- The Link Lazarus Method (Metehan.ai)
- threatexpress/domainhunter
- luigigubello/expired-domain-finder
- tomnomnom/waybackurls
- icann/czds-api-client-python
- acidvegas/czds
- CaliDog/certstream-server
- crt.sh
- UCSB: Certifiably Vulnerable
- Common Crawl
- DropDomainsList — Common Crawl based
- DomCop Open PageRank
- hahwul/deadfinder
- sindresorhus/awesome — broken-links issue #1810
- EdOverflow/can-i-take-over-xyz
- ReversingLabs — bootstrap script exposes PyPI to domain takeover
- ReversingLabs — PyPI domain resurrection
- TheHackerNews — Legacy Python Bootstrap Scripts Create Domain-Takeover Risk
- JFrog — NPM package hijacking through domain takeover
- The Register — Expert grabs expired NPM domain
- arXiv 2010.04892 — broken external links on Stack Overflow
- Ahrefs — 66.5% of links from last 9 years are dead
- HN BigQuery dataset (Felipe Hoffa)
- Tell HN: HN BigQuery updated daily
- Startups.RIP — YC graveyard
- Failory — Y Combinator failures
- biglocalnews/warn-scraper
- WARNTracker.com
- dgunning/edgartools
- SEC EDGAR APIs
- USPTO TSDR bulk downloads
- Google Patents Public Datasets (Cloud Blog)
- CatchDoms API docs + DEV blog
- DomainsDB.info
- WhoisFreaks Domain Availability API
- SecurityTrails API
- GoDaddy engineering — Domain name valuation
- arXiv 2509.18403 — Persistence of Retracted Papers on Wikipedia
- OpenCitations COCI (arXiv 1904.06052)
