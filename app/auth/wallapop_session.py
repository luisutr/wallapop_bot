from __future__ import annotations

from playwright.sync_api import sync_playwright

from config import WALLAPOP_STATE_PATH, SESIONES_DIR


def guardar_sesion_wallapop() -> None:
    """
    Abre un navegador Chromium para que el usuario inicie sesión en Wallapop
    manualmente, y guarda el estado de sesión en sesiones/wallapop_state.json.
    """
    SESIONES_DIR.mkdir(parents=True, exist_ok=True)

    print("\n→ Abriendo navegador Wallapop...")
    print("  Inicia sesión con tu cuenta y pulsa ENTER aquí cuando termines.\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto("https://es.wallapop.com/app/")
        input("  [Pulsa ENTER cuando hayas iniciado sesión] ")
        context.storage_state(path=str(WALLAPOP_STATE_PATH))
        browser.close()

    print(f"  ✓ Sesión Wallapop guardada en {WALLAPOP_STATE_PATH}\n")
