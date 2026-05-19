from __future__ import annotations

import os
from typing import Callable, Optional

import certifi

from config import SESIONES_DIR, WALLAPOP_STATE_PATH

from ._playwright_storage import (
    read_local_storage,
    save_storage_state,
    selenium_cookies_to_playwright,
)

WALLAPOP_ORIGIN = "https://es.wallapop.com"
WALLAPOP_LOGIN_URL = f"{WALLAPOP_ORIGIN}/app/"


def guardar_sesion_wallapop(
    wait_fn: Optional[Callable[[], None]] = None,
) -> None:
    """
    Abre Chrome sin detección de bots para login en Wallapop y guarda storage_state.

    Playwright Chromium suele activar captchas invisibles en el login por correo;
    undetected_chromedriver evita ese bloqueo en la mayoría de casos.

    wait_fn: si se pasa (p. ej. desde la GUI), se llama en lugar de input()
             cuando el usuario confirma que ya inició sesión.
    """
    SESIONES_DIR.mkdir(parents=True, exist_ok=True)
    os.environ["SSL_CERT_FILE"] = certifi.where()

    try:
        import undetected_chromedriver as uc
    except ImportError as exc:
        hint = (
            "pip install undetected-chromedriver setuptools"
            if "distutils" in str(exc).lower()
            else "pip install undetected-chromedriver"
        )
        raise RuntimeError(
            f"No se pudo cargar undetected-chromedriver ({exc}). Ejecuta: {hint}"
        ) from exc

    options = uc.ChromeOptions()
    options.add_argument("--window-size=1280,900")
    options.add_argument("--lang=es-ES")

    driver = uc.Chrome(options=options, use_subprocess=True)
    try:
        driver.get(WALLAPOP_LOGIN_URL)

        if wait_fn:
            wait_fn()
        else:
            print("\n→ Inicia sesión en Wallapop (Chrome) y pulsa ENTER aquí...")
            print("  Consejo: si el correo pide captcha, prueba «Continuar con Google».")
            input("  [ENTER cuando hayas iniciado sesión] ")

        storage_state = selenium_cookies_to_playwright(
            driver.get_cookies(),
            origins=read_local_storage(driver, WALLAPOP_ORIGIN),
        )
        save_storage_state(WALLAPOP_STATE_PATH, storage_state)
    finally:
        driver.quit()

    print(f"  ✓ Sesión guardada en {WALLAPOP_STATE_PATH}")
