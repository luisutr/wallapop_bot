from __future__ import annotations

import certifi
import json
import os
import pickle
from typing import Callable, Optional
from pathlib import Path

from config import VINTED_COOKIES_PATH, VINTED_STATE_PATH, SESIONES_DIR


def guardar_sesion_vinted(wait_fn: Optional[Callable[[], None]] = None) -> None:
    """
    Usa Playwright (con fallback a Chrome oficial) para login en Vinted.
    Incluye flags anti-detección de automatización para permitir login de Google.
    """
    SESIONES_DIR.mkdir(parents=True, exist_ok=True)
    os.environ["SSL_CERT_FILE"] = certifi.where()

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        # Intentamos usar Chrome de Google si está instalado para evitar detección de bots
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
        page.goto("https://www.vinted.es/login")

        if wait_fn:
            wait_fn()
        else:
            print("\n→ Inicia sesión en Vinted y pulsa ENTER...")
            input("  [ENTER cuando hayas iniciado sesión] ")

        # Guardar storage state (Playwright)
        context.storage_state(path=str(VINTED_STATE_PATH))

        # Guardar cookies en formato viejo pickle para retrocompatibilidad
        cookies = context.cookies()
        selenium_cookies = []
        for c in cookies:
            selenium_cookies.append({
                "name": c["name"],
                "value": c["value"],
                "domain": c["domain"],
                "path": c["path"],
                "expiry": c.get("expires"),
                "secure": c["secure"],
                "httpOnly": c["httpOnly"],
                "sameSite": c.get("sameSite", "Lax"),
            })
        
        with open(VINTED_COOKIES_PATH, "wb") as f:
            pickle.dump(selenium_cookies, f)

        browser.close()

    print(f"  ✓ Sesión Vinted guardada en {VINTED_STATE_PATH}")
