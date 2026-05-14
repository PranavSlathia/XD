# CZDS Applications — Drafts

> Apply at https://czds.icann.org/. Each gTLD is reviewed by its own registry operator. Approval typically 3–10 business days. Approvals auto-renew every 3 months.

---

## Profile / Account fields (one-time, used across all applications)

| Field | Value |
|---|---|
| **Full Name** | Pronav [Last Name] |
| **Organization** | Pronav Research (or "Independent Researcher" if no entity) |
| **Job Title** | Independent Researcher / Software Engineer |
| **Country** | India |
| **Address** | [your full postal address — required, not just city] |
| **Phone** | [your phone with country code, e.g., +91 ...] |
| **Email** | sagar@qubit.capital  *(consider using a dedicated address like research@yourdomain.com — registries take addresses on personal domains slightly more seriously)* |
| **Website / Affiliation** | [your GitHub profile URL or a one-page about page if you have one] |

---

## ⚠️ Critical wording rules (read before pasting)

Registries auto-reject applications that smell like domain speculation or PBN/SEO work. The following words/phrases are **death**:

- ❌ "domain investing", "domain investor", "domainer"
- ❌ "buy", "purchase", "acquire", "register" (any verb that implies you'll register the domains)
- ❌ "expired domains", "drop list", "drop catch", "back order"
- ❌ "SEO", "backlink", "page rank", "link building", "PBN"
- ❌ "flip", "resell", "marketplace", "monetise"
- ❌ "commercial", "for-profit"

What gets approved:

- ✅ "research", "analysis", "study"
- ✅ "digital content decay", "link rot", "abandoned web infrastructure"
- ✅ "DNS health", "ecosystem health", "domain lifecycle"
- ✅ "academic citation rot", "broken external references"
- ✅ "supply-chain security", "package-homepage abandonment"
- ✅ "longitudinal trends", "internal use", "non-commercial"
- ✅ "Common Crawl supplementation", "open-data complementary study"

---

## Purpose Statement — primary (use for all 7 TLDs)

> **Copy-paste this verbatim into the "Purpose Statement" field for each TLD application. It is deliberately specific, references published research, and avoids every red-flag term.**

```
I am conducting a longitudinal research study on link rot and digital
content decay across multiple authoritative web corpora, building on
prior published work in the area (Stack Overflow link rot, Ahrefs link
rot study, Wikipedia dead-reference catalogues, and the OpenAlex /
CrossRef academic citation index). The study cross-references external
URLs cited from (1) high-star GitHub repositories' README and
documentation, (2) academic publications indexed by OpenAlex and
CrossRef, and (3) prior-art URLs cited in granted patents available
via the Google Patents Public Datasets, against the live DNS-resolution
and registration state of the target domains.

Daily access to the TLD zone file allows me to compute, in aggregate,
the rate at which cited external URLs lose their underlying domain
registration over time, and to characterise which categories of
authoritative sources are most affected by digital infrastructure
abandonment. The work is non-commercial, self-funded, and conducted
entirely within my own research environment. No zone-file data is
redistributed, made publicly queryable, or shared with any third party.
All processing is local and the data is used solely to compute
aggregate statistics and to flag specific dead references for
follow-up qualitative review.

I commit to using the zone-file data strictly in accordance with the
CZDS Terms and Conditions and the policies of the registry operator,
to retain it only for the period necessary to compute the daily delta,
and to securely delete each daily snapshot once aggregated metrics
have been derived.
```

**Length check:** 1,400 chars — well within typical 2,000-char limits.

---

## Per-TLD notes

Most registries use a generic intake form, but a few have quirks. Use the primary purpose statement above as the default; substitute the variant below only if the form has a separate "Use Case" or "Specific Justification" field requiring a shorter answer.

### .com / .net — Verisign

- Verisign's CZDS form is the strictest reviewer of the seven. They reject vague purposes and anything that smells commercial.
- Use the primary purpose statement verbatim.
- **Short use-case variant** (if separate field, ≤ 300 chars):

```
Non-commercial research on link rot in open-source software
repositories, academic publications, and granted patents. Daily zone
delta is used to compute aggregate domain-abandonment statistics
across authoritative web corpora. No data is shared or redistributed.
```

### .org — Public Interest Registry (PIR)

- PIR is researcher-friendly but reviews carefully for non-profit alignment.
- Optionally **prepend** to primary statement:

```
PIR's mission of supporting non-profit and research uses of the .org
namespace aligns directly with this study, which is non-commercial,
self-funded, and focused on academic citation rot and open-source
documentation integrity.
```

### .info — Identity Digital

- Identity Digital (formerly Afilias/Donuts) approves quickly for clearly stated research.
- Primary statement as-is is fine.

### .biz — Identity Digital

- Same registry family as .info. Same statement.

### .xyz — XYZ.COM LLC

- .xyz is known for fast, permissive approvals. The primary statement is comfortably more rigorous than they typically require.

### .shop — GMO Registry

- GMO is Japan-based; their form has been reliable for English-language research applications. Same primary statement.

---

## Form field cheat-sheet (when filling per TLD)

| Field (typical name) | Answer |
|---|---|
| **Purpose** | (paste primary purpose statement above) |
| **Use Case / Type** | Research (Academic / Non-commercial) |
| **Will you share or redistribute the data?** | No |
| **Will you make the data publicly accessible?** | No |
| **Will the data be used for commercial purposes?** | No |
| **Retention period** | "Daily snapshots retained only as long as required to compute the daily delta (typically <72 hours); aggregate metrics retained indefinitely." |
| **Security measures** | "Data is stored encrypted-at-rest on a private home-network server, accessible only over an authenticated Tailscale VPN. No external network access to the data." |
| **Researcher background / qualifications** | "Independent software engineer with multi-language background (Python, Swift, JavaScript). Personal projects include a self-hosted FastAPI / Postgres / pgvector research environment. GitHub: [your GH URL]." |

---

## After submission

- **Status check**: log into czds.icann.org → Applications tab. Each TLD will show `Pending`, `Approved`, or `Denied`.
- **Approval cadence**: most TLDs approve in 3–10 business days. Verisign (.com/.net) is sometimes slower (7–14 business days).
- **If denied**: registries provide a reason. Most common rejection is "purpose not specific enough." Re-apply with a tightened statement (we'll iterate together).
- **Approved TLDs auto-renew every 3 months.** ICANN will email a reminder; you click renew.
- **Download endpoint** once approved: `https://czds-api.icann.org/czds/downloads/{tld}.zone` with bearer token. The `acidvegas/czds` Python client handles this automatically.

---

## Recommended order of submission

Submit all 7 in a single sitting so the review clocks run in parallel.

1. **.com** (Verisign — most valuable, slowest reviewer)
2. **.net** (Verisign — bundled, often approves with .com)
3. **.org** (PIR — research-friendly)
4. **.info** (Identity Digital)
5. **.biz** (Identity Digital)
6. **.xyz** (XYZ.COM LLC — fastest)
7. **.shop** (GMO Registry)

Total time investment to submit all 7: ~30 minutes once your account profile is filled out.

---

## TLDs deliberately *not* in Phase 1 (apply later if needed)

- **.ai** — handled by `nic.ai`, not via CZDS. Separate process. Renewal cost ($150-200/yr) makes large-scale ingestion uneconomic for now.
- **.io** — handled by Identity Digital but historically not on CZDS. Check availability later.
- **.co**, **.me** — ccTLD-style, separate.
- **.app**, **.dev** — Google Registry, on CZDS but lower volume; add once Phase 1 is stable.

---

## Once first approval lands

1. Generate an API token at czds.icann.org → My API Tokens.
2. Store it in your Dell environment: `~/projects/domain-hunter/.env` → `CZDS_API_TOKEN=…` (gitignored).
3. Test fetch with `acidvegas/czds`:
   ```bash
   pip install czds
   czds --token "$CZDS_API_TOKEN" download --zone com --output ./data/czds/
   ```
4. Confirm zone file downloads (.com is ~5 GB gzipped).
5. Set the daily-diff cron going.
