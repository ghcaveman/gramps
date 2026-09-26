#!/usr/bin/env python3
# ---------------------------------------------------------------
#
# Gramps - a GTK+/GNOME based genealogy program
#
# ---------------------------------------------------------------
"""
Quick script to verify that Selenium can render JavaScript‑heavy pages.

It calls the same helper functions used by the Gramps HTML view, but
adds a site‑specific CSS selector to wait for the element that only
appears after the page’s JavaScript has finished loading.

Run it from the repository root:

    python test_js_render.py
"""

# -------------------------------------------------------------------------
# Standard Python modules
# -------------------------------------------------------------------------
import sys
from pathlib import Path

# -------------------------------------------------------------------------
# Third‑party modules
# -------------------------------------------------------------------------
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium_stealth import stealth
from selenium.webdriver.support.ui import WebDriverWait

# -------------------------------------------------------------------------
# Constants
# -------------------------------------------------------------------------
CHROME_BINARY = "C:/Program Files/Google/Chrome/Application/chrome.exe"

# -------------------------------------------------------------------------
# Helper – fetch a page with Selenium and wait for a selector
# -------------------------------------------------------------------------
def fetch_with_selenium(url: str, wait_selector: str | None = None,
                         timeout: int = 60) -> str:
    """
    Load *url* in a head‑less Chrome instance, apply stealth tricks,
    wait for ``document.readyState == "complete"`` and optionally for
    *wait_selector*, then return the page source.

    If anything goes wrong a short HTML comment with the error is
    returned (the same behaviour the Gramps scraper uses).
    """
    try:
        opts = Options()
        if CHROME_BINARY:
            opts.binary_location = CHROME_BINARY
        opts.add_argument("--headless=new")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-extensions")
        opts.add_argument("--disable-infobars")

        driver_path = ChromeDriverManager().install()
        service = Service(driver_path)
        driver = webdriver.Chrome(service=service, options=opts)

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

        # Wait for the document to be fully loaded.
        WebDriverWait(driver, timeout).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )

        # Optional extra wait for a specific element that appears after JS runs.
        if wait_selector:
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support import expected_conditions as EC

            WebDriverWait(driver, timeout).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, wait_selector))
            )

        html = driver.page_source
    except Exception as exc:  # pragma: no cover – defensive fallback
        html = f"<!-- Scrape error: {exc} -->"
    finally:
        try:
            driver.quit()
        except Exception:
            pass
    return html


# -------------------------------------------------------------------------
# Site‑specific configuration
# -------------------------------------------------------------------------
TEST_SITES = [
    {
        "url": 'https://www.archive.org/search.php?query="White+Milton"',
        # Archive.org loads the results into a <div id="search-results">
        "selector": "#search-results",
        "name": "Archive.org",
    },
    {
        "url": "https://openlibrary.org/search?q=White,%20Milton",
        # OpenLibrary puts the list of works in <ul class="searchResults">
        "selector": "ul.searchResults",
        "name": "OpenLibrary.org",
    },
    {
        "url": "https://www.google.com/search?q=White+Milton",
        # Google’s main result container has id “search”
        "selector": "#search",
        "name": "Google.com",
    },
    {
        "url": "https://www.familysearch.org/en/tree/person/details/GHR5-28Q",
        # FamilySearch renders the profile inside <section id="profile">
        "selector": "section#profile",
        "name": "FamilySearch.org",
    },
    {
        "url": "https://billiongraves.com/search/results?given_names=Milton&family_names=White&birth_year=1822&death_year=1898&size=15",
        # Results are placed in <div class="search-results">
        "selector": "div.search-results",
        "name": "BillionGraves.com",
    },
    {
        "url": "https://www.findagrave.com/memorial/search?firstname=Milton&middlename=&lastname=White&birthyear=1822&birthyearfilter=&deathyear=1898&deathyearfilter=&location=&locationId=&bio=&linkedToName=&plot=&memorialid=&mcid=&datefilter=&orderby=r",
        # FindAGrave puts hits in <div class="search-results">
        "selector": "div.search-results",
        "name": "FindAGrave.com",
    },
]

# -------------------------------------------------------------------------
# Main driver
# -------------------------------------------------------------------------
def main() -> None:
    out_dir = Path("selenium_test_output")
    out_dir.mkdir(exist_ok=True)

    for site in TEST_SITES:
        print(f"\nFetching {site['name']} …")
        html = fetch_with_selenium(
            site["url"], wait_selector=site["selector"], timeout=60
        )
        # Save a short snippet for quick inspection
        snippet_path = out_dir / f"{site['name'].replace('.', '_')}.html"
        snippet_path.write_text(html, encoding="utf-8")
        print(f"  → saved {snippet_path} (length {len(html)} chars)")

        # Quick sanity check – print the first <title> tag if present
        title_start = html.find("<title>")
        title_end = html.find("</title>", title_start + 1)
        if 0 <= title_start < title_end:
            print("  Title:", html[title_start + 7 : title_end].strip())
        else:
            print("  No <title> found – page may still be the “JavaScript required” placeholder.")


if __name__ == "__main__":
    # Ensure the script can be run from the repository root even when the
    # current working directory is elsewhere.
    sys.path.append(str(Path(__file__).parent.parent))
    main()
