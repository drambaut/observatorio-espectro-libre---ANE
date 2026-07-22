from pathlib import Path
import sys

import yaml
from sqlalchemy import inspect, select, text

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT_DIR))

from app.db.session import SessionLocal, engine
from app.models.keyword import Keyword
from app.models.regulator import Regulator
from app.models.topic import Topic

CONFIG_DIR = ROOT_DIR / "app" / "config"


def ensure_keyword_columns(session) -> None:
    inspector = inspect(engine)
    columns = {column["name"] for column in inspector.get_columns("keywords")}
    if "keyword_ar" not in columns:
        session.execute(text("ALTER TABLE keywords ADD COLUMN keyword_ar VARCHAR(255)"))


def load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file) or {}


def seed_regulators(session) -> dict[str, object]:
    data = load_yaml(CONFIG_DIR / "regulators.yaml")
    yaml_regulators = data.get("regulators", [])
    yaml_short_names: set[str] = set()
    activated_or_updated: list[str] = []
    deactivated_missing: list[str] = []

    for item in yaml_regulators:
        short_name = item["short_name"]
        yaml_short_names.add(short_name)
        regulator = session.scalar(select(Regulator).where(Regulator.short_name == short_name))

        values = {
            "name": item["name"],
            "short_name": short_name,
            "country": item.get("country"),
            "region": item.get("region"),
            "url_base": item.get("url_base"),
            "url_news": item.get("url_news"),
            "url_search": item.get("url_search"),
            "language": item.get("language"),
            "priority": item.get("priority", 3),
            "is_active": item.get("is_active", True),
        }

        if regulator is None:
            session.add(Regulator(**values))
        else:
            for field, value in values.items():
                setattr(regulator, field, value)
        activated_or_updated.append(short_name)

    existing_regulators = session.scalars(select(Regulator)).all()
    for regulator in existing_regulators:
        if regulator.short_name not in yaml_short_names and regulator.is_active:
            regulator.is_active = False
            deactivated_missing.append(regulator.short_name)

    session.flush()
    active_short_names = list(
        session.scalars(
            select(Regulator.short_name)
            .where(Regulator.is_active.is_(True))
            .order_by(Regulator.short_name.asc())
        )
    )

    return {
        "yaml_count": len(yaml_regulators),
        "updated_count": len(activated_or_updated),
        "deactivated_missing": sorted(deactivated_missing),
        "active_short_names": active_short_names,
    }


def seed_keywords(session) -> int:
    ensure_keyword_columns(session)
    data = load_yaml(CONFIG_DIR / "keywords.yaml")
    count = 0
    yaml_keywords: set[str] = set()

    for item in data.get("keywords", []):
        original = item["keyword_original"]
        yaml_keywords.add(original)
        keyword = session.scalar(select(Keyword).where(Keyword.keyword_original == original))

        values = {
            "keyword_original": original,
            "keyword_en": item.get("keyword_en"),
            "keyword_es": item.get("keyword_es"),
            "keyword_pt": item.get("keyword_pt"),
            "keyword_ko": item.get("keyword_ko"),
            "keyword_ar": item.get("keyword_ar"),
            "is_active": item.get("is_active", True),
        }

        if keyword is None:
            session.add(Keyword(**values))
        else:
            for field, value in values.items():
                setattr(keyword, field, value)
        count += 1

    existing_keywords = session.scalars(select(Keyword)).all()
    for keyword in existing_keywords:
        if keyword.keyword_original not in yaml_keywords and keyword.is_active:
            keyword.is_active = False

    return count


def seed_mechanisms(session) -> int:
    data = load_yaml(CONFIG_DIR / "mechanisms.yaml")
    count = 0

    for dimension_item in data.get("dimensions", []):
        dimension_name = dimension_item["name"]
        dimension = session.scalar(select(Topic).where(Topic.name == dimension_name))
        dimension_values = {
            "name": dimension_name,
            "name_en": dimension_item.get("name_en"),
            "description": dimension_item.get("description"),
        }
        if dimension is None:
            dimension = Topic(**dimension_values)
            session.add(dimension)
            session.flush()
        else:
            for field, value in dimension_values.items():
                setattr(dimension, field, value)
        count += 1

        for value_item in dimension_item.get("values", []):
            value_name = value_item["name"]
            topic = session.scalar(select(Topic).where(Topic.name == value_name))
            topic_values = {
                "name": value_name,
                "name_en": value_item.get("name_en"),
                "parent_id": dimension.id,
            }
            if topic is None:
                session.add(Topic(**topic_values))
            else:
                for field, value in topic_values.items():
                    setattr(topic, field, value)
            count += 1

    return count


def main() -> None:
    with SessionLocal() as session:
        regulators_summary = seed_regulators(session)
        keywords_count = seed_keywords(session)
        mechanisms_count = seed_mechanisms(session)
        session.commit()

    print(f"Reguladores encontrados en YAML: {regulators_summary['yaml_count']}")
    print(f"Reguladores activados/actualizados: {regulators_summary['updated_count']}")
    print(
        "Reguladores desactivados porque ya no estan en YAML: "
        f"{len(regulators_summary['deactivated_missing'])}"
    )
    if regulators_summary["deactivated_missing"]:
        print(", ".join(regulators_summary["deactivated_missing"]))
    print(f"Total activos finales en base de datos: {len(regulators_summary['active_short_names'])}")
    print("Activos finales:", ", ".join(regulators_summary["active_short_names"]))
    print(f"Keywords cargadas/actualizadas: {keywords_count}")
    print(f"Topics de mecanismos flexibles cargados/actualizados: {mechanisms_count}")


if __name__ == "__main__":
    main()
