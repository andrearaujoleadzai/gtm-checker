import csv
import requests
from playwright.sync_api import sync_playwright

SHEET_URL = "https://docs.google.com/spreadsheets/d/1dktdNbgWmTPl-yGbVsg3x2sta1Zb4ZEDyGJuKC2IXhI/export?format=csv&gid=1949940405"


def get_urls():
    response = requests.get(SHEET_URL)
    response.raise_for_status()

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
    found = False

    def handle_request(request):
        nonlocal found
        if "adviocdn.net/cnv" in request.url.lower():
            found = True

    page.on("request", handle_request)

    try:
        page.goto(url, timeout=20000)

        # esperar carregamento completo (mais fiável)
        page.wait_for_load_state("networkidle")

        # 🔍 check adicional via DOM (backup)
        scripts = page.query_selector_all("script[src]")

        for script in scripts:
            src = script.get_attribute("src")
            if src and "adviocdn.net/cnv" in src.lower():
                found = True
                break

        if found:
            return None
        else:
            return url

    except Exception as e:
        print(f"Erro em {url}: {e}")
        return None

    finally:
        # limpar listeners para evitar acumulação
        page.remove_listener("request", handle_request)


def main():
    urls = get_urls()

    missing = []
    checked = 0
    failed = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        for url in urls:
            result = check_site(page, url)

            if result is None:
                checked += 1
            else:
                missing.append(result)
                checked += 1

        browser.close()

    print(f"\nChecked: {checked}")
    print(f"Missing tracking: {len(missing)}\n")

    for site in missing:
        print(site)


if __name__ == "__main__":
    main()
