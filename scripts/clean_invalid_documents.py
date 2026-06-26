from pathlib import Path
import argparse
import sys

import yaml
from sqlalchemy import select

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT_DIR))

from app.db.session import SessionLocal
from app.models.document import Document
from app.models.regulator import Regulator
from app.scrapers.result_quality import validate_result

REGULATORS_CONFIG_PATH = ROOT_DIR / "app" / "config" / "regulators.yaml"

BLOCKED_TITLE_CONTAINS = (
    "About government",
    "Departments and agencies",
    "Canada.ca",
    "Manage life events",
    "Money and finances",
    "Cloudflare",
    "Skip to",
)

BLOCKED_URL_CONTAINS = (
    "cloudflare.com",
    "/government/",
    "/services/",
    "/finance",
    "/culture",
    "/transport",
    "/policing",
    "#nav",
    "#main",
    "#content",
)

MIN_TITLE_LENGTH = 8

RSM_BLOCKED_URL_CONTAINS = (
    "/search?",
    "keyword=",
    "#nav",
    "#main",
    "#content",
)

RSM_BLOCKED_TITLE_CONTAINS = (
    "kirkpatrick",
    "compliance information about land mobile radio telephones",
    "fees framework",
    "Skip to",
    "Menu",
    "Contact us",
    "Feedback",
)

RSM_ALLOWED_URL_CONTAINS = (
    "/about/news-and-updates",
    "/about/our-work/general-user-licences",
    "/projects-and-auctions",
    "/about/publications/pibs",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Elimina documentos invalidos guardados por scraping.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Muestra los documentos que se eliminarian, sin borrar datos.",
    )
    return parser.parse_args()


def load_regulator_config() -> dict[str, dict]:
    with REGULATORS_CONFIG_PATH.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}
    return {item["short_name"]: item for item in data.get("regulators", [])}


def contains_any(value: str | None, fragments: list[str] | tuple[str, ...]) -> str | None:
    lowered = (value or "").lower()
    for fragment in fragments:
        if fragment.lower() in lowered:
            return fragment
    return None


def invalid_reason(document: Document, regulator_short_name: str, config: dict) -> str | None:
    title = document.title or ""
    url = document.url or ""

    if regulator_short_name == "rsm":
        rsm_reason = rsm_invalid_reason(title, url)
        if rsm_reason:
            return rsm_reason

    if len(title.strip()) < MIN_TITLE_LENGTH:
        return f"titulo menor de {MIN_TITLE_LENGTH} caracteres"

    blocked_title = contains_any(title, BLOCKED_TITLE_CONTAINS)
    if blocked_title:
        return f"titulo bloqueado global: {blocked_title}"

    blocked_url = contains_any(url, BLOCKED_URL_CONTAINS)
    if blocked_url:
        return f"url bloqueada global: {blocked_url}"

    yaml_blocked_title = contains_any(title, config.get("blocked_title_contains") or [])
    if yaml_blocked_title:
        return f"titulo bloqueado por YAML ({regulator_short_name}): {yaml_blocked_title}"

    yaml_blocked_url = contains_any(url, config.get("blocked_url_contains") or [])
    if yaml_blocked_url:
        return f"url bloqueada por YAML ({regulator_short_name}): {yaml_blocked_url}"

    is_valid, reason = validate_result(title, url)
    if not is_valid:
        return reason or "resultado invalido"

    return None


def rsm_invalid_reason(title: str, url: str) -> str | None:
    blocked_url = contains_any(url, RSM_BLOCKED_URL_CONTAINS)
    if blocked_url:
        return f"RSM url bloqueada: {blocked_url}"

    blocked_title = contains_any(title, RSM_BLOCKED_TITLE_CONTAINS)
    if blocked_title:
        return f"RSM titulo bloqueado: {blocked_title}"

    if not contains_any(url, RSM_ALLOWED_URL_CONTAINS):
        return "RSM url fuera de rutas validas"

    return None


def main() -> None:
    args = parse_args()
    regulator_config = load_regulator_config()

    with SessionLocal() as session:
        rows = session.execute(
            select(Document, Regulator.short_name)
            .join(Regulator, Document.regulator_id == Regulator.id)
            .order_by(Document.id.asc())
        ).all()
        invalid_documents: list[tuple[Document, str, str]] = []

        for document, regulator_short_name in rows:
            config = regulator_config.get(regulator_short_name, {})
            reason = invalid_reason(document, regulator_short_name, config)
            if reason:
                invalid_documents.append((document, regulator_short_name, reason))

        print(f"Documentos revisados: {len(rows)}")
        print(f"Documentos a eliminar: {len(invalid_documents)}")

        for document, regulator_short_name, reason in invalid_documents:
            print(
                f"- id={document.id} | regulator={regulator_short_name} | "
                f"{reason} | {document.title} | {document.url}"
            )

        if args.dry_run:
            print("Dry run: no se eliminaron documentos.")
            return

        for document, _regulator_short_name, _reason in invalid_documents:
            session.delete(document)
        session.commit()

    print(f"Documentos eliminados: {len(invalid_documents)}")


if __name__ == "__main__":
    main()
