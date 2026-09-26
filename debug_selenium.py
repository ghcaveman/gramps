# debug_selenium.py
import os
import sys
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager

print("Python:", sys.version.split()[0])
print("TMP:", os.getenv("TMP"))
print("TEMP:", os.getenv("TEMP"))
print("USERPROFILE:", os.getenv("USERPROFILE"))

options = Options()
options.add_argument("--headless=new")
options.add_argument("--disable-gpu")
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")
# optional extra stability flags
options.add_argument("--disable-extensions")
options.add_argument("--disable-infobars")

# Let webdriver‑manager download the driver for you
driver_path = ChromeDriverManager().install()
service = Service(driver_path)

print("Driver path:", driver_path)

try:
    driver = webdriver.Chrome(service=service, options=options)
    driver.get("https://www.google.com")
    print("Page title:", driver.title)
    driver.quit()
except Exception as exc:
    print("Selenium failed:", exc)
    raise
