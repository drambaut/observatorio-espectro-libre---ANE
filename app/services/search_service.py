from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import date, datetime
from io import BytesIO
import json
import re
import sys
import time
import unicodedata
from urllib.parse import quote, quote_plus, urlparse

import requests
import yaml
from bs4 import BeautifulSoup
from pypdf import PdfReader
from sqlalchemy import select

from app.config.settings import BASE_DIR
from app.models.document import Document
from app.models.keyword import Keyword
from app.models.regulator import Regulator
from app.models.scraping_run import ScrapingRun
from app.scrapers.generic_url_scraper import GenericUrlScraper, SearchResult
from app.scrapers.playwright_form_scraper import PlaywrightFormScraper
from app.scrapers.playwright_url_scraper import PlaywrightUrlScraper
from app.scrapers.result_quality import is_blocked_or_challenge_reason, is_interface_link
from app.scrapers.rss_scraper import RssScraper


@dataclass(slots=True)
class RegulatorRunResult:
    raw_found: int = 0
    valid_found: int = 0
    discarded: int = 0
    saved: int = 0
    duplicates: int = 0
    strategies: set[str] = field(default_factory=set)
    errors: list[str] = field(default_factory=list)


@dataclass(slots=True)
class SearchSummary:
    total_regulators_processed: int = 0
    total_keywords_used: int = 0
    total_found: int = 0
    total_saved: int = 0
    total_duplicates: int = 0
    errors_by_regulator: dict[str, list[str]] = field(default_factory=dict)
    results_by_regulator: dict[str, RegulatorRunResult] = field(default_factory=dict)
    skipped: list[str] = field(default_factory=list)


