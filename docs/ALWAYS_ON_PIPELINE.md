# Domain Hunter — always-on acquisition research contract

> Current source of truth as of 2026-08-20. This supersedes the old dashboard,
> 20–50-candidates-per-day, GitHub-first, and CZDS-first plans.

## Outcome

Domain Hunter should keep searching even when no good domain is available. Its
job is to reduce a very large, noisy inventory to at most a handful of domains
that deserve manual due diligence. A zero-item shortlist is a successful result
when the evidence is weak or risky.

The product ends at **research recommendation**. It has no authenticated
marketplace write client and no operation for bidding, buying, backordering,
listing, emailing, or spending money.

## Six-stage funnel

| Stage | Question | Automatic evidence | Failure behavior |
|---|---|---|---|
| Inventory | Is it actually approaching deletion? | DropCatch public five-day pending-delete CSV | Keep the previous database state; mark the run failed |
| Authority | Is there enough link signal to inspect? | Cached OpenPageRank Top-10-Million rank, OPR, referring domains | Use a validated stale cache; never invent metrics |
| Demand | Do buyers historically pay for its words? | NameBio RetailStats, conservative weakest-placement floor | Continue as `observe`; never promote without demand |
| Acquisition | Is there a real channel, date, and price? | DropCatch public detail plus listing URL | Keep drop date; lower confidence if exact price/time is absent |
| Integrity | Is the authority/history suspicious? | Authority-cohort anomaly, RDAP, Wayback metadata, name/spam rules | `observe` or `reject`; missing evidence remains visible |
| Decision | Should Pranav spend? | Independent backlinks, archive pages, trademarks, comps, buyer thesis, max bid | Human only; no default action |

## Cadence and bounded work

- Inventory cycle: every 6 hours.
- DropCatch file: one bulk download per cycle; public detail requests are capped
  and politely rate-limited.
- OpenPageRank reference: monthly refresh, otherwise local intersection.
- NameBio RetailStats: minimum 24-hour cache with attribution.
- RDAP: active inventory twice daily; registered names every 30 days; unknown
  responses back off for 7 days.
- Wayback: only active marketplace candidates, not the entire historic table.
- Every discovery run records source version, counts, duration, partial errors,
  and reference refresh state.

Default limits live in `.env.example`. Increasing the candidate or detail caps
must follow measured funnel loss, not intuition.

## Score semantics

`market-v2` stores five independent scores:

- **Authority** — OPR plus logarithmic referring-domain breadth.
- **Resale** — name quality plus qualifying keyword retail-sales evidence.
- **Risk** — famous marks, obvious abuse terms, and suspicious authority cohorts.
- **Confidence** — which acquisition and market facts were directly observed.
- **Overall** — a prioritization number, not a valuation.

The verdicts are:

- `research`: market demand cleared the floor, authority is not in a suspicious
  cohort, no automatic hard rejection fired, and overall score clears the gate.
- `observe`: interesting but incomplete, weak-demand, anomalous, or below gate.
- `reject`: an automatic abuse/famous-mark rule fired. Manual review can add
  additional rejects that the generic model cannot know.

NameBio placement counts are not independent sets, so the pipeline never adds
them. For a compound name it uses the weakest meaningful word/placement count
and the lowest corresponding average price. These are demand priors, not
domain-specific comparable sales or an appraisal.

OpenPageRank is also a prefilter, not proof of clean or transferable links.
Near-identical high metrics across several drop-list names are treated as a
network/spam warning, not a windfall.

## Mandatory human acquisition checklist

No domain is acquisition-ready until all boxes are answered and evidence is
recorded:

1. **RDAP:** still pending delete/available, with no restoration or status change.
2. **Acquisition channel:** live deadline, price, fees, auction rules, and account
   eligibility verified directly at the marketplace.
3. **Archive:** representative early, middle, late, and suspicious URL captures
   read—not just capture count.
4. **Backlinks:** independent provider/export reviewed for referring pages,
   anchors, topical relevance, followability, link survival, and network patterns.
5. **Reputation:** malware, phishing, adult, casino, pharma, scam, and search-spam
   history checked.
6. **Rights:** exact/fuzzy trademark search, common-law/current brand search, and
   former-owner identity reviewed. Escalate uncertainty to counsel.
