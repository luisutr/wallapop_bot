from __future__ import annotations

import certifi
import os
import pickle
import random
import re
import time
from pathlib import Path
from typing import Callable, Optional

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

from config import (
    VINTED_COOKIES_PATH,
    VINTED_STATE_PATH,
    VINTED_UPLOAD_URL,
    VINTED_RATING_DEFAULT,
    ERRORES_DIR,
)
from app.publishers.form_audit import PublishAudit, raise_if_not_verified

CAMPOS_VINTED_NO_TOCAR: frozenset[str] = frozenset({"material"})

TALLAS_VINTED: list[str] = [
    "Talla única",
    "Una talla",
    "Talla unica",
    "Única",
    "Sin talla",
]


def _log(msg: str, log_fn=None) -> None:
    print(f"  [vinted] {msg}")
    if log_fn:
        log_fn(msg)


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
    return [
        {
            "name": c["name"], "value": c["value"],
            "domain": c.get("domain") or ".vinted.es",
            "path": c.get("path", "/"),
            "expires": int(c.get("expiry", 0) or 0),
            "httpOnly": bool(c.get("httpOnly", False)),
            "secure": bool(c.get("secure", True)),
            "sameSite": _map_samesite(c.get("sameSite")),
        }
        for c in raw
        if c.get("name")
    ]


def _crear_contexto(p, browser):
    base_opts = dict(
        viewport={"width": 1280, "height": 900},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
    )
    if VINTED_STATE_PATH.exists():
        try:
            return browser.new_context(storage_state=str(VINTED_STATE_PATH), **base_opts)
        except Exception:
            pass
    ctx = browser.new_context(**base_opts)
    cookies = _cargar_cookies()
    if cookies:
        ctx.add_cookies(cookies)
    return ctx


def _cerrar_desplegables_vinted(page, log_fn=None) -> None:
    for _ in range(3):
        page.keyboard.press("Escape")
        time.sleep(0.12)
    try:
        page.locator("#title").click(position={"x": 5, "y": 5}, force=True)
    except Exception:
        pass
    time.sleep(0.3)


def _leer_input(page, field_id: str) -> str:
    try:
        loc = page.locator(f"#{field_id}")
        if loc.count() > 0:
            return (loc.first.input_value() or "").strip()
    except Exception:
        pass
    return ""


def _abrir_desplegable(page, field_id: str, log_fn=None) -> None:
    """
    Abre un dropdown readonly de Vinted.
    Estrategia: clic force sobre el propio input (funciona en la mayoría de campos),
    si falla intenta el chevron vecino o el label.
    """
    _cerrar_desplegables_vinted(page, log_fn)
    field = page.locator(f"#{field_id}")
    field.scroll_into_view_if_needed()

    # 1) Clic directo con force — funciona para todos los inputs readonly de Vinted
    try:
        field.click(force=True, timeout=5_000)
        _human_sleep(900, 300)
        return
    except Exception:
        pass

    # 2) Clic en el icono chevron que está en el mismo bloque c-input
    try:
        chevron = page.evaluate(
            """(id) => {
                const el = document.getElementById(id);
                if (!el) return false;
                const icon = el.closest('.c-input')?.querySelector('.c-input__icon[role="button"]');
                if (icon) { icon.click(); return true; }
                return false;
            }""",
            field_id,
        )
        if chevron:
            _human_sleep(900, 300)
            return
    except Exception:
        pass

    # 3) Clic en el label
    try:
        page.locator(f'label[for="{field_id}"]').first.click(force=True)
    except Exception:
        pass
    _human_sleep(900, 300)


