from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright


URLS = [
    "https://www.fcc.gov/",
    "https://www.fcc.gov/search/",
    "https://www.fcc.gov/search/#q=unlicensed%20spectrum",
]

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


def screenshot_name(url: str, index: int) -> str:
    parsed = urlparse(url)
    path = parsed.path.strip("/").replace("/", "_") or "home"
    fragment = parsed.fragment.replace("=", "_").replace("%20", "_") if parsed.fragment else ""
    suffix = f"_{fragment}" if fragment else ""
    return f"debug_fcc_basic_{index}_{path}{suffix}.png"


def launch_chromium(playwright):
    return playwright.chromium.launch(headless=True)


def launch_chrome(playwright):
    return playwright.chromium.launch(
        channel="chrome",
        headless=False,
        args=[
            "--disable-http2",
            "--disable-blink-features=AutomationControlled",
        ],
    )


def launch_firefox(playwright):
    return playwright.firefox.launch(headless=False)


def run_browser_tests(playwright, browser_name: str, launcher, debug_dir: Path) -> None:
    print(f"\n=== Navegador: {browser_name} ===")
    browser = None
    context = None
    try:
        browser = launcher(playwright)
        context = browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1366, "height": 768},
            locale="en-US",
        )
        page = context.new_page()

        for index, url in enumerate(URLS, start=1):
            print("\nNavegador:", browser_name)
            print("URL:", url)
            try:
                page.goto(url, wait_until="commit", timeout=30000)
                print("Estado: cargo")
                print("page.url:", page.url)
                print("page.title():", page.title())
                screenshot_path = debug_dir / f"{browser_name}_{screenshot_name(url, index)}"
                page.screenshot(path=str(screenshot_path), full_page=True)
                print("screenshot:", screenshot_path.resolve())
            except Exception as exc:
                print("Estado: fallo")
                print("page.url:", page.url)
                try:
                    print("page.title():", page.title())
                except Exception as title_exc:
                    print("page.title() fallo:", repr(title_exc))
                print("error:", repr(exc))
    except Exception as exc:
        print("Navegador:", browser_name)
        print("Estado: fallo al iniciar navegador")
        print("error:", repr(exc))
    finally:
        if context:
            context.close()
        if browser:
            browser.close()


def main() -> None:
    debug_dir = Path.cwd()
    print("Directorio de debug:", debug_dir.resolve())

    with sync_playwright() as playwright:
        run_browser_tests(playwright, "chromium-playwright", launch_chromium, debug_dir)
        run_browser_tests(playwright, "chrome-system", launch_chrome, debug_dir)
        run_browser_tests(playwright, "firefox-playwright", launch_firefox, debug_dir)


if __name__ == "__main__":
    main()
