from __future__ import annotations

import argparse
from pathlib import Path
import sys

from sqlalchemy import bindparam, func, inspect, select, text

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT_DIR))

from app.db.session import SessionLocal, engine
from app.models.document import Document
from app.models.regulator import Regulator


PROTECTED_TABLES = {
    "regulators",
    "keywords",
    "topics",
    "scraping_runs",
}

REGULATOR_DEPENDENT_TABLES = {
    "result_audit",
    "search_logs",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Elimina documentos y dependencias asociados a un regulador."
    )
    parser.add_argument(
        "--regulator",
        required=True,
        help="short_name del regulador a limpiar, por ejemplo: arcep",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Muestra que se borraria sin ejecutar DELETE.",
    )
    mode.add_argument(
        "--confirm",
        action="store_true",
        help="Ejecuta el borrado.",
    )
    return parser.parse_args()


def count_rows_by_document_ids(session, table_name: str, document_ids: list[int]) -> int:
    if not document_ids:
        return 0
    statement = (
        text(f"SELECT COUNT(*) FROM {table_name} WHERE document_id IN :document_ids")
        .bindparams(bindparam("document_ids", expanding=True))
    )
    return session.execute(statement, {"document_ids": document_ids}).scalar_one()


def delete_rows_by_document_ids(session, table_name: str, document_ids: list[int]) -> int:
    if not document_ids:
        return 0
    statement = (
        text(f"DELETE FROM {table_name} WHERE document_id IN :document_ids")
        .bindparams(bindparam("document_ids", expanding=True))
    )
    result = session.execute(statement, {"document_ids": document_ids})
    return result.rowcount or 0


def count_rows_by_regulator_id(session, table_name: str, regulator_id: int) -> int:
    statement = text(f"SELECT COUNT(*) FROM {table_name} WHERE regulator_id = :regulator_id")
    return session.execute(statement, {"regulator_id": regulator_id}).scalar_one()


def delete_rows_by_regulator_id(session, table_name: str, regulator_id: int) -> int:
    statement = text(f"DELETE FROM {table_name} WHERE regulator_id = :regulator_id")
    result = session.execute(statement, {"regulator_id": regulator_id})
    return result.rowcount or 0


def dependent_tables() -> tuple[list[str], list[str]]:
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    by_document_id: list[str] = []
    by_regulator_id: list[str] = []

    for table_name in sorted(table_names):
        if table_name in PROTECTED_TABLES or table_name == "documents":
            continue

        columns = {column["name"] for column in inspector.get_columns(table_name)}
        foreign_keys = inspector.get_foreign_keys(table_name)
        references_documents = any(
            foreign_key.get("referred_table") == "documents"
            for foreign_key in foreign_keys
        )

        if "document_id" in columns or references_documents:
            by_document_id.append(table_name)
            continue

        table_name_lower = table_name.lower()
        looks_like_log_or_audit = (
            table_name in REGULATOR_DEPENDENT_TABLES
            or "audit" in table_name_lower
            or "log" in table_name_lower
            or "result" in table_name_lower
        )
        if "regulator_id" in columns and looks_like_log_or_audit:
            by_regulator_id.append(table_name)

    return by_document_id, by_regulator_id


def main() -> None:
    args = parse_args()
    regulator_short_name = args.regulator.strip().lower()

    with SessionLocal() as session:
        regulator = session.scalar(
            select(Regulator).where(Regulator.short_name == regulator_short_name)
        )
        if regulator is None:
            print(f"No existe regulador con short_name={regulator_short_name!r}.")
            return

        document_ids = list(
            session.scalars(
                select(Document.id).where(Document.regulator_id == regulator.id)
            )
        )
        document_count = len(document_ids)
        print(f"Regulador encontrado: {regulator.short_name} - {regulator.name}")
        print(f"Documentos asociados antes de borrar: {document_count}")

        by_document_id, by_regulator_id = dependent_tables()
        planned_deletes: list[tuple[str, int, str]] = []

        for table_name in by_document_id:
            count = count_rows_by_document_ids(session, table_name, document_ids)
            if count:
                planned_deletes.append((table_name, count, "document_id"))

        for table_name in by_regulator_id:
            count = count_rows_by_regulator_id(session, table_name, regulator.id)
            if count:
                planned_deletes.append((table_name, count, "regulator_id"))

        planned_deletes.append(("documents", document_count, "regulator_id"))

        print("Registros que se eliminarian:")
        for table_name, count, key in planned_deletes:
            print(f"- {table_name}: {count} ({key})")

        if args.dry_run:
            print("Dry-run activo. No se borro ningun dato.")
            return

        deleted_counts: list[tuple[str, int]] = []
        for table_name, _count, key in planned_deletes:
            if table_name == "documents":
                result = session.execute(
                    text("DELETE FROM documents WHERE regulator_id = :regulator_id"),
                    {"regulator_id": regulator.id},
                )
                deleted_counts.append((table_name, result.rowcount or 0))
            elif key == "document_id":
                deleted_counts.append(
                    (table_name, delete_rows_by_document_ids(session, table_name, document_ids))
                )
            elif key == "regulator_id":
                deleted_counts.append(
                    (table_name, delete_rows_by_regulator_id(session, table_name, regulator.id))
                )

        session.commit()

        remaining = session.scalar(
            select(func.count()).select_from(Document).where(Document.regulator_id == regulator.id)
        )
        print("Registros eliminados:")
        for table_name, count in deleted_counts:
            print(f"- {table_name}: {count}")
        print(f"Documentos asociados despues de borrar: {remaining or 0}")
        print("No se borro la tabla regulators ni la fila del regulador.")


if __name__ == "__main__":
    main()