_JS_CLICK_OPCION = """
(texto) => {
    const lower = texto.toLowerCase().trim();

    // Busca en todos los candidatos del overlay abierto
    const candidatos = [
        ...document.querySelectorAll('motion\\\\:div[role="button"]'),
        ...document.querySelectorAll('li.web_ui__Item__item'),
        ...document.querySelectorAll('[role="option"]'),
        ...document.querySelectorAll('[role="listitem"]'),
    ];

    for (const el of candidatos) {
        const t = (el.innerText || el.textContent || '').trim().toLowerCase();
        if (t === lower || t.startsWith(lower) || t.includes(lower)) {
            el.click();
            return el.innerText?.trim() || '(ok)';
        }
    }

    // Fallback: cualquier elemento con la clase title que contenga el texto
    for (const el of document.querySelectorAll('.web_ui__Cell__title')) {
        const t = (el.innerText || '').trim().toLowerCase();
        if (t === lower || t.includes(lower)) {
            el.click();
            return el.innerText?.trim() || '(ok)';
        }
    }

    return null;
}
"""

_JS_CLICK_PRIMERA = """
() => {
    const selectores = [
        'motion\\\\:div[role="button"] .web_ui__Cell__title',
        'li.web_ui__Item__item .web_ui__Cell__title',
        '[role="option"] .web_ui__Cell__title',
        '.web_ui__Cell__title',
    ];
    for (const sel of selectores) {
        const items = [...document.querySelectorAll(sel)]
            .filter(el => {
                const t = (el.innerText || '').trim();
                return t.length > 0 && t.length < 80;
            });
        if (items.length > 0) {
            items[0].click();
            return items[0].innerText?.trim() || '(ok)';
        }
    }
    return null;
}
"""


def _elegir_opcion_lista(page, texto: str, timeout: int = 6_000) -> bool:
    """Clic en opción del overlay de Vinted. Intenta JS primero (sin restricciones de pointer-events)."""
    try:
        res = page.evaluate(_JS_CLICK_OPCION, texto)
        if res:
            return True
    except Exception:
        pass

    # Fallback Playwright
    patron = re.compile(re.escape(texto), re.I)
    for sel in (
        "motion\\:div[role='button'] .web_ui__Cell__title",
        "li.web_ui__Item__item .web_ui__Cell__title",
        "li.web_ui__Item__item",
        ".web_ui__Cell__title",
    ):
        try:
            loc = page.locator(sel).filter(has_text=patron)
            if loc.count() > 0:
                loc.first.wait_for(state="visible", timeout=timeout)
                loc.first.click(force=True)
                return True
        except Exception:
            continue
    return False


def _elegir_primera_opcion(page, log_fn=None, field_id: str = "") -> bool:
    """Elige la primera opción del overlay abierto, usando JS para evitar problemas de pointer-events."""
    try:
        res = page.evaluate(_JS_CLICK_PRIMERA)
        if res:
            _log(f"#{field_id or '?'} → 1ª opción JS: {res!r}", log_fn)
            return True
    except Exception:
        pass

    # Fallback Playwright
    for sel in (
        "motion\\:div[role='button'] .web_ui__Cell__title",
        "li.web_ui__Item__item .web_ui__Cell__title",
        ".web_ui__Cell__title",
    ):
        try:
            loc = page.locator(sel)
            for i in range(min(loc.count(), 8)):
                item = loc.nth(i)
                if not item.is_visible(timeout=500):
                    continue
                texto = (item.inner_text(timeout=800) or "").strip()
                if not texto or len(texto) > 80:
                    continue
                item.click(force=True)
                _log(f"#{field_id or '?'} → 1ª opción: {texto!r}", log_fn)
                return True
        except Exception:
            continue
    return False


