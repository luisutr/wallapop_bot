from __future__ import annotations

from typing import Callable, Optional

from playwright.sync_api import sync_playwright

from config import WALLAPOP_STATE_PATH, SESIONES_DIR


def guardar_sesion_wallapop(
    wait_fn: Optional[Callable[[], None]] = None,
) -> None:
    """
    Abre Chromium para login en Wallapop y guarda storage_state.

    wait_fn: si se pasa (p. ej. desde la GUI), se llama en lugar de input()
             cuando el usuario confirma que ya inició sesión.
    """
    SESIONES_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
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
