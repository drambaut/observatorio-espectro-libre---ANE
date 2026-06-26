from pathlib import Path

from dotenv import load_dotenv
import os


BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"

load_dotenv(BASE_DIR / ".env")

DATABASE_PATH = os.getenv("DATABASE_PATH")
if DATABASE_PATH and not os.getenv("DATABASE_URL"):
    DATABASE_URL = f"sqlite:///{DATABASE_PATH}"
else:
    DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///data/observatorio_ane.db")


def resolve_sqlite_path(database_url: str = DATABASE_URL) -> Path | None:
    """Return the local SQLite path for file-backed SQLite URLs."""
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        return None

    raw_path = database_url.removeprefix(prefix)
    db_path = Path(raw_path)
    if not db_path.is_absolute():
        db_path = BASE_DIR / db_path
    return db_path