def _seleccionar_dropdown(
    page,
    field_id: str,
    valor: str,
    log_fn=None,
    *,
    buscar_en_catalogo: bool = False,
    candidatos: list[str] | None = None,
) -> bool:
    if field_id in CAMPOS_VINTED_NO_TOCAR:
        return True

    field = page.locator(f"#{field_id}")
    if field.count() == 0 or not field.is_visible(timeout=2_000):
        return False

    actual = _leer_input(page, field_id)
    if actual and valor and valor.lower() in actual.lower():
        _log(f"#{field_id} ya OK: {actual!r}", log_fn)
        return True

    textos = candidatos or [valor]
    _log(f"#{field_id} → {textos!r}", log_fn)
    _abrir_desplegable(page, field_id, log_fn)

    if buscar_en_catalogo or field_id == "category":
        srch = page.locator("#catalog-search-input")
        if srch.count() > 0 and srch.is_visible(timeout=1_500):
            srch.fill(textos[0])
            _human_sleep(2000, 600)

    for texto in textos:
        if _elegir_opcion_lista(page, texto):
            _human_sleep(500, 150)
            val = _leer_input(page, field_id)
            if val:
                _log(f"#{field_id} OK: {val!r}", log_fn)
                _cerrar_desplegables_vinted(page, log_fn)
                return True

    if _elegir_primera_opcion(page, log_fn, field_id=field_id):
        _human_sleep(500, 150)
        val = _leer_input(page, field_id)
        if val:
            _cerrar_desplegables_vinted(page, log_fn)
            return True

    # Último recurso: teclado (ArrowDown + Enter)
    try:
        page.keyboard.press("ArrowDown")
        time.sleep(0.25)
        page.keyboard.press("Enter")
        _human_sleep(600, 150)
        val = _leer_input(page, field_id)
        if val:
            _log(f"#{field_id} OK (teclado): {val!r}", log_fn)
            _cerrar_desplegables_vinted(page, log_fn)
            return True
    except Exception:
        pass

    _cerrar_desplegables_vinted(page, log_fn)
    _log(f"#{field_id}: fallo al seleccionar", log_fn)
    return False


def _marcas_candidatas(producto: dict) -> list[str]:
    if producto.get("marca"):
        return [str(producto["marca"])]
    titulo = str(producto.get("titulo", "")).lower()
    if any(x in titulo for x in ("playstation", "ps1", "ps2", "ps3", "ps4", "ps5", "psp")):
        return ["PlayStation", "Sony"]
    if producto.get("tipo") == "accesorio_consola":
        return ["PlayStation", "Sony"]
    return ["Sony"]


def _seleccionar_marca(page, producto: dict, log_fn=None) -> bool:
    if not page.locator("#brand").is_visible(timeout=2_000):
        return True
    if _leer_input(page, "brand"):
        _log(f"Marca ya OK: {_leer_input(page, 'brand')!r}", log_fn)
        return True
    return _seleccionar_dropdown(
        page, "brand", "", log_fn, candidatos=_marcas_candidatas(producto)
    )


def _seleccionar_plataforma(page, producto: dict, log_fn=None) -> bool:
    if not page.locator("#video_game_platform").is_visible(timeout=1_500):
        return True
    if _leer_input(page, "video_game_platform"):
        return True

    radios = page.locator('input[data-testid^="video_game_platform-radio"]')
    if radios.count() > 0:
        try:
            radios.first.click(force=True)
            _log("Plataforma OK (radio)", log_fn)
            return True
        except Exception:
            pass

    candidatos: list[str] = []
    if producto.get("plataforma_vinted"):
        candidatos.append(str(producto["plataforma_vinted"]))
    candidatos.extend(["PlayStation 2", "PlayStation", "PS2"])

    return _seleccionar_dropdown(
        page, "video_game_platform", "", log_fn, candidatos=candidatos
    )


def _seleccionar_clasificacion(page, producto: dict, log_fn=None) -> bool:
    if not page.locator("#video_game_rating").is_visible(timeout=1_500):
        return True
    if _leer_input(page, "video_game_rating"):
        return True
    pref = str(producto.get("pegi") or VINTED_RATING_DEFAULT)
    return _seleccionar_dropdown(
        page, "video_game_rating", pref, log_fn,
        candidatos=[pref, "AO – Solo adultos", "PEGI 18"],
    )


_ALIAS_CONDICION: dict[str, list[str]] = {
    "Nuevo sin etiquetas": ["Nuevo sin etiquetas", "Nuevo con etiquetas"],
    "Nuevo con etiquetas": ["Nuevo con etiquetas", "Nuevo sin etiquetas"],
    "Muy bueno":           ["Muy bueno"],
    "Bueno":               ["Bueno"],
    "Satisfactorio":       ["Satisfactorio"],
}


