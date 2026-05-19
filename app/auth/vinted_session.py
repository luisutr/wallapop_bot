from __future__ import annotations

import certifi
import os
import pickle
from typing import Callable, Optional

from config import VINTED_COOKIES_PATH, VINTED_STATE_PATH, SESIONES_DIR

from ._playwright_storage import (
    read_local_storage,
    save_storage_state,
    selenium_cookies_to_playwright,
)


def guardar_sesion_vinted(wait_fn: Optional[Callable[[], None]] = None) -> None:
    """
    Chrome sin detección de bots (undetected_chromedriver) para login con Google.

    wait_fn: sustituye a input() cuando se llama desde la GUI.
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
    driver = uc.Chrome(options=options, use_subprocess=True)
    driver.get("https://www.vinted.es/login")

    if wait_fn:
        wait_fn()
    else:
        print("\n→ Inicia sesión en Vinted y pulsa ENTER...")
        input("  [ENTER cuando hayas iniciado sesión] ")

    selenium_cookies = driver.get_cookies()
    storage_state = selenium_cookies_to_playwright(
        selenium_cookies,
        origins=read_local_storage(driver, "https://www.vinted.es"),
    )
    driver.quit()

    save_storage_state(VINTED_STATE_PATH, storage_state)
    with open(VINTED_COOKIES_PATH, "wb") as f:
        pickle.dump(selenium_cookies, f)

    print(f"  ✓ Sesión Vinted guardada en {VINTED_STATE_PATH}")
