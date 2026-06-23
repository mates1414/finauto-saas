import asyncio
import json
import os
import tempfile
import traceback
from pathlib import Path
from typing import List

from sqlalchemy.orm import Session

from ..config import settings
from .. import deps
from ..deps import get_storage_dep
from ..models import CachedFinancials, Job, Snapshot
from ..pubsub import pubsub

# Import finauto libraries
from finauto.config import get_settings as get_finauto_settings
from finauto.ingestion.base import get_extractor
from finauto.schemas import (
    CompanyFinancials,
    FiscalYearData,
    MarketData,
    _merge_periods,
)
from finauto.engine.readback import recalc, read_inputs
from finauto.report.generator import build_context, generate, ungrounded_figures


class StreamingReportWriter:
    """Custom ReportWriter conforming to finauto protocol that publishes tokens to Pub/Sub."""

    def __init__(self, finauto_settings, job_id):
        self.settings = finauto_settings
        self.job_id = job_id
        self.model = ""

    def complete(self, system: str, user: str, *, stream: bool = True) -> str:
        provider, model = self.settings.stage("report")
        self.model = model
        tokens = []

        # Get or create an event loop to publish to pubsub
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        if provider == "claude":
            import anthropic

            client = anthropic.Anthropic()
            kwargs = dict(
                model=model,
                max_tokens=8000,
                system=system,
                thinking={"type": "adaptive"},
                messages=[{"role": "user", "content": user}],
            )
            if stream:
                with client.messages.stream(**kwargs) as s:
                    for text in s.text_stream:
                        tokens.append(text)
                        if loop.is_running():
                            asyncio.run_coroutine_threadsafe(
                                pubsub.publish(self.job_id, text), loop
                            )
                        else:
                            loop.run_until_complete(pubsub.publish(self.job_id, text))
            else:
                msg = client.messages.create(**kwargs)
                text = "".join(b.text for b in msg.content if b.type == "text")
                tokens.append(text)
                if loop.is_running():
                    asyncio.run_coroutine_threadsafe(
                        pubsub.publish(self.job_id, text), loop
                    )
                else:
                    loop.run_until_complete(pubsub.publish(self.job_id, text))
            return "".join(tokens)

        elif provider == "gemini":
            from google import genai
            from google.genai import types

            client = genai.Client()
            config = types.GenerateContentConfig(system_instruction=system)
            if stream:
                chunks = client.models.generate_content_stream(
                    model=model, contents=user, config=config
                )
                for chunk in chunks:
                    text = chunk.text or ""
                    tokens.append(text)
                    if loop.is_running():
                        asyncio.run_coroutine_threadsafe(
                            pubsub.publish(self.job_id, text), loop
                        )
                    else:
                        loop.run_until_complete(pubsub.publish(self.job_id, text))
            else:
                resp = client.models.generate_content(
                    model=model, contents=user, config=config
                )
                text = resp.text or ""
                tokens.append(text)
                if loop.is_running():
                    asyncio.run_coroutine_threadsafe(
                        pubsub.publish(self.job_id, text), loop
                    )
                else:
                    loop.run_until_complete(pubsub.publish(self.job_id, text))
            return "".join(tokens)

        else:
            raise ValueError(f"unknown report provider: {provider}")


def _upsert_cached_financials(db: Session, financials: CompanyFinancials) -> None:
    """Write each extracted fiscal year into the global, shared CachedFinancials store.

    One row per (ticker, year). On a year already present, merge to *fill blanks* via
    finauto's ``_merge_periods`` (existing non-null values win, the new extraction only
    fills gaps) — this never overwrites good data with blanks or fabricates values.
    """
    for period in financials.sorted_periods():
        row = (
            db.query(CachedFinancials)
            .filter(
                CachedFinancials.ticker == financials.ticker,
                CachedFinancials.fiscal_year == period.year,
            )
            .first()
        )
        if row is None:
            db.add(
                CachedFinancials(
                    ticker=financials.ticker,
                    fiscal_year=period.year,
                    source=financials.source,
                    name=financials.name,
                    currency=financials.currency,
                    units=financials.units,
                    sector_hint=financials.sector_hint,
                    period_json=period.model_dump_json(),
                )
            )
        else:
            existing = FiscalYearData.model_validate_json(row.period_json)
            row.period_json = _merge_periods(existing, period).model_dump_json()
            row.source = financials.source
            row.name = financials.name
            row.currency = financials.currency
            row.units = financials.units
            row.sector_hint = financials.sector_hint
    db.commit()


