from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .config import settings
from .deps import engine
from .models import Base
from .routers import auth, extract, financials, peers, workbook, report, research
from sqlalchemy import text

# Create database tables automatically
Base.metadata.create_all(bind=engine)

# Apply SQLite migration for is_private column on jobs table if needed
with engine.connect() as conn:
    try:
        conn.execute(text("SELECT is_private FROM jobs LIMIT 1"))
    except Exception:
        try:
            conn.execute(text("ALTER TABLE jobs ADD COLUMN is_private BOOLEAN DEFAULT 0"))
            conn.commit()
        except Exception:
            pass

app = FastAPI(
    title=settings.app_name,
    description="Backend API service for FinAuto SaaS",
    version="0.1.0",
    debug=settings.debug,
)

# CORS configurations.
# Note: the wildcard "*" is invalid together with allow_credentials=True (browsers reject it),
# so origins are an explicit, configurable allow-list (see Settings.cors_origins).
cors_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router)
app.include_router(extract.router)
app.include_router(financials.router)
app.include_router(peers.router)
app.include_router(workbook.router)
app.include_router(report.router)
app.include_router(research.router)


@app.get("/")
def read_root():
    return {
        "message": "Welcome to the FinAuto SaaS API. Go to /docs for API documentation."
    }
