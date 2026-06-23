# Valuation Pipeline Enhancements: Server Fallback, Private PDFs, and PDF Report Downloads

This document details the design and implementation plan to add three key requested features to the FinAuto SaaS platform:
1. **Direct Server-Compiled Excel Fallback** (skip download/upload of the XLSX workbook in Step 4).
2. **Private Ingestion Option** (prevent uploading sensitive PDFs from caching/sharing extracted financials globally in Step 1).
3. **PDF Strategic Report Downloads** (generate downloadable PDF reports at Step 5 complete with valuation method summaries, charts, and disclaimers).

---

## User Review Required

### Database Schema Changes
Adding a column (`is_private`) to the SQLite database is required. To prevent migration friction or database crashes for existing databases, we will add a self-healing column check in the FastAPI initialization script (`main.py`) that alters the database automatically if the column is missing.

### PDF Generation Approach
To capture client-side charts (SVG-based Recharts) and keep dependencies light (no complex OS-level GTK libraries or wkhtmltopdf binaries required on the backend), we propose a **browser-print CSS `@media print` styling approach** coupled with a dedicated UI action button. This creates a clean PDF layout on any OS, preserving styling, text selection, and dynamic graphics.

---

## Open Questions

There are no major open questions, but we will confirm:
1. Should the default weighting for DCF vs Peers EV/EBITDA, EV/Sales, and P/E be dynamically displayed on the new valuation summary table (matching the Excel sheet's defaults)? *Yes, we will read and display these defaults.*

---

## Proposed Changes

### Component 1: Core CLI & Database Schema

#### [MODIFY] [models.py](file:///d:/projects/finance/finauto-saas/api/src/finauto_api/models.py)
* Add `is_private` field to the `Job` database model:
  ```python
  is_private = Column(Boolean, default=False, nullable=True)
  ```

#### [MODIFY] [main.py](file:///d:/projects/finance/finauto-saas/api/src/finauto_api/main.py)
* Add a check during app startup to perform a lightweight SQLite migration for `is_private`.
* Register the new `research.router` (`app.include_router(research.router)`).
  ```python
  from sqlalchemy import text
  with engine.connect() as conn:
      try:
          conn.execute(text("SELECT is_private FROM jobs LIMIT 1"))
      except Exception:
          try:
              conn.execute(text("ALTER TABLE jobs ADD COLUMN is_private BOOLEAN DEFAULT 0"))
              conn.commit()
          except Exception:
              pass
  ```

---

### Component 2: Backend API Endpoints

#### [MODIFY] [extract.py](file:///d:/projects/finance/finauto-saas/api/src/finauto_api/routers/extract.py)
* Accept an optional `is_private: bool = Form(False)` parameter in the `/api/extract` POST endpoint.
* Assign this `is_private` parameter to the created `Job` database record.

#### [MODIFY] [tasks.py](file:///d:/projects/finance/finauto-saas/api/src/finauto_api/jobs/tasks.py)
* Update `run_extraction_task` so that it checks `job.is_private` before calling `_upsert_cached_financials`:
  ```python
  if not job.is_private:
      try:
          _upsert_cached_financials(db, financials)
      except Exception:
          db.rollback()
          traceback.print_exc()
  ```

#### [MODIFY] [report.py](file:///d:/projects/finance/finauto-saas/api/src/finauto_api/routers/report.py)
* Update the `/api/report` POST endpoint to make the `file` upload parameter optional and add a `workbook_job_id: Optional[str] = Form(None)` parameter.
* Check the parameters:
  - If a file is uploaded, save it to storage and use it.
  - If no file is uploaded, verify that `workbook_job_id` points to a completed `"build"` job belonging to the user. Copy its `output_file_key` to use as the `input_file_keys` for the report job.
  - Raise `400 Bad Request` if neither is provided.

#### [NEW] [research.py](file:///d:/projects/finance/finauto-saas/api/src/finauto_api/routers/research.py)
* Implement `/api/research/build` endpoint to trigger a `type="research"` background job.
* Implement `/api/research/{job_id}/stream` to stream live SSE Markdown tokens of company/sector deep research.
* Implement `/api/research/{job_id}` to retrieve completed research results.

#### [MODIFY] [tasks.py](file:///d:/projects/finance/finauto-saas/api/src/finauto_api/jobs/tasks.py)
* Add `run_research_task(job_id)` which:
  - Loads target financials, industry classification, and yfinance descriptions.
  - Prompts the LLM to write a comprehensive sector analysis, macro risk brief, and DCF assumptions guidance (WACC, terminal growth margins).
  - Streams intermediate tokens via PubSub and stores the final result in the database.
* Add `research_task` to the arq worker functions registry.

---

### Component 3: Frontend Wizard UI

#### [MODIFY] [App.tsx](file:///d:/projects/finance/finauto-saas/web/src/App.tsx)
* Expand `stepsList` from 5 to 6 steps, positioning **Deep Research** before spreadsheet generation:
  1. Ingestion
  2. Competitors
  3. Deep Research (New Step)
  4. Spreadsheet (Shifted)
  5. Model Read-back (Shifted)
  6. Strategic Report (Shifted)
* Map step switch cases: render `Step3Research` at step 3, shift Step 3 compiler to step 4, Step 4 uploader to step 5, and Step 5 report to step 6.

#### [MODIFY] [WizardSteps.tsx](file:///d:/projects/finance/finauto-saas/web/src/components/WizardSteps.tsx)

##### Step 1: Ingestion
* Add a checkbox label: `"Keep this data private (do not add financials to global cache)"` under the file uploader.
* Append `is_private` to the FormData payload sent to `/api/extract`.

##### Step 3: Deep Research [NEW COMPONENT]
* Add `Step3Research` component:
  - When entered, triggers `/api/research/build` for the current `ticker`.
  - Establishes SSE stream connection to `/api/research/{jobId}/stream`.
  - Renders live markdown showing industry parameters, macro trends, and guidance for key Excel model inputs (WACC, margins, growth).
  - Provides strategic context to the user *before* they compile and customize the Excel sheet.
  - Renders a button to proceed to Step 4.

##### Step 4: Spreadsheet (Formerly Step 3)
* Retain compilation trigger button and download links. In the future, this generation step will pass the research context parameters to the LLM to output a more accurate default Excel workbook.

##### Step 5: Model Read-back (Formerly Step 4)
* Retain the existing manual file upload functionality. **Yes, users can still upload a revised/edited version** of the Excel model if they choose to do so.
* Add a new section in the UI showing: `"Alternatively, use the server-compiled workbook directly if you don't need to make manual edits."`
* Render a button `"Use Server-Compiled Workbook"` that calls the updated `/api/report` route with `workbook_job_id: jobId` and skips the local file selection requirements. This handles the scenario where the user wants the generated report without making any local modifications.

##### Step 6: Strategic Report (Formerly Step 5)
* Display a **Valuation Summary Table** detailing the valuation ranges, weights, and contribution towards the target price.
* Style a printable layout containing:
  - Header block (Company Name, Ticker, Valuation Date)
  - Recommendations Dashboard (BUY/HOLD/SELL signal badge, upside, target price)
  - Valuation Table (DCF, Peers EV/EBITDA, EV/Sales, P/E ranges and weights)
  - Football Field Chart
  - Grounded AI Narrative Report (the streamed text formatted nicely)
* Add a **"Download PDF Report"** button that invokes `window.print()` and applies `@media print` CSS layout filters to output a clean, formatted report PDF.

#### [MODIFY] [index.css](file:///d:/projects/finance/finauto-saas/web/src/index.css)
* Add `@media print` styles:
  - Hide header navbar, step indicators, buttons, and scrollable containers.
  - Force page breaks before large sections (e.g. before the narrative).
  - Convert dark mode theme colors to light mode print-friendly colors (white background, dark grey text, black table borders) to conserve ink.
  - Structure the page margins (`margin: 15mm 20mm`).

---

## Verification Plan

### Automated Tests
- Run backend unit tests: `cd finauto-saas/api; pytest`
- Run core engine tests: `cd finauto; pytest`
- Add integration test in `tests/` verifying the `/api/report` fallback mechanism when `workbook_job_id` is supplied without a file.
- Add backend test verifying `/api/research/build` and `/api/research/{job_id}/stream` responses.

### Manual Verification
1. **Extraction Privacy**: Upload a PDF with the "Private PDF" toggle checked. Verify that the extracted financials are not queryable via the `/api/financials/{ticker}/available` endpoint.
2. **Deep Research Step**: Complete Step 2 (competitors), verify Step 3 loads, triggers the research background job, streams company/sector trends, and displays competitive benchmarking and Porter's Five Forces.
3. **Spreadsheet Compilation**: Proceed to Step 4, compile the spreadsheet, and download the workbook.
4. **Server-Compiled Fallback**: In Step 5 (read-back), click "Use Server-Compiled Workbook". Verify that the app transitions to Step 6 and successfully streams the final strategic report.
5. **Print PDF**: Generate a report in Step 6, click the "Download PDF Report" button, verify the print dialog shows a clean black-and-white valuation report layout including the Valuation Table, Football Field Chart, and narrative.

---

## Deep Research: Enhancing Equity Report Quality & Financial Implications

To elevate the Step 5 strategic equity report from a basic description to a institutional-grade research memo, we will implement several key analytical methodologies and data-enrichment modifications. These will be added to both the prompt structure and the data context fed to the LLM.

### 1. Context Expansion: Multi-Year Trends & Growth Trajectories
Currently, the LLM only receives the single latest year of financials. This makes it impossible for the model to discuss operational trajectories or financial stability.
* **Methodology**: Modify [prompts.py](file:///d:/projects/finance/finauto/src/finauto/report/prompts.py) to provide a 3-to-5-year table of historical financials (Revenue, EBITDA, Net Income).
* **Implication**: Enables the LLM to calculate and discuss compound annual growth rates (CAGR), margin expansion/contraction trends, and earnings stability over time. This transforms the report from a static snapshot into a dynamic historical analysis, allowing investors to evaluate management's track record in scaling the business and navigating past economic cycles.

### 2. Operational Health: DuPont Analysis & Capital Efficiency
A professional report must explain *how* a company generates returns for its shareholders.
* **Methodology**: Add core capital efficiency metrics to the LLM context, specifically:
  - **Return on Equity (ROE)** and **Return on Invested Capital (ROIC)**.
  - **DuPont Breakdown components**: Net Profit Margin (Profitability), Asset Turnover (Operational Efficiency), and Equity Multiplier (Financial Leverage).
* **Implication**: The LLM can analyze whether the company's return profile is driven by high-margin pricing power, lean asset operations, or aggressive debt leverage. By deconstructing ROE, the report will provide institutional-grade insights into capital allocation efficiency and operational moats, identifying structural competitive advantages.

### 3. Peer Competitiveness: Relative Performance Metrics
The peer set is currently passed as a list of strings, meaning the LLM does not know how the target performs relative to competitors.
* **Methodology**: Feed the peer group's average/median financial metrics (e.g. median Peer EV/EBITDA, median Peer Revenue Growth, and median Peer EBITDA margin) to the LLM.
* **Implication**: Enables the LLM to conduct a competitive benchmarking analysis (e.g. "BIMAS.IS trades at a premium to peers but is justified by its 3% higher EBITDA margin and superior cash conversion"). This grounds the valuation in relative market reality, ensuring the narrative aligns with how the market actually prices competitors.

### 4. Valuation Reconciliation (DCF vs. Multiples Spread)
The target price is a weighted average of DCF and relative multiples. However, these methods often produce widely different prices.
* **Methodology**: Add instructions in `SYSTEM_PROMPT` to analyze the valuation spread:
  - Discuss the divergence between the intrinsic value (DCF) and market value (peer multiples).
  - Highlight key DCF assumptions (WACC, terminal growth rate $g$) and why they cause the intrinsic value to be higher or lower than peer multiples.
* **Implication**: Reconciles the theoretical intrinsic valuation with current market pricing, helping analysts understand if the stock is undervalued intrinsically but depressed by broader market multiples. This bridging of DCF and relative valuation is a hallmark of top-tier equity research, providing actionable buy/sell context to the user.

### 5. Macro Risk Contextualization (Inflation & FX)
For BIST-focused companies, TMS-29/IAS-29 inflation adjustments distort historical growth rates in TRY.
* **Methodology**: Provide the FX conversion rates and mandate a dedicated segment in the prompt that reconciles Turkish inflation-adjusted growth rates against hard-currency performance.
* **Implication**: Prevents the LLM from hallucinating nominal TRY growth rates as real growth, pointing out TMS-29 distortions and providing a sound, hard-currency valuation alternative. Crucial for emerging market equities, this ensures valuation integrity despite hyperinflationary environments.

---

## Deep Research: Enhancing Deep Research (Step 3) Information Quality

To ensure the new **Deep Research Step (Step 3)** provides institutional-grade competitive and sector intelligence rather than generic LLM descriptions, we will incorporate several professional financial methodologies:

### 1. Competitive Benchmarking Table
Instead of just displaying text, Step 4 will present a structured **Financial Peer Benchmarking Table** comparing target operating ratios to peers.
* **Methodology**: Aggregate the data fetched from Yahoo Finance in Step 2:
  - **Revenue Growth Rate (YoY)**
  - **EBITDA Margin**
  - **Leverage (Debt-to-Equity & Net Debt / EBITDA)**
  - **Return on Invested Capital (ROIC)**
* **Implication**: Directly highlights to the user whether the target possesses a competitive cost advantage, higher efficiency, or superior leverage margins relative to the industry. By providing this before Excel generation, the user can adjust their model inputs (like target margins) to reflect realistic industry convergence or sustained premium performance.

### 2. Porter's Five Forces Structural Analysis
The industry narrative must map to a standardized corporate strategy framework.
* **Methodology**: Mandate the research LLM task to analyze the sector using **Michael Porter's Five Forces Framework**:
  - Threat of new entrants & substitute products.
  - Bargaining power of suppliers & buyers.
  - Rivalry intensity among industry competitors.
* **Implication**: Provides structural strategic analysis of the industry's pricing power, input cost threats, and profit potential. This theoretical framework enriches the user's understanding of the sector's long-term viability and barriers to entry, directly influencing their long-term growth ($g$) and WACC assumptions in the subsequent step.

### 3. Valuation Assumption Bounds & Safety Margins
Give the user concrete boundaries for input assumptions before they edit the Excel model.
* **Methodology**: Calculate and display advised ranges for key parameters:
  - **Terminal Growth Rate ($g$) Bounds**: Constrain $g$ recommendations by the currency's long-term GDP growth or target inflation rate (e.g. $2\%-3\%$ for USD, $8\%-12\%$ for TRY).
  - **WACC Thresholds**: Advise WACC ranges based on country risk premiums (CRP) and interest rate environments.
  - **Mathematical Singularity Warning**: Highlight the risk of inputs approaching $WACC \le g$ and outline WACC-to-$g$ spread recommendations.
* **Implication**: Prevents valuation model breakages (e.g. negative DCF prices or `#DIV/0!` errors) by encouraging financially consistent inputs. It also establishes "guardrails" for the user, ensuring the resulting Excel model is robust and conforms to fundamental finance theory before it is generated.

### 4. Life-Cycle Driven CAPEX Guidance
Operating margins and capital expenditures vary significantly by company life stage.
* **Methodology**: Instruct the LLM to identify the company's lifecycle stage (High-Growth, Mature, Cash Cow, or Decline) based on historical growth rates and free cash flow conversion.
* **Implication**: Advises the analyst on appropriate long-term CAPEX-to-Sales ratios and terminal multiples (e.g., high-growth firms require larger CAPEX-to-sales ratios, while mature firms require terminal multiples capped nearer to historical median ranges). This prevents common novice mistakes, such as projecting high terminal growth rates without the corresponding capital reinvestment, ensuring the forecasted Free Cash Flow to Firm (FCFF) is mathematically and logically sound.


