# Data Sources — automatically pulling BIST financials (KAP, Fintables, İş Yatırım, …)

**Status:** research / design note. Nothing here is wired up yet.
**Audience:** finauto-saas + the `finauto` core library.
**Date:** 2026-06-14.

## Why this doc exists

Today the pipeline starts from a **manual PDF upload**:

- `finauto extract` takes `pdf_paths: list[Path]` and runs an LLM extractor
  (`finauto/src/finauto/ingestion/base.py` — the `Extractor` protocol).
- In the SaaS, `POST /api/extract` accepts `UploadFile`s, stores them, and enqueues an
  extraction job (`finauto-saas/api/src/finauto_api/routers/extract.py`).

The goal of this note: let a user type a **ticker** (e.g. `THYAO`) and have the system
**fetch the financial-statement file itself** instead of asking them to download a PDF from
KAP by hand. This is exactly finauto's **Phase 2 "KAP auto-download"** roadmap item, so the
fetching logic belongs in the `finauto` library's `ingestion/` layer and the SaaS just
exposes it as an endpoint.

---

## TL;DR — what to use, and the catch

| Source | What you get | Access | Format | Commercial-SaaS verdict |
|---|---|---|---|---|
| **KAP** (kap.org.tr) | Official disclosures: annual/interim financial statements, footnotes, material events | Public site + internal JSON endpoints (no documented public REST API); community lib `kap-client` | PDF + **XBRL** + HTML | ✅ **Primary source.** Data is public. For heavy/commercial use, use the official **KAP Data Publishing Service** / data licence and rate-limit politely. |
| **Fintables** (fintables.com) | *Standardized* & normalized BIST statements, ratios, dividends | **No official public API.** Community scrapers exist | JSON (scraped) | ⛔ **Avoid scraping for a paid product.** Their normalized data is a licensed product (BIST licence). Partner/licence instead. |
| **İş Yatırım** (isyatirim.com.tr) | Financial statements, prices, indices | Undocumented `Data.aspx` JSON endpoints; libs `isyatirimhisse`, `borsapy` | JSON | ⚠️ **Prototyping / cross-check only.** Libs state *personal/non-commercial use*. ToS risk for a SaaS. |
| **yfinance** (Yahoo) | Prices, betas, some fundamentals | `yfinance` (already used in `marketdata/yahoo.py`) | JSON | ⚠️ Already integrated. **Unreliable for BIST** (workspace invariant #6) — always emit the gap report. |
| **TEFAS** | Mutual-fund NAV / performance | Official site; wrapped by `borsapy` | JSON | ✅ Official, fine for funds. |
| **TCMB EVDS** | Macro series (FX, CPI, rates) | Official REST API, free key | JSON | ✅ Official + free. Good for the inflation/FX restatement (invariant #5). |

**The one-line legal reality:** because finauto-saas is a *commercial* product, the only clean
sources are **official/licensed** ones (KAP public disclosures under appropriate terms, an
official BIST data licence, or a paid vendor). Scraping Fintables or İş Yatırım is acceptable
for personal prototyping but is a **terms-of-service and licensing risk for a paid SaaS** — the
community libraries that wrap them say so explicitly. Treat them as cross-checks, not as the
production feed.

---

## 1. KAP — the recommended primary source

> **✅ Implemented (2026-06-14).** A self-contained KAP client lives in the `finauto`
> library: `finauto/src/finauto/ingestion/sources/kap.py` (`KapClient` + `KapSource`,
> behind the new `StatementSource` protocol in `sources/base.py`), plus a CLI verb
> `finauto fetch -t THYAO.IS --year 2024`. We did **not** depend on a third-party lib —
> two verified endpoints are enough:
> - `GET /tr/api/member/filter/{code}` → `mkkMemberOid` (live-verified shape)
> - `GET /tr/api/home-financial/download-file/{oid}/{year}/T` → a **ZIP** that, per a live
>   smoke test, contains **both the disclosure PDFs** (TR + EN, every quarter) **and the
>   `.xls` statement tables**. So the fetched PDFs feed finauto's existing LLM `extract`
>   stage directly; the `.xls` bundle enables the future structured-parser path.
>
> Network is isolated behind `KapClient` (inject a session in tests — `tests/test_kap_source.py`
> runs fully offline). Still TODO: wire `fetch → extract`, and the SaaS `/api/fetch/kap` endpoint.

KAP (Kamuyu Aydınlatma Platformu / Public Disclosure Platform) is the **official** venue where
every BIST-listed company files its disclosures. It is operated by Merkezi Kayıt İstanbul (MKK)
and runs on an **XBRL** data infrastructure, with delivery via the website, mobile app, a
**KAP Data Publishing Service**, and SWIFT. Disclosures are public.

For finauto this is the ideal source because:
- It's where the PDFs we already extract from **come from** (`pdf_loader.py` even tells users to
  "re-download the report PDF from KAP" on a bad file).
- Statements are also available as **XBRL** — structured, machine-readable, and far more
  reliable than LLM-reading a PDF. A future path is XBRL → schema directly, with the LLM/PDF
  route as fallback.

### Option A — `kap-client` (recommended starting point)

A type-safe Python client for KAP. It can:
- search **company disclosures** by BIST ticker or KAP OID, with subject filtering (e.g. only
  financial-statement disclosures),
- list companies/funds,
- **parse attachments** — it extracts the file links from a disclosure's HTML page and
  **downloads the attachment files** (the PDFs),
- with built-in **retry & back-off** (3 attempts).

```python
# pip install kap-client   (verify license + pin a version before adding to pyproject)
from kap_client import KapClient   # API names — confirm against the installed version

client = KapClient()
# 1) find this company's financial-statement disclosures
disclosures = client.fetch_disclosures(ticker="THYAO", subject="financial_statements")
latest = disclosures[0]
# 2) download the attached files (PDF / XBRL) to disk
paths = client.fetch_attachments(latest, dest_dir="storage_data/kap/THYAO")
# 3) hand the PDFs straight to finauto's existing extractor
```

> ⚠️ The method/class names above are illustrative — pin a version and check the actual API
> surface, because community KAP libraries change. Alternatives if it doesn't fit: `pykap`,
> `kap-tr-sdk`.

### Option B — call KAP's own endpoints directly

The website is backed by internal JSON endpoints (disclosure query → disclosure detail →
attachment file). This avoids a dependency but means **you** own the brittleness when KAP
changes its markup. Prefer Option A unless you need something the library doesn't expose.

### KAP integration notes (do this right)

- **Rate-limit & cache.** Disclosures update only every few minutes; there is no need to hammer
  KAP. Cache by `(ticker, period)` and store the raw file so re-runs don't re-download.
- **Pick the right disclosure.** A company files many disclosure types. Filter to the
  consolidated **financial statements** for the target period; prefer the latest amended
  version if one exists.
- **Inflation caveat still applies** (invariant #5): post-2022 statements are TMS-29/IAS-29
  inflation-restated — flag it; don't treat nominal TRY growth at face value.
- **For volume/commercial scale**, move to the official **KAP Data Publishing Service** / a
  data licence rather than scraping the public site.

---

## 2. Fintables — what it is, and why not to scrape it

Fintables (est. 2019) is a commercial fundamental-analysis platform that **takes KAP + BIST
data, standardizes/normalizes it** into clean, comparable statements and ratios, under licences
obtained from Borsa İstanbul. That normalization is genuinely valuable — but it is **their
licensed product**, and they **do not publish an official developer API**. Community projects
that scrape Fintables (e.g. a FastAPI microservice pulling dividends) exist, but:

- scraping it for a **paid** product risks their ToS and BIST's data licence, and
- you'd be rebuilding on an undocumented surface that can break or be blocked at any time.

**Recommendation:** don't make Fintables a production dependency. If you want their *normalized*
data quality, the right move is to **contact them for a data partnership/licence**. Otherwise,
do the normalization yourself from KAP's XBRL (which is what finauto's schema layer already aims
to do).

---

## 3. İş Yatırım — good for prototyping & cross-checks

İş Yatırım exposes undocumented JSON endpoints (the `…/Common/Data.aspx/…` family) that return
prices, indices, and **financial statements** by financial group (e.g. `XI_29` for industrials,
`UFRS` for banks). Two maintained wrappers:

- **`isyatirimhisse`** (MIT) — `fetch_stock_data`, `fetch_index_data`, `fetch_financials`.
  Explicitly *"not official … designed for personal use only"*, and warns about **IP blocking**
  if you over-request — cache locally.
- **`borsapy`** (Apache-2.0) — broader: İş Yatırım financials (`balance_sheet`, `income_stmt`,
  `cashflow`, quarterly/TTM), plus TradingView prices, TEFAS funds, BtcTurk crypto, TCMB EVDS
  macro. **States: personal & educational use only; not for commercial use — contact Borsa
  İstanbul for a commercial licence.**

```python
import borsapy as bp
t = bp.Ticker("THYAO")
print(t.balance_sheet, t.income_stmt, t.cashflow)   # industrials (XI_29)
print(bp.Ticker("AKBNK").get_balance_sheet(financial_group="UFRS"))  # banks
```

**Use them to**: bootstrap a dataset, sanity-check the LLM extraction against an independent
source, or fill yfinance's BIST gaps during development. **Don't** ship them as the commercial
production feed (licence terms).

---

## 4. Official sources worth adding (no ToS drama)

- **TCMB EVDS** — Turkey's central-bank data service. Free API key. 145+ macro series:
  USD/TRY, CPI (for the IAS-29 restatement), policy rate, bond yields. Ideal feed for the
  **inflation/FX restatement** (invariant #5) and for hard-currency terminal-value cross-checks.
- **TEFAS** — official mutual-fund data (if the product ever covers funds).
- **US comps (later):** SEC EDGAR has a clean official XBRL **company-facts API** if you ever
  add US peers; FMP / sec-api are paid options.

---

## Proposed implementation (fits the existing architecture)

Keep the fetcher in the **`finauto` library** (it's Phase 2 there) and expose it from the SaaS.

### In `finauto` — a new `ingestion/sources/` fetcher, separate from the LLM extractor

```python
# finauto/src/finauto/ingestion/sources/base.py
from pathlib import Path
from typing import Protocol

class StatementSource(Protocol):
    """Fetches raw financial-statement files for a ticker. I/O at the edge —
    returns local paths that feed the existing Extractor unchanged."""
    def fetch(self, ticker: str, *, period: str | None = None,
              dest_dir: Path) -> list[Path]: ...
```

```python
# finauto/src/finauto/ingestion/sources/kap.py
class KapSource:                       # wraps kap-client (or raw endpoints)
    def fetch(self, ticker, *, period=None, dest_dir): ...
```

- Route it via config the same way extractors are routed (`Settings.stage(...)`), so adding a
  source is "implement the protocol", never "branch in callers" — matching the existing
  `Extractor` factory pattern.
- The fetched PDFs flow into the **current** `get_extractor(...).extract(pdf_paths, ticker)`
  with **zero changes** to the extractor. (Phase 2+: add an XBRL-direct path that skips the LLM.)
- Add a CLI verb, e.g. `finauto fetch THYAO --source kap` (or fold into `finauto run --from-kap`).

### In `finauto-saas` — a sibling endpoint that reuses the extract job

```python
# new: POST /api/fetch/kap   (mirrors routers/extract.py)
#   body: { ticker, period? }
#   -> KapSource.fetch(...) into storage -> create Job(type="extract") -> queue.enqueue_extraction
```

It reuses the **same `Job` model, storage, and queue** as the upload path — only the file
*acquisition* differs. The frontend gains a "Fetch from KAP" button next to the upload box.

### Sequencing

1. `KapSource` in `finauto` + unit test with a **recorded fixture** (no live KAP in tests —
   workspace rule).
2. `/api/fetch/kap` endpoint reusing the extract job.
3. Watchlist auto-pull (Phase 2 "watchlists"): nightly job checks KAP for new statements on
   tracked tickers and auto-runs extraction.
4. (Later) XBRL → schema path; TCMB EVDS feed for the inflation restatement.

---

## Other things we could add to the project (broader backlog)

- **XBRL-first extraction** from KAP — structured, deterministic, cheaper than LLM PDF reads;
  keep the LLM path as fallback for older/odd filings.
- **Watchlists + alerts** — "tell me when SAHOL files Q2"; pairs naturally with the SSE the API
  already has for report streaming.
- **TCMB EVDS macro feed** — real inflation/FX for the IAS-29 restatement and hard-currency
  cross-checks, instead of leaving that caveat purely advisory.
- **Multi-source reconciliation** — extract from KAP, cross-check key lines against İş Yatırım
  in dev, and surface discrepancies in the gap report.
- **Caching/snapshot layer** — the `Snapshot` model is already in the schema; persist fetched
  filings + market snapshots so re-runs are instant and auditable.
- **Peer auto-discovery from KAP sector codes** — complement the existing LLM web-search peer
  discovery with KAP's own sector classification.

---

## Sources

- [KAP — Public Disclosure Platform (MKK)](https://www.mkk.com.tr/en/corporate-governance-services/kap-public-disclosure-platform) · [kap.org.tr](https://www.kap.org.tr/en) · [Turkey demonstrates XBRL data access](https://www.xbrl.org/news/7343/)
- [kap-client (PyPI)](https://pypi.org/project/kap-client/) · [pykap (GitHub)](https://github.com/cemsinano/pykap) · [kap-tr-sdk (GitHub)](https://github.com/enciyo/kap-tr-sdk) · [kap-notifier (GitHub)](https://github.com/cahitihac/kap-notifier)
- [Fintables (Crunchbase)](https://www.crunchbase.com/organization/fintables) · [borsa-istanbul-temettu-api — Fintables scraper (GitHub)](https://github.com/barangokcekli/borsa-istanbul-temettu-api)
- [isyatirimhisse (GitHub)](https://github.com/urazakgul/isyatirimhisse) · [borsapy (GitHub)](https://github.com/saidsurucu/borsapy) · [İş Yatırım — Financial Reports](https://www.isyatirim.com.tr/en-us/who-we-are/investor-relations/pages/financial-reports.aspx)
- [TCMB EVDS](https://evds3.tcmb.gov.tr) · [SEC EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
