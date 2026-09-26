# selenium_check_debug.py
# ---------------------------------------------------------
# Standard Python modules
# ---------------------------------------------------------
import sys
import platform
import shutil
import traceback

print("🔹 Script started – Python version:", sys.version.split()[0])
print("🔹 Platform:", platform.system(), platform.release())

# ---------------------------------------------------------
# Selenium / WebDriver‑Manager
# ---------------------------------------------------------
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    from webdriver_manager.chrome import ChromeDriverManager
    print("✅ Imported Selenium & webdriver‑manager")
except Exception as exc:
    print("❌ FAILED to import Selenium or webdriver‑manager")
    traceback.print_exc()
    sys.exit(1)

def _chrome_executable() -> str | None:
    """Return the full path to a Chrome/Chromium binary, or None."""
    candidates = {
        "Windows": ["chrome.exe", "chromium.exe"],
        "Darwin":  ["google-chrome", "chromium", "chrome"],
        "Linux":   ["google-chrome", "chromium-browser", "chromium", "chrome"],
    }.get(platform.system(), [])
    for name in candidates:
        path = shutil.which(name)
        if path:
            return path
    return None

def main() -> None:
    print("\n🔹 Beginning Selenium sanity‑check …")

    # 1️⃣  Find Chrome/Chromium
    chrome_path = _chrome_executable()
    if not chrome_path:
        print("❌ No Chrome/Chromium executable found on PATH.")
        print("   Install Google Chrome (or Chromium) and ensure its folder is on PATH.")
        sys.exit(1)
    print(f"✅ Chrome binary found: {chrome_path}")

    # 2️⃣  Build head‑less options
    chrome_options = webdriver.ChromeOptions()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    print("✅ Chrome options prepared (head‑less)")

    # 3️⃣  Download / locate matching ChromeDriver
    try:
        driver_path = ChromeDriverManager().install()
        print(f"✅ ChromeDriver ready at: {driver_path}")
    except Exception as exc:
        print("❌ ChromeDriver download/lookup failed")
        traceback.print_exc()
        sys.exit(1)

    # 4️⃣  Start the driver (Selenium 4 API – Service + options)
    try:
        service = Service(driver_path)
        driver = webdriver.Chrome(service=service, options=chrome_options)
        print("✅ ChromeDriver started successfully")
    except Exception as exc:
        print("❌ Could NOT start ChromeDriver")
        traceback.print_exc()
        sys.exit(1)

    # 5️⃣  Load a page that needs JavaScript
    test_url = "https://www.archive.org/search.php?query=White+Milton"
    print(f"🔹 Loading test URL: {test_url}")
    try:
        driver.get(test_url)
        print("✅ Page fetched")
        print("🗒️  Page title:", driver.title)
    except Exception as exc:
        print("❌ Error while loading the page")
        traceback.print_exc()
    finally:
        driver.quit()
        print("✅ ChromeDriver shut down cleanly")

if __name__ == "__main__":
    # Run with unbuffered output so you see everything immediately
    # (you can also invoke the script with `python -u selenium_check_debug.py`)
    main()
