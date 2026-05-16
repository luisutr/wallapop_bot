from __future__ import annotations

import certifi
import os
import pickle

from config import VINTED_COOKIES_PATH, SESIONES_DIR


def guardar_sesion_vinted() -> None:
    """
    Abre un navegador Chrome (undetected) para que el usuario inicie sesión
    en Vinted manualmente, y guarda las cookies en sesiones/vinted_cookies.pkl.
    """
    SESIONES_DIR.mkdir(parents=True, exist_ok=True)
    os.environ["SSL_CERT_FILE"] = certifi.where()

    try:
        import undetected_chromedriver as uc  # type: ignore
    except ImportError:
        print("  ✗ Falta undetected-chromedriver. Instálalo con:")
        print("    pip install undetected-chromedriver")
        return

    print("\n→ Abriendo navegador Vinted...")
    print("  Inicia sesión con tu cuenta y pulsa ENTER aquí cuando termines.\n")

    options = uc.ChromeOptions()
    driver = uc.Chrome(options=options)
    driver.get("https://www.vinted.es/login")

    input("  [Pulsa ENTER cuando hayas iniciado sesión] ")

    cookies = driver.get_cookies()
    driver.quit()

    with open(VINTED_COOKIES_PATH, "wb") as f:
        pickle.dump(cookies, f)

    print(f"  ✓ Sesión Vinted guardada en {VINTED_COOKIES_PATH}\n")
