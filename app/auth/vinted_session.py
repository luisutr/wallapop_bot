from __future__ import annotations

import certifi
import json
import os
import pickle
from typing import Callable, Optional

from config import VINTED_COOKIES_PATH, VINTED_STATE_PATH, SESIONES_DIR


def guardar_sesion_vinted(wait_fn: Optional[Callable[[], None]] = None) -> None:
    """
    Chrome sin detección de bots (undetected_chromedriver) para login con Google.

    wait_fn: sustituye a input() cuando se llama desde la GUI.
    """
    SESIONES_DIR.mkdir(parents=True, exist_ok=True)
    os.environ["SSL_CERT_FILE"] = certifi.where()

    try:
        import undetected_chromedriver as uc
    except ImportError:
        raise RuntimeError(
            "Falta undetected-chromedriver. Ejecuta: pip install undetected-chromedriver"
        )

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
    local_storage_items: list[dict] = []
    try:
        ls_raw = driver.execute_script(
            "return Object.entries(localStorage).map(([k,v]) => ({name:k, value:v}))"
        )
        if ls_raw:
            local_storage_items = ls_raw
    except Exception:
        pass
    driver.quit()

    def _map_samesite(v) -> str:
        if v is None:
            return "Lax"
        v = str(v).strip().lower()
        return {"no_restriction": "None", "none": "None", "strict": "Strict"}.get(v, "Lax")

    pw_cookies = []
    for c in selenium_cookies:
        try:
            pw_cookies.append({
                "name": c["name"], "value": c["value"],
                "domain": c.get("domain", ".vinted.es"),
                "path": c.get("path", "/"),
                "expires": int(c.get("expiry", -1)),
                "httpOnly": bool(c.get("httpOnly", False)),
                "secure": bool(c.get("secure", True)),
                "sameSite": _map_samesite(c.get("sameSite")),
            })
        except Exception:
            continue

    storage_state = {
        "cookies": pw_cookies,
        "origins": [{"origin": "https://www.vinted.es", "localStorage": local_storage_items}],
    }
    with open(VINTED_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(storage_state, f, ensure_ascii=False)
    with open(VINTED_COOKIES_PATH, "wb") as f:
        pickle.dump(selenium_cookies, f)

    print(f"  ✓ Sesión Vinted guardada en {VINTED_STATE_PATH}")
