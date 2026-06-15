import datetime
import uuid
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)

    jobs = relationship("Job", back_populates="user", cascade="all, delete-orphan")
    snapshots = relationship(
        "Snapshot", back_populates="user", cascade="all, delete-orphan"
    )


class Job(Base):
    __tablename__ = "jobs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    type = Column(String, nullable=False)  # "extract", "report", "build"
    status = Column(
        String, default="pending", nullable=False
    )  # "pending", "running", "completed", "failed"
    ticker = Column(String, nullable=True)  # target ticker context for the worker
    error = Column(Text, nullable=True)
    result_json = Column(
        Text, nullable=True
    )  # Stores CompanyFinancials or StrategicReport JSON

    # Store local or remote file paths associated with the job (e.g. uploaded pdfs or xlsx, or output xlsx)
    input_file_keys = Column(
        Text, nullable=True
    )  # Comma-separated or JSON list of file keys in storage
    output_file_key = Column(
        Text, nullable=True
    )  # Key of generated workbook in storage

    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow,
        nullable=False,
    )

    user = relationship("User", back_populates="jobs")


class Snapshot(Base):
    __tablename__ = "snapshots"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    ticker = Column(String, index=True, nullable=False)
    name = Column(String, nullable=True)
    financials_json = Column(Text, nullable=True)  # CompanyFinancials JSON
    market_json = Column(Text, nullable=True)  # MarketData JSON
    peers_json = Column(Text, nullable=True)  # list of peer tickers JSON
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="snapshots")


class CachedFinancials(Base):
    """Global, shared cache of extracted financials, one row per (ticker, fiscal year).

    A public company's statements are identical for every user, so this store has no
    ``user_id`` — any user's extraction populates it and any user can reuse it ("Use
    previous data"). Storing one ``FiscalYearData`` per row lets the cache accumulate
    year coverage across overlapping filings and lets the UI list/select individual years.
    """

    __tablename__ = "cached_financials"

    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String, index=True, nullable=False)
    fiscal_year = Column(Integer, nullable=False)
    source = Column(
        String, nullable=True
    )  # provider:model, e.g. "claude:claude-opus-..."
    name = Column(String, nullable=True)
    currency = Column(String, nullable=True)  # carried for faithful reassembly
    units = Column(String, nullable=True)  # "units" | "thousands" | "millions"
    sector_hint = Column(String, nullable=True)
    period_json = Column(Text, nullable=False)  # one FiscalYearData as JSON
    updated_at = Column(
        DateTime,
        default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow,
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("ticker", "fiscal_year", name="uq_cached_fin_ticker_year"),
    )
