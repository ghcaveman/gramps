# ---------------------------------------------------------------
#
# Gramps - a GTK+/GNOME based genealogy program
#
# ---------------------------------------------------------------
"""Utility for asynchronous web‑scraping using Selenium.

Provides both asynchronous (threaded) and synchronous helpers that load a URL
with a headless Chrome instance, apply ``selenium‑stealth`` tricks, and return
the rendered HTML.  The asynchronous version delivers the result to the GTK
main loop via ``GLib.idle_add``.
"""

# -------------------------------------------------------------------------
# Standard Python modules
# -------------------------------------------------------------------------
import threading
from typing import Callable

# -------------------------------------------------------------------------
# GTK/Gnome modules
# -------------------------------------------------------------------------
from gi.repository import GLib

# -------------------------------------------------------------------------
# Third‑party modules
# -------------------------------------------------------------------------
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium_stealth import stealth

# -------------------------------------------------------------------------
# Constants
# -------------------------------------------------------------------------
CHROME_BINARY = "C:/Program Files/Google/Chrome/Application/chrome.exe"


class _ScrapeThread(threading.Thread):
    """Thread that performs the Selenium scrape.

    Parameters
    ----------
    url: str
        The page to load.
    callback: Callable[[str], bool]
        Function called on the GTK main thread with the page HTML. It must
        return ``True`` to keep the idle handler alive or ``False`` to stop.
    """

    def __init__(self, url: str, callback: Callable[[str], bool]):
        super().__init__(daemon=True)
        self.url = url
        self.callback = callback

    def run(self) -> None:  # pragma: no cover – exercised via integration test
        """Background thread entry point for Selenium scraping.

        Mirrors :func:`scrape_page_direct` but returns the result to the GTK main
        loop via ``GLib.idle_add``.
        """
        try:
            options = Options()
            if CHROME_BINARY:
                options.binary_location = CHROME_BINARY
            options.add_argument("--headless=new")
            options.add_argument("--disable-gpu")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-extensions")
            options.add_argument("--disable-infobars")

            driver_path = ChromeDriverManager().install()
            service = Service(driver_path)
            driver = webdriver.Chrome(service=service, options=options)

            stealth(
                driver,
                languages=["en-US", "en"],
                vendor="Google Inc.",
                platform="Win32",
                webgl_vendor="Intel Inc.",
                renderer="Intel Iris OpenGL Engine",
                fix_hairline=True,
            )

            driver.set_page_load_timeout(30)
            driver.get(self.url)

            from selenium.webdriver.support.ui import WebDriverWait

            WebDriverWait(30).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
            html = driver.page_source
        except Exception as exc:  # pragma: no cover – defensive fallback
            html = f"<!-- Scrape error: {exc} -->"
        finally:
            try:
                driver.quit()
            except Exception:
                pass

        GLib.idle_add(self.callback, html)


def scrape_page_async(url: str, callback: Callable[[str], bool]) -> None:
    """Start an asynchronous scrape of *url*.

    The *callback* receives the rendered HTML on the GTK main thread. It must
    return ``False`` to stop the idle handler.
    """
    thread = _ScrapeThread(url, callback)
    thread.start()


def scrape_page_direct(
    url: str, wait_selector: str | None = None, timeout: int = 30
) -> str:
    """Fetch *url* synchronously using Selenium and return the rendered HTML.

    *wait_selector* can be supplied to wait for a specific element after the
    document reports ``readyState == "complete"``.
    """
    try:
        options = Options()
        if CHROME_BINARY:
            options.binary_location = CHROME_BINARY
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")

        driver_path = ChromeDriverManager().install()
        service = Service(driver_path)
        driver = webdriver.Chrome(service=service, options=options)

        stealth(
            driver,
            languages=["en-US", "en"],
            vendor="Google Inc.",
            platform="Win32",
            webgl_vendor="Intel Inc.",
            renderer="Intel Iris OpenGL Engine",
            fix_hairline=True,
        )

        driver.set_page_load_timeout(timeout)
        driver.get(url)

        from selenium.webdriver.support.ui import WebDriverWait

        WebDriverWait(driver, timeout).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
        if wait_selector:
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support import expected_conditions as EC

            WebDriverWait(driver, timeout).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, wait_selector))
            )
        html = driver.page_source
    except Exception as exc:  # pragma: no cover – defensive fallback
        html = f"<!-- Scrape error: {exc} -->"
        try:
            from pathlib import Path

            Path("htmlview.log").open("a", encoding="utf-8").write(
                f"Selenium scrape failed for {url}: {exc}\n"
            )
        except Exception:
            pass
    finally:
        try:
            driver.quit()
        except Exception:
            pass
    return html