class SearchService:
    def __init__(
        self,
        session,
        scraper: GenericUrlScraper | None = None,
        playwright_scraper: PlaywrightUrlScraper | None = None,
        form_scraper: PlaywrightFormScraper | None = None,
        rss_scraper: RssScraper | None = None,
        regulator_short_names: set[str] | None = None,
        keyword_originals: set[str] | None = None,
        max_results_per_query: int = 10,
        timeout_seconds: int = 30,
        debug: bool = False,
    ) -> None:
        self.session = session
        self.debug = debug
        self.scraper = scraper or GenericUrlScraper(
            timeout_seconds=timeout_seconds,
            max_results=max_results_per_query,
            debug=debug,
        )
        self.playwright_scraper = playwright_scraper or PlaywrightUrlScraper(
            timeout_seconds=timeout_seconds,
            max_results=max_results_per_query,
            debug=debug,
        )
        self.form_scraper = form_scraper or PlaywrightFormScraper(
            timeout_seconds=timeout_seconds,
            max_results=max_results_per_query,
            debug=debug,
        )
        self.rss_scraper = rss_scraper or RssScraper(
            timeout_seconds=timeout_seconds,
            max_results=max_results_per_query,
        )
        self.regulator_short_names = regulator_short_names
        self.keyword_originals = keyword_originals
        self.max_results_per_query = max_results_per_query
        self.timeout_seconds = timeout_seconds
        self.regulator_config = self._load_regulator_config()
        self.related_terms = self._load_related_terms()

    def run(self) -> SearchSummary:
        started_at = time.monotonic()
        summary = SearchSummary()
        notes: list[str] = []

        regulators = self._active_regulators()
        keywords = self._active_keywords()
        keywords_used: set[str] = set()

        scraping_run = ScrapingRun(
            run_date=date.today(),
            keywords_used="",
            total_sites=0,
            total_found=0,
            total_saved=0,
            status="running",
        )
        self.session.add(scraping_run)
        self.session.commit()
        self.session.refresh(scraping_run)

        seen_urls_this_run: set[str] = set()

        for regulator in regulators:
            config = self.regulator_config.get(regulator.short_name, {})
            search_method = config.get("search_method", "url")
            url_search = config.get("url_search") or regulator.url_search
            if regulator.short_name == "itu":
                search_method = "form"
            if search_method not in {"url", "rss", "form", "listing"}:
                message = f"{regulator.short_name}: search_method={search_method} omitido"
                notes.append(message)
                summary.skipped.append(message)
                print(message)
                continue

            if search_method == "url" and (not url_search or "{query}" not in url_search):
                message = f"{regulator.short_name}: url_search invalida u omite {{query}}"
                notes.append(message)
                summary.errors_by_regulator.setdefault(regulator.short_name, []).append(message)
                print(message)
                continue
            if search_method == "rss" and not config.get("url_rss"):
                message = f"{regulator.short_name}: search_method=rss sin url_rss"
                notes.append(message)
                summary.errors_by_regulator.setdefault(regulator.short_name, []).append(message)
                print(message)
                continue
            if search_method == "form" and not config.get("url_search"):
                message = f"{regulator.short_name}: search_method=form sin url_search"
                notes.append(message)
                summary.errors_by_regulator.setdefault(regulator.short_name, []).append(message)
                print(message)
                continue
            if search_method == "listing" and not (config.get("listing_urls") or url_search or regulator.url_news):
                message = f"{regulator.short_name}: search_method=listing sin url_search/url_news"
                notes.append(message)
                summary.errors_by_regulator.setdefault(regulator.short_name, []).append(message)
                print(message)
                continue

            summary.total_regulators_processed += 1
            regulator_result = summary.results_by_regulator.setdefault(
                regulator.short_name,
                RegulatorRunResult(),
            )
            regulator_started_at = time.monotonic()
            regulator_deadline = regulator_started_at + self.timeout_seconds
            print(f"\nInicio regulador: {regulator.short_name} - {regulator.name}")

            for keyword in keywords:
                remaining_seconds = regulator_deadline - time.monotonic()
                if remaining_seconds <= 0:
                    message = f"{regulator.short_name}: timeout de regulador ({self.timeout_seconds}s)"
                    regulator_result.errors.append(message)
                    summary.errors_by_regulator.setdefault(regulator.short_name, []).append(message)
                    print(f"Error en {regulator.short_name}: {message}")
                    break
                if remaining_seconds <= self._minimum_seconds_for_next_keyword(regulator.short_name):
                    print(
                        f"{regulator.short_name}: tiempo insuficiente para siguiente keyword "
                        f"({remaining_seconds:.1f}s restantes), se omite"
                    )
                    break

                keyword_value = self._keyword_for_language(keyword, regulator.language)
                if not keyword_value:
                    continue

                keywords_used.add(keyword_value)
                summary.total_keywords_used += 1
                query_encoded = self._encode_query(regulator.short_name, keyword_value)
                search_url = self._build_search_url(
                    regulator=regulator,
                    search_method=search_method,
                    config=config,
                    url_search=url_search,
                    query_encoded=query_encoded,
                )

                self._safe_print(f"Keyword usada: {keyword_value}")
                if self.debug:
                    if (regulator.language or "").lower() == "ar":
                        self._safe_print(f"Keyword AR usada: {keyword_value}")
                    self._safe_print(f"Keyword original: {keyword_value!r}")
                    print("Keyword codificada:", repr(query_encoded))
                    print("URL final:", search_url)
                print(f"URL de busqueda: {search_url}")

                if search_method == "rss":
                    results, strategy, error = self._search_rss(
                        regulator=regulator,
                        config=config,
                        search_url=search_url,
                        keyword=keyword_value,
                        related_terms=self._related_terms_for(keyword.keyword_original),
                        regulator_deadline=regulator_deadline,
                    )
                elif search_method == "form":
                    results, strategy, error = self._search_form(
                        config=config,
                        search_url=search_url,
                        keyword=keyword_value,
                        regulator_deadline=regulator_deadline,
                    )
                elif search_method == "listing":
                    results, strategy, error = self._search_listing(
                        regulator=regulator,
                        config=config,
                        search_url=search_url,
                        keyword=keyword_value,
                        regulator_deadline=regulator_deadline,
                    )
                else:
                    results, strategy, error = self._search_with_fallback(
                        regulator,
                        search_url,
                        keyword_value,
                        regulator_deadline,
                    )
                results, validation_stats = self._apply_global_result_validation(results, keyword_value)
                regulator_result.strategies.add(strategy)
                print(f"Estrategia usada: {strategy}")
                valid_results = self._valid_results(results)
                discarded_results = self._discarded_results(results)
                discard_counts = self._discard_counts(results)
                regulator_result.raw_found += len(results)
                regulator_result.valid_found += len(valid_results)
                regulator_result.discarded += len(discarded_results)

                print(f"Resultados encontrados crudos: {len(results)}")
                if self.debug:
                    print(f"URLs candidatas despues de filtros basicos: {validation_stats['candidate_urls']}")
                    print(f"Paginas abiertas para validacion interna: {validation_stats['pages_opened']}")
                    print(f"PDFs abiertos para validacion interna: {validation_stats['pdfs_opened']}")
                    print(f"Descartados por URL bloqueada: {discard_counts['blocked_url']}")
                    print(f"Descartados por titulo bloqueado: {discard_counts['blocked_title']}")
                    print(f"Descartados porque la keyword no aparece en contenido: {discard_counts['no_keyword']}")
                    print(f"Descartados por error al abrir: {discard_counts['open_error']}")
                print(f"Resultados validos: {len(valid_results)}")
                print(f"Resultados descartados: {len(discarded_results)}")
                if self.debug:
                    for discarded in discarded_results:
                        self._safe_print(
                            "Descartado: "
                            f"{discarded.rejection_reason} | {discarded.title[:120]} | {discarded.url}"
                        )

                if error:
                    regulator_result.errors.append(error)
                    summary.errors_by_regulator.setdefault(regulator.short_name, []).append(error)
                    print(f"Error en {regulator.short_name}: {error}")
                    if not valid_results:
                        continue

                saved, duplicates = self._save_results(
                    regulator=regulator,
                    scraping_run=scraping_run,
                    keyword_matched=keyword_value,
                    results=results,
                    seen_urls_this_run=seen_urls_this_run,
                )
                summary.total_found += len(valid_results)
                summary.total_saved += saved
                summary.total_duplicates += duplicates
                regulator_result.saved += saved
                regulator_result.duplicates += duplicates

                print(f"Resultados guardados: {saved}")
                print(f"Duplicados omitidos: {duplicates}")

            regulator_duration = time.monotonic() - regulator_started_at
            print(f"Fin regulador: {regulator.short_name}")
            print(f"Duracion regulador: {regulator_duration:.2f}s")

        duration_seconds = time.monotonic() - started_at
        scraping_run.keywords_used = json.dumps(sorted(keywords_used), ensure_ascii=False)
        scraping_run.total_sites = summary.total_regulators_processed
        scraping_run.total_found = summary.total_found
        scraping_run.total_saved = summary.total_saved
        scraping_run.duration_seconds = round(duration_seconds, 2)
        scraping_run.notes = "\n".join(notes + self._error_notes(summary)) or None
        scraping_run.status = "partial_failed" if summary.errors_by_regulator else "completed"
        self.session.commit()
        print(f"Duracion total: {duration_seconds:.2f}s")

        return summary

    def _encode_query(self, regulator_short_name: str, keyword: str) -> str:
        keyword_clean = keyword.strip()
        if regulator_short_name in {"ised", "gov_il"}:
            return quote(keyword_clean)
        return quote_plus(keyword_clean)

    def _build_search_url(
        self,
        regulator: Regulator,
        search_method: str,
        config: dict,
        url_search: str,
        query_encoded: str,
    ) -> str:
        if search_method == "rss":
            return config["url_rss"]
        if search_method == "form":
            return config["url_search"]
        if search_method == "listing":
            return url_search or regulator.url_news
        try:
            return url_search.format(query=query_encoded)
        except KeyError:
            return url_search.replace("{query}", query_encoded)

    def _search_with_fallback(
        self,
        regulator: Regulator,
        search_url: str,
        keyword: str,
        regulator_deadline: float,
    ) -> tuple[list[SearchResult], str, str | None]:
        remaining_seconds = max(1, int(regulator_deadline - time.monotonic()))
        config = self.regulator_config.get(regulator.short_name, {})
        if regulator.short_name == "acma":
            if self.debug:
                print("acma: usando Playwright directo")
            return self._search_with_playwright(
                regulator,
                search_url,
                None,
                max(1, remaining_seconds - 5),
                keyword,
            )
        if config.get("requires_playwright") is True:
            if self.debug:
                print("requires_playwright=true, usando Playwright")
            return self._search_with_playwright(
                regulator,
                search_url,
                None,
                max(1, remaining_seconds - 5),
                keyword,
            )

        self.scraper.timeout_seconds = self._bounded_scraper_timeout(
            regulator.short_name,
            remaining_seconds,
        )
        try:
            results = self.scraper.search(
                search_url,
                regulator.url_base,
                selectors=config.get("selectors") or {},
                filters=config,
            )
            if self._valid_results(results) or regulator.priority != 1:
                return results, "requests", None

            remaining_after_requests = int(regulator_deadline - time.monotonic())
            if remaining_after_requests <= 1:
                return results, "requests", "timeout de regulador antes de fallback playwright"
            if self.debug:
                print("Requests devolvio 0 resultados validos en regulador prioritario; intentando Playwright.")
            return self._search_with_playwright(
                regulator,
                search_url,
                "requests: 0 resultados validos",
                max(1, remaining_after_requests - 5),
                keyword,
            )
        except Exception as exc:
            message = f"requests {type(exc).__name__}: {exc}"
            if self._is_http_status(exc, 403):
                reason = "sitio bloqueado por 403/challenge"
                message = f"{regulator.short_name}: {reason}, se omite scraping"
                print(message)
                self._record_blocked_site(regulator.short_name, search_url, reason)
                return [], "blocked", message
            if self._should_fallback(exc):
                if self._is_blocked_regulator(regulator, exc):
                    reason = "sitio bloqueado por Cloudflare/403"
                    message = f"{regulator.short_name}: {reason}, se omite scraping"
                    print(message)
                    self._record_blocked_site(regulator.short_name, search_url, reason)
                    return [], "blocked", message
                remaining_after_requests = int(regulator_deadline - time.monotonic())
                if remaining_after_requests <= 1:
                    return [], "requests", message
                if self.debug:
                    print(f"Requests fallo con condicion recuperable; intentando Playwright. {message}")
                return self._search_with_playwright(
                    regulator,
                    search_url,
                    message,
                    max(1, remaining_after_requests - 5),
                    keyword,
                )
            return [], "requests", message

    def _search_with_playwright(
        self,
        regulator: Regulator,
        search_url: str,
        requests_error: str | None,
        remaining_seconds: int | None = None,
        keyword: str | None = None,
    ) -> tuple[list[SearchResult], str, str | None]:
        try:
            config = dict(self.regulator_config.get(regulator.short_name, {}))
            if keyword is not None:
                config["keyword"] = keyword
            if remaining_seconds is not None:
                self.playwright_scraper.timeout_seconds = self._bounded_playwright_timeout(
                    regulator.short_name,
                    remaining_seconds,
                )
            results = self.playwright_scraper.search(
                search_url,
                regulator.url_base,
                selectors=config.get("selectors") or {},
                filters=config,
            )
            valid_results = self._valid_results(results)
            if valid_results:
                return results, "playwright", None
            blocked_reasons = [
                result.rejection_reason
                for result in results
                if is_blocked_or_challenge_reason(result.rejection_reason)
            ]
            if blocked_reasons:
                reason = "; ".join(sorted(set(reason for reason in blocked_reasons if reason)))
                return results, "playwright", f"blocked/challenge detectado: {reason}"
            return results, "playwright", requests_error
        except Exception as exc:
            playwright_error = f"playwright {type(exc).__name__}: {exc}"
            if requests_error:
                return [], "playwright", f"{requests_error}; {playwright_error}"
            return [], "playwright", playwright_error

    def _bounded_scraper_timeout(self, regulator_short_name: str, remaining_seconds: int) -> int:
        timeout = max(1, remaining_seconds)
        if regulator_short_name == "acma":
            return min(timeout, 10)
        return timeout

    def _bounded_playwright_timeout(self, regulator_short_name: str, remaining_seconds: int) -> int:
        timeout = max(1, remaining_seconds)
        if regulator_short_name == "acma":
            return min(timeout, 12)
        return timeout

    def _minimum_seconds_for_next_keyword(self, regulator_short_name: str) -> int:
        if regulator_short_name == "acma":
            return 15
        return 5

    def _search_rss(
        self,
        regulator: Regulator,
        config: dict,
        search_url: str,
        keyword: str,
        related_terms: list[str],
        regulator_deadline: float,
    ) -> tuple[list[SearchResult], str, str | None]:
        remaining_seconds = max(1, int(regulator_deadline - time.monotonic()))
        self.rss_scraper.timeout_seconds = remaining_seconds
        try:
            results = self.rss_scraper.search(
                feed_url=search_url,
                keyword=keyword,
                related_terms=related_terms,
                filters=config,
            )
            return results, "rss", None
        except Exception as exc:
            return [], "rss", f"rss {type(exc).__name__}: {exc}"

    def _search_form(
        self,
        config: dict,
        search_url: str,
        keyword: str,
        regulator_deadline: float,
    ) -> tuple[list[SearchResult], str, str | None]:
        remaining_seconds = max(1, int(regulator_deadline - time.monotonic()))
        self.form_scraper.timeout_seconds = remaining_seconds
        try:
            results = self.form_scraper.search(
                search_url=search_url,
                keyword=keyword,
                selectors=config.get("selectors") or {},
                filters=config,
            )
            return results, "playwright_form", None
        except Exception as exc:
            return [], "playwright_form", f"form {type(exc).__name__}: {exc}"

    def _search_listing(
        self,
        regulator: Regulator,
        config: dict,
        search_url: str,
        keyword: str,
        regulator_deadline: float,
    ) -> tuple[list[SearchResult], str, str | None]:
        remaining_seconds = max(1, int(regulator_deadline - time.monotonic()))
        try:
            listing_urls = config.get("listing_urls") or [search_url]
            results: list[SearchResult] = []
            seen_urls: set[str] = set()
            quiet_imda_listing = regulator.short_name == "imda"
            for listing_url in listing_urls:
                remaining_seconds = max(1, int(regulator_deadline - time.monotonic()))
                page_results = self._search_listing_url(
                    regulator=regulator,
                    config=config,
                    listing_url=listing_url,
                    remaining_seconds=remaining_seconds,
                )
                if self.debug and not quiet_imda_listing:
                    print(f"URL listing procesada: {listing_url}")
                    print(f"Resultados candidatos antes de keyword: {len(self._valid_results(page_results))}")
                for result in page_results:
                    if result.url in seen_urls:
                        continue
                    results.append(result)
                    seen_urls.add(result.url)
                    if len(self._valid_results(results)) >= self.max_results_per_query:
                        break
                if len(self._valid_results(results)) >= self.max_results_per_query:
                    break

            if self.debug and not quiet_imda_listing:
                print(f"Resultados candidatos antes de validacion interna: {len(self._valid_results(results))}")
            if len(self._valid_results(results)) > self.max_results_per_query:
                results = self._limit_valid_results(results, self.max_results_per_query)
            return results, "listing", None
        except Exception as exc:
            return [], "listing", f"listing {type(exc).__name__}: {exc}"

    def _search_listing_url(
        self,
        regulator: Regulator,
        config: dict,
        listing_url: str,
        remaining_seconds: int,
    ) -> list[SearchResult]:
        if config.get("requires_playwright") is True:
            self.playwright_scraper.timeout_seconds = remaining_seconds
            return self.playwright_scraper.search(
                listing_url,
                regulator.url_base,
                selectors=config.get("selectors") or {},
                filters=config,
            )

        self.scraper.timeout_seconds = remaining_seconds
        return self.scraper.search(
            listing_url,
            regulator.url_base,
            selectors=config.get("selectors") or {},
            filters=config,
        )

    def _limit_valid_results(
        self,
        results: list[SearchResult],
        max_valid: int,
    ) -> list[SearchResult]:
        limited: list[SearchResult] = []
        valid_count = 0
        for result in results:
            limited.append(result)
            if result.is_valid_result:
                valid_count += 1
            if valid_count >= max_valid:
                break
        return limited

    def _filter_listing_results_by_keyword(
        self,
        results: list[SearchResult],
        keyword: str,
    ) -> list[SearchResult]:
        keyword_lower = keyword.lower()
        filtered: list[SearchResult] = []
        for result in results:
            haystack = " ".join(
                value
                for value in (result.title, result.summary or "", result.url)
                if value
            ).lower()
            if keyword_lower in haystack:
                filtered.append(result)
        return filtered

    def _should_fallback(self, exc: Exception) -> bool:
        if isinstance(exc, requests.Timeout):
            return True
        if isinstance(exc, requests.HTTPError):
            response = exc.response
            return response is not None and response.status_code not in {403}
        return False

    def _is_http_status(self, exc: Exception, status_code: int) -> bool:
        if not isinstance(exc, requests.HTTPError):
            return False
        response = exc.response
        return response is not None and response.status_code == status_code

    def _is_blocked_regulator(self, regulator: Regulator, exc: Exception) -> bool:
        if regulator.short_name != "ofcom":
            return False
        if isinstance(exc, requests.HTTPError):
            response = exc.response
            return response is not None and response.status_code == 403
        return False

    def _record_blocked_site(self, regulator: str, url: str, reason: str) -> None:
        path = BASE_DIR / "data" / "blocked_sites_log.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        write_header = not path.exists()
        with path.open("a", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(
                file,
                fieldnames=["regulator", "url", "motivo_bloqueo", "fecha"],
            )
            if write_header:
                writer.writeheader()
            writer.writerow(
                {
                    "regulator": regulator,
                    "url": url,
                    "motivo_bloqueo": reason,
                    "fecha": datetime.utcnow().isoformat(timespec="seconds"),
                }
            )

    def _active_regulators(self) -> list[Regulator]:
        statement = (
            select(Regulator)
            .where(Regulator.is_active.is_(True))
            .order_by(Regulator.priority.asc(), Regulator.short_name.asc())
        )
        regulators = self.session.scalars(statement).all()
        if self.regulator_short_names is None:
            return regulators
        return [regulator for regulator in regulators if regulator.short_name in self.regulator_short_names]

    def _active_keywords(self) -> list[Keyword]:
        statement = select(Keyword).where(Keyword.is_active.is_(True)).order_by(Keyword.id.asc())
        keywords = self.session.scalars(statement).all()
        if self.keyword_originals is None:
            return keywords
        return [
            keyword
            for keyword in keywords
            if keyword.keyword_original.lower() in self.keyword_originals
        ]

    def _save_results(
        self,
        regulator: Regulator,
        scraping_run: ScrapingRun,
        keyword_matched: str,
        results: list[SearchResult],
        seen_urls_this_run: set[str],
    ) -> tuple[int, int]:
        saved = 0
        duplicates = 0
        extraction_date = datetime.utcnow()

        for result in results:
            if not result.is_valid_result:
                continue
            if result.url in seen_urls_this_run or self._document_exists(result.url):
                duplicates += 1
                seen_urls_this_run.add(result.url)
                continue
            if regulator.short_name == "rsm" and not self._rsm_contains_exact_phrase(
                result,
                keyword_matched,
            ):
                if self.debug:
                    print(
                        "RSM descartado por no contener frase exacta "
                        f"'{keyword_matched}': {result.title} | {result.url}"
                    )
                seen_urls_this_run.add(result.url)
                continue

            document = Document(
                regulator_id=regulator.id,
                title=result.title or result.url,
                summary=result.summary,
                url=result.url,
                content_excerpt=result.summary,
                language=regulator.language,
                doc_type=result.doc_type or "web",
                publish_date=result.publish_date,
                extraction_date=extraction_date,
                keyword_matched=keyword_matched,
                scraping_run_id=scraping_run.id,
                has_attachment=False,
                is_duplicate=False,
                status="new",
            )
            self.session.add(document)
            seen_urls_this_run.add(result.url)
            saved += 1

        self.session.commit()
        return saved, duplicates

    def _rsm_contains_exact_phrase(self, result: SearchResult, keyword_matched: str) -> bool:
        phrase = (keyword_matched or "").strip().lower()
        if not phrase:
            return False

        remote_text, document_kind = self._extract_rsm_document_text(result.url)
        found = phrase in remote_text.lower()
        if self.debug:
            print(
                "RSM validacion exacta: "
                f"url={result.url} | tipo={document_kind} | frase='{keyword_matched}' | "
                f"encontrada={'si' if found else 'no'}"
            )
            if not found:
                print(
                    "RSM descartado: frase exacta no encontrada en contenido real "
                    f"({document_kind}) | {result.title} | {result.url}"
                )
        return found

    def _extract_rsm_document_text(self, url: str) -> tuple[str, str]:
        if self.debug:
            print(f"RSM evaluando URL: {url}")
        try:
            response = requests.get(
                url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; ObservatorioANE/0.1)"},
                timeout=min(self.timeout_seconds, 15),
            )
            response.raise_for_status()
        except Exception as exc:
            if self.debug:
                print(f"RSM validacion exacta: no se pudo leer {url}: {type(exc).__name__}: {exc}")
            return "", "unknown"

        content_type = response.headers.get("content-type", "").lower()
        if "pdf" in content_type or url.lower().endswith(".pdf"):
            if self.debug:
                print(f"RSM tipo detectado: PDF | {url}")
            return self._extract_pdf_text(response.content, url), "pdf"

        if self.debug:
            print(f"RSM tipo detectado: HTML | {url}")
        if response.encoding is None or response.encoding.lower() == "iso-8859-1":
            response.encoding = response.apparent_encoding
        soup = BeautifulSoup(response.text, "html.parser")
        for element in soup(["nav", "header", "footer", "aside", "script", "style", "noscript"]):
            element.decompose()
        content_node = (
            soup.select_one("main")
            or soup.select_one("article")
            or soup.select_one("[role='main']")
            or soup.body
            or soup
        )
        return content_node.get_text(" ", strip=True), "html"

    def _extract_pdf_text(self, content: bytes, url: str) -> str:
        try:
            reader = PdfReader(BytesIO(content))
            return " ".join(page.extract_text() or "" for page in reader.pages)
        except Exception as exc:
            if self.debug:
                print(f"RSM validacion exacta: no se pudo extraer PDF {url}: {type(exc).__name__}: {exc}")
            return ""

    def _apply_global_result_validation(
        self,
        results: list[SearchResult],
        keyword: str,
    ) -> tuple[list[SearchResult], dict[str, int]]:
        keyword_terms = self._keyword_terms(keyword)
        stats = {
            "candidate_urls": 0,
            "pages_opened": 0,
            "pdfs_opened": 0,
            "content_missing_keyword": 0,
            "open_errors": 0,
        }
        for result in results:
            if not result.is_valid_result:
                continue

            if is_interface_link(result.title, result.url):
                result.is_valid_result = False
                result.rejection_reason = "discarded_interface_link"
                continue

            if self._is_global_blocked_url(result.url):
                result.is_valid_result = False
                result.rejection_reason = "discarded_blocked_url"
                continue

            stats["candidate_urls"] += 1
            page_text, document_kind, error = self._extract_result_content_text(result.url)
            if document_kind == "pdf":
                stats["pdfs_opened"] += 1
            elif document_kind == "html":
                stats["pages_opened"] += 1

            if error:
                result.is_valid_result = False
                result.rejection_reason = "discarded_error_opening_result"
                stats["open_errors"] += 1
                continue

            if not self._validation_text_matches_keyword(page_text, keyword_terms):
                result.is_valid_result = False
                result.rejection_reason = "discarded_keyword_not_found_in_page_content"
                stats["content_missing_keyword"] += 1

        return results, stats

    def _extract_result_content_text(self, url: str | None) -> tuple[str, str, str | None]:
        if not url:
            return "", "unknown", "missing_url"
        try:
            response = requests.get(
                url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; ObservatorioANE/0.1)"},
                timeout=min(self.timeout_seconds, 15),
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            return "", "unknown", f"{type(exc).__name__}: {exc}"

        content_type = response.headers.get("content-type", "").lower()
        lowered_url = url.lower()
        if "pdf" in content_type or lowered_url.endswith(".pdf"):
            return self._extract_pdf_text(response.content, url), "pdf", None

        if response.encoding is None or response.encoding.lower() == "iso-8859-1":
            response.encoding = response.apparent_encoding
        soup = BeautifulSoup(response.text, "html.parser")
        for element in soup(["nav", "header", "footer", "aside", "script", "style", "noscript"]):
            element.decompose()
        content_node = (
            soup.select_one("main")
            or soup.select_one("article")
            or soup.select_one("[role='main']")
            or soup.body
            or soup
        )
        return content_node.get_text(" ", strip=True), "html", None

    def _validation_text_matches_keyword(self, validation_text: str, keyword_terms: list[str]) -> bool:
        if not keyword_terms:
            return True
        validation_words = set(self._normalize_for_keyword(validation_text).split())
        return all(term in validation_words for term in keyword_terms)

    def _keyword_terms(self, keyword: str) -> list[str]:
        stopwords = {
            "and",
            "or",
            "the",
            "of",
            "for",
            "in",
            "to",
            "de",
            "la",
            "el",
            "los",
            "las",
            "del",
        }
        normalized = self._normalize_for_keyword(keyword)
        return [word for word in normalized.split() if word and word not in stopwords]

    def _normalize_for_keyword(self, value: str | None) -> str:
        normalized = unicodedata.normalize("NFD", value or "")
        without_accents = "".join(
            char for char in normalized if unicodedata.category(char) != "Mn"
        )
        without_separators = without_accents.lower().replace("-", " ").replace("_", " ")
        alnum_space = re.sub(r"[^\w\s]", " ", without_separators, flags=re.UNICODE)
        return re.sub(r"\s+", " ", alnum_space).strip()

    def _is_global_blocked_url(self, url: str | None) -> bool:
        lowered = (url or "").lower()
        if not lowered:
            return True
        if self._looks_like_document_url(lowered):
            return False
        if "#" in lowered:
            return True

        parsed = urlparse(lowered)
        path = parsed.path or ""
        query = parsed.query or ""
        if any(marker in lowered for marker in ("/search", "tx_solr", "resultsperpage")):
            return True
        if query.startswith("q=") or "&q=" in query or "?q=" in lowered:
            return True
        if any(
            marker in path
            for marker in (
                "/home",
                "/contact",
                "/legal",
                "/privacy",
                "/maps",
                "/map",
                "/login",
                "/account",
                "/access-map",
            )
        ):
            return True
        if path.rstrip("/") in {"", "/", "/home", "/about", "/about-us"}:
            return True
        return False

    def _looks_like_document_url(self, lowered_url: str) -> bool:
        path = urlparse(lowered_url).path
        return path.endswith((".pdf", ".doc", ".docx", ".xls", ".xlsx", ".csv", ".zip"))

    def _discard_counts(self, results: list[SearchResult]) -> dict[str, int]:
        counts = {"blocked_url": 0, "blocked_title": 0, "no_keyword": 0}
        for result in results:
            reason = (result.rejection_reason or "").lower()
            if not reason:
                continue
            if (
                "discarded_blocked_url" in reason
                or "discarded_interface_link" in reason
                or "url coincide" in reason
                or "url no coincide" in reason
                or "url bloqueada" in reason
            ):
                counts["blocked_url"] += 1
            if "discarded_blocked_title" in reason or "titulo coincide" in reason:
                counts["blocked_title"] += 1
            if (
                "discarded_no_keyword_match" in reason
                or "discarded_keyword_not_found_in_page_content" in reason
                or "sin keyword" in reason
            ):
                counts["no_keyword"] += 1
            if "discarded_error_opening_result" in reason:
                counts.setdefault("open_error", 0)
                counts["open_error"] += 1
        counts.setdefault("open_error", 0)
        return counts

    def _valid_results(self, results: list[SearchResult]) -> list[SearchResult]:
        return [result for result in results if result.is_valid_result]

    def _discarded_results(self, results: list[SearchResult]) -> list[SearchResult]:
        return [result for result in results if not result.is_valid_result]

    def _document_exists(self, url: str) -> bool:
        return self.session.scalar(select(Document.id).where(Document.url == url).limit(1)) is not None

    def _keyword_for_language(self, keyword: Keyword, language: str | None) -> str | None:
        normalized_language = (language or "").lower()
        if normalized_language == "ar":
            return keyword.keyword_ar or keyword.keyword_en or keyword.keyword_original
        language_field = {
            "en": keyword.keyword_en,
            "es": keyword.keyword_es,
            "pt": keyword.keyword_pt,
            "ko": keyword.keyword_ko,
        }.get(normalized_language)
        return language_field or keyword.keyword_original

    def _load_regulator_config(self) -> dict[str, dict]:
        path = BASE_DIR / "app" / "config" / "regulators.yaml"
        with path.open("r", encoding="utf-8") as file:
            data = yaml.safe_load(file) or {}
        return {item["short_name"]: item for item in data.get("regulators", [])}

    def _load_related_terms(self) -> dict[str, list[str]]:
        path = BASE_DIR / "app" / "config" / "related_terms.yaml"
        if not path.exists():
            return {}
        with path.open("r", encoding="utf-8") as file:
            data = yaml.safe_load(file) or {}
        return data.get("related_terms", {})

    def _related_terms_for(self, keyword_original: str) -> list[str]:
        return self.related_terms.get(keyword_original, [])

    def _error_notes(self, summary: SearchSummary) -> list[str]:
        notes = []
        for regulator, errors in summary.errors_by_regulator.items():
            for error in errors:
                notes.append(f"{regulator}: {error}")
        return notes

    def _safe_print(self, message: str) -> None:
        encoding = sys.stdout.encoding or "utf-8"
        print(str(message).encode(encoding, errors="backslashreplace").decode(encoding))
