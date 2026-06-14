from typing import Generator, Optional
import datetime
from jose import jwt, JWTError
import bcrypt
from sqlalchemy.orm import Session
from fastapi import Depends, HTTPException, Query, status
from fastapi.security import OAuth2PasswordBearer
from .config import settings
from .models import User
from .storage import Storage, get_storage
from .jobs.queue import JobQueue, get_job_queue

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# DB engine config
engine_kwargs = {}
if settings.database_url.startswith("sqlite"):
    engine_kwargs["connect_args"] = {"check_same_thread": False}

engine = create_engine(settings.database_url, **engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/auth/token")
# Header is optional here so the token can also arrive as a query param — needed
# for browser-initiated GETs (file downloads via <a>, EventSource/SSE) which
# cannot set an Authorization header.
oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="api/auth/token", auto_error=False)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception:
        return False

def get_password_hash(password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")

def create_access_token(data: dict, expires_delta: Optional[datetime.timedelta] = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.datetime.utcnow() + expires_delta
    else:
        expire = datetime.datetime.utcnow() + datetime.timedelta(minutes=settings.access_token_expire_minutes)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return encoded_jwt

def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_storage_dep() -> Storage:
    return get_storage(settings)

def get_queue_dep() -> JobQueue:
    return get_job_queue(settings)

def _user_from_token(db: Session, token: Optional[str]) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        raise credentials_exception
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.query(User).filter(User.email == email).first()
    if user is None:
        raise credentials_exception
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return user


async def get_current_user(
    db: Session = Depends(get_db),
    token: str = Depends(oauth2_scheme),
) -> User:
    return _user_from_token(db, token)


async def get_current_user_flexible(
    db: Session = Depends(get_db),
    header_token: Optional[str] = Depends(oauth2_scheme_optional),
    token: Optional[str] = Query(None),
) -> User:
    """Accept the bearer token from the Authorization header OR a ``token`` query
    param. Used by GET endpoints the browser hits directly (xlsx download, SSE
    report stream), where custom headers cannot be set."""
    return _user_from_token(db, header_token or token)
