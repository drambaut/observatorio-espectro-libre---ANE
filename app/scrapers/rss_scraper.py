from __future__ import annotations

from datetime import date
import re
from time import struct_time
from urllib.parse import urlparse

import feedparser
import requests
from bs4 import BeautifulSoup

from app.scrapers.generic_url_scraper import SearchResult
from app.scrapers.result_quality import validate_result


class RssScraper:
    def __init__(self, timeout_seconds: int = 30, max_results: int = 10) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_results = max_results

    def search(
        self,
        feed_url: str,
        keyword: str,
        related_terms: list[str],
        filters: dict | None = None,
    ) -> list[SearchResult]:
        response = requests.get(feed_url, headers=self._headers(), timeout=self.timeout_seconds)
        response.raise_for_status()

        feed = feedparser.parse(response.content)
        filters = filters or {}
        results: list[SearchResult] = []
        seen_urls: set[str] = set()

        for entry in feed.entries:
            title = self._clean_text(entry.get("title"))
            url = entry.get("link") or entry.get("id")
            summary = self._html_to_text(entry.get("summary") or entry.get("description"))

            if not url or url in seen_urls:
                continue

            is_valid, rejection_reason = self._validate_entry(
                title=title,
                url=url,
                summary=summary,
                keyword=keyword,
                related_terms=related_terms,
                filters=filters,
            )

            results.append(
                SearchResult(
                    title=title[:500] if title else url,
                    url=url,
                    summary=summary,
                    publish_date=self._entry_date(entry),
                    doc_type="rss_item",
                    is_valid_result=is_valid,
                    rejection_reason=rejection_reason,
                )
            )
            seen_urls.add(url)

            if len([result for result in results if result.is_valid_result]) >= self.max_results:
                break

        return results

    def _validate_entry(
        self,
        title: str,
        url: str,
        summary: str | None,
        keyword: str,
        related_terms: list[str],
        filters: dict,
    ) -> tuple[bool, str | None]:
        is_valid, rejection_reason = validate_result(title, url)
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

    def _entry_date(self, entry) -> date | None:
        parsed = entry.get("published_parsed") or entry.get("updated_parsed")
        if isinstance(parsed, struct_time):
            return date(parsed.tm_year, parsed.tm_mon, parsed.tm_mday)
        return None

    def _html_to_text(self, value: str | None) -> str | None:
        if not value:
            return None
        soup = BeautifulSoup(value, "html.parser")
        return self._clean_text(soup.get_text(" ", strip=True)) or None

    def _contains_any(self, value: str, fragments: list[str]) -> bool:
        lowered = (value or "").lower()
        return any(fragment.lower() in lowered for fragment in fragments)

    def _term_found(self, value: str, term: str) -> bool:
        return re.search(re.escape(term), value or "", flags=re.IGNORECASE) is not None

    def _clean_text(self, value: str | None) -> str:
        return re.sub(r"\s+", " ", value or "").strip()

    def _headers(self) -> dict[str, str]:
        return {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
        }
