from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
import sys

import yaml
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT_DIR))

from app.db.base import Base
import app.models  # noqa: F401
from app.models.document import Document
from app.models.keyword import Keyword
from app.models.regulator import Regulator
from app.models.scraping_run import ScrapingRun


CONFIG_DIR = ROOT_DIR / "app" / "config"
DEMO_DB_PATH = ROOT_DIR / "data" / "demo_observatorio.db"


DEMO_DOCUMENTS = [
    {
        "regulator": "itu",
        "title": "ITU report on licence-exempt spectrum for wireless innovation",
        "summary": "Demo record about licence-exempt spectrum and wireless policy.",
        "url": "https://www.itu.int/demo/licence-exempt-spectrum",
        "keyword": "licence-exempt",
        "doc_type": "report",
    },
    {
        "regulator": "rsm",
        "title": "General User Licences and unlicensed spectrum overview",
        "summary": "Demo record for New Zealand general user licences and unlicensed spectrum.",
        "url": "https://www.rsm.govt.nz/demo/general-user-licences-unlicensed-spectrum",
        "keyword": "unlicensed spectrum",
        "doc_type": "publication",
    },
    {
        "regulator": "acma",
        "title": "Spectrum planning and licence-exempt devices",
        "summary": "Demo ACMA item mentioning licence-exempt wireless devices.",
        "url": "https://www.acma.gov.au/demo/licence-exempt-devices",
        "keyword": "licence-exempt",
        "doc_type": "web",
    },
    {
        "regulator": "fcc",
        "title": "Unlicensed spectrum policy update",
        "summary": "Demo FCC item about unlicensed spectrum and broadband access.",
        "url": "https://www.fcc.gov/demo/unlicensed-spectrum-policy",
        "keyword": "unlicensed spectrum",
        "doc_type": "news",
    },
    {
        "regulator": "imda",
        "title": "Licence-exempt equipment framework",
        "summary": "Demo IMDA item for licence-exempt radio equipment.",
        "url": "https://www.imda.gov.sg/demo/licence-exempt-equipment",
        "keyword": "licence-exempt",
        "doc_type": "web",
    },
    {
        "regulator": "arcep",
        "title": "IoT and unlicensed spectrum regulation",
        "summary": "Demo ARCEP item validated for unlicensed spectrum.",
        "url": "https://en.arcep.fr/demo/iot-unlicensed-spectrum",
        "keyword": "unlicensed spectrum",
        "doc_type": "news",
    },
    {
        "regulator": "comreg",
        "title": "Short range devices and licence-exempt use",
        "summary": "Demo ComReg item about licence-exempt use.",
        "url": "https://www.comreg.ie/demo/licence-exempt-use",
        "keyword": "licence-exempt",
        "doc_type": "publication",
    },
    {
        "regulator": "rdi_nl",
        "title": "Licence-exempt spectrum monitoring",
        "summary": "Demo RDI item about licence-exempt spectrum monitoring.",
        "url": "https://www.rdi.nl/demo/licence-exempt-spectrum",
        "keyword": "licence-exempt",
        "doc_type": "web",
    },
]


def load_yaml(name: str) -> dict:
    with (CONFIG_DIR / name).open("r", encoding="utf-8") as file:
        return yaml.safe_load(file) or {}


def recreate_database() -> sessionmaker:
    DEMO_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if DEMO_DB_PATH.exists():
        DEMO_DB_PATH.unlink()

    engine = create_engine(f"sqlite:///{DEMO_DB_PATH}", future=True)
    Base.metadata.create_all(bind=engine)
    return sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        future=True,
        expire_on_commit=False,
    )


def seed_regulators(session) -> dict[str, Regulator]:
    data = load_yaml("regulators.yaml")
    regulators: dict[str, Regulator] = {}
    for item in data.get("regulators", []):
        regulator = Regulator(
            name=item["name"],
            short_name=item["short_name"],
            country=item.get("country"),
            region=item.get("region"),
            url_base=item.get("url_base"),
            url_news=item.get("url_news"),
            url_search=item.get("url_search"),
            language=item.get("language"),
            priority=item.get("priority", 3),
            is_active=item.get("is_active", True),
        )
        session.add(regulator)
        regulators[regulator.short_name] = regulator
    session.flush()
    return regulators


def seed_keywords(session) -> None:
    data = load_yaml("keywords.yaml")
    for item in data.get("keywords", []):
        session.add(
            Keyword(
                keyword_original=item["keyword_original"],
                keyword_en=item.get("keyword_en"),
                keyword_es=item.get("keyword_es"),
                keyword_pt=item.get("keyword_pt"),
                keyword_ko=item.get("keyword_ko"),
                keyword_ar=item.get("keyword_ar"),
                is_active=item.get("is_active", True),
            )
        )


def seed_documents(session, regulators: dict[str, Regulator]) -> None:
    run = ScrapingRun(
        run_date=datetime.now(UTC).date(),
        keywords_used='["unlicensed spectrum", "licence-exempt"]',
        total_sites=len([item for item in regulators.values() if item.is_active]),
        total_found=len(DEMO_DOCUMENTS),
        total_saved=len(DEMO_DOCUMENTS),
        status="completed",
        duration_seconds=12.5,
        notes="Demo database generated locally. Not real scraping output.",
    )
    session.add(run)
    session.flush()

    now = datetime.now(UTC).replace(tzinfo=None)
    for index, item in enumerate(DEMO_DOCUMENTS):
        regulator = regulators.get(item["regulator"])
        if regulator is None:
            continue
        session.add(
            Document(
                regulator_id=regulator.id,
                title=item["title"],
                summary=item["summary"],
                url=item["url"],
                content_excerpt=item["summary"],
                language=regulator.language,
                doc_type=item["doc_type"],
                extraction_date=now - timedelta(days=index % 4),
                keyword_matched=item["keyword"],
                scraping_run_id=run.id,
                has_attachment=False,
                is_duplicate=False,
                status="demo",
            )
        )


def main() -> None:
    Session = recreate_database()
    with Session() as session:
        regulators = seed_regulators(session)
        seed_keywords(session)
        seed_documents(session, regulators)
        active_count = sum(1 for regulator in regulators.values() if regulator.is_active)
        session.commit()

    print(f"Base demo creada: {DEMO_DB_PATH}")
    print(f"Reguladores activos incluidos: {active_count}")
    print(f"Documentos demo incluidos: {len(DEMO_DOCUMENTS)}")
    print("Esta base es solo para demostracion; no contiene credenciales ni datos locales reales.")


if __name__ == "__main__":
    main()
