from __future__ import annotations

from datetime import date, datetime
import re
import time
from urllib.parse import urljoin, urlparse

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from app.scrapers.generic_url_scraper import SearchResult
from app.scrapers.result_quality import is_interface_link, validate_result


class PlaywrightUrlScraper:
    def __init__(self, timeout_seconds: int = 30, max_results: int = 20, debug: bool = False) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_results = max_results
        self.debug = debug
        self.user_agent = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        )

    def search(
        self,
        search_url: str,
        url_base: str | None = None,
        selectors: dict | None = None,
        filters: dict | None = None,
    ) -> list[SearchResult]:
        timeout_ms = self.timeout_seconds * 1000
        deadline = time.monotonic() + self.timeout_seconds
        is_fcc = "fcc.gov" in search_url
        is_acma = "acma.gov.au" in search_url
        selectors = selectors or {}
        filters = filters or {}
        quiet_imda_listing = (
            filters.get("short_name") == "imda"
            and filters.get("search_method") == "listing"
        )
        result_container = selectors.get("result_container", "main a[href]")
        result_link = selectors.get("result_link", "a[href]")
        result_title = selectors.get("result_title", "a")
        result_summary = selectors.get("result_summary", "p")
        acma_goto_timed_out = False
        chromium_args = [
            "--disable-http2",
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
        ]

        with sync_playwright() as playwright:
            browser = None
            context = None
            browser = self._launch_browser(playwright, is_fcc, is_acma, chromium_args)
            context = browser.new_context(
                user_agent=self.user_agent,
                locale="en-US",
                viewport={"width": 1366, "height": 768},
                ignore_https_errors=True,
                extra_http_headers={
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Cache-Control": "no-cache",
                },
            )
            page = context.new_page()
            page.set_default_timeout(timeout_ms)
            page.set_default_navigation_timeout(timeout_ms)
            if is_acma:
                page.route(
                    "**/*",
                    lambda route: route.abort()
                    if route.request.resource_type in {"image", "font", "media", "stylesheet"}
                    else route.continue_(),
                )
            try:
                try:
                    if is_fcc:
                        page.goto(search_url, wait_until="commit", timeout=30000)
                        page.wait_for_timeout(5000)
                    else:
                        page.goto(search_url, wait_until="domcontentloaded", timeout=timeout_ms)
                    if self.debug:
                        print(f"Playwright URL cargada: {search_url}")
                except Exception as exc:
                    if is_fcc:
                        return []
                    if not isinstance(exc, PlaywrightTimeoutError):
                        raise
                    if is_acma:
                        if self.debug:
                            print("acma: goto timeout controlado, intentando extraer resultados visibles")
                        acma_goto_timed_out = True
                        self._stop_loading(context, page)
                    else:
                        if self.debug:
                            print(f"Playwright goto timeout controlado: {search_url}")
                        return []

                if is_fcc:
                    try:
                        page.wait_for_selector(".searchresult", timeout=30000)
                    except PlaywrightTimeoutError:
                        if self.debug:
                            print("fcc: timeout esperando resultados, se omite keyword")
                        return []
                    if self.debug:
                        print("FCC .searchresult count:", page.locator(".searchresult").count())
                        print("FCC links count:", page.locator(".searchresult a[href]").count())
                elif is_acma:
                    if self.debug:
                        print("acma: esperando resultados visibles")
                    if acma_goto_timed_out:
                        page.wait_for_timeout(1000)
                    else:
                        remaining_ms = min(self._remaining_ms(deadline), 8000)
                        if remaining_ms <= 0:
                            if self.debug:
                                print("acma: timeout Playwright, se omite keyword")
                            return []
                        try:
                            page.wait_for_selector(result_container, timeout=remaining_ms)
                        except PlaywrightTimeoutError:
                            if self.debug:
                                print("acma: timeout esperando resultados visibles")
                else:
                    remaining_ms = self._remaining_ms(deadline)
                    if remaining_ms > 0:
                        page.wait_for_timeout(min(1500, remaining_ms))

                is_listing = filters.get("search_method") == "listing"
                if not is_listing and self._page_has_no_results(page):
                    if self.debug:
                        print("Playwright pagina indica No results found; se omite keyword")
                    return []

                if self.debug and not quiet_imda_listing:
                    print(f"Playwright selector de contenedor usado: {result_container}")
                containers = page.locator(result_container)
                container_count = self._safe_count(containers)
                if self.debug and not quiet_imda_listing:
                    print(f"Playwright nodos encontrados con contenedor: {container_count}")
                if is_acma:
                    if self.debug:
                        print(f"acma: resultados visibles encontrados: {container_count}")
                items = self._extract_items_from_containers(
                    containers=containers,
                    container_count=container_count,
                    result_link=result_link,
                    result_title=result_title,
                    result_summary=result_summary,
                    max_items=self.max_results,
                    fallback_url=search_url if is_acma else None,
                    base_url=url_base or search_url,
                )
                if is_acma and not items:
                    items = self._extract_acma_fallback_links(page, max_items=50)
            finally:
                if context:
                    self._safe_close(context, "context")
                if browser:
                    self._safe_close(browser, "browser")

        return self._to_results(items, search_url, filters)

    def _remaining_ms(self, deadline: float) -> int:
        return max(0, int((deadline - time.monotonic()) * 1000))

    def _launch_browser(
        self,
        playwright,
        is_fcc: bool,
        is_acma: bool,
        chromium_args: list[str],
    ):
        if is_fcc:
            if self.debug:
                print("FCC usando Chrome del sistema")
            try:
                return playwright.chromium.launch(
                    channel="chrome",
                    headless=True,
                    args=[
                        "--disable-http2",
                        "--disable-blink-features=AutomationControlled",
                    ],
                )
            except Exception as exc:
                message = (
                    "FCC requiere Google Chrome instalado. "
                    "Chromium Playwright falla con ERR_HTTP2_PROTOCOL_ERROR."
                )
                if self.debug:
                    print(message)
                raise RuntimeError(message) from exc
        if is_acma:
            try:
                return playwright.chromium.launch(
                    channel="chrome",
                    headless=True,
                    args=chromium_args,
                )
            except Exception as exc:
                if self.debug:
                    print(f"acma: no se pudo lanzar Chrome estable, usando Chromium: {type(exc).__name__}: {exc}")
        return playwright.chromium.launch(
            headless=True,
            args=chromium_args,
        )

    def _extract_items_from_containers(
        self,
        containers,
        container_count: int,
        result_link: str,
        result_title: str,
        result_summary: str | None,
        max_items: int,
        fallback_url: str | None = None,
        base_url: str | None = None,
    ) -> list[dict]:
        items: list[dict] = []
        discarded_navigation = 0
        count = min(container_count, max_items)
        for index in range(count):
            container = containers.nth(index)
            href = self._extract_href(container, result_link)
            title = self._extract_title(container, result_title)

            summary = None
            if result_summary:
                summary_locator = container.locator(result_summary).first
                if self._safe_count(container.locator(result_summary)) > 0:
                    summary = self._safe_text(summary_locator)

            if title and not href:
                href = fallback_url

            if href and title:
                normalized_url = urljoin(base_url or "", href)
                if is_interface_link(title, normalized_url):
                    discarded_navigation += 1
                    continue
                items.append(
                    {
                        "title": title,
                        "url": href,
                        "summary": summary,
                        "containerText": " ".join(value for value in (title, summary) if value),
                    }
                )
        if self.debug and discarded_navigation:
            print(f"Playwright resultados descartados por navegacion: {discarded_navigation}")
        return items

    def _page_has_no_results(self, page) -> bool:
        body_text = (self._safe_text(page.locator("body")) or "").lower()
        return "no results found" in body_text or "no results" in body_text

    def _extract_href(self, container, result_link: str) -> str | None:
        if result_link == "__self__":
            return self._safe_attr(container, "href")

        href = self._safe_attr(container, "href")
        link_locator = container.locator(result_link)
        if self._safe_count(link_locator) > 0:
            href = self._safe_attr(link_locator.first, "href") or href
        return href

    def _extract_title(self, container, result_title: str) -> str | None:
        if result_title == "__self__":
            return self._safe_text(container)

        title = self._safe_text(container)
        title_locator = container.locator(result_title)
        if self._safe_count(title_locator) > 0:
            title = self._safe_text(title_locator.first) or title
        return title

    def _extract_acma_fallback_links(self, page, max_items: int) -> list[dict]:
        fallback_selector = (
            "main a[href*='/articles/'], "
            "main a[href*='/consultations/'], "
            "main a[href*='/publications/'], "
            "main a[href*='/spectrum'], "
            "main a[href*='/radiocommunications'], "
            "main a[href*='/licences']"
        )
        links = page.locator(fallback_selector)
        count = min(self._safe_count(links), max_items)
        if self.debug:
            print(f"ACMA fallback enlaces encontrados: {count}")
        items: list[dict] = []
        for index in range(count):
            link = links.nth(index)
            href = self._safe_attr(link, "href")
            title = self._safe_text(link)
            if href and title:
                items.append(
                    {
                        "title": title,
                        "url": href,
                        "summary": None,
                        "containerText": title,
                    }
                )
        return items

    def _to_results(self, items: list[dict], search_url: str, filters: dict | None = None) -> list[SearchResult]:
        results: list[SearchResult] = []
        seen_urls: set[str] = set()
        filters = filters or {}
        is_gov_il = filters.get("short_name") == "gov_il"

        for index, item in enumerate(items):
            title = self._clean_text(item.get("title"))
            raw_url = item.get("url")
            normalized_url = urljoin(search_url, raw_url) if raw_url else None
            summary = self._clean_text(item.get("summary")) or None

            rejection_reason = None
            if not title:
                rejection_reason = "sin titulo"
            elif not raw_url:
                rejection_reason = "sin href"
            elif normalized_url in seen_urls:
                rejection_reason = "url duplicada"
            else:
                is_valid, rejection_reason = self._validate_result(
                    title,
                    normalized_url,
                    search_url,
                    filters,
                )
                if is_valid:
                    rejection_reason = None

            if is_gov_il and rejection_reason is None:
                rejection_reason = self._validate_gov_il_relevance(
                    title,
                    summary,
                    normalized_url,
                    search_url,
                    filters,
                )

            if rejection_reason:
                continue
            url = normalized_url
            if "acma.gov.au" in search_url:
                if self.debug:
                    print(f"acma: resultado crudo: {title[:160]} | {url}")

            container_text = self._clean_text(item.get("containerText"))
            if not summary:
                summary = self._extract_summary(container_text, title)
            results.append(
                SearchResult(
                    title=title[:500],
                    url=url,
                    summary=summary,
                    publish_date=self._extract_publish_date(container_text),
                    doc_type=self._detect_doc_type(url, title),
                    is_valid_result=is_valid,
                    rejection_reason=rejection_reason,
                )
            )
            seen_urls.add(url)

            if len([result for result in results if result.is_valid_result]) >= self.max_results:
                break

        return results

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

    def _validate_gov_il_relevance(
        self,
        title: str,
        summary: str | None,
        url: str | None,
        search_url: str,
        filters: dict,
    ) -> str | None:
        lowered_url = (url or "").lower()
        blocked_paths = (
            "/pages/gov_terms_of_use",
            "/departments/govil-landing-page",
            "/privacy",
            "/accessibility",
            "/contact",
            "/search",
        )
        if any(path in lowered_url for path in blocked_paths):
            return "gov_il url bloqueada explicitamente"

        text = f"{title or ''} {summary or ''}".lower()
        keyword = (filters.get("keyword") or self._extract_gov_il_keyword(search_url) or "").lower().strip()
        if keyword and keyword in text:
            return None
        if "ministry_of_communications" in lowered_url:
            return None
        if "communication_services" in lowered_url:
            return None
        if any(
            term in text
            for term in (
                "spectrum",
                "wireless",
                "telecommunications",
                "communications",
            )
        ):
            return None
        return "gov_il sin keyword ni relevancia telecom/espectro"

    def _extract_gov_il_keyword(self, search_url: str) -> str | None:
        parsed = urlparse(search_url)
        match = re.search(r"(?:^|&)query=([^&]+)", parsed.query.lower())
        if not match:
            return None
        return match.group(1).replace("+", " ").replace("%20", " ").strip()

    def _contains_any(self, value: str, fragments: list[str]) -> bool:
        lowered = (value or "").lower()
        return any(fragment.lower() in lowered for fragment in fragments)

    def _safe_count(self, locator) -> int:
        try:
            return locator.count()
        except Exception as exc:
            if self.debug:
                print(f"Playwright extraccion: count fallo: {type(exc).__name__}: {exc}")
            return 0

    def _safe_text(self, locator) -> str | None:
        try:
            return self._clean_text(locator.text_content(timeout=1000))
        except Exception:
            return None

    def _safe_attr(self, locator, name: str) -> str | None:
        try:
            return locator.get_attribute(name, timeout=1000)
        except Exception:
            return None

    def _safe_close(self, target, name: str) -> None:
        try:
            target.close()
        except Exception as exc:
            if self.debug:
                print(f"Playwright cierre {name} fallo controlado: {type(exc).__name__}: {exc}")

    def _stop_loading(self, context, page) -> None:
        try:
            session = context.new_cdp_session(page)
            session.send("Page.stopLoading")
            session.detach()
        except Exception as exc:
            if self.debug:
                print(f"Playwright stopLoading fallo controlado: {type(exc).__name__}: {exc}")

    def _extract_summary(self, container_text: str, title: str) -> str | None:
        if not container_text or container_text == title:
            return None
        summary = container_text.replace(title, "", 1).strip()
        return summary[:1000] or None

    def _extract_publish_date(self, text: str) -> date | None:
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

    def _parse_date(self, value: str) -> date | None:
        for date_format in (
            "%Y-%m-%d",
            "%d/%m/%Y",
            "%m/%d/%Y",
            "%d %B %Y",
            "%d %b %Y",
            "%B %d, %Y",
            "%b %d, %Y",
        ):
            try:
                return datetime.strptime(value.strip(), date_format).date()
            except ValueError:
                continue
        return None

    def _detect_doc_type(self, url: str, title: str) -> str:
        path = urlparse(url).path.lower()
        title_lower = title.lower()
        if path.endswith(".pdf") or "pdf" in title_lower:
            return "pdf"
        if path.endswith((".doc", ".docx")):
            return "word"
        if "news" in path or "press" in path:
            return "news"
        if "consult" in path:
            return "consultation"
        if "publication" in path or "document" in path:
            return "publication"
        return "web"

    def _clean_text(self, value: str | None) -> str:
        return re.sub(r"\s+", " ", value or "").strip()
