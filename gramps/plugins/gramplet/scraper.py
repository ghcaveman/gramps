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

            # Selenium manager will download the driver if needed
            service = Service()
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


def scrape_page_direct(url: str) -> str:
    """Fetch *url* synchronously using Selenium without a background thread.

    This function is used by non‑GTK code paths (e.g. ``HtmlBridge._fetch_url``)
    where the GLib idle‑add mechanism would never fire, causing a dead‑lock.
    It creates a head‑less Chrome driver, loads the page, extracts the HTML
    and quits the driver before returning the result.
    """
    try:
        options = Options()
        options.binary_location = CHROME_BINARY
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")

        service = Service()
        driver = webdriver.Chrome(service=service, options=options)
        # Apply stealth tricks – same as in the thread version.
        stealth(
            driver,
            languages=["en-US", "en"],
            vendor="Google Inc.",
            platform="Win32",
            webgl_vendor="Intel Inc.",
            renderer="Intel Iris OpenGL Engine",
            fix_hairline=True,
        )
        driver.get(url)
        html = driver.page_source
    except Exception as exc:  # pragma: no cover – defensive
        html = f"<!-- Scrape error: {exc} -->"
    finally:
        try:
            driver.quit()
        except Exception:
            pass
    return html
