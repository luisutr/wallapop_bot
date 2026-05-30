from __future__ import annotations

from typing import Callable, Optional
import os

from playwright.sync_api import sync_playwright

from config import WALLAPOP_STATE_PATH, SESIONES_DIR


def guardar_sesion_wallapop(
    wait_fn: Optional[Callable[[], None]] = None,
) -> None:
    """
    Abre Chrome/Chromium con Playwright con flags anti-detección para login en Wallapop.
    """
    SESIONES_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        try:
            print("Lanzando Chrome oficial con evasión de automatización...")
            browser = p.chromium.launch(
                headless=False,
                channel="chrome",
                args=["--disable-blink-features=AutomationControlled"],
                ignore_default_args=["--enable-automation"]
            )
        except Exception:
            print("Chrome oficial no disponible. Lanzando Chromium de Playwright con evasión...")
            browser = p.chromium.launch(
                headless=False,
                args=["--disable-blink-features=AutomationControlled"],
                ignore_default_args=["--enable-automation"]
            )

        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        page.goto("https://es.wallapop.com/app/")

        if wait_fn:
            wait_fn()
        else:
            print("\n→ Inicia sesión en Wallapop y pulsa ENTER aquí...")
            input("  [ENTER cuando hayas iniciado sesión] ")

        context.storage_state(path=str(WALLAPOP_STATE_PATH))
        browser.close()

    print(f"  ✓ Sesión guardada en {WALLAPOP_STATE_PATH}")
