import csv
import requests
from playwright.sync_api import sync_playwright

SHEET_URL = "https://docs.google.com/spreadsheets/d/1dktdNbgWmTPl-yGbVsg3x2sta1Zb4ZEDyGJuKC2IXhI/export?format=csv&gid=1949940405"

def get_urls():
    response = requests.get(SHEET_URL)
    lines = response.text.splitlines()
    reader = csv.DictReader(lines)

    urls = []
    for row in reader:
        website = row.get("website")
        if website:
            website = website.strip().lower()
            if "." not in website:
                continue
            if not website.startswith("http"):
                website = "https://" + website
            urls.append(website)
    return urls


def check_site(page, url):
    try:
        page.goto(url, timeout=15000)

        # esperar carregamento JS
        page.wait_for_timeout(3000)

        html = page.content().lower()

        if "adviocdn.net/cnv" not in html:
            return url

    except:
        return None


def main():
    urls = get_urls()
    missing = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        for url in urls:
            result = check_site(page, url)
            if result:
                missing.append(result)

        browser.close()

    print(f"Checked: {len(urls)}")
    print(f"Missing tracking: {len(missing)}")

    for site in missing:
        print(site)


if __name__ == "__main__":
    main()
