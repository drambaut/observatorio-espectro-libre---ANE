from pathlib import Path
import sys

from sqlalchemy import delete, func, select

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT_DIR))

from app.db.session import SessionLocal
from app.models.document import Document, DocumentTopic
from app.models.scraping_run import ScrapingRun


TABLES = (
    ("document_topics", DocumentTopic),
    ("documents", Document),
    ("scraping_runs", ScrapingRun),
)


def table_counts(session) -> dict[str, int]:
    return {
        table_name: session.scalar(select(func.count()).select_from(model)) or 0
        for table_name, model in TABLES
    }


def print_counts(title: str, counts: dict[str, int]) -> None:
    print(title)
    for table_name, count in counts.items():
        print(f"- {table_name}: {count}")


def main() -> None:
    with SessionLocal() as session:
        print_counts("Conteos actuales:", table_counts(session))
        confirmation = input('Escribe exactamente "RESET" para borrar resultados: ')

        if confirmation != "RESET":
            print("Cancelado. No se borro ningun dato.")
            return

        for _table_name, model in TABLES:
            session.execute(delete(model))
        session.commit()

        print_counts("Conteos finales:", table_counts(session))


if __name__ == "__main__":
    main()
