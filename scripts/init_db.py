from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT_DIR))

from app.db.base import Base
from app.db.session import engine
import app.models  # noqa: F401


def main() -> None:
    Base.metadata.create_all(bind=engine)
    print("Base de datos inicializada correctamente.")


if __name__ == "__main__":
    main()
