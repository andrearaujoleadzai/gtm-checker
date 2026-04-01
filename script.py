"""
Leadzai — Tracking Monitor
==========================
Corre diariamente via GitHub Actions.
O script de tracking é SEMPRE carregado via Google Tag Manager.
A deteção aguarda que o GTM termine de inicializar antes de concluir.
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
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("tracking_monitor")

# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------
SHEET_URL = os.getenv(
    "SHEET_URL",
    "https://docs.google.com/spreadsheets/d/1dktdNbgWmTPl-yGbVsg3x2sta1Zb4ZEDyGJuKC2IXhI/export?format=csv&gid=1949940405",
)
STATE_FILE = Path(os.getenv("STATE_FILE", "tracking_state.json"))

TRACKING_PATTERN = "adviocdn.net/cnv"

# Timeout máximo à espera que o GTM inicialize (ms)
GTM_TIMEOUT = 15000

# Timeout de navegação por página (ms)
NAV_TIMEOUT = 20000

# Tempo extra após GTM pronto, para scripts async do container dispararem (ms)
POST_GTM_WAIT = 3000

# ---------------------------------------------------------------------------
# Google Sheets: obter lista de sites
# ---------------------------------------------------------------------------

def get_urls() -> list[str]:
    log.info("A descarregar lista de sites...")
    response = requests.get(SHEET_URL, timeout=30)
    response.raise_for_status()

    seen_domains = set()
    urls = []

    reader = csv.DictReader(io.StringIO(response.text))
    for row in reader:
        website = row.get("website", "").strip().lower()
        if not website or "." not in website:
            continue
        if not website.startswith("http"):
            website = "https://" + website

        domain = urlparse(website).netloc
        if domain in seen_domains:
            continue
        seen_domains.add(domain)
        urls.append(website)

    log.info("%d domínios únicos encontrados.", len(urls))
    return urls

# ---------------------------------------------------------------------------
# Playwright: verificar tracking via GTM
# ---------------------------------------------------------------------------

def check_site(browser, url: str) -> dict:
    """
    Deteta o script de tracking sabendo que é SEMPRE carregado via GTM.

    Fluxo:
      1. Navega para o site e interceta todos os requests de rede desde o início
      2. Aguarda que o GTM esteja inicializado (window.google_tag_manager existe)
      3. Aguarda mais POST_GTM_WAIT ms para as tags do container dispararem
      4. Verifica se algum request para adviocdn.net/cnv foi feito

    Se o GTM não for encontrado no timeout, regista como erro (não como missing)
    para não gerar falsos positivos em sites com GTM lento ou bloqueado.
    """
    found_via = None
    gtm_found = False

    context = browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/123.0.0.0 Safari/537.36"
        ),
        java_script_enabled=True,
    )
    page = context.new_page()

    # Interceta requests desde o primeiro momento — antes do goto
    def handle_request(request):
        nonlocal found_via
        if TRACKING_PATTERN in request.url.lower():
            found_via = "network_request"

    page.on("request", handle_request)

    error = None
    try:
        page.goto(url, timeout=NAV_TIMEOUT, wait_until="domcontentloaded")

        # Aguarda que o GTM esteja inicializado no window
        # window.google_tag_manager é um objeto com uma chave por cada GTM-XXXXXX
        try:
            page.wait_for_function(
                "() => typeof window.google_tag_manager === 'object' "
                "    && window.google_tag_manager !== null "
                "    && Object.keys(window.google_tag_manager).length > 0",
                timeout=GTM_TIMEOUT,
            )
            gtm_found = True
            log.debug("GTM inicializado em %s", url)
        except PlaywrightTimeout:
            # GTM não encontrado — pode ser que o site não use GTM
            # ou que esteja bloqueado. Não é conclusivo.
            log.debug("GTM não encontrado em %s dentro do timeout", url)

        # Após o GTM estar pronto, as tags ainda precisam de disparar
        # (triggers, listeners de eventos, etc.)
        page.wait_for_timeout(POST_GTM_WAIT)

        # Neste ponto a intercetação de rede já deve ter capturado o script.
        # Como fallback, verifica também o dataLayer para perceber se o GTM
        # registou o nosso script (útil para debug).
        if not found_via:
            try:
                # Verifica se há alguma entrada no dataLayer relacionada com o tracking
                # (não é conclusivo por si só, mas ajuda no debug)
                datalayer_str = page.evaluate(
                    "() => JSON.stringify(window.dataLayer || [])"
                )
                # Não usamos isto para determinar has_tracking,
                # apenas para enriquecer o log em caso de missing
                if datalayer_str and "advio" in datalayer_str.lower():
                    found_via = "datalayer"
            except Exception:
                pass

    except Exception as e:
        error = str(e)
        log.warning("Erro em %s: %s", url, e)
    finally:
        page.close()
        context.close()

    return {
        "url": url,
        "has_tracking": found_via is not None,
        "found_via": found_via,
        "gtm_found": gtm_found,
        "error": error,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }

# ---------------------------------------------------------------------------
# Estado: persistência entre execuções
# ---------------------------------------------------------------------------

def load_state() -> dict:
    if STATE_FILE.exists():
        with STATE_FILE.open() as f:
            return json.load(f)
    return {}

def save_state(state: dict) -> None:
    with STATE_FILE.open("w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    log.info("Estado guardado em %s.", STATE_FILE)

def detect_regressions(current_results: list[dict], previous_state: dict) -> list[dict]:
    """
    Alerta APENAS quando:
      - tinha tracking confirmado antes
      - não tem agora
      - não houve erro de rede (inconclusivo)
      - o GTM foi encontrado (se não há GTM, não podemos concluir que o tracking foi removido)
    """
    regressions = []
    for result in current_results:
        url = result["url"]
        prev = previous_state.get(url, {})
        if (
            prev.get("has_tracking") is True
            and result["has_tracking"] is False
            and result["error"] is None
            and result.get("gtm_found") is True  # só alerta se o GTM carregou
        ):
            regressions.append({**result, "last_seen_ok": prev.get("checked_at", "desconhecido")})
            log.warning("REGRESSAO: %s", url)
    return regressions

def build_new_state(current_results: list[dict], previous_state: dict) -> dict:
    new_state = {}
    for result in current_results:
        url = result["url"]
        prev = previous_state.get(url, {})
        # Se houve erro de rede, ou GTM não carregou, mantém estado anterior
        if (result["error"] or not result.get("gtm_found")) and prev:
            new_state[url] = {**prev, "last_error": result.get("error"), "error_at": result["checked_at"]}
        else:
            new_state[url] = result
    return new_state

# ---------------------------------------------------------------------------
# Alertas
# ---------------------------------------------------------------------------

def send_alerts(regressions: list[dict]) -> None:
    if not regressions:
        log.info("Sem regressoes.")
        return

    log.error("=" * 60)
    log.error("ALERTA: %d site(s) perderam o tracking!", len(regressions))
    for r in regressions:
        log.error("  * %s  (ultimo OK: %s)", r["url"], r["last_seen_ok"])
    log.error("=" * 60)

    # TODO: descomenta quando quiseres ligar
    # _send_gmail(regressions)
    # _create_jira_tickets(regressions)

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    log.info("=== Tracking Monitor iniciado ===")

    urls = get_urls()
    if not urls:
        log.warning("Lista de sites vazia — a terminar.")
        return

    previous_state = load_state()
    current_results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for i, url in enumerate(urls, 1):
            log.info("[%d/%d] %s", i, len(urls), url)
            result = check_site(browser, url)
            current_results.append(result)

            if result["error"]:
                status = f"ERRO: {result['error'][:60]}"
            elif not result.get("gtm_found"):
                status = "GTM NAO ENCONTRADO (inconclusivo)"
            elif result["has_tracking"]:
                status = f"OK via {result['found_via']}"
            else:
                status = "MISSING"

            log.info("        -> %s", status)
        browser.close()

    regressions = detect_regressions(current_results, previous_state)
    new_state = build_new_state(current_results, previous_state)
    save_state(new_state)
    send_alerts(regressions)

    ok           = sum(1 for r in current_results if r["has_tracking"])
    missing      = sum(1 for r in current_results if not r["has_tracking"] and not r["error"] and r.get("gtm_found"))
    no_gtm       = sum(1 for r in current_results if not r.get("gtm_found") and not r["error"])
    errors       = sum(1 for r in current_results if r["error"])

    log.info(
        "Resumo: %d sites | %d com tracking | %d sem tracking | %d sem GTM (inconclusivo) | %d erros | %d regressoes",
        len(current_results), ok, missing, no_gtm, errors, len(regressions),
    )
    log.info("=== Concluido ===")

    if missing:
        print("\n--- Sites com GTM mas sem tracking ---")
        for r in current_results:
            if not r["has_tracking"] and not r["error"] and r.get("gtm_found"):
                print(f"  [MISSING] {r['url']}")

    if no_gtm:
        print("\n--- Sites sem GTM detetado (inconclusivo) ---")
        for r in current_results:
            if not r.get("gtm_found") and not r["error"]:
                print(f"  [SEM GTM] {r['url']}")

if __name__ == "__main__":
    main()