def _seleccionar_condicion(page, estado_vinted: str, log_fn=None) -> bool:
    """
    Estado en Vinted: siempre por texto exacto, NUNCA primera sugerencia.
    Opciones: Nuevo sin etiquetas, Nuevo con etiquetas, Muy bueno, Bueno, Satisfactorio.
    """
    if not page.locator("#condition").is_visible(timeout=2_000):
        return True
    actual = _leer_input(page, "condition")
    if actual:
        _log(f"Condición ya OK: {actual!r}", log_fn)
        return True

    candidatos = _ALIAS_CONDICION.get(estado_vinted, [estado_vinted])
    _log(f"Condición → buscar {candidatos}", log_fn)
    _abrir_desplegable(page, "condition", log_fn)
    _human_sleep(1200, 300)

    for texto in candidatos:
        # JS click exacto (más fiable que Playwright en overlays de Vinted)
        res = page.evaluate(_JS_CLICK_OPCION, texto)
        if res:
            _human_sleep(400, 100)
            val = _leer_input(page, "condition")
            if val:
                _log(f"Condición OK: {val!r}", log_fn)
                _cerrar_desplegables_vinted(page, log_fn)
                return True

        # Fallback Playwright
        if _elegir_opcion_lista(page, texto):
            _human_sleep(400, 100)
            val = _leer_input(page, "condition")
            if val:
                _log(f"Condición OK: {val!r}", log_fn)
                _cerrar_desplegables_vinted(page, log_fn)
                return True

    _cerrar_desplegables_vinted(page, log_fn)
    _log(f"FALLO condición — no encontré {candidatos} en el listado", log_fn)
    return False


def _seleccionar_color(page, log_fn=None) -> bool:
    if not page.locator("#color").is_visible(timeout=1_500):
        return True
    if _leer_input(page, "color"):
        return True
    return _seleccionar_dropdown(
        page, "color", "Varios", log_fn,
        candidatos=["Varios", "Negro", "Gris", "Plateado", "Multicolor"],
    )


def _seleccionar_talla(page, log_fn=None) -> bool:
    if not page.locator("#size").is_visible(timeout=2_000):
        return True
    if _leer_input(page, "size"):
        return True
    for texto in TALLAS_VINTED:
        if _seleccionar_dropdown(page, "size", texto, log_fn, candidatos=[texto]):
            return True
    return False


def _rellenar_precio(page, precio: float, log_fn=None) -> bool:
    loc = page.locator('[data-testid="price-input--input"], #price').first
    loc.wait_for(state="visible", timeout=8_000)
    loc.scroll_into_view_if_needed()
    loc.click(force=True)
    loc.fill("")
    texto = f"{precio:.2f}".replace(".", ",") if precio != int(precio) else str(int(precio))
    loc.fill(texto)
    page.keyboard.press("Tab")
    _human_sleep(400, 150)
    val = loc.input_value() or ""
    ok = str(int(precio)) in val.replace(",", ".")
    _log(f"Precio {'OK' if ok else 'FALLO'}: {val!r}", log_fn)
    return ok


def _seleccionar_paquete(page, log_fn=None) -> bool:
    # Seleccionar «Paquete pequeño» (tamaño 1)
    for sel in (
        '[data-testid="package_type_selector_1--input"]',   # radio input directo
        'input[aria-labelledby="package-size-1"]',           # por aria
        '[data-testid="1-package-size--cell"]',              # celda entera
        "#package-size-1",
        'label:has-text("Pequeño") input[type="radio"]',
    ):
        loc = page.locator(sel).first
        if loc.count() == 0:
            continue
        try:
            loc.scroll_into_view_if_needed()
            loc.click(force=True, timeout=3_000)
            _log("Paquete pequeño OK", log_fn)
            return True
        except Exception:
            continue
    _log("Paquete no seleccionado (no crítico)", log_fn)
    return False


