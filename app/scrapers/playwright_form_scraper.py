from __future__ import annotations

from datetime import date, datetime
import re
from urllib.parse import urljoin, urlparse

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from app.scrapers.generic_url_scraper import SearchResult
from app.scrapers.result_quality import validate_result


class PlaywrightFormScraper:
    def __init__(self, timeout_seconds: int = 60, max_results: int = 10, debug: bool = False) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_results = max_results
        self.debug = debug
        self.user_agent = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        )

    def search(self, search_url: str, keyword: str, selectors: dict, filters: dict) -> list[SearchResult]:
        timeout_ms = self.timeout_seconds * 1000
        is_gov_il = filters.get("short_name") == "gov_il"
        search_box = selectors.get("search_box", "input#gsc-i-id1")
        search_button = selectors.get("search_button", "button.gsc-search-button")
        result_container = selectors.get("result_container", ".gsc-webResult.gsc-result")
        result_link = selectors.get("result_link", "a.gs-title")
        result_summary = selectors.get("result_summary", ".gs-snippet")

        with sync_playwright() as playwright:
            browser = self._launch_browser(playwright, is_gov_il)
            context = browser.new_context(
                user_agent=self.user_agent,
                locale="en-US",
                viewport={"width": 1366, "height": 768},
            )
            page = context.new_page()
            try:
                if is_gov_il:
                    items = self._search_gov_il_form(
                        page=page,
                        search_url=search_url,
                        keyword=keyword,
                        result_container=result_container,
                    )
                    return self._to_results(items, search_url, filters)

                page.goto(search_url, wait_until="domcontentloaded", timeout=timeout_ms)
                self._open_search_if_needed(page)
                page.wait_for_selector(search_box, timeout=timeout_ms)
                page.fill(search_box, keyword)
                try:
                    page.press(search_box, "Enter")
                except Exception:
                    button = page.locator(search_button)
                    if button.count() > 0 and button.first.is_visible():
                        button.first.click()
                    else:
                        page.evaluate(
                            """
                            ({ selector }) => {
                              const input = document.querySelector(selector);
                              if (!input) return;
                              input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
                              input.dispatchEvent(new KeyboardEvent('keyup', { key: 'Enter', bubbles: true }));
                            }
                            """,
                            {"selector": search_box},
                        )

                try:
                    page.wait_for_selector(result_container, timeout=timeout_ms)
                except PlaywrightTimeoutError:
                    page.wait_for_selector(result_link, timeout=timeout_ms)
                page.wait_for_timeout(1500)

                items = page.evaluate(
                    """
                    ({ resultContainer, resultLink, resultSummary }) => {
                      const containers = Array.from(document.querySelectorAll(resultContainer));
                      const source = containers.length ? containers : Array.from(document.querySelectorAll(resultLink));
                      return source.map((node) => {
                        const link = node.matches && node.matches(resultLink)
                          ? node
                          : node.querySelector(resultLink);
                        const summary = node.querySelector ? node.querySelector(resultSummary) : null;
                        return {
                          title: link ? (link.innerText || link.textContent || '') : '',
                          url: link ? link.href : '',
                          summary: summary ? (summary.innerText || summary.textContent || '') : '',
                          containerText: node.innerText || node.textContent || ''
                        };
                      });
                    }
                    """,
                    {
                        "resultContainer": result_container,
                        "resultLink": result_link,
                        "resultSummary": result_summary,
                    },
                )
            finally:
                context.close()
                browser.close()

        return self._to_results(items, search_url, filters)

    def _launch_browser(self, playwright, is_gov_il: bool):
        args = ["--disable-http2", "--disable-blink-features=AutomationControlled", "--no-sandbox"]
        if is_gov_il:
            try:
                return playwright.chromium.launch(channel="chrome", headless=True, args=args)
            except Exception:
                pass
        return playwright.chromium.launch(headless=True, args=args)

    def _search_gov_il_form(
        self,
        page,
        search_url: str,
        keyword: str,
        result_container: str,
    ) -> list[dict]:
        if self.debug:
            print("gov_il busqueda por formulario")
        form_url = "https://www.gov.il/en/Search"
        operation_timeout = min(self.timeout_seconds * 1000, 30000)
        page.goto(form_url, wait_until="domcontentloaded", timeout=operation_timeout)
        page.wait_for_timeout(3000)
        initial_body_text = self._safe_text(page.locator("body")) or ""
        if self._is_blocked_or_challenge(page.title(), initial_body_text):
            if self.debug:
                print("gov_il sitio bloqueado por verificacion/Cloudflare, se omite scraping")
                print("gov_il resultados extraidos: 0")
            return []
        self._open_search_if_needed(page)

        input_selector = (
            "input[id='query'], input[name='query'], input[type='search'], "
            "input[id*='query' i], input[name*='query' i], "
            "input[placeholder*='Search' i], input[class*='search' i], input[type='text']"
        )
        search_input = page.locator(input_selector).first
        search_input.wait_for(timeout=10000)
        search_input.fill("", timeout=5000)
        search_input.fill(keyword, timeout=5000)

        button_selector = "button[type='submit'], button[aria-label*='Search'], .search-button"
        try:
            button = page.locator(button_selector).first
            if page.locator(button_selector).count() > 0:
                button.click(timeout=5000, no_wait_after=True)
            else:
                search_input.press("Enter", timeout=3000)
        except Exception:
            search_input.press("Enter", timeout=3000)

        page.wait_for_timeout(5000)
        body_text = self._safe_text(page.locator("body")) or ""
        if self._is_blocked_or_challenge(page.title(), body_text):
            if self.debug:
                print("gov_il sitio bloqueado por verificacion/Cloudflare, se omite scraping")
                print("gov_il resultados extraidos: 0")
            return []
        not_found = "not found" in body_text.lower()
        if not_found:
            if self.debug:
                print("gov_il resultados extraidos: 0")
            return []

        containers = page.locator(result_container)
        items = self._extract_gov_il_items(containers, self._safe_count(containers), search_url)
        if self.debug:
            print(f"gov_il resultados extraidos: {len(items)}")
        return items

    def _extract_gov_il_items(self, containers, container_count: int, search_url: str) -> list[dict]:
        items: list[dict] = []
        for index in range(min(container_count, self.max_results * 3)):
            container = containers.nth(index)
            href, link_text = self._first_non_empty_link(container)
            if not href:
                continue
            title = self._first_text(container, "h2, h3, h4, strong") or link_text
            container_text = self._safe_text(container) or ""
            summary = self._first_text(container, "p")
            if not summary and container_text and container_text != title:
                summary = container_text
            if title:
                items.append(
                    {
                        "title": title,
                        "url": urljoin(search_url, href),
                        "summary": summary,
                        "containerText": container_text,
                    }
                )
            if len(items) >= self.max_results:
                break
        return items

    def _first_non_empty_link(self, container) -> tuple[str | None, str | None]:
        links = container.locator("a[href]")
        for index in range(self._safe_count(links)):
            link = links.nth(index)
            href = (self._safe_attr(link, "href") or "").strip()
            if href:
                return href, self._safe_text(link)
        return None, None

    def _first_text(self, container, selector: str) -> str | None:
        locator = container.locator(selector)
        for index in range(self._safe_count(locator)):
            text = self._safe_text(locator.nth(index))
            if text:
                return text
        return None

    def _is_blocked_or_challenge(self, title: str, body_text: str) -> bool:
        haystack = f"{title or ''} {body_text or ''}".lower()
        return any(
            marker in haystack
            for marker in (
                "just a moment",
                "security verification",
                "enable javascript and cookies",
                "cloudflare",
                "challenge-error-text",
            )
        )

    def _open_search_if_needed(self, page) -> None:
        for selector in ("button[aria-label*='Search']", "a[aria-label*='Search']", ".search-toggle", "#search"):
            try:
                locator = page.locator(selector)
                if locator.count() > 0 and locator.first.is_visible():
                    locator.first.click(timeout=1500)
                    page.wait_for_timeout(500)
                    return
            except Exception:
                continue

    def _to_results(self, items: list[dict], search_url: str, filters: dict) -> list[SearchResult]:
        results: list[SearchResult] = []
        seen_urls: set[str] = set()

        for item in items:
            title = self._clean_text(item.get("title"))
            url = item.get("url")
            if not title or not url or url in seen_urls:
                continue

            summary = self._clean_text(item.get("summary")) or self._extract_summary(
                self._clean_text(item.get("containerText")),
                title,
            )
            is_valid, rejection_reason = self._validate(title, url, search_url, filters)
            results.append(
                SearchResult(
                    title=title[:500],
                    url=url,
                    summary=summary,
                    publish_date=self._extract_publish_date(item.get("containerText") or ""),
                    doc_type=self._detect_doc_type(url, title),
                    is_valid_result=is_valid,
                    rejection_reason=rejection_reason,
                )
            )
            seen_urls.add(url)

            if len([result for result in results if result.is_valid_result]) >= self.max_results:
                break

        return results

    def _validate(self, title: str, url: str, search_url: str, filters: dict) -> tuple[bool, str | None]:
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

    def _safe_count(self, locator) -> int:
        try:
            return locator.count()
        except Exception:
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

    def _extract_summary(self, container_text: str, title: str) -> str | None:
        if not container_text or container_text == title:
            return None
        return container_text.replace(title, "", 1).strip()[:1000] or None

    def _extract_publish_date(self, text: str) -> date | None:
        for pattern in (r"\b\d{4}-\d{2}-\d{2}\b", r"\b\d{1,2}/\d{1,2}/\d{4}\b"):
            match = re.search(pattern, text)
            if match:
                for date_format in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
                    try:
                        return datetime.strptime(match.group(0), date_format).date()
                    except ValueError:
                        continue
        return None

    def _detect_doc_type(self, url: str, title: str) -> str:
        path = urlparse(url).path.lower()
        if path.endswith(".pdf") or "pdf" in title.lower():
            return "pdf"
        if "news" in path or "press" in path:
            return "news"
        if "publication" in path or "pub" in path:
            return "publication"
        return "web"

    def _clean_text(self, value: str | None) -> str:
        return re.sub(r"\s+", " ", value or "").strip()
