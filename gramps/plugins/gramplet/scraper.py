# ---------------------------------------------------------------
#
# Gramps - a GTK+/GNOME based genealogy program
#
# Copyright (C) 2026  OpenAI ChatGPT
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#
# ---------------------------------------------------------------

"""Utility for asynchronous web‑scraping using Selenium.

The :func:`scrape_page_async` function starts a background thread that
loads the given URL with a headless Chrome instance, applies the
``selenium_stealth`` tricks to bypass basic bot detection, extracts the
page HTML and returns it to the caller via a callback executed in the
GTK main loop using :func:`GLib.idle_add`.

Typical usage from a GTK widget::

    from gramps.plugins.gramplet.scraper import scrape_page_async

    def on_page_ready(html: str) -> bool:
        # update UI here
        self.textview.get_buffer().set_text(html)
        return False  # stop idle handler

    scrape_page_async("https://example.com", on_page_ready)

The implementation respects the project's coding standards: type hints,
Black‑compatible formatting, and a GPL‑2.0‑or‑later header.
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
# webdriver‑manager will download a matching ChromeDriver automatically
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
        try:
        options = Options()
        options.binary_location = CHROME_BINARY
        # Headless mode – use the new headless implementation
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        # Prevent Chrome from showing dialogs that could block the thread
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        # Chrome needs a writable temporary user‑data directory.  On Windows the
        # default location can be a protected folder, causing the
        # "cannot create temp dir for user data dir" error.  We explicitly point
        # it to a safe temporary directory.
        import tempfile, os
        temp_dir = tempfile.mkdtemp(prefix="chromedriver_user_data_")
        options.add_argument(f"--user-data-dir={temp_dir}")

            # Selenium manager will download the driver if needed via webdriver‑manager
            driver_path = ChromeDriverManager().install()
            service = Service(driver_path)
            driver = webdriver.Chrome(service=service, options=options)

            # Apply stealth tricks – these are the defaults recommended by the
            # library; they can be tweaked if required.
            stealth(
                driver,
                languages=["en-US", "en"],
                vendor="Google Inc.",
                platform="Win32",
                webgl_vendor="Intel Inc.",
                renderer="Intel Iris OpenGL Engine",
                fix_hairline=True,
            )

            driver.get(self.url)
            html = driver.page_source
        except Exception as exc:  # pragma: no cover – defensive
            html = f"<!-- Scrape error: {exc} -->"
        finally:
            try:
                driver.quit()
            except Exception:
                pass

        # Pass the result back to the GTK main loop safely.
        GLib.idle_add(self.callback, html)


def scrape_page_async(url: str, callback: Callable[[str], bool]) -> None:
    """Start an asynchronous scrape of *url*.

    The *callback* receives the HTML string and is executed in the GTK main
    thread via :func:`GLib.idle_add`. The callback should return ``False`` to
    indicate that the idle handler can be removed.
    """

    thread = _ScrapeThread(url, callback)
    thread.start()


def scrape_page_sync(url: str) -> str:
    """Fetch *url* synchronously and return the rendered HTML.

    This helper is used by the non‑GTK parts of Gramps (e.g. ``HtmlBridge``)
    where we need the HTML immediately.  It starts a ``_ScrapeThread`` with a
    tiny callback that stores the result in a list and signals a ``threading``
    ``Event``.  The calling thread then blocks on the event until the scrape
    finishes and returns the captured HTML string.
    """
    # Container for the result – using a list avoids the need for ``nonlocal``
    # in the inner callback.
    result: list[str] = []
    done = threading.Event()

    def _cb(html: str) -> bool:
        result.append(html)
        done.set()
        # Returning ``False`` tells GLib to remove the idle handler (not that it
        # matters here because we are not in the GTK main loop).
        return False

    thread = _ScrapeThread(url, _cb)
    thread.start()
    # Wait for the background thread to finish fetching.
    done.wait()
    return result[0] if result else ""


def scrape_page_direct(url: str, wait_selector: str | None = None, timeout: int = 30) -> str:
    """Fetch *url* synchronously using Selenium and return the rendered HTML.

    * **Head‑less Chrome** is started, the page is loaded, and we wait until the
      browser reports that the document is fully loaded (``document.readyState ==
      "complete"``).  If *wait_selector* is supplied we additionally wait for an
      element matching that CSS selector to appear – this is useful for pages
      that load content via AJAX after the initial document load.
    * The driver is **always quit** before the function returns, so no stray
      Chrome windows remain.
    * Any exception is caught and turned into an HTML comment so the caller
      never crashes; the comment is also written to ``htmlview.log`` for
      debugging.
    """
    try:
        options = Options()
        options.binary_location = CHROME_BINARY
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")

        driver_path = ChromeDriverManager().install()
        service = Service(driver_path)
        driver = webdriver.Chrome(service=service, options=options)

        # Apply the same stealth tricks used in the async version.
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

        # -----------------------------------------------------------------
        # 1️⃣  Wait for the document to be fully loaded.
        # -----------------------------------------------------------------
        driver.execute_script("return document.readyState")  # force a poll
        from selenium.webdriver.support.ui import WebDriverWait
        WebDriverWait(driver, timeout).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )

        # -----------------------------------------------------------------
        # 2️⃣  Optional extra wait for a specific element (useful for AJAX).
        # -----------------------------------------------------------------
        if wait_selector:
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support import expected_conditions as EC
            WebDriverWait(driver, timeout).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, wait_selector))
            )

        html = driver.page_source
    except Exception as exc:  # pragma: no cover – defensive fallback
        html = f"<!-- Scrape error: {exc} -->"
        # Write a short note to the workspace log for easier debugging.
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