def subir_vinted(producto: dict, log_fn=None) -> bool:
    if not VINTED_COOKIES_PATH.exists() and not VINTED_STATE_PATH.exists():
        raise RuntimeError("No hay sesión de Vinted guardada.")

    os.environ["SSL_CERT_FILE"] = certifi.where()
    ERRORES_DIR.mkdir(parents=True, exist_ok=True)
    slug = producto.get("slug", "producto")
    audit = PublishAudit("vinted", slug, producto, log_fn=log_fn)

    _log(f"Publicando: {producto.get('titulo')}", log_fn)
    claimed_ok = False
    exc_msg: str | None = None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=150)
        context = _crear_contexto(p, browser)
        page = context.new_page()
        page.goto(VINTED_UPLOAD_URL, wait_until="domcontentloaded")
        _human_sleep(3000, 1000)

        try:
            page.wait_for_selector(
                "input[data-testid='add-photos-input']", state="attached", timeout=20_000
            )

            fotos = [str(Path(f).resolve()) for f in producto["fotos"]]
            page.locator("input[data-testid='add-photos-input']").first.set_input_files(fotos)
            _human_sleep(4000, 1000)

            page.locator("#title").fill(str(producto["titulo"]))
            page.locator("#description").fill(str(producto["descripcion"]))
            _human_sleep(1200, 300)

            cat_ok = _seleccionar_dropdown(
                page, "category", str(producto["categoria_vinted"]), log_fn,
                buscar_en_catalogo=True,
            )
            marca_ok = _seleccionar_marca(page, producto, log_fn)
            plat_ok = _seleccionar_plataforma(page, producto, log_fn)
            cond_ok = _seleccionar_condicion(page, str(producto["estado_vinted"]), log_fn)
            color_ok = _seleccionar_color(page, log_fn)
            talla_ok = _seleccionar_talla(page, log_fn)
            _seleccionar_clasificacion(page, producto, log_fn)

            precio_ok = _rellenar_precio(page, float(producto["precio"]), log_fn)
            paquete_ok = _seleccionar_paquete(page, log_fn)

            audit.snapshot(page, "despues_rellenar_todo", {
                "category_ok": cat_ok,
                "marca_ok": marca_ok,
                "plataforma_ok": plat_ok,
                "cond_ok": cond_ok,
                "color_ok": color_ok,
                "talla_ok": talla_ok,
                "precio_ok": precio_ok,
                "paquete_ok": paquete_ok,
            })

            if not cat_ok:
                raise RuntimeError(f"Categoría no seleccionada ({producto.get('categoria_vinted')})")
            if not marca_ok:
                raise RuntimeError("Marca no seleccionada en Vinted")
            if not cond_ok:
                raise RuntimeError(f"Condición no seleccionada ({producto.get('estado_vinted')})")
            if not precio_ok:
                raise RuntimeError(f"Precio no aplicado ({producto.get('precio')}€)")
            if page.locator("#video_game_platform").is_visible(timeout=500) and not _leer_input(page, "video_game_platform"):
                raise RuntimeError("Plataforma no seleccionada en Vinted")
            if page.locator("#color").is_visible(timeout=500) and not _leer_input(page, "color"):
                raise RuntimeError("Color no seleccionado en Vinted")

            body = page.locator("body").inner_text(timeout=3_000).lower()
            if "talla" in body and "rellena" in body:
                raise RuntimeError("Vinted pide rellenar talla — revisa logs/")

            page.locator("button[data-testid='upload-form-save-button']").click()
            verify = audit.verify_after_submit(page, wait_ms=15_000)
            raise_if_not_verified(audit, verify)

            claimed_ok = True
            _log("✓ Publicado y verificado en Vinted.", log_fn)
            audit.finalize(True, None, verify)
            return True

        except Exception as exc:
            exc_msg = str(exc)
            try:
                audit.snapshot(page, "error", screenshot=True)
                d = ERRORES_DIR / f"vinted_{slug}"
                d.mkdir(exist_ok=True)
                page.screenshot(path=str(d / "error.png"), full_page=True)
            except Exception:
                pass
            raise RuntimeError(f"Vinted — {slug}: {exc}") from exc
        finally:
            if not claimed_ok:
                audit.finalize(claimed_ok, exc_msg)
            context.close()
            browser.close()
