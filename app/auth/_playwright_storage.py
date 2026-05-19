from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _map_samesite(value: Any) -> str:
    if value is None:
        return "Lax"
    v = str(value).strip().lower()
    return {"no_restriction": "None", "none": "None", "strict": "Strict"}.get(v, "Lax")


def selenium_cookies_to_playwright(
    selenium_cookies: list[dict],
    *,
    origins: list[dict[str, Any]],
) -> dict:
    pw_cookies = []
    for c in selenium_cookies:
        try:
            pw_cookies.append({
                "name": c["name"],
                "value": c["value"],
                "domain": c.get("domain", ""),
                "path": c.get("path", "/"),
                "expires": int(c.get("expiry", -1)),
                "httpOnly": bool(c.get("httpOnly", False)),
                "secure": bool(c.get("secure", True)),
                "sameSite": _map_samesite(c.get("sameSite")),
            })
        except Exception:
            continue
    return {"cookies": pw_cookies, "origins": origins}


def read_local_storage(driver, origin: str) -> list[dict]:
    items: list[dict] = []
    try:
        raw = driver.execute_script(
            "return Object.entries(localStorage).map(([k,v]) => ({name:k, value:v}))"
        )
        if raw:
            items = raw
    except Exception:
        pass
    return [{"origin": origin, "localStorage": items}]


def save_storage_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)
