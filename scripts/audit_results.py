from pathlib import Path
import csv
import re
import sys

import requests
import yaml
from bs4 import BeautifulSoup
from sqlalchemy import select

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT_DIR))

from app.db.session import SessionLocal
from app.models.document import Document
from app.models.regulator import Regulator

REPORT_PATH = ROOT_DIR / "data" / "audit_report.csv"
RELATED_TERMS_PATH = ROOT_DIR / "app" / "config" / "related_terms.yaml"
MAX_DOCUMENTS = 50


def fetch_main_text(url: str) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        )
    }
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    for element in soup(["nav", "header", "footer", "aside", "script", "style", "noscript"]):
        element.decompose()

    content_node = first_content_node(soup)
    return clean_text(content_node.get_text(" ", strip=True) if content_node else soup.get_text(" ", strip=True))


def first_content_node(soup: BeautifulSoup):
    selectors = [
        "main",
        "article",
        "[role='main']",
        ".content",
        ".main-content",
        ".page-content",
        ".body-content",
        ".entry-content",
        "#content",
    ]
    for selector in selectors:
        node = soup.select_one(selector)
        if node and clean_text(node.get_text(" ", strip=True)):
            return node
    return soup.body or soup


def clean_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def count_occurrences(text: str, keyword: str) -> int:
    if not text or not keyword:
        return 0
    pattern = re.compile(re.escape(keyword), re.IGNORECASE)
    return len(pattern.findall(text))


def contains_term(text: str, term: str) -> bool:
    return count_occurrences(text, term) > 0


def load_related_terms() -> dict[str, list[str]]:
    if not RELATED_TERMS_PATH.exists():
        return {}
    with RELATED_TERMS_PATH.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}
    return data.get("related_terms", {})


def related_terms_for(keyword: str, related_terms: dict[str, list[str]]) -> list[str]:
    terms = related_terms.get(keyword, [])
    normalized = []
    for term in [keyword, *terms]:
        if term and term not in normalized:
            normalized.append(term)
    return normalized


def find_related_terms(content: str, terms: list[str]) -> tuple[list[str], int]:
    found_terms = []
    total_occurrences = 0

    for term in terms:
        occurrences = count_occurrences(content, term)
        if occurrences:
            found_terms.append(term)
            total_occurrences += occurrences

    return found_terms, total_occurrences


def matched_terms_in_title(title: str, terms: list[str]) -> list[str]:
    return [term for term in terms if contains_term(title, term)]


def relevance_class(score: int) -> str:
    if score >= 70:
        return "HIGH"
    if score >= 40:
        return "MEDIUM"
    if score >= 15:
        return "LOW"
    return "IRRELEVANT"


def load_documents():
    statement = (
        select(
            Regulator.short_name.label("regulator"),
            Document.title,
            Document.url,
            Document.keyword_matched,
        )
        .join(Regulator, Document.regulator_id == Regulator.id)
        .order_by(Document.id.desc())
        .limit(MAX_DOCUMENTS)
    )
    with SessionLocal() as session:
        return session.execute(statement).mappings().all()


def main() -> None:
    documents = load_documents()
    related_terms = load_related_terms()
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    relevant_count = 0

    for document in documents:
        keyword = document["keyword_matched"] or ""
        try:
            content = fetch_main_text(document["url"])
            main_content_length = len(content)
            occurrences = count_occurrences(content, keyword)
            terms = related_terms_for(keyword, related_terms)
            title_terms = matched_terms_in_title(document["title"], terms)
            found_terms, related_terms_count = find_related_terms(content, terms)
            keyword_found = occurrences > 0
            matched_in_title = bool(title_terms)
            matched_in_body = bool(keyword_found or found_terms)

            title_score = 40 if matched_in_title else 0
            exact_score = 40 if keyword_found else 0
            related_terms_score = min(len(found_terms) * 10, 50)
            body_score = exact_score + related_terms_score
            thematic_score = min(title_score + body_score, 100)
        except Exception as exc:
            main_content_length = 0
            occurrences = 0
            keyword_found = False
            matched_in_title = False
            matched_in_body = False
            title_score = 0
            body_score = 0
            exact_score = 0
            related_terms_score = 0
            found_terms = []
            related_terms_count = 0
            thematic_score = 0
            print(f"Error auditando {document['url']}: {type(exc).__name__}: {exc}")

        classification = relevance_class(thematic_score)
        if classification in {"HIGH", "MEDIUM", "LOW"}:
            relevant_count += 1

        rows.append(
            {
                "regulator": document["regulator"],
                "title": document["title"],
                "url": document["url"],
                "keyword": keyword,
                "keyword_found": "si" if keyword_found else "no",
                "keyword_found_exact": "si" if keyword_found else "no",
                "occurrences": occurrences,
                "title_score": title_score,
                "body_score": body_score,
                "exact_match_score": exact_score,
                "related_terms_found": "; ".join(found_terms),
                "related_terms_count": related_terms_count,
                "related_terms_score": related_terms_score,
                "relevance_score": thematic_score,
                "thematic_relevance_score": thematic_score,
                "matched_in_title": "si" if matched_in_title else "no",
                "matched_in_body": "si" if matched_in_body else "no",
                "main_content_length": main_content_length,
                "classification": classification,
            }
        )

    with REPORT_PATH.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "regulator",
                "title",
                "url",
                "keyword",
                "keyword_found",
                "keyword_found_exact",
                "occurrences",
                "title_score",
                "body_score",
                "exact_match_score",
                "related_terms_found",
                "related_terms_count",
                "related_terms_score",
                "relevance_score",
                "thematic_relevance_score",
                "matched_in_title",
                "matched_in_body",
                "main_content_length",
                "classification",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    audited_count = len(rows)
    possibly_irrelevant = audited_count - relevant_count

    print(f"Documentos auditados: {audited_count}")
    print(f"Documentos relevantes: {relevant_count}")
    print(f"Documentos posiblemente irrelevantes: {possibly_irrelevant}")
    print(f"Reporte generado: {REPORT_PATH}")


if __name__ == "__main__":
    main()
