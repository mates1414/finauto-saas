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


# --- arq Worker Exports ---
# These functions will be imported by the arq worker CLI
async def extract_task(ctx, job_id: str):
    await run_extraction_task(job_id)


async def report_task(ctx, job_id: str):
    await run_report_task(job_id)


class WorkerSettings:
    """arq worker configuration settings."""

    functions = [extract_task, report_task]
    redis_settings = None

    # Enable dynamic setup based on settings
    def __init__(self):
        if settings.redis_url:
            from arq.connections import RedisSettings

            self.redis_settings = RedisSettings.from_dsn(settings.redis_url)
