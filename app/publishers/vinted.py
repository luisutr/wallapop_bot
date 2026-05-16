from __future__ import annotations

import certifi
import os
import pickle
import random
import time
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

from config import VINTED_COOKIES_PATH, VINTED_UPLOAD_URL, ERRORES_DIR


# ── Utilidades ───────────────────────────────────────────────────────────────

def _human_sleep(base: int = 1000, variation: int = 500) -> None:
    time.sleep((base + random.randint(-variation, variation)) / 1000)


def _map_samesite(v) -> str:
    if v is None:
        return "Lax"
    v = str(v).strip().lower()
    return {"no_restriction": "None", "none": "None", "strict": "Strict"}.get(v, "Lax")


def _cargar_cookies() -> list[dict]:
    if not VINTED_COOKIES_PATH.exists():
        return []
    with open(VINTED_COOKIES_PATH, "rb") as f:
        raw = pickle.load(f)
    cookies = []
    for c in raw:
        try:
            cookies.append({
                "name":     c["name"],
                "value":    c["value"],
                "domain":   c.get("domain") or ".vinted.es",
                "path":     c.get("path", "/"),
                "expires":  int(c.get("expiry", 0) or 0),
                "httpOnly": bool(c.get("httpOnly", False)),
                "secure":   bool(c.get("secure", True)),
                "sameSite": _map_samesite(c.get("sameSite")),
            })
        except Exception:
            continue
    return cookies


# ── Helpers de formulario ────────────────────────────────────────────────────

def _click_dropdown(page, input_id: str, value_text: str, timeout: int = 15_000) -> None:
    page.locator(f"#{input_id}").click()
    if input_id == "category":
        srch = page.locator("#catalog-search-input")
        if srch.count() > 0:
            srch.fill(value_text)
            _human_sleep(3000, 1000)
    option = (
        page.locator("div[role='button'] div.web_ui__Cell__title")
        .filter(has_text=value_text)
        .first
    )
    if option.count() == 0:
        option = page.locator(f"//li//span[normalize-space()='{value_text}']").first
    option.wait_for(state="visible", timeout=timeout)
    option.click()


def _buscar_y_elegir(page, input_id: str, value_text: str, timeout: int = 15_000) -> None:
    inp = page.locator(f"#{input_id}")
    inp.click()
    inp.fill(value_text)
    _human_sleep(3000, 1000)
    option = (
        page.locator("div[role='button'] div.web_ui__Cell__title")
        .filter(has_text=value_text)
        .first
    )
    if option.count() == 0:
        inp.press("Enter")
    else:
        option.wait_for(state="visible", timeout=timeout)
        option.click()


def _seleccionar_condicion(page, estado_vinted: str) -> None:
    page.locator("input#condition").click()
    page.wait_for_selector(
        f"div.web_ui__Cell__title:text('{estado_vinted}')", timeout=8_000
    )
    page.locator(f"div.web_ui__Cell__title:text('{estado_vinted}')").first.click()


# ── Publicador principal ──────────────────────────────────────────────────────

def subir_vinted(producto: dict) -> bool:
    """
    Publica un producto en Vinted usando Playwright + cookies guardadas.

    producto dict keys:
        slug              str           Identificador del producto
        titulo            str           Título del anuncio
        descripcion       str           Descripción completa
        precio            float         Precio de venta
        estado_vinted     str           Texto de estado tal como aparece en Vinted
                                        ej. "Nuevo sin etiquetas", "Muy bueno"…
        categoria_vinted  str           Texto del dropdown #category en Vinted
        plataforma_vinted str | None    Plataforma (solo videojuegos)
        pegi              str | None    Clasificación PEGI (solo videojuegos)
        tipo              str           "videojuego", "ropa_hombre", etc.
        fotos             list[str]     Rutas absolutas a las imágenes

    Retorna True si se publicó con éxito, lanza RuntimeError en caso de fallo.
    """
    if not VINTED_COOKIES_PATH.exists():
        raise RuntimeError(
            "No hay sesión de Vinted guardada. "
            "Ejecuta la opción 'Guardar sesión Vinted' primero."
        )

    os.environ["SSL_CERT_FILE"] = certifi.where()
    ERRORES_DIR.mkdir(parents=True, exist_ok=True)
    slug = producto.get("slug", "producto")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=150)
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        cookies = _cargar_cookies()
        if cookies:
            context.add_cookies(cookies)

        page = context.new_page()
        page.goto(VINTED_UPLOAD_URL, wait_until="domcontentloaded")
        _human_sleep(3000, 1000)
        page.goto(VINTED_UPLOAD_URL, wait_until="domcontentloaded")

        try:
            page.wait_for_selector(
                "input[data-testid='add-photos-input']", state="attached", timeout=20_000
            )

            # Fotos
            fotos = [str(Path(f).resolve()) for f in producto["fotos"]]
            page.locator("input[data-testid='add-photos-input']").first.set_input_files(fotos)
            _human_sleep(3000, 1000)

            # Campos de texto
            page.locator("#title").fill(str(producto["titulo"]))
            page.locator("#description").fill(str(producto["descripcion"]))
            page.locator("#price").fill(str(round(producto["precio"], 2)))
            _human_sleep(2000, 500)

            # Categoría
            _click_dropdown(page, "category", str(producto["categoria_vinted"]))

            # Campos específicos para videojuegos
            tipo = producto.get("tipo", "otro")
            if tipo == "videojuego":
                if producto.get("plataforma_vinted"):
                    _buscar_y_elegir(page, "video_game_platform", str(producto["plataforma_vinted"]))
                if producto.get("pegi"):
                    _click_dropdown(page, "video_game_rating", str(producto["pegi"]))

            # Condición
            _seleccionar_condicion(page, str(producto["estado_vinted"]))
            _human_sleep(2000, 500)

            # Publicar
            page.locator("button[data-testid='upload-form-save-button']").click()
            _human_sleep(3000, 1000)
            return True

        except Exception as exc:
            error_dir = ERRORES_DIR / f"vinted_{slug}"
            error_dir.mkdir(exist_ok=True)
            page.screenshot(path=str(error_dir / "error.png"), full_page=True)
            with open(error_dir / "error.html", "w", encoding="utf-8") as f:
                f.write(page.content())
            raise RuntimeError(f"Error publicando '{slug}' en Vinted: {exc}") from exc

        finally:
            context.close()
            browser.close()
