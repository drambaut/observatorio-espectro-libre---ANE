from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import re
from typing import Iterable
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from app.scrapers.result_quality import is_interface_link, validate_result


@dataclass(slots=True)
class SearchResult:
    title: str
    url: str
    summary: str | None = None
    publish_date: date | None = None
    doc_type: str | None = None
    is_valid_result: bool = True
    rejection_reason: str | None = None


class GenericUrlScraper:
    def __init__(self, timeout_seconds: int = 20, max_results: int = 20, debug: bool = False) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_results = max_results
        self.debug = debug
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (compatible; ObservatorioANE/0.1; "
                    "+https://www.ane.gov.co/)"
                )
            }
        )

    def search(
        self,
        search_url: str,
        url_base: str | None = None,
        selectors: dict | None = None,
        filters: dict | None = None,
    ) -> list[SearchResult]:
        response = self.session.get(search_url, timeout=self.timeout_seconds)
        response.raise_for_status()
        if response.encoding is None or response.encoding.lower() == "iso-8859-1":
            response.encoding = response.apparent_encoding

        soup = BeautifulSoup(response.text, "html.parser")
        base_url = url_base or self._origin_from_url(search_url)
        selectors = selectors or {}
        filters = filters or {}
        results: list[SearchResult] = []
        seen_urls: set[str] = set()

        self._debug_arcep_blocks(soup, selectors, filters)

        for anchor in self._candidate_anchors(soup, selectors, filters, base_url):
            title = self._clean_text(anchor.get_text(" ", strip=True))
            href = anchor.get("href")
            if not title or not href:
                continue

            absolute_url = urljoin(base_url, href)
            if absolute_url in seen_urls:
                continue

            container = self._result_container(anchor)
            summary = self._extract_summary(container, anchor)
            publish_date = self._extract_publish_date(container)
            doc_type = self._detect_doc_type(absolute_url, title)
            is_valid, rejection_reason = self._validate_result(
                title,
                absolute_url,
                search_url,
                filters,
            )

            results.append(
                SearchResult(
                    title=title[:500],
                    url=absolute_url,
                    summary=summary,
                    publish_date=publish_date,
                    doc_type=doc_type,
                    is_valid_result=is_valid,
                    rejection_reason=rejection_reason,
                )
            )
            seen_urls.add(absolute_url)

            if len([result for result in results if result.is_valid_result]) >= self.max_results:
                break

        return results

    def _candidate_anchors(
        self,
        soup: BeautifulSoup,
        selectors: dict | None = None,
        filters: dict | None = None,
        base_url: str | None = None,
    ) -> Iterable:
        selectors = selectors or {}
        filters = filters or {}
        result_container = selectors.get("result_container")
        result_link = selectors.get("result_link") or "a[href]"
        if result_container:
            yielded_configured: set[int] = set()
            containers = soup.select(result_container)
            if self.debug:
                print(f"Requests selector de contenedor usado: {result_container}")
                print(f"Requests nodos encontrados con contenedor: {len(containers)}")
            for container in containers:
                for anchor in container.select(result_link):
                    title = self._clean_text(anchor.get_text(" ", strip=True))
                    href = anchor.get("href")
                    absolute_url = urljoin(base_url or "", href or "")
                    if is_interface_link(title, absolute_url):
                        continue
                    marker = id(anchor)
                    if marker not in yielded_configured:
                        yielded_configured.add(marker)
                        yield anchor
                        break
            if yielded_configured:
                return

        selectors = [
            "main a[href]",
            "article a[href]",
            ".search-results a[href]",
            ".search-results__item a[href]",
            ".search-result a[href]",
            ".results a[href]",
            "li a[href]",
        ]

        yielded: set[int] = set()
        for selector in selectors:
            for anchor in soup.select(selector):
                title = self._clean_text(anchor.get_text(" ", strip=True))
                href = anchor.get("href")
                absolute_url = urljoin(base_url or "", href or "")
                if is_interface_link(title, absolute_url):
                    continue
                marker = id(anchor)
                if marker not in yielded:
                    yielded.add(marker)
                    yield anchor

    def _debug_arcep_blocks(self, soup: BeautifulSoup, selectors: dict, filters: dict) -> None:
        if filters.get("short_name") != "arcep":
            return
        if not self.debug:
            return
        blocks = soup.select(selectors.get("result_container") or "#items-list .search-result")
        for index, block in enumerate(blocks[:5], 1):
            title_node = block.select_one(selectors.get("result_title") or "h2, h3, h4, a")
            link_node = block.select_one(selectors.get("result_link") or "a[href]")
            summary_node = block.select_one(selectors.get("result_summary") or "p")
            title = self._clean_text(title_node.get_text(" ", strip=True)) if title_node else None
            url = link_node.get("href") if link_node else None
            summary = self._clean_text(summary_node.get_text(" ", strip=True)) if summary_node else None
            print(f"ARCEP debug bloque {index} HTML: {str(block)[:1000].replace(chr(10), ' ')}")
            print(f"ARCEP debug bloque {index} titulo detectado: {title}")
            print(f"ARCEP debug bloque {index} URL detectada: {url}")
            print(f"ARCEP debug bloque {index} resumen detectado: {summary}")

    def _validate_result(
        self,
        title: str,
        url: str,
        search_url: str,
        filters: dict,
    ) -> tuple[bool, str | None]:
        is_valid, rejection_reason = validate_result(title, url, search_url)
        if not is_valid:
            return is_valid, rejection_reason
        min_title_length = filters.get("min_title_length")
        if min_title_length and len(title) < int(min_title_length):
            return False, f"titulo menor a min_title_length={min_title_length}"
        allowed_url_contains = filters.get("allowed_url_contains") or []
        if allowed_url_contains and not self._contains_any(url, allowed_url_contains):
            return False, "url no coincide con allowed_url_contains"
        blocked_url_contains = filters.get("blocked_url_contains") or []
        if blocked_url_contains and self._contains_any(url, blocked_url_contains):
            return False, "url coincide con blocked_url_contains"
        blocked_title_contains = filters.get("blocked_title_contains") or []
        if blocked_title_contains and self._contains_any(title, blocked_title_contains):
            return False, "titulo coincide con blocked_title_contains"
        return True, None

    def _contains_any(self, value: str, fragments: list[str]) -> bool:
        lowered = (value or "").lower()
        return any(fragment.lower() in lowered for fragment in fragments)

    def _result_container(self, anchor):
        for parent in anchor.parents:
            if getattr(parent, "name", None) in {"li", "article", "section", "div"}:
                return parent
        return anchor.parent

    def _extract_summary(self, container, anchor) -> str | None:
        if container is None:
            return None

        paragraphs = container.select("p")
        for paragraph in paragraphs:
            text = self._clean_text(paragraph.get_text(" ", strip=True))
            if text and text != self._clean_text(anchor.get_text(" ", strip=True)):
                return text[:1000]

        text = self._clean_text(container.get_text(" ", strip=True))
        title = self._clean_text(anchor.get_text(" ", strip=True))
        if text and title and text != title:
            return text.replace(title, "", 1).strip()[:1000] or None
        return None

    def _extract_publish_date(self, container) -> date | None:
        if container is None:
            return None

        time_tag = container.select_one("time")
        if time_tag:
            value = time_tag.get("datetime") or time_tag.get_text(" ", strip=True)
            parsed = self._parse_date(value)
            if parsed:
                return parsed

        text = self._clean_text(container.get_text(" ", strip=True))
        for pattern in (
            r"\b\d{4}-\d{2}-\d{2}\b",
            r"\b\d{1,2}/\d{1,2}/\d{4}\b",
            r"\b\d{1,2}\s+[A-Za-z]+\s+\d{4}\b",
            r"\b[A-Za-z]+\s+\d{1,2},\s+\d{4}\b",
        ):
            match = re.search(pattern, text)
            if match:
                parsed = self._parse_date(match.group(0))
                if parsed:
                    return parsed
        return None

    def _parse_date(self, value: str | None) -> date | None:
        if not value:
            return None

        cleaned = value.strip()
        cleaned = cleaned.replace("Published:", "").replace("Date:", "").strip()
        formats = (
            "%Y-%m-%d",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%SZ",
            "%d/%m/%Y",
            "%m/%d/%Y",
            "%d %B %Y",
            "%d %b %Y",
            "%B %d, %Y",
            "%b %d, %Y",
        )
        for date_format in formats:
            try:
                return datetime.strptime(cleaned[: len(cleaned)], date_format).date()
            except ValueError:
                continue

        iso_match = re.match(r"(\d{4}-\d{2}-\d{2})", cleaned)
        if iso_match:
            try:
                return datetime.strptime(iso_match.group(1), "%Y-%m-%d").date()
            except ValueError:
                return None
        return None

    def _detect_doc_type(self, url: str, title: str) -> str:
        path = urlparse(url).path.lower()
        if path.endswith(".pdf"):
            return "pdf"
        if path.endswith((".doc", ".docx")):
            return "word"
        if "news" in path or "press" in path:
            return "news"
        if "consult" in path:
            return "consultation"
        if "publication" in path or "document" in path:
            return "publication"
        if "pdf" in title.lower():
            return "pdf"
        return "web"

    def _origin_from_url(self, url: str) -> str:
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}"

    def _clean_text(self, value: str | None) -> str:
        return re.sub(r"\s+", " ", value or "").strip()
