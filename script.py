"""
Leadzai — Tracking Monitor (FINAL)
=================================
✔ Suporta GTM + Consent Mode
✔ Aceita cookies automaticamente
✔ Faz reload após consentimento (CRÍTICO)
✔ Deteta tracking via network + DOM
✔ Minimiza falsos negativos
"""

import csv
import io
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
)
log = logging.getLogger("tracking_monitor")

SHEET_URL = os.getenv(
    "SHEET_URL",
    "https://docs.google.com/spreadsheets/d/1dktdNbgWmTPl-yGbVsg3x2sta1Zb4ZEDyGJuKC2IXhI/export?format=csv&gid=1949940405",
)

STATE_FILE = Path("tracking_state.json")
TRACKING_PATTERN = "adviocdn.net/cnv"

GTM_TIMEOUT = 15000
NAV_TIMEOUT = 20000
POST_GTM_WAIT = 3000


# ---------------------------------------------------------------------------
# URLs
# ---------------------------------------------------------------------------
def get_urls():
    response = requests.get(SHEET_URL)
    response.raise_for_status()

    seen = set()
    urls = []

    reader = csv.DictReader(io.StringIO(response.text))
    for row in reader:
        website = row.get("website", "").strip().lower()

        if not website or "." not in website:
            continue

        if not website.startswith("http"):
            website = "https://" + website

        domain = urlparse(website).netloc
        if domain in seen:
            continue

        seen.add(domain)
        urls.append(website)

    return urls


# ---------------------------------------------------------------------------
# COOKIE CONSENT
# ---------------------------------------------------------------------------
def accept_cookies(page):
    try:
        selectors = [
            "button:has-text('Accept')",
            "button:has-text('I agree')",
            "button:has-text('Agree')",
            "button:has-text('Aceitar')",
            "button:has-text('Aceito')",
            "button:has-text('Aceptar')",
            "button:has-text('Allow all')",
        ]

        for selector in selectors:
            try:
                btn = page.locator(selector).first
                if btn.is_visible(timeout=2000):
                    btn.click()
                    page.wait_for_timeout(1000)
                    return True
            except:
                continue

        # fallback JS (CMPs comuns)
        page.evaluate("""
            () => {
                if (window.Cookiebot) {
                    Cookiebot.submitConsent(true, true, true);
                }
                if (window.OneTrust) {
                    try { OneTrust.AcceptAllConsent(); } catch(e){}
                }
                document.cookie = "cookie_consent=true; path=/";
            }
        """)

        page.wait_for_timeout(1000)

    except:
        pass

    return False


# ---------------------------------------------------------------------------
# CHECK SITE
# ---------------------------------------------------------------------------
def check_site(browser, url):
    found = False
    gtm_found = False
    error = None

    context = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        java_script_enabled=True,
    )

    page = context.new_page()

    def handle_request(request):
        nonlocal found
        if TRACKING_PATTERN in request.url.lower():
            found = True

    page.on("request", handle_request)

    try:
        # 1. primeira navegação
        page.goto(url, timeout=NAV_TIMEOUT, wait_until="domcontentloaded")

        # 2. aceitar cookies
        accept_cookies(page)

        # 3. pequena espera
        page.wait_for_timeout(2000)

        # 🔥 4. reload após consentimento (CRÍTICO)
        page.reload(wait_until="domcontentloaded")

        # 5. esperar GTM após reload
        try:
            page.wait_for_function(
                "() => window.google_tag_manager && Object.keys(window.google_tag_manager).length > 0",
                timeout=GTM_TIMEOUT,
            )
            gtm_found = True
        except PlaywrightTimeout:
            pass

        # 6. esperar triggers do GTM
        page.wait_for_timeout(POST_GTM_WAIT)

        # 7. fallback DOM check
        if not found:
            scripts = page.query_selector_all("script[src]")
            for s in scripts:
                src = s.get_attribute("src")
                if src and TRACKING_PATTERN in src.lower():
                    found = True
                    break

    except Exception as e:
        error = str(e)
        log.warning(f"Erro em {url}: {e}")

    finally:
        page.close()
        context.close()

    return {
        "url": url,
        "has_tracking": found,
        "gtm_found": gtm_found,
        "error": error,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# STATE
# ---------------------------------------------------------------------------
def load_state():
    if STATE_FILE.exists():
        return json.load(open(STATE_FILE))
    return {}


def save_state(state):
    json.dump(state, open(STATE_FILE, "w"), indent=2)


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def main():
    urls = get_urls()
    previous = load_state()

    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        for i, url in enumerate(urls, 1):
            log.info(f"[{i}/{len(urls)}] {url}")
            result = check_site(browser, url)
            results.append(result)

            if result["error"]:
                log.info("   -> ERRO")
            elif not result["gtm_found"]:
                log.info("   -> SEM GTM")
            elif result["has_tracking"]:
                log.info("   -> OK")
            else:
                log.info("   -> MISSING")

        browser.close()

    save_state({r["url"]: r for r in results})

    missing = [
        r["url"]
        for r in results
        if not r["has_tracking"] and not r["error"] and r["gtm_found"]
    ]

    print("\n--- RESULTADO ---")
    print(f"Total: {len(results)}")
    print(f"Missing: {len(missing)}\n")

    for m in missing:
        print(m)


if __name__ == "__main__":
    main()