async def run_extraction_task(job_id: str) -> None:
    """PDF extraction task: fetches PDFs, extracts financials, saves results."""
    db: Session = deps.SessionLocal()
    storage = get_storage_dep()
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        db.close()
        return

    job.status = "running"
    db.commit()

    temp_dir = tempfile.TemporaryDirectory()
    try:
        # 1. Retrieve PDF files from storage and save them to temporary files
        pdf_keys = [k.strip() for k in job.input_file_keys.split(",") if k.strip()]
        temp_paths: List[Path] = []
        for i, key in enumerate(pdf_keys):
            content = storage.get_file(key)
            temp_path = Path(temp_dir.name) / f"doc_{i}.pdf"
            temp_path.write_bytes(content)
            temp_paths.append(temp_path)

        # 2. Extract financials using finauto
        finauto_settings = get_finauto_settings()

        # Override settings with specific values if provided in env
        if settings.gemini_api_key:
            os.environ["GEMINI_API_KEY"] = settings.gemini_api_key
        if settings.anthropic_api_key:
            os.environ["ANTHROPIC_API_KEY"] = settings.anthropic_api_key

        # The target ticker is carried on the job's dedicated `ticker` column.
        ticker = job.ticker or "UNKNOWN.IS"

        extractor = get_extractor(finauto_settings)
        financials = extractor.extract(temp_paths, ticker)
        financials = financials.with_deduped_periods()

        # 3. Save result to DB and update job status
        result_json = financials.model_dump_json(indent=2)
        job.result_json = result_json
        job.status = "completed"
        db.commit()

        # 4. Update/Create Snapshot
        snapshot = (
            db.query(Snapshot)
            .filter(Snapshot.user_id == job.user_id, Snapshot.ticker == ticker)
            .first()
        )

        if not snapshot:
            snapshot = Snapshot(
                user_id=job.user_id,
                ticker=ticker,
                name=financials.name,
                financials_json=result_json,
            )
            db.add(snapshot)
        else:
            snapshot.name = financials.name
            snapshot.financials_json = result_json
        db.commit()

        # 5. Populate the global "previous data" cache (best-effort: a cache-write
        # failure must never fail an otherwise-successful extraction).
        if not job.is_private:
            try:
                _upsert_cached_financials(db, financials)
            except Exception:
                db.rollback()
                traceback.print_exc()

    except Exception as e:
        job.status = "failed"
        job.error = f"Extraction failed: {str(e)}\n{traceback.format_exc()}"
        db.commit()
    finally:
        temp_dir.cleanup()
        db.close()


async def run_report_task(job_id: str) -> None:
    """Report task: recalculates xlsx, reads inputs, diffs, generates report with streaming."""
    db: Session = deps.SessionLocal()
    storage = get_storage_dep()
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        db.close()
        return

    job.status = "running"
    db.commit()

    temp_dir = tempfile.TemporaryDirectory()
    try:
        # Retrieve workbook file from storage
        xlsx_key = job.input_file_keys.strip()
        xlsx_content = storage.get_file(xlsx_key)
        temp_xlsx = Path(temp_dir.name) / "edited.xlsx"
        temp_xlsx.write_bytes(xlsx_content)

        # 1. Recalculate formula values
        recalced = recalc(temp_xlsx)

        # The target ticker is carried on the job's dedicated `ticker` column.
        ticker = job.ticker or ""

        # 2. Find original snapshot for the user to generate diffs and read peer info
        snapshot = (
            db.query(Snapshot)
            .filter(Snapshot.user_id == job.user_id, Snapshot.ticker == ticker)
            .first()
        )

        original_fin = None
        market_data = None
        name = None
        if snapshot:
            name = snapshot.name
            if snapshot.financials_json:
                original_fin = CompanyFinancials.model_validate_json(
                    snapshot.financials_json
                )
            if snapshot.market_json:
                market_data = MarketData.model_validate_json(snapshot.market_json)

        # 3. Read back inputs and computed outputs
        fin_edited, _asm, computed = read_inputs(recalced, ticker=ticker, name=name)

        # 4. Build grounded report context
        ctx = build_context(
            fin_edited, computed, original=original_fin, market=market_data
        )

        # 5. Generate report narrative using our Custom Streaming Writer
        finauto_settings = get_finauto_settings()
        if settings.gemini_api_key:
            os.environ["GEMINI_API_KEY"] = settings.gemini_api_key
        if settings.anthropic_api_key:
            os.environ["ANTHROPIC_API_KEY"] = settings.anthropic_api_key

        writer = StreamingReportWriter(finauto_settings, job_id)

        # This will call our writer.complete which publishes tokens to PubSub
        rpt = generate(ctx, finauto_settings, writer=writer)

        # 6. Check for ungrounded figures (invariant #8)
        ungrounded = ungrounded_figures(rpt.markdown, ctx)

        # 7. Update Job DB record
        job.result_json = rpt.model_dump_json(indent=2)
        job.status = "completed"
        if ungrounded:
            # Save warnings in the error field for the client to read
            job.error = json.dumps(
                {"warnings": [f"Ungrounded figure: {num}" for num in ungrounded]}
            )
        db.commit()

    except Exception as e:
        job.status = "failed"
        job.error = f"Report generation failed: {str(e)}\n{traceback.format_exc()}"
        db.commit()
    finally:
        # Publish final DONE token to close the client SSE stream
        await pubsub.publish(job_id, "[DONE]")
        temp_dir.cleanup()
        db.close()


