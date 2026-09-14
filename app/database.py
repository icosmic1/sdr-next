from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from .config import get_settings

url = get_settings().database_url

# Render hands out "postgres://", which SQLAlchemy 2.x no longer accepts.
# Normalise it and pin the psycopg 3 driver.
if url.startswith("postgres://"):
    url = url.replace("postgres://", "postgresql+psycopg://", 1)
elif url.startswith("postgresql://"):
    url = url.replace("postgresql://", "postgresql+psycopg://", 1)

is_sqlite = url.startswith("sqlite")

if is_sqlite:
    Path("data").mkdir(exist_ok=True)
    engine = create_engine(url, connect_args={"check_same_thread": False})
else:
    # Free-tier Postgres drops idle connections; pre_ping avoids a 500 on the
    # first request after the service has been idle.
    engine = create_engine(url, pool_pre_ping=True, pool_recycle=300, pool_size=5, max_overflow=5)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

class Base(DeclarativeBase):
    pass

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
