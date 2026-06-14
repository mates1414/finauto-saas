# FinAuto SaaS — API Service

This is the FastAPI backend service for the FinAuto SaaS platform. It handles user authentication, PDF financial data extraction, automated peer discovery, valuation Excel workbook generation/download, and strategic report generation with real-time SSE streaming.

## Tech Stack
- **Web Framework**: FastAPI
- **Database**: PostgreSQL / SQLite (via SQLAlchemy 2.0 ORM)
- **Task Queue**: Redis + arq (with in-memory fallback for local dev/testing)
- **File Storage**: Amazon S3 / MinIO (with local disk fallback)

## Directory Structure
```
finauto-saas/api/
├── pyproject.toml              # Project configuration and dependency declarations
├── src/
│   └── finauto_api/
│       ├── __init__.py
│       ├── main.py             # FastAPI entry point
│       ├── config.py           # Configuration & environment settings
│       ├── models.py           # SQLAlchemy database models (User, Job, Snapshot)
│       ├── deps.py             # Dependency injections (database, auth, storage, queue)
│       ├── pubsub.py           # Pub/Sub client for token streaming
│       ├── jobs/
│       │   ├── __init__.py
│       │   ├── queue.py        # Pluggable Task Queue (arq / In-Memory)
│       │   └── tasks.py        # Background jobs (PDF extraction & strategic report)
│       └── routers/
│           ├── __init__.py
│           ├── auth.py         # User registration and authentication (JWT)
│           ├── extract.py      # PDF extraction endpoints
│           ├── peers.py        # Peer discovery endpoints
│           ├── workbook.py     # Spreadsheet building and download endpoints
│           └── report.py       # Strategic report upload and SSE streaming endpoints
└── tests/                      # Integration and unit tests
```

## Getting Started

### 1. Installation
Initialize the virtual environment and install dependencies (including the `finauto` library in editable mode):
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .[dev] -e ..\..\finauto[llm,report,dev]
```

### 2. Configuration
Create a `.env` file in this directory and populate the required settings:
```ini
# Database (SQLite default)
DATABASE_URL=sqlite:///./finauto_saas.db

# Queue Settings ("in_memory" or "arq")
QUEUE_PROVIDER=in_memory
REDIS_URL=redis://localhost:6379

# Storage Provider ("local" or "s3")
STORAGE_PROVIDER=local
STORAGE_LOCAL_PATH=./storage_data

# LLM Keys (falls back to FINAUTO_ prefix if not set)
GEMINI_API_KEY=your_key_here
ANTHROPIC_API_KEY=your_key_here
```

### 3. Running the Server
Run the local development server using Uvicorn:
```powershell
uvicorn finauto_api.main:app --reload
```
You can view the interactive Swagger API documentation at [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs).

### 4. Running the Tests
To run the automated test suite:
```powershell
pytest
```
The test suite utilizes an in-memory SQLite database, in-memory task queues, and mocked LLM/Yahoo Finance edge layers, requiring no running external servers (Redis/Postgres) or live API keys.
