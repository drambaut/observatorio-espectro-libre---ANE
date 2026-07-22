"""Etiqueta documentos existentes con topics de mecanismos flexibles (app/config/mechanisms.yaml).

Heuristico por coincidencia de texto (title + summary + content_excerpt). No es un
clasificador semantico: si un termino no aparece literalmente en el documento, no se
etiqueta. La mayoria de los documentos scrapeados hoy solo hablan de "uso libre"
(unlicensed / license-exempt), por lo que valores como "Subasta" o "PSO" pueden quedar
sin ningun documento etiquetado hasta que el corpus incluya ese tipo de contenido.

Requiere haber corrido scripts/seed_data.py antes (para que existan los Topics).
Se puede correr varias veces; no duplica etiquetas existentes.
"""

from __future__ import annotations

from pathlib import Path
import sys
import unicodedata

import yaml
from sqlalchemy import select

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT_DIR))

from app.db.session import SessionLocal
from app.models.document import Document, DocumentTopic
from app.models.topic import Topic

CONFIG_DIR = ROOT_DIR / "app" / "config"


def normalize(text: str) -> str:
    text = text.lower()
    text = "".join(
        char for char in unicodedata.normalize("NFD", text) if unicodedata.category(char) != "Mn"
    )
    return text


def load_terms_by_topic_name() -> dict[str, list[str]]:
    with (CONFIG_DIR / "mechanisms.yaml").open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}

    terms_by_topic: dict[str, list[str]] = {}
    for dimension in data.get("dimensions", []):
        for value in dimension.get("values", []):
            terms_by_topic[value["name"]] = [normalize(term) for term in value.get("terms", [])]
    return terms_by_topic


def document_text(document: Document) -> str:
    parts = [document.title, document.summary, document.content_excerpt]
    return normalize(" ".join(part for part in parts if part))


def main() -> None:
    terms_by_topic_name = load_terms_by_topic_name()

    with SessionLocal() as session:
        topics = session.scalars(select(Topic).where(Topic.name.in_(terms_by_topic_name.keys()))).all()
        topic_by_name = {topic.name: topic for topic in topics}

        missing_topics = set(terms_by_topic_name) - set(topic_by_name)
        if missing_topics:
            print("Faltan estos topics en la base de datos, corre scripts/seed_data.py primero:")
            for name in sorted(missing_topics):
                print(f"  - {name}")
            return

        existing_pairs = {
            (document_topic.document_id, document_topic.topic_id)
            for document_topic in session.scalars(select(DocumentTopic)).all()
        }

        documents = session.scalars(select(Document)).all()
        tagged_count = 0
        per_topic_count: dict[str, int] = {name: 0 for name in terms_by_topic_name}

        for document in documents:
            text = document_text(document)
            for topic_name, terms in terms_by_topic_name.items():
                if not terms or not any(term in text for term in terms):
                    continue
                topic = topic_by_name[topic_name]
                if (document.id, topic.id) in existing_pairs:
                    continue
                session.add(DocumentTopic(document_id=document.id, topic_id=topic.id))
                existing_pairs.add((document.id, topic.id))
                tagged_count += 1
                per_topic_count[topic_name] += 1

        session.commit()

    print(f"Documentos revisados: {len(documents)}")
    print(f"Etiquetas nuevas creadas: {tagged_count}")
    for topic_name, count in per_topic_count.items():
        print(f"  - {topic_name}: {count}")


if __name__ == "__main__":
    main()
