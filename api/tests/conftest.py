import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from finauto_api.main import app
from finauto_api.deps import get_db
from finauto_api.models import Base
from finauto_api.config import settings

# Global settings overrides for test isolation
settings.redis_url = None
settings.queue_provider = "in_memory"
settings.storage_provider = "local"
settings.storage_local_path = "./test_storage_data"

from sqlalchemy.pool import StaticPool
import finauto_api.deps as api_deps

# Use an in-memory SQLite database for testing with StaticPool to share connection
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Global overrides for background tasks and routes using deps.py imports
api_deps.engine = engine
api_deps.SessionLocal = TestingSessionLocal


@pytest.fixture(scope="function")
def db():
    # Create the database tables
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client(db):
    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    # Override storage settings for testing
    settings.storage_provider = "local"
    settings.storage_local_path = "./test_storage_data"
    
    with TestClient(app) as c:
        yield c
        
    app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def auth_headers(client, db):
    """Helper to create a test user and obtain authentication headers."""
    email = "test@example.com"
    password = "password123"
    
    # Register user
    client.post("/api/auth/register", json={"email": email, "password": password})
    
    # Login to get token
    response = client.post(
        "/api/auth/token",
        data={"username": email, "password": password}
    )
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