7. **Demand:** domain-specific comparable retail sales checked; wholesale auction
   results are not mixed with retail end-user sales.
8. **Buyer thesis:** at least three plausible unrelated buyers exist for the
   generic meaning; a prior owner is not the thesis.
9. **Economics:** maximum bid includes catch fee, renewal, marketplace commission,
   expected hold time, and a conservative sell-through probability.
10. **Use:** the intended landing/content adds genuine value and does not exploit
    the former site's reputation or redirect old visitors deceptively.

The WIPO UDRP test and local law matter. Registering a name primarily to sell it
to a trademark owner can be evidence of bad faith. This checklist is operational
risk control, not legal advice.

## Operator surfaces

```bash
curl -fsS http://127.0.0.1:8007/api/pipeline/status
curl -fsS 'http://127.0.0.1:8007/api/opportunities?verdict=research&active_only=true'
curl -fsS http://127.0.0.1:8007/api/digest/today
```

`/api/pipeline/status` should always report
`automated_purchase_enabled=false` and `human_approval_required=true`.

Human decisions are append-only. The latest `passed`, `bought`, or
`lost_to_other` decision removes a domain from the API, Discord shortlist, RDAP,
and Wayback actionable queues. A later `watching` or `needs_manual_review`
decision deliberately reopens it. Use `actionable_only=false` on
`/api/opportunities` when an audit must include manually closed names.

Discord is optional. Set a real bot token, guild, owner, and channel to receive
the daily research digest. A missing channel must not stop discovery.

## Failure and safety model

- Downloads are size-, host-, archive-, and schema-validated before replacement.
- Reference refresh failures use the last validated local copy and are visible in
  run metrics.
- Per-domain detail failures produce a partial run, not a lost cycle.
- Database writes are idempotent by marketplace external key and model version.
- Old listings expire; old candidates and evidence remain for audit.
- The latest human outcome overrides automation; terminal outcomes suppress
  further actionable work without deleting evidence.
- DNS non-resolution never proves availability. RDAP or registrar evidence does.
- Stub classifier output is never persisted as real evidence.
- OpenTelemetry console spam is off by default.
- All exposed service ports bind explicitly to localhost. MOC, Desk OS, landing,
  and their ports/networks are outside this Compose project and untouchable.

## Next upgrades, in evidence order

1. Add an independent backlink provider or a locally processed Common Crawl
   domain graph. Common Crawl includes technical links, so topical/anchor review
   is still required.
2. Add authenticated USPTO Open Data ingestion after Pranav creates the required
   account/key; combine with manual global/common-law searches. Do not label an
   automated exact match as legal clearance.
3. Add NameBio domain-specific comps only after written API access and terms are
   confirmed. RetailStats remains only an aggregated keyword prior.
4. Add additional official auction/pre-release feeds one at a time, with source
   terms, rate limits, idempotency keys, and read-only clients.
5. Train/evaluate history and spam classification only on a labelled review set.
   A model without measured precision must not hard-reject or authorize spend.
6. Record realised outcomes—bid, won/lost, hold cost, inquiry, sale, net profit—so
   thresholds can be calibrated against money rather than attractive anecdotes.

More scraping is not the first priority. Better independent evidence and
closed-loop outcome data are.

## Source-policy references

- [DropCatch downloads](https://www.dropcatch.com/downloads)
- [NameBio API and RetailStats rules](https://api.namebio.com/docs/)
- [OpenPageRank API](https://openpagerank.keywordseverywhere.com/docs)
- [ICANN RDAP](https://www.icann.org/rdap/)
- [ICANN EPP status codes](https://www.icann.org/resources/pages/epp-status-codes-2014-06-16-en)
- [Common Crawl web graphs](https://commoncrawl.org/web-graphs)
- [USPTO trademark bulk data](https://www.uspto.gov/trademarks/apply/check-status-view-documents/trademark-bulk-data)
- [WIPO UDRP guide](https://www.wipo.int/en/web/amc/domain-name-disputes/guide/index)
- [Google expired-domain abuse policy](https://developers.google.com/search/docs/essentials/spam-policies#expired-domain-abuse)