async def run_research_task(job_id: str) -> None:
    """Research task: fetches target company & peer info, prompts LLM for deep research, streams tokens."""
    db: Session = deps.SessionLocal()
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        db.close()
        return

    job.status = "running"
    db.commit()

    try:
        # Load snapshot & financials
        ticker = job.ticker or "UNKNOWN.IS"
        snapshot = (
            db.query(Snapshot)
            .filter(Snapshot.user_id == job.user_id, Snapshot.ticker == ticker)
            .first()
        )

        financials_data = ""
        peers_list = []
        if snapshot:
            if snapshot.financials_json:
                try:
                    cf = CompanyFinancials.model_validate_json(snapshot.financials_json)
                    financials_data += f"Target Company: {cf.name or ticker}\n"
                    financials_data += f"Currency: {cf.currency}\n"
                    financials_data += f"Historical Financials:\n"
                    for period in cf.sorted_periods():
                        is_ = period.income_statement
                        bs = period.balance_sheet
                        cf_ = period.cash_flow
                        financials_data += f"- Year {period.year}:\n"
                        financials_data += f"  - Revenue: {is_.revenue}\n"
                        financials_data += f"  - EBITDA: {is_.ebitda}\n"
                        financials_data += f"  - Net Income: {is_.net_income}\n"
                        financials_data += f"  - Cash: {bs.cash_and_equivalents}\n"
                        financials_data += f"  - Total Assets: {bs.total_assets}\n"
                        financials_data += f"  - Total Liabilities: {bs.total_liabilities}\n"
                        financials_data += f"  - Capex: {cf_.capex}\n"
                except Exception as e:
                    financials_data += f"Could not parse financials: {str(e)}\n"
            if snapshot.peers_json:
                try:
                    peers_list = json.loads(snapshot.peers_json)
                except Exception:
                    pass

        # Fetch yfinance details
        import yfinance as yf
        ticker_obj = yf.Ticker(ticker)
        info = {}
        try:
            info = ticker_obj.info or {}
        except Exception:
            pass
        comp_name = info.get("longName") or info.get("shortName") or ticker
        comp_desc = info.get("longBusinessSummary") or "No business summary available."
        sector = info.get("sector") or "Unknown Sector"
        industry = info.get("industry") or "Unknown Industry"

        # Let's fetch basic financials for peers to create a benchmarking table
        peer_benchmark_str = ""
        if peers_list:
            peer_benchmark_str += "Financial Benchmarking Table (Target vs. Peers):\n"
            peer_benchmark_str += "| Ticker | Company Name | Revenue Growth (YoY) | EBITDA Margin | ROE | Return on Assets | Debt-to-Equity |\n"
            peer_benchmark_str += "| --- | --- | --- | --- | --- | --- | --- |\n"
            
            # Fetch for target first
            t_growth = info.get("revenueGrowth")
            t_growth_str = f"{t_growth*100:.2f}%" if t_growth is not None else "N/A"
            t_margin = info.get("ebitdaMargins")
            t_margin_str = f"{t_margin*100:.2f}%" if t_margin is not None else "N/A"
            t_roe = info.get("returnOnEquity")
            t_roe_str = f"{t_roe*100:.2f}%" if t_roe is not None else "N/A"
            t_roa = info.get("returnOnAssets")
            t_roa_str = f"{t_roa*100:.2f}%" if t_roa is not None else "N/A"
            t_de = info.get("debtToEquity")
            t_de_str = f"{t_de:.2f}" if t_de is not None else "N/A"
            peer_benchmark_str += f"| {ticker} (Target) | {comp_name} | {t_growth_str} | {t_margin_str} | {t_roe_str} | {t_roa_str} | {t_de_str} |\n"

            for peer in peers_list[:5]: # Cap at 5 peers to avoid rate limiting
                try:
                    p_ticker = yf.Ticker(peer)
                    p_info = p_ticker.info or {}
                    p_name = p_info.get("longName") or p_info.get("shortName") or peer
                    p_growth = p_info.get("revenueGrowth")
                    p_growth_str = f"{p_growth*100:.2f}%" if p_growth is not None else "N/A"
                    p_margin = p_info.get("ebitdaMargins")
                    p_margin_str = f"{p_margin*100:.2f}%" if p_margin is not None else "N/A"
                    p_roe = p_info.get("returnOnEquity")
                    p_roe_str = f"{p_roe*100:.2f}%" if p_roe is not None else "N/A"
                    p_roa = p_info.get("returnOnAssets")
                    p_roa_str = f"{p_roa*100:.2f}%" if p_roa is not None else "N/A"
                    p_de = p_info.get("debtToEquity")
                    p_de_str = f"{p_de:.2f}" if p_de is not None else "N/A"
                    peer_benchmark_str += f"| {peer} | {p_name} | {p_growth_str} | {p_margin_str} | {p_roe_str} | {p_roa_str} | {p_de_str} |\n"
                except Exception:
                    peer_benchmark_str += f"| {peer} | N/A | N/A | N/A | N/A | N/A | N/A |\n"

        # Build research system & user prompt
        system_prompt = (
            "You are an expert equity research analyst. Your task is to write a comprehensive, "
            "institutional-grade Deep Research Report on a target company and its sector. "
            "Your report must be structured using the following sections, formatted in markdown:\n\n"
            "1. **Executive Summary**: Brief overview of the company and key research findings.\n"
            "2. **Industry & Competitive Dynamics (Porter's Five Forces)**: Analyze the sector using Porter's Five Forces framework.\n"
            "3. **Company Financial Health & Capital Efficiency**: Analyze historical financials, ROE, ROIC, and DuPont deconstruct (Profitability, Asset Turnover, Leverage).\n"
            "4. **Valuation Guidance & Excel Input Ranges**: Recommend concrete boundaries for model inputs:\n"
            "   - Terminal Growth Rate (g) bounds (e.g. 2%-3% for USD, 8%-12% for TRY depending on currency/country risk).\n"
            "   - WACC thresholds and Cost of Equity/Debt ranges.\n"
            "   - Mathematical singularity warning (encourage WACC > g and WACC-to-g spread recommendations).\n"
            "5. **Lifecycle Stage & CAPEX Guidance**: Classify the firm's lifecycle stage and recommend long-term CAPEX-to-Sales ratios."
        )

        user_prompt = (
            f"Here is the details for the company:\n"
            f"Ticker: {ticker}\n"
            f"Company Name: {comp_name}\n"
            f"Sector: {sector}\n"
            f"Industry: {industry}\n"
            f"Business Description: {comp_desc}\n\n"
        )
        if financials_data:
            user_prompt += f"Historical Financials Context:\n{financials_data}\n\n"
        if peer_benchmark_str:
            user_prompt += f"Peer Benchmarking Context:\n{peer_benchmark_str}\n\n"

        user_prompt += (
            "Write the Deep Research report based on the above information. Be quantitative, professional, "
            "and precise. For the peer benchmarking table, you may reproduce the benchmarking table in your response. "
            "Format the entire report beautifully in GitHub-style markdown."
        )

        # Call LLM and stream tokens
        finauto_settings = get_finauto_settings()
        
        # Override credentials if needed
        if settings.gemini_api_key:
            os.environ["GEMINI_API_KEY"] = settings.gemini_api_key
        if settings.anthropic_api_key:
            os.environ["ANTHROPIC_API_KEY"] = settings.anthropic_api_key

        writer = StreamingReportWriter(finauto_settings, job_id)
        report_text = writer.complete(system_prompt, user_prompt, stream=True)

        # Save result to DB and mark as completed
        job.result_json = json.dumps({"markdown": report_text})
        job.status = "completed"
        db.commit()

    except Exception as e:
        job.status = "failed"
        job.error = f"Research failed: {str(e)}\n{traceback.format_exc()}"
        db.commit()
    finally:
        await pubsub.publish(job_id, "[DONE]")
        db.close()


# --- arq Worker Exports ---
# These functions will be imported by the arq worker CLI
async def extract_task(ctx, job_id: str):
    await run_extraction_task(job_id)


async def report_task(ctx, job_id: str):
    await run_report_task(job_id)


async def research_task(ctx, job_id: str):
    await run_research_task(job_id)


class WorkerSettings:
    """arq worker configuration settings."""

    functions = [extract_task, report_task, research_task]
    redis_settings = None

    # Enable dynamic setup based on settings
    def __init__(self):
        if settings.redis_url:
            from arq.connections import RedisSettings

            self.redis_settings = RedisSettings.from_dsn(settings.redis_url)
