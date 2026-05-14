# Domain Hunter — Implementation Notes (Audit Pass)

> Audit of 8 open-source repos + WHOIS-API matrix. Companion to PRD.md and RESEARCH.md.
> Date: 2026-05-14. All clones under `/tmp/dh-audit/` were inspected then deleted.

Scope under audit: Python 3.12 + FastAPI + Postgres+pgvector ingestion + enrichment for Phase 1 (A2 GitHub README mining, A3 OpenAlex, A4 Patents), with availability + Wayback + ExpiredDomains-equivalent filters.

---

## 1. `threatexpress/domainhunter`

| Property | Value |
|---|---|
| License | **3-clause BSD** (Joe Vest, Andrew Chiles, 2017) — attribution required, vendoring OK |
| Last meaningful commit | **2022-10-25** — ~3.5 years stale |
| Lang / shape | Single-file Python 3 CLI, ~825 LOC, no package layout |
| Deps | `requests`, `texttable==0.8.7` (pinned ancient), `beautifulsoup4==4.5.3` (pinned ancient), `lxml`, `pillow`, `pytesseract`, `urllib3` |

### What to REUSE (specific functions, by file:line)
The reputation lookups are the only part worth vendoring. All live in `threatexpress-domainhunter/domainhunter.py`:

- **`checkBluecoat(domain)`** — `domainhunter.py:70` — Symantec SiteReview reputation. Already updated for the May-2022 XSRF + SHA256 challenge scheme (`xsrf_token_parts`, base64 phrase set). This is the part that breaks first and they re-patched it; useful starting point but **expect to re-fix within months**.
- **`checkIBMXForce(domain)`** — `domainhunter.py:175` — XForce Exchange categorization. Stable endpoint, no auth, JSON response.
- **`checkTalos(domain)`** — `domainhunter.py:215` — Cisco Talos web reputation. Scrape-style, brittle.
- **`checkUmbrella(domain)`** — `domainhunter.py:44` — Cisco Umbrella categorization (free tier).
- **`checkMcAfeeWG(domain)`** — `domainhunter.py:245` — McAfee WebGateway/TrustedSource. Brittle (captcha-fronted; they ship `solveCaptcha()` via pytesseract OCR).

### What to NOT reuse
- **ExpiredDomains.net scraper** (`loginExpiredDomains()` `domainhunter.py:391` + `getIndex()` `:411`) — we are not "competing with ExpiredDomains" per RESEARCH §2; we *replicate the filter set* on our own data. Scraping ED.net is also a ToS risk for what is effectively redistributing their aggregation.
- **`solveCaptcha()` `:350` + `pytesseract` dep** — for McAfeeWG. The OCR pathway is fragile and adds a heavy native dep. Skip McAfeeWG entirely or accept rate-limited misses.
- **`downloadMalwareDomains()` `:309`** — points at a defunct mirror (`mirror1.malwaredomains.com` has been dead since ~2019). Replace with current SURBL / Spamhaus / Google SafeBrowsing API.
- **HTML report generation** (`drawTable()` `:382` and the inlined CSS at the end) — we ship a FastAPI+SvelteKit dashboard; their HTML is not reusable.

### APIs / current status
| Endpoint | Status (2026) | Notes |
|---|---|---|
| `sitereview.bluecoat.com` | Working, hostile to scripts; CAPTCHA + XSRF + base64 phrase challenge | Already-mitigated in 2022 update; expect re-break |
| `exchange.xforce.ibmcloud.com` | Working, public, no key needed for category | Stable |
| `talosintelligence.com/sb_api/...` | Working, returns HTML; scrape | Brittle |
| `umbrella.cisco.com/api/v1/...` | Working free tier | Stable |
| `trustedsource.org` (McAfee/Skyhigh) | Captcha-fronted, partially merged into Skyhigh | Skip |
| `expireddomains.net` login | Working, requires paid account, ToS-questionable | Skip |

### Throughput
Synchronous `requests`, one domain at a time, with `doSleep(timing)` `:29` random sleep. **~1–3 domains/sec realistic** before tripping CAPTCHAs. For our 1k–10k candidates/day this is fine if we cache reputations per-domain (we will).

