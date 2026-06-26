from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config.settings import DATABASE_URL, resolve_sqlite_path


sqlite_path = resolve_sqlite_path(DATABASE_URL)
if sqlite_path is not None:
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(DATABASE_URL, echo=False, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
