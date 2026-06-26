from __future__ import annotations

from urllib.parse import urldefrag, urlparse


BLOCKED_TITLE_FRAGMENTS = (
    "cloudflare",
    "just a moment",
    "attention required",
    "skip to",
    "skip to main",
    "skip to primary",
    "skip to secondary",
    "menu",
    "search",
    "home",
    "contact",
    "privacy",
    "terms",
    "sitemap",
    "accessibility",
)

BLOCKED_URL_FRAGMENTS = (
    "cloudflare.com",
    "challenge",
    "cdn-cgi",
    "#nav",
    "#main",
    "#content",
    "#footer",
    "mailto:",
    "javascript:",
    "tel:",
)

INTERFACE_EXACT_TITLES = {
    "all",
    "relevance",
    "date",
    "home",
    "menu",
    "linkedin",
    "instagram",
    "bluesky",
    "mastodon",
    "share",
    "share by email",
}

INTERFACE_TITLE_FRAGMENTS = (
    " results",
    "join us",
)

INTERFACE_URL_FRAGMENTS = (
    "/search.html",
    "tx_solr",
    "resultsperpage",
    "sort=",
    "filter=",
    "#tab",
    "mailto:",
    "facebook.com",
    "twitter.com",
    "x.com",
    "linkedin.com",
    "instagram.com",
    "youtube.com",
    "bsky.app",
    "mastodon",
)

BLOCKED_EXACT_TITLES = {
    "about us",
    "close the primary navigation",
    "feedback, enquiry and complaints form",
    "our history",
    "our legislation",
    "our role and objectives",
    "our role in the international community",
    "our team",
    "our work",
    "publications",
    "register of radio frequencies (rrf)",
    "report non-compliance",
    "rrf system issues and improvements reporting form",
    "search now",
    "statements of government policy and directions",
    "toggle sub menu",
}

BLOCKED_PATHS = {
    "/about/about-us",
    "/about/contact-us",
    "/about/contact-us/feedback-enquiry-and-complaints-form",
    "/about/contact-us/report-non-compliance",
    "/about/contact-us/rrf-system-issues-and-improvements-reporting-form",
    "/about/our-history",
    "/about/our-legislation",
    "/about/our-team",
    "/about/our-work",
    "/about/our-work/our-history",
    "/about/our-work/our-role-in-the-international-community",
    "/about/publications",
}


def validate_result(title: str | None, url: str | None, search_url: str | None = None) -> tuple[bool, str | None]:
    normalized_title = (title or "").strip().lower()
    normalized_url = (url or "").strip()
    normalized_url_lower = normalized_url.lower()

    if not normalized_title:
        return False, "titulo vacio"
    if len(normalized_title) < 4:
        return False, "titulo demasiado corto"
    if normalized_title in BLOCKED_EXACT_TITLES:
        return False, f"titulo general/no resultado: {normalized_title}"
    for fragment in BLOCKED_TITLE_FRAGMENTS:
        if fragment in normalized_title:
            return False, f"titulo bloqueado: {fragment}"

    if not normalized_url:
        return False, "url vacia"
    parsed = urlparse(normalized_url)
    if parsed.scheme not in {"http", "https"}:
        return False, f"esquema no permitido: {parsed.scheme or 'sin esquema'}"
    if parsed.path.rstrip("/") in BLOCKED_PATHS:
        return False, f"ruta general/no resultado: {parsed.path}"

    for fragment in BLOCKED_URL_FRAGMENTS:
        if fragment in normalized_url_lower:
            return False, f"url bloqueada: {fragment}"

    if search_url and _same_url_ignoring_fragment(normalized_url, search_url):
        return False, "url igual a pagina de busqueda o anchor interno"

    if parsed.fragment and search_url and _same_page(normalized_url, search_url):
        return False, "anchor interno de pagina de busqueda"

    return True, None


def is_blocked_or_challenge_reason(reason: str | None) -> bool:
    if not reason:
        return False
    lowered = reason.lower()
    return any(token in lowered for token in ("cloudflare", "challenge", "just a moment", "attention required"))


def is_interface_link(title: str | None, url: str | None) -> bool:
    normalized_title = " ".join((title or "").strip().lower().split())
    normalized_url = (url or "").strip().lower()
    if not normalized_title or not normalized_url:
        return True
    if normalized_title in INTERFACE_EXACT_TITLES:
        return True
    if normalized_title.startswith("all ") or normalized_title.startswith("all("):
        return True
    if any(fragment in normalized_title for fragment in INTERFACE_TITLE_FRAGMENTS):
        return True
    return any(fragment in normalized_url for fragment in INTERFACE_URL_FRAGMENTS)


def _same_url_ignoring_fragment(url: str, other_url: str) -> bool:
    return _normalize_without_fragment(url) == _normalize_without_fragment(other_url)


def _same_page(url: str, other_url: str) -> bool:
    first = urlparse(urldefrag(url).url)
    second = urlparse(urldefrag(other_url).url)
    return (
        first.scheme == second.scheme
        and first.netloc == second.netloc
        and first.path.rstrip("/") == second.path.rstrip("/")
        and first.query == second.query
    )


def _normalize_without_fragment(url: str) -> tuple[str, str, str, str]:
    parsed = urlparse(urldefrag(url).url)
    return (
        parsed.scheme.lower(),
        parsed.netloc.lower(),
        parsed.path.rstrip("/"),
        parsed.query,
    )