### Integration pattern
**Vendor as a single `domain_hunter/enrichment/reputation.py` module.** Don't `pip install` — the repo isn't on PyPI and the pinned `texttable==0.8.7` / `beautifulsoup4==4.5.3` will conflict with edgartools' `bs4>=4.10`. Strategy:
1. Copy `checkBluecoat`, `checkIBMXForce`, `checkTalos`, `checkUmbrella` verbatim into our codebase.
2. Drop `texttable`/`pytesseract`/`pillow` deps entirely.
3. Wrap each in `tenacity` retry + async `httpx` shim (their `requests.Session` is sync).
4. Cache hits in `reputation_cache` Postgres table keyed by `(domain, source, fetched_at)` with 90-day TTL.
5. Keep the BSD copyright notice in the file header — license requires it.

---

## 2. `luigigubello/expired-domain-finder`

| Property | Value |
|---|---|
| License | **MIT** (Luigi, 2022) |
| Last commit | **2022-06-01** — frozen, single contributor |
| Lang / shape | Single-file Python CLI, **155 LOC** — basically a snippet |
| Deps | `requests`, `click`, `whois` (DannyCork's `python-whois`, **not** `whois==1.x` PyPI which is a different lib) |

### What to REUSE
Honestly: just the **pattern**, not the code. The whole tool is 155 lines. The logic worth lifting (file: `expired-domain-finder/expired-domain-finder.py`):

- **`pypi_domain(package, verbose)` :33** — fetches `https://pypi.org/project/<pkg>/`, extracts `<a href="mailto:...">` via regex, then runs `url_ping` + `whois_query` + `expiration_date_check` + `status_check` on the email's domain.
- **3-stage liveness ladder** (`url_ping` `:78` → `whois_query` `:118` → `expiration_date_check` `:96` → `status_check` `:106`) — sensible fallback ordering when one signal is ambiguous.
- **`well_known_domains = ['gmail.com', 'outlook.com', 'hotmail.com']` :11** — the bypass list pattern. Extend to ~50 entries (icloud, yahoo, qq, mail.ru, protonmail, etc.) before running at scale.

### What to NOT reuse
- **`list_packages_python()` :14** — naïve `requirements.txt` parser, splits on `>|<|=|\n`. Use `packaging.requirements.Requirement` instead.
- **Bare `try/except: pass` blocks** throughout — silently swallows errors. We must log every failure mode for the audit trail.
- **The maintainer-email angle (`mailto:` extraction)** — RESEARCH §9 flags this as **illegal under CFAA / Computer Misuse Act** ("Maintainer-email domain registration is illegal in most jurisdictions"). For O3 we stay on **homepage URLs only**, never email-domain takeover.

### Integration pattern
**Reference only — do not vendor.** Rewrite as a clean `domain_hunter/sources/registry_homepage.py` module with these sub-sources:
- **PyPI**: `https://pypi.org/pypi/<pkg>/json` → `info.home_page` + `info.project_urls` (no HTML scraping needed; JSON API is documented).
- **NPM**: `https://registry.npmjs.org/<pkg>` → `homepage`.
- **CRAN**: `https://crandb.r-pkg.org/<pkg>` → `URL` and `BugReports` fields (RESEARCH §O5).
- **Bioconductor**: parses `URL:` and `URL_BugReports:` in DESCRIPTION files (`https://bioconductor.org/packages/release/bioc/...`).
- **DockerHub**: `https://hub.docker.com/v2/repositories/<ns>/<repo>/` → `full_description` regex-mined for URLs (RESEARCH §O4).

All feed the same `raw_links` table with `source='pypi'|'npm'|'cran'|'bioc'|'dockerhub'`. This is the O3+O4+O5 stack — **Phase 1 should add at least PyPI + NPM**, the other three can wait.

---

## 3. `acidvegas/czds`

| Property | Value |
|---|---|
| License | **ISC** (acidvegas, 2025) — permissive, attribution-only |
| Last commit | **2025-03-26**, **v1.3.8** — actively maintained |
| Lang / shape | Python package, on PyPI as **`czds-api`** |
| Deps | `aiohttp`, `aiofiles`, `tqdm` (per `setup.py`) |

### What to REUSE
All of it. **`pip install czds-api`** and use as library. Public surface in `czds/czds/client.py`:

- **`CZDS(username, password)`** class `:34`, full async context manager (`__aenter__` `:71` / `__aexit__` `:80`).
- **`authenticate() -> str`** `:96` — POST to `account-api.icann.org/api/authenticate`, returns bearer JWT. Cached for the session.
- **`fetch_zone_links() -> list`** `:120` — returns S3 presigned URLs for every approved zone the account has.
- **`get_report(filepath, format='csv'|'json')`** `:138` — pulls the per-account approval-status report.
- **`download_zone(url, output_directory, semaphore)`** `:185` — streams a single `.txt.gz`. Supports optional gzip decompression. Built-in retry via internal `_download()` `:194`.
- **`download_zones(output_directory, concurrency)`** `:293` — orchestrator: fetches all links and downloads with `asyncio.Semaphore(concurrency)`.

### What to NOT reuse
- Nothing notable to skip — the package is small and tight.
- One gotcha: the CLI lives in `czds/__main__.py`; for library use, import directly: `from czds import CZDS`. (`czds/__init__.py` re-exports.)

### APIs / status
- `account-api.icann.org/api/authenticate` and `czds-api.icann.org/czds/downloads/*` — official ICANN endpoints, free for approved users. **Phase 0 dependency**: CZDS application submitted day 1 per PRD §8; approval is 3–10 days per TLD.

### Throughput
Designed for **1,200+ zones/day**, sized as small (.shop, ~5MB) to massive (.com, ~6GB gzipped). With `concurrency=10` on a residential link, full pull is ~20–40 min. Disk is the constraint: **~150 GB compressed for the full CZDS portfolio**, ~1 TB decompressed. PRD §8 plans 10 TLDs initially → ~30 GB compressed.

### Integration pattern
**Use as-is via `pip install czds-api==1.3.8`**. Wire into a daily APScheduler job. Persist zone files to `/var/dh/czds/<tld>/<yyyymmdd>.txt.gz`, then a separate worker computes the daily diff (today minus yesterday → newly-deleted domains) and inserts into `czds_deletes` table. This is **Phase 4** material — gated on approval.

---

## 4. `hahwul/deadfinder`

| Property | Value |
|---|---|
| License | **MIT** (hahwul, 2026) — current copyright |
| Last commit | **2026-05-04** — actively maintained, current |
| Lang / shape | **Crystal** (not Ruby anymore — v2 rewrite). Ruby v1 is on `legacy/v1` branch and still publishes the `deadfinder` gem. |
| Distribution | `brew install deadfinder`, `docker run ghcr.io/hahwul/deadfinder:latest`, prebuilt binaries, AUR, snap |

### What to REUSE
**Use as a binary**, not as a library. From `deadfinder/src/cli_main.cr`:
- Commands: `url`, `file <file>`, `pipe` (stdin), `sitemap <url>`.
- Output formats: `json`, `yaml`, `toml`, `csv`, `sarif` — JSON is what we want.
- Key flags: `--concurrency=N` (default 50), `--timeout=N` (default 10), `--include30x` (treat redirects as alive), `--match=PATTERN`, `--ignore=PATTERN`, `--silent`.

### What to NOT reuse
- **Don't try to vendor the Crystal source.** Our stack is Python 3.12; a Crystal sub-dependency would mean a Crystal toolchain in our Docker image (~400 MB) just for this. **Use the official Docker image instead** (`ghcr.io/hahwul/deadfinder:latest`).
- **Don't depend on the legacy `deadfinder` Ruby gem** (`legacy/v1` branch) — bug-fix-only mode, no new features. v2 is the future.

### APIs
None — it makes outbound HTTP only. Targets-as-input, dead-URLs-as-output. Caller controls all URLs.

### Throughput
Default `--concurrency=50` workers. Author's own GitHub Action uses it on sitemaps with thousands of URLs. **Realistic ceiling ~500–1000 URLs/sec** on a single beefy host with `--concurrency=200`, network-bound. Easily handles our 10k/day budget; for the A2 firehose at 100k+ URLs/day from large repos, run inside a worker with a Redis-backed queue.

### Integration pattern
**Container sidecar.** Add to our `docker-compose.yml`:
```yaml
deadfinder:
  image: ghcr.io/hahwul/deadfinder:latest
  entrypoint: ["sleep", "infinity"]   # we'll `docker exec` per batch
```
Then a Python helper `domain_hunter/enrichment/liveness.py` does:
```python
proc = await asyncio.create_subprocess_exec(
    "docker", "exec", "-i", "dh-deadfinder",
    "deadfinder", "pipe", "-c", "50", "-f", "json", "-s",
    stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE)
```
Alternative: **just use `httpx.AsyncClient` directly.** For our 10k/day scale a 200-line async-httpx liveness probe is enough; deadfinder is worth it only if we ingest A2 at firehose (100k+/day).

---

## 5. `biglocalnews/warn-scraper`

| Property | Value |
|---|---|
| License | **Apache 2.0** (Big Local News / Stanford, 2025) — attribution + NOTICE required |
| Last commit | **2026-05-11** — actively maintained |
| Lang / shape | Python package on PyPI as **`warn-scraper`** (`pip install warn-scraper`); also a CLI |
| Deps | `click`, `bs4`, `requests`, `openpyxl`, `pdfplumber` (per `setup.py`) |

### What to REUSE
**Install from PyPI and call as a library**. Surface:
- **`warn.Runner(data_dir, cache_dir)`** class in `warn/runner.py:10`. Method: `Runner.scrape(state: str) -> Path` `:39` returns a CSV path.
- **42 per-state scrapers** under `warn/scrapers/*.py` (ak, al, az, ca, co, ct, dc, de, fl, ga, hi, ia, id, il, in, ks, ky, la, md, me, mi, mo, mo, mt, ne, nj, nm, ny, oh, ok, or, pa, ri, sc, sd, tn, tx, ut, va, vt, wa, wi). Each exposes a `scrape(data_dir, cache_dir) -> Path` callable.
- **`warn.cache.Cache`** (`warn/cache.py`) — disk-backed HTTP cache keyed by URL; we re-use for idempotent re-runs.
- **`warn.platforms`** — shared scraper helpers for state portals (ny.gov, etc.).

### What to NOT reuse
- **Their CSV output format directly** — schemas vary across states. We need a normalizer step that maps state CSVs into a unified `warn_notices` table with `(employer_name, location, n_layoffs, effective_date, source_state, raw_url)`. The normalizer is **ours to write**.
- The CLI (`warn/cli.py`) is fine for ad-hoc but our scheduler should call the `Runner` API directly.

### APIs
None. Each scraper hits its own state Dept-of-Labor portal directly. **Rate-limit politely** — Big Local News asks scrapers to be respectful and many states ban the project's User-Agent if abused. Use the project's existing UA strings; don't customize.

### Throughput
Per-state runs vary wildly: CA + NY pull thousands of rows in <30s; smaller states are seconds. Daily incremental: ~5–10 min for all 42 states. Not a scale concern.

### Integration pattern
**`pip install warn-scraper`** as a dep. Schedule a daily APScheduler job that calls `Runner().scrape(state)` for each state in parallel via `asyncio.to_thread()` (the scrapers are sync). Normalize CSVs into `warn_notices`. Cross-reference employer-name against company-website lookups (via Wikidata or company search) to derive **company-domain candidates** → push to `candidates` table for D11. This is **Phase 3** material — wait until A2/A3/A4 are flowing first.

### Attribution
Apache-2.0 requires shipping a `NOTICE` file referencing Big Local News + listing modified files if we patch the scrapers.

---

## 6. `dgunning/edgartools`

| Property | Value |
|---|---|
| License | **MIT** (Dwight Gunning, 2022–) — attribution-only |
| Last commit | active (in current dev cycle per CHANGELOG) |
| Lang / shape | Python package on PyPI as **`edgartools`** |
| Deps | `httpx`, `pandas`, `pyarrow`, `bs4`, `lxml`, `rich`, `pydantic`, `pyrate-limiter`, `httpxthrottlecache`, `truststore`, `stamina`, `orjson`, `textdistance`, `rapidfuzz`, `tqdm` — heavy but well-maintained |

### What to REUSE
**`pip install edgartools`** and use the library. For D8 (bankruptcy 8-K mining), the entry points:

- **`from edgar import get_filings`** — `edgar/__init__.py` re-exports `Filings` and `get_filings()` from `edgar/_filings.py`. Call as `get_filings(form="8-K", filing_date="2026-05-01:2026-05-14")` → `Filings` object.
- **`CurrentReport`** class — `edgar/company_reports/current_report.py:201`. This is the 8-K parser. Key methods:
  - **`.items() -> List[str]`** `:626` — returns the 8-K Item codes (e.g. `["1.03", "2.01"]`). **Item 1.03 = Bankruptcy or Receivership.**
  - **`.has_press_release()`** `:435`, **`.press_releases()`** `:594` — exhibit extraction.
  - **`.date_of_report()`** `:735`, **`.is_amendment()`** `:399`.
  - **`.__getitem__(item_name)`** `:670` — direct lookup by item code, e.g. `report["1.03"]` returns the section text.
- **`_extract_items_from_text()`** `edgar/company_reports/current_report.py:51` and **`_extract_item_content_from_text()`** `:126` — if we ever need to parse 8-K text outside the `CurrentReport` wrapper (we won't).
- **`get_current_filings()`** / `iter_current_filings_pages()` from `edgar/current_filings.py` — for the firehose of filings filed *after* the 5:30 EST daily cutoff.

### What to NOT reuse
- **The whole XBRL / financial-statement stack** (`edgar/xbrl/*`, `edgar/earnings.py`, `edgar/company_reports/*` beyond `current_report.py`) — we don't need balance sheets, income statements, fund holdings, insider transactions for Domain Hunter. They add a lot of import surface.
- **The `mcp` / `tiktoken` / `starlette` / `uvicorn` optional deps** (under `[project.optional-dependencies] ai`) — explicitly skip; we don't want edgartools' MCP server competing with ours.

### APIs
Hits **`data.sec.gov`** and **`www.sec.gov/cgi-bin/browse-edgar`** directly — both free, no key. SEC enforces a User-Agent policy: must include a contact email (edgartools handles this; we set `EDGAR_IDENTITY` env). Rate limit: **10 req/sec** total to SEC; edgartools' `pyrate-limiter` + `httpxthrottlecache` enforces.

### Throughput
SEC cap = 10 req/sec. Daily 8-K volume = 100–300 filings on a normal day, spike days 500+. Easily within budget. Library handles caching to `~/.edgar/` so re-runs are cheap.

### Integration pattern
**`pip install edgartools`** as a direct dep. Schedule a daily APScheduler job:
```python
from edgar import get_filings, set_identity
set_identity("Domain Hunter <ops@example.com>")  # SEC requires
filings = get_filings(form="8-K", filing_date=yesterday_iso)
for f in filings:
    report = f.obj()  # CurrentReport
    if "1.03" in report.items():
        # extract company name + CIK → look up domain via Wikidata/manual
        # push to candidates with source='edgar_8k_103', authority=high
```
For D8 specifically: filter on Item 1.03 (Bankruptcy/Receivership) and Item 2.01 (Completion of Asset Acquisition — includes asset sales out of bankruptcy). **Phase 3** material.

---

## 7. `tomnomnom/waybackurls`

| Property | Value |
|---|---|
| License | **None in repo** (no `LICENSE` file). tomnomnom's tools are generally MIT but **this repo lacks an explicit license — treat as all-rights-reserved**. Don't vendor; use as binary only. |
| Last commit | **2022-04-05** — frozen ~4 years |
| Lang / shape | Go, single `main.go` ~297 LOC |
| Distribution | `go install github.com/tomnomnom/waybackurls@latest` |

### What to REUSE
**Use as a binary in a sidecar container, or skip entirely.** What it does (functions in `waybackurls/main.go`):
- **`getWaybackURLs(domain, noSubs)`** `:127` — hits `http://web.archive.org/cdx/search/cdx?url=<wildcard>.<domain>/*&output=json&collapse=urlkey`.
- **`getCommonCrawlURLs(domain, noSubs)`** `:167` — **hardcoded `CC-MAIN-2018-22-index`** ⚠️ **8 years out of date.** This is broken for any modern CC snapshot. Don't rely on it.
- **`getVirusTotalURLs(domain, noSubs)`** `:204` — requires `VT_API_KEY` env. VT free tier = 4 req/min, 500/day.
- **`getVersions(u)`** `:257` — fetches list of all Wayback captures of a single URL.

### What to NOT reuse
- **`getCommonCrawlURLs`** — the hardcoded 2018 index is dead/cold. If we want CC data, query the **CC Index API** directly: `https://index.commoncrawl.org/collinfo.json` lists current indexes (~`CC-MAIN-2025-*`).
- **`getVirusTotalURLs`** — VT free-tier rate limit (4 req/min) is below our needs; skip unless we pay.

### APIs / status
- **Wayback CDX**: `web.archive.org/cdx/search/cdx` — **still free, still working** in 2026. No key. **Be polite**: ~10 req/sec sustained, IA throttles aggressively beyond that. Their docs recommend ≤5 req/sec.
- **Common Crawl index**: free, but use a current index name.
- **VirusTotal v3 API**: needs key, 4 req/min on free tier.

### Throughput
Single-domain, synchronous Go calls. Throughput is **CDX API-bound** (~5–10 domain queries/sec is the polite ceiling). Our 10k available-domains/day → 30 min/day of CDX time, easy.

### Integration pattern
**Reimplement in Python directly — don't use the Go binary at all.** ~30 lines of `httpx.AsyncClient` against the same CDX endpoint gives us:
- Native control over the User-Agent (we want `Domain-Hunter/0.1 (contact: ops@...)`).
- Proper async batching with `asyncio.Semaphore`.
- No second runtime in the Docker image.
- Avoid the no-license problem with the Go source.

For Wayback **content classification** (Section 4.3 of PRD), what we need beyond CDX URL enumeration is the **HTML snapshot** itself: `https://web.archive.org/web/<timestamp>/<url>` returns the archived page. Pass to Claude Haiku for spam/adult/parking classification.

Skip `gau` (getallurls) — it has the same hardcoded-CC-index problem and the same VirusTotal rate-limit problem; not worth a second binary.

---

## 8. `CaliDog/certstream-server`

| Property | Value |
|---|---|
| License | **MIT** (Cali Dog Security, 2018) |
| Last commit | **2025-09-04** — actively maintained |
| Lang / shape | **Elixir/OTP** application using `cowboy` + `pobox` |
| Distribution | Docker image; build via `mix deps.get && mix run --no-halt` |

### Architecture (per `README.md`)
- 1 HTTP-watcher Erlang process per Certificate-Transparency log in Google's `all_logs_list.json` (currently ~50 active logs).
- Each watcher polls the log's STH every 10s; on Merkle-tree change, fetches new entries, parses with `EasySSL`, pushes to `ClientManager`.
- `ClientManager` fans out to websocket clients via `pobox` for load-shedding.
- `CertificateBuffer` keeps a 25-cert ring buffer in memory.
- Public WS endpoints: `/` (cert metadata only) and `/full-stream` (with DER blob).
- Public HTTP: `/latest.json`, `/example.json`.

### What to REUSE
**Do not host this ourselves.** Reasons:
- Elixir is outside our stack and adds operational debt for a single firehose.
- Cali Dog already runs the public stream at `wss://certstream.calidog.io/` for free.
- They claim "millions of certs/day, ~250 TB/month" on a single Hetzner box — replicating that on a Dell is wasteful.

### Integration pattern
**Consume via the public stream using `certstream-python` (`pip install certstream`)** — the Python client maintained by the same org. Pattern:
```python
import certstream
def on_message(msg, ctx):
    if msg["message_type"] == "certificate_update":
        for dom in msg["data"]["leaf_cert"]["all_domains"]:
            # push to ct_log_observations table
certstream.listen_for_events(on_message, url="wss://certstream.calidog.io")
```
For **D1 (cert-decay detection)**, we don't actually need realtime; we want **historical** cert observations. Use **`crt.sh`** Postgres replica directly: `psql -h crt.sh -U guest certwatch -c "SELECT ... FROM certificate_identity WHERE name_value ILIKE '%.example.com'"`. CertStream is realtime *signal*; crt.sh is historical *query*. Pick crt.sh first for D1; CertStream is **Phase 4+** material.

### Fallback
If CertStream's public stream goes away (it has been spotty in 2024–2025), self-host the **Python** version (`CaliDog/certstream-server-python`, also MIT) — same architecture, single Python process, ~5x less efficient than Elixir but fine for our scale.

---

## WHOIS API Comparison

All checked 2026-05-14. Costs in USD/month unless noted.

| API | Free tier | Paid entry | Availability boolean | Expiry date | Registrar | Historical WHOIS | RPS / RPM | TLDs (.io/.ai/.info/.biz/.xyz/.shop) | Python client | Auth | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **`python-whois` (PyPI)** | Free, unlimited | — | ✅ (parse-based) | ✅ | ✅ | ❌ | Local network only; ~1–5 q/s sustainable, registries rate-limit | All TLDs that ship a public WHOIS server (.io ✅, .ai ✅, .info ✅, .biz ✅, .xyz ✅, .shop ✅) | self | **First pass — keep as primary** |
| **WhoisFreaks Domain Availability** | 500 credits once, 10 rpm live / 5 rpm bulk | $19 = 5k credits (~$0.0038/check) up to $399 = 1M (~$0.0004/check) | ✅ | Live API yes; availability API just yes/no | ✅ on Live API | ✅ separate Historical WHOIS product | up to 300 rpm on top tier | **1528+ TLDs** including all six target TLDs | unofficial pip `whoisfreaks` exists, thin REST wrapper | API key | **Keep as fallback for .ai/.io bulk** (PRD baseline) |
| **WhoAPI Domain Availability** | 10,000 requests once (non-renewable) | $23 = 40k/mo, $49 = 200k, $99 = 1M, $399 = 5M | ✅ | ❌ (availability product is yes/no only) | ❌ | ❌ (separate Whois API at $52+/mo) | not published, ~40+ rpm typical | "hundreds of TLDs"; specific TLD list at whoapi.com/list-of-available-tlds — confirmed .com/.net/.org/.me/.co; .io/.ai/.info/.biz/.xyz/.shop are likely-but-not-explicitly-stated | no official Python; REST `apikey=` query param | URL apikey param (insecure) | **Skip** — 10k free is generous one-time but per-request cost ($0.000575 at Startup tier) is only marginally cheaper than WhoisFreaks, and the auth model passes the key in URL |
| **WhoisJSON** | **1,000 req/mo recurring** (renews monthly), 20 rpm | $10 = 30k, $30 = 150k, $50 = 1M, $80–600 = unlimited | ✅ via `/domain-availability` | ✅ via `/whois` | ✅ | ❌ | 20 rpm free, up to 900 rpm | **1,500+ TLDs including .io/.ai/.info/.biz/.xyz/.shop confirmed** | **Official: `pip install whoisjson`, Python 3.7+** | `Authorization: TOKEN=...` header | **⭐ Best free tier of the paid APIs; promote to primary fallback** |
| **DomainsDB.info** | Free public API, no auth | None | Database of seen domains, **not realtime availability** — returns metadata if known | partial | partial | ❌ | undocumented; politeness only | DB-driven; coverage uneven across new TLDs | none official | none | **Use as bulk metadata lookup, not authoritative availability** |

### Recommended WHOIS waterfall

```
1. `python-whois` (free)         — fast first pass, 100% local
2. `dnspython` NXDOMAIN check    — sanity
3. WhoisJSON `/domain-availability` (free 1k/mo recurring)
                                  — fallback when python-whois is ambiguous
4. WhoisFreaks bulk (500 free + paid credits)
                                  — bulk batches of 100 for nightly re-checks
```
This replaces the PRD §4.2 plan of WhoisFreaks-as-primary-fallback. WhoisJSON's 1k/mo **recurring** free tier (vs WhoisFreaks's one-time 500) plus the **official Python client** make it the better default for spot-checks; WhoisFreaks stays for true bulk.

---

## Recommended pip install / Docker dependency list

### Python deps (target `pyproject.toml`)
```toml
[project]
name = "domain-hunter"
requires-python = ">=3.12"
dependencies = [
  # Framework
  "fastapi>=0.115.0",
  "uvicorn[standard]>=0.32.0",
  "pydantic>=2.9.0",
  "pydantic-settings>=2.5.0",

  # Async HTTP + retry
  "httpx>=0.27.0",
  "tenacity>=9.0.0",

  # DB
  "psycopg[binary,pool]>=3.2.0",
  "sqlalchemy[asyncio]>=2.0.35",
  "pgvector>=0.3.0",
  "alembic>=1.13.0",

  # Scheduler / queue
  "apscheduler>=3.10.0",
  "redis>=5.1.0",

  # Domain-specific clients (external repos audited above)
  "czds-api>=1.3.8",            # acidvegas/czds
  "warn-scraper>=2.0.0",        # biglocalnews/warn-scraper
  "edgartools>=3.0.0",          # dgunning/edgartools
  "whoisjson>=0.2.0",           # official client for WhoisJSON
  "python-whois>=0.9.0",        # DannyCork's WHOIS (note: NOT `whois` pkg)
  "dnspython>=2.7.0",
  "certstream>=2.0.0",          # for CT-log streaming, when D1 lands

  # Parsing / scraping
  "beautifulsoup4>=4.12.0",
  "lxml>=5.3.0",
  "selectolax>=0.3.21",         # fast HTML parser for Wayback snapshots

  # Data
  "pandas>=2.2.0",
  "pyarrow>=17.0.0",
  "duckdb>=1.1.0",              # Common Crawl + OpenAlex Parquet querying

  # LLM
  "anthropic>=0.40.0",
  "voyageai>=0.3.0",            # embeddings

  # GitHub / GHArchive
  "google-cloud-bigquery>=3.25.0",
  "google-cloud-storage>=2.18.0",
  "PyGithub>=2.4.0",
  "gitpython>=3.1.0",           # shallow clone for README mining

  # Observability
  "structlog>=24.4.0",
  "sentry-sdk[fastapi]>=2.15.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.3", "pytest-asyncio>=0.24", "ruff>=0.7", "mypy>=1.11"]
```

### Vendored (not pip-installed) modules
- `domain_hunter/enrichment/reputation.py` — copied from `threatexpress/domainhunter` (BSD; preserve copyright header). Keeps `checkBluecoat` / `checkIBMXForce` / `checkTalos` / `checkUmbrella` only.

### Docker base image
```
FROM python:3.12-slim AS base
# system deps for psycopg, lxml, pyarrow native wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 git curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*
```
Sidecar:
```
deadfinder:
  image: ghcr.io/hahwul/deadfinder:latest
  entrypoint: ["sleep", "infinity"]
```
Plus Postgres 16 with pgvector (`pgvector/pgvector:pg16`).

---

## Things we should fold into PRD / RESEARCH

Concrete edits surfaced by this audit. **Not making them here — flagging for review.**

### PRD.md changes
1. **§4.2 (Availability check)** — swap WhoisFreaks-as-primary-fallback for **WhoisJSON** (1k/mo recurring free tier vs WhoisFreaks's one-time 500, plus official Python client `pip install whoisjson`). Keep WhoisFreaks for true bulk (>1k/day). Remove **Domainr** entry — confirmed deprecated and no public free API endpoint remains.
2. **§6 (Tech stack), `Liveness` row** — currently says `hahwul/deadfinder` + httpx async. Note: **`deadfinder` is now Crystal, not Ruby**. We can't `pip install` it. Either (a) drop it and use pure `httpx` async (recommended for 10k/day), or (b) run as Docker sidecar via `docker exec`. The PRD wording should be updated to reflect this.
3. **§6 (Tech stack), `Reputation` row** — `threatexpress/domainhunter` is **BSD-3-Clause** (not MIT as RESEARCH §3 implies). Attribution + copyright header retention required when vendoring. Note the 2022-stale status.
4. **§4.4 (Filter set)** — add a `ct_log_observations_count` field (cheap signal from crt.sh; useful as a "domain was ever real" indicator for Wayback-content-decay's negative class).
5. **§4.3 (Wayback)** — explicitly note that **`waybackurls` is unlicensed Go source**; we will reimplement its CDX call in `httpx` (~30 lines) rather than shipping the Go binary or vendoring.
6. **§8 Phase 4 (CZDS)** — `czds-api` PyPI package is at v1.3.8 and stable; no fork/vendor needed. Use as direct dep.

### RESEARCH.md changes
1. **§3 table** — `hahwul/deadfinder` is Crystal v2.x now; legacy Ruby gem on `legacy/v1` branch (bug-fix only). Update the "Use for" / install column.
2. **§3 table** — `tomnomnom/waybackurls` has **no LICENSE file** in repo as of 2026-05; treat as all-rights-reserved and reimplement instead of vendoring.
3. **§3 table** — `threatexpress/domainhunter` license is **BSD-3-Clause** (not MIT).
4. **§3 table** — `acidvegas/czds` is **ISC** (license col currently correct) and ships as PyPI **`czds-api`** — note install command.
5. **§4 table** — Replace **Domainr** row (deprecated, no working free API) with **WhoisJSON** (1k/mo free, 1500+ TLDs, official Python client).
6. **§4 table** — Add a row for **`crt.sh` Postgres replica** as the historical CT-log query path (free, public `psql -h crt.sh -U guest certwatch`) — currently RESEARCH only references it in §13 sources and §5 D1. It should be a first-class API row alongside CertStream.
7. **§5 A2 starter repo callout** — `luigigubello/expired-domain-finder` is 155 LOC and email-domain-based (CFAA/CMA risk per §9). Reference-only; rewrite as homepage-URL-only PyPI/NPM/CRAN/DockerHub fan-out (matches §5 O3+O4+O5 stack).

---

## Final notes

- Cumulative new Python deps (post-audit): 32 packages. All MIT/Apache/BSD compatible with each other; no GPL surface introduced.
- One known risk: `python-whois` (DannyCork's package) ships as the import name `whois`, which **collides with the totally different `whois` PyPI package**. Pin `python-whois>=0.9.0` and never `pip install whois`.
- `threatexpress/domainhunter` is the only **vendored-source** dependency (BSD requires the copyright preserved). Everything else is `pip install`.
- The Crystal/Go binaries (`deadfinder`, `waybackurls`) can be skipped entirely for Phase 1 — pure-Python `httpx` async covers our 10k/day liveness budget.
