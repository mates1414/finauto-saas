import datetime
import uuid
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)

    jobs = relationship("Job", back_populates="user", cascade="all, delete-orphan")
    snapshots = relationship("Snapshot", back_populates="user", cascade="all, delete-orphan")


class Job(Base):
    __tablename__ = "jobs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    type = Column(String, nullable=False)  # "extract", "report", "build"
    status = Column(String, default="pending", nullable=False)  # "pending", "running", "completed", "failed"
    ticker = Column(String, nullable=True)  # target ticker context for the worker
    error = Column(Text, nullable=True)
    result_json = Column(Text, nullable=True)  # Stores CompanyFinancials or StrategicReport JSON
    
    # Store local or remote file paths associated with the job (e.g. uploaded pdfs or xlsx, or output xlsx)
    input_file_keys = Column(Text, nullable=True)  # Comma-separated or JSON list of file keys in storage
    output_file_key = Column(Text, nullable=True)  # Key of generated workbook in storage

    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="jobs")


class Snapshot(Base):
    __tablename__ = "snapshots"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    ticker = Column(String, index=True, nullable=False)
    name = Column(String, nullable=True)
    financials_json = Column(Text, nullable=True)  # CompanyFinancials JSON
    market_json = Column(Text, nullable=True)      # MarketData JSON
    peers_json = Column(Text, nullable=True)       # list of peer tickers JSON
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="snapshots")
