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
    ERRORES_DIR,
    VINTED_CONDICION_PUBLICACION,
    VINTED_COOKIES_PATH,
    VINTED_RATING_DEFAULT,
    VINTED_STATE_PATH,
    VINTED_UPLOAD_URL,
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
            _log(f"#{field_id} OK (click exacto): {texto!r}", log_fn)
            _cerrar_desplegables_vinted(page, log_fn)
            return True

    if _elegir_primera_opcion(page, log_fn, field_id=field_id):
        _human_sleep(500, 150)
        _log(f"#{field_id} OK (primera opción)", log_fn)
        _cerrar_desplegables_vinted(page, log_fn)
        return True

    # Último recurso: teclado (ArrowDown + Enter)
    try:
        page.keyboard.press("ArrowDown")
        time.sleep(0.25)
        page.keyboard.press("Enter")
        _human_sleep(600, 150)
        _log(f"#{field_id} OK (teclado)", log_fn)
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
    
    actual = _leer_input(page, "brand")
    if actual:
        _log(f"Marca ya OK: {actual!r}", log_fn)
        return True

    _log("Seleccionando primera marca sugerida por Vinted...", log_fn)
    try:
        _abrir_desplegable(page, "brand", log_fn)
        _human_sleep(1500, 500)

        # Elegir primera opción disponible (las sugerencias salen al principio)
        if _elegir_primera_opcion(page, log_fn, field_id="brand"):
            _human_sleep(500, 150)
            _cerrar_desplegables_vinted(page, log_fn)
            return True
    except Exception as e:
        _log(f"Fallo al elegir primera marca sugerida: {e}", log_fn)

    # Fallback: escribir candidatos
    _log("Fallback: intentando escribir candidatos manuales...", log_fn)
    candidatos = _marcas_candidatas(producto)
    if candidatos:
        _log(f"Escribiendo marca: {candidatos[0]}", log_fn)
        try:
            _cerrar_desplegables_vinted(page, log_fn)
            inp = page.locator("#brand")
            inp.click(force=True)
            _human_sleep(1000, 300)
            page.keyboard.type(candidatos[0], delay=100)
            _human_sleep(2500, 600)
            
            ok = _seleccionar_dropdown(
                page, "brand", candidatos[0], log_fn, candidatos=candidatos
            )
            if ok:
                return True
        except Exception as e:
            _log(f"Error escribiendo marca: {e}", log_fn)
            
    return _seleccionar_dropdown(
        page, "brand", "", log_fn, candidatos=candidatos
    )


def _seleccionar_plataforma(page, producto: dict, log_fn=None) -> bool:
    if not page.locator("#video_game_platform").is_visible(timeout=1_500):
        return True

    actual = _leer_input(page, "video_game_platform")
    if actual:
        _log(f"Plataforma ya OK: {actual!r}", log_fn)
        return True

    candidatos: list[str] = []
    if producto.get("plataforma_vinted"):
        candidatos.append(str(producto["plataforma_vinted"]))
    else:
        # Extraer candidatos por slug o título si no viene definido
        titulo = str(producto.get("titulo", "")).lower()
        for plat, text in [
            ("ps5", "PlayStation 5"), ("ps4", "PlayStation 4"), ("ps3", "PlayStation 3"),
            ("ps2", "PlayStation 2"), ("ps1", "PlayStation 1"), ("psp", "PlayStation Portable"),
            ("switch", "Nintendo Switch"), ("gamecube", "GameCube"), ("wii", "Wii"),
            ("xbox 360", "Xbox 360"), ("xbox one", "Xbox One"), ("xbox", "Xbox")
        ]:
            if plat in titulo:
                candidatos.append(text)
                break

    if not candidatos:
        candidatos.append("Xbox 360")  # Fallback estándar

    _log(f"Plataforma candidatos: {candidatos}", log_fn)
    try:
        _abrir_desplegable(page, "video_game_platform", log_fn)
        _human_sleep(1200, 300)

        # Localizar y rellenar el campo de búsqueda de plataforma
        search_input = page.locator("#video_game_platform-search-input")
        if search_input.count() > 0 and search_input.is_visible(timeout=2_000):
            search_input.fill(candidatos[0])
            _human_sleep(1500, 400)

            # Hacer clic en el primer resultado (label de radio button)
            # Los labels tienen data-testid="video_game_platform-radio-<id>"
            first_option = page.locator('label[data-testid^="video_game_platform-radio-"]').first
            if first_option.count() > 0:
                first_option.click(force=True)
                _log(f"Plataforma seleccionada (búsqueda): {candidatos[0]}", log_fn)
                _human_sleep(800, 200)
                _cerrar_desplegables_vinted(page, log_fn)
                return True
    except Exception as e:
        _log(f"Error seleccionando plataforma mediante búsqueda: {e}", log_fn)

    # Fallback supremo
    _log("Fallback: intentando seleccionar primera opción disponible de plataforma...", log_fn)
    if _elegir_primera_opcion(page, log_fn, field_id="video_game_platform"):
        _cerrar_desplegables_vinted(page, log_fn)
        return True

    _cerrar_desplegables_vinted(page, log_fn)
    return False


def _seleccionar_clasificacion(page, producto: dict, log_fn=None) -> bool:
    """Campo opcional: Clasificación de contenidos (video_game_ratings)."""
    field_id = None
    for fid in ("video_game_ratings", "video_game_rating"):
        if page.locator(f"#{fid}").is_visible(timeout=1_000):
            field_id = fid
            break
    if field_id is None:
        return True
    if _leer_input(page, field_id):
        return True

    # Priorizar PEGI 12 tal como pide el usuario, seguido por lo que venga en el producto
    pref = str(producto.get("pegi") or "PEGI 12")
    _log(f"Seleccionando clasificación de contenidos: {pref}...", log_fn)
    _seleccionar_dropdown(
        page, field_id, pref, log_fn,
        candidatos=[pref, "PEGI 12", "PEGI 18", "AO – Solo adultos"],
    )
    return True  # siempre True: campo opcional


_JS_CLICK_EXACTO = """
(texto) => {
    const objetivo = texto.toLowerCase().trim();
    const candidatos = [
        ...document.querySelectorAll('motion\\\\:div[role="button"]'),
        ...document.querySelectorAll('li.web_ui__Item__item'),
        ...document.querySelectorAll('[role="option"]'),
        ...document.querySelectorAll('[role="listitem"]'),
    ];
    for (const el of candidatos) {
        const linea = (el.innerText || el.textContent || '').trim().split('\\n')[0].trim();
        if (linea.toLowerCase() === objetivo) {
            el.click();
            return linea;
        }
    }
    for (const el of document.querySelectorAll('.web_ui__Cell__title')) {
        const t = (el.innerText || '').trim().toLowerCase();
        if (t === objetivo) {
            el.click();
            return el.innerText.trim();
        }
    }
    return null;
}
"""


def _abrir_condicion_vinted(page, log_fn=None) -> None:
    """Abre el desplegable de condición (#condition / data-testid category-condition)."""
    _cerrar_desplegables_vinted(page, log_fn)
    for sel in (
        "input#condition",
        'input[data-testid="category-condition-single-list-input"]',
    ):
        loc = page.locator(sel)
        if loc.count() == 0:
            continue
        try:
            if loc.first.is_visible(timeout=1_500):
                loc.first.scroll_into_view_if_needed()
                loc.first.click(force=True)
                _human_sleep(900, 300)
                return
        except Exception:
            continue
    _abrir_desplegable(page, "condition", log_fn)


def _condicion_vinted_ok(page, objetivo: str = VINTED_CONDICION_PUBLICACION) -> bool:
    val = _leer_input(page, "condition")
    return val.strip().lower() == objetivo.strip().lower()


def _seleccionar_condicion(page, estado_vinted: str = "", log_fn=None) -> bool:
    """
    Condición en Vinted: dinámica según el producto, o «Bueno» por defecto.
    """
    # Estandarizar y capitalizar la condición
    estado_limpio = (estado_vinted or "").strip().lower()
    if estado_limpio in ("nuevo", "nuevo con etiquetas"):
        objetivo = "Nuevo con etiquetas"
    elif estado_limpio in ("como_nuevo", "como nuevo", "nuevo sin etiquetas"):
        objetivo = "Nuevo sin etiquetas"
    elif estado_limpio in ("muy_bueno", "muy bueno"):
        objetivo = "Muy bueno"
    elif estado_limpio in ("bueno", "buen_estado", "buen estado"):
        objetivo = "Bueno"
    elif estado_limpio in ("aceptable", "satisfactorio"):
        objetivo = "Satisfactorio"
    else:
        # Fallback a lo configurado o Bueno
        objetivo = VINTED_CONDICION_PUBLICACION or "Bueno"

    if not page.locator("input#condition").is_visible(timeout=2_000):
        return True

    if _condicion_vinted_ok(page, objetivo):
        _log(f"Condición ya OK: {objetivo!r}", log_fn)
        return True

    actual = _leer_input(page, "condition")
    if actual and actual != objetivo:
        _log(f"Condición actual {actual!r} → forzando {objetivo!r}", log_fn)

    _log(f"Condición → {objetivo!r}", log_fn)
    _abrir_condicion_vinted(page, log_fn)
    _human_sleep(1200, 300)

    res = page.evaluate(_JS_CLICK_EXACTO, objetivo)
    if res:
        _human_sleep(500, 100)
        if _condicion_vinted_ok(page, objetivo):
            _log(f"Condición OK: {res!r}", log_fn)
            _cerrar_desplegables_vinted(page, log_fn)
            return True

    # Fallback Playwright (coincidencia exacta en la lista visible)
    for sel in (
        "motion\\:div[role='button']",
        "li.web_ui__Item__item",
        "[role='option']",
        ".web_ui__Cell__title",
    ):
        try:
            loc = page.locator(sel).filter(has_text=objetivo)
            visible = [
                loc.nth(i)
                for i in range(loc.count())
                if loc.nth(i).inner_text().strip().split("\n")[0].strip().lower() == objetivo.lower()
            ]
            if visible:
                visible[0].click(force=True)
                _human_sleep(400, 100)
                if _condicion_vinted_ok(page, objetivo):
                    _log(f"Condición OK (playwright): {objetivo!r}", log_fn)
                    _cerrar_desplegables_vinted(page, log_fn)
                    return True
        except Exception:
            continue

    _cerrar_desplegables_vinted(page, log_fn)
    _log(f"FALLO condición — esperado {objetivo!r}, DOM={_leer_input(page, 'condition')!r}", log_fn)
    return False


def _seleccionar_color(page, log_fn=None) -> bool:
    if not page.locator("#color").is_visible(timeout=1_500):
        return True
    actual = _leer_input(page, "color")
    if actual:
        _log(f"Color ya OK: {actual!r}", log_fn)
        return True

    _log("Seleccionando primer color sugerido...", log_fn)
    try:
        _abrir_desplegable(page, "color", log_fn)
        _human_sleep(1200, 300)

        # Elegir la primera opción disponible
        if _elegir_primera_opcion(page, log_fn, field_id="color"):
            _human_sleep(500, 150)
            _cerrar_desplegables_vinted(page, log_fn)
            return True
    except Exception as e:
        _log(f"Fallo al elegir primer color sugerido: {e}", log_fn)

    # Fallback clásico
    _log("Fallback: intentando seleccionar color Varios...", log_fn)
    _cerrar_desplegables_vinted(page, log_fn)
    return _seleccionar_dropdown(
        page, "color", "Varios", log_fn,
        candidatos=["Varios", "Negro", "Gris", "Plateado", "Multicolor"],
    )


def _seleccionar_categoria_recomendada(page, log_fn=None) -> bool:
    try:
        _log("Buscando categoría recomendada directamente en la página...", log_fn)
        # Capa 1: Buscar sugerencia en la página principal directamente (sin abrir modal)
        # Esperamos un momento para que Vinted genere las recomendaciones basadas en título/descripción
        for _ in range(6): # Esperar hasta 3 segundos (6 * 500ms)
            res = page.evaluate("""() => {
                // Buscamos cualquier elemento con separador de ruta de categoría (e.g. ' > ' o ' › ')
                // que sea clicable/interactivo
                const candidates = [...document.querySelectorAll('button, [role="button"], span, div.web_ui__Chip__chip')]
                    .filter(el => {
                        const txt = (el.innerText || '').trim();
                        return (txt.includes('>') || txt.includes('›')) && txt.length > 5 && txt.length < 120;
                    });
                if (candidates.length > 0) {
                    candidates[0].click();
                    return candidates[0].innerText || '(ok)';
                }
                
                // Fallback de cabecera de sugerencias en la página principal
                const headers = [...document.querySelectorAll('h3, h4, p, div, span')]
                    .filter(el => {
                        const txt = (el.innerText || '').trim().toLowerCase();
                        return txt.includes('categor') && (txt.includes('suger') || txt.includes('recomend'));
                    });
                for (const h of headers) {
                    const parent = h.parentElement;
                    if (parent) {
                        const btn = parent.querySelector('button, [role="button"], div.web_ui__Chip__chip');
                        if (btn) {
                            btn.click();
                            return btn.innerText || '(ok)';
                        }
                    }
                }
                return null;
            }""")
            if res:
                _log(f"Categoría recomendada seleccionada directamente en página: {res!r}", log_fn)
                _human_sleep(1000, 300)
                return True
            time.sleep(0.5)

        # Capa 2: Si no se encuentra en la página principal, abrimos el modal de categoría
        _log("No se encontró sugerencia directa en página. Abriendo buscador de categoría...", log_fn)
        _abrir_desplegable(page, "category", log_fn)
        _human_sleep(1500, 500)

        # Esperamos a que carguen las sugerencias en la modal (buscando cabeceras de sugerencia)
        for _ in range(6): # Esperar hasta 3 segundos
            res = page.evaluate("""() => {
                // Buscamos cabeceras de sugerencias dentro de la modal/dialog de categoría
                const modal = document.querySelector('.web_ui__Modal__modal, [role="dialog"]');
                if (!modal) return null;
                const headers = [...modal.querySelectorAll('h3, h4, div, span')]
                    .filter(el => {
                        const txt = (el.innerText || '').trim().toLowerCase();
                        return txt.includes('suger') || txt.includes('recomend') || txt.includes('suggest');
                    });
                if (headers.length > 0) {
                    const header = headers[0];
                    let sibling = header.nextElementSibling;
                    while (sibling) {
                        const opt = sibling.querySelector('button, [role="button"], li, .web_ui__Cell__title') 
                            || (sibling.matches('button, [role="button"], li, .web_ui__Cell__title') ? sibling : null);
                        if (opt) {
                            opt.click();
                            return opt.innerText || '(ok)';
                        }
                        sibling = sibling.nextElementSibling;
                    }
                    const parent = header.parentElement;
                    if (parent) {
                        const opt = parent.querySelector('button, [role="button"], li, .web_ui__Cell__title');
                        if (opt) {
                            opt.click();
                            return opt.innerText || '(ok)';
                        }
                    }
                }
                // Si aún no hay cabecera de sugerencias, buscamos si hay alguna opción que sea una ruta completa
                const items = [...modal.querySelectorAll('.web_ui__Cell__title, [role="option"], li.web_ui__Item__item')];
                const paths = items.filter(el => {
                    const txt = (el.innerText || '');
                    return (txt.includes('>') || txt.includes('›')) && txt.length < 100;
                });
                if (paths.length > 0) {
                    paths[0].click();
                    return paths[0].innerText || '(ok)';
                }
                return null;
            }""")
            if res:
                _log(f"Categoría recomendada seleccionada en modal: {res!r}", log_fn)
                _human_sleep(1000, 300)
                _cerrar_desplegables_vinted(page, log_fn)
                return True
            time.sleep(0.5)

        # Fallback de último recurso: elegir la primera opción que encontremos
        _log("Ninguna sugerencia de categoría encontrada en modal. Eligiendo primera opción disponible...", log_fn)
        if _elegir_primera_opcion(page, log_fn, field_id="category"):
            _human_sleep(1000, 300)
            _cerrar_desplegables_vinted(page, log_fn)
            return True
            
    except Exception as e:
        _log(f"Error al seleccionar categoría recomendada: {e}", log_fn)
    return False


def _seleccionar_categoria(page, producto: dict, log_fn=None) -> bool:
    actual = _leer_input(page, "category")
    if actual:
        _log(f"Categoría ya seleccionada: {actual!r}", log_fn)
        return True
    return _seleccionar_categoria_recomendada(page, log_fn)


def _seleccionar_talla(page, log_fn=None) -> bool:
    if not page.locator("#size").is_visible(timeout=2_000):
        return True

    # Si ya tiene una de las tallas únicas seleccionadas, no la tocamos
    actual = _leer_input(page, "size")
    if actual and any(t.lower() in actual.lower() for t in TALLAS_VINTED):
        _log(f"#size ya OK (es talla única): {actual!r}", log_fn)
        return True

    _log("Forzando selección de 'Talla única'...", log_fn)
    _abrir_desplegable(page, "size", log_fn)
    _human_sleep(1200, 300)

    # Intentar buscar "Talla única" o similares en la lista usando JS optimizado para cuadrículas (filter-grid)
    res = page.evaluate("""() => {
        const targets = ["talla única", "una talla", "talla unica", "única", "sin talla", "one size"];
        
        // 1. Intentar buscar por aria-label exacto en cualquier checkbox o elemento de la modal
        const elements = [...document.querySelectorAll('[role="checkbox"], [role="option"], .filter-grid__option, li, div, span')];
        for (const el of elements) {
            const ariaLabel = (el.getAttribute('aria-label') || '').trim().toLowerCase();
            if (targets.some(t => ariaLabel === t || ariaLabel.startsWith(t))) {
                el.click();
                return `aria-label match: ${el.getAttribute('aria-label')}`;
            }
        }
        
        // 2. Buscar por coincidencia de texto en elementos hoja específicos (spans, celdas) para evitar pulsar contenedores grandes
        const leaves = [...document.querySelectorAll('span, div.web_ui__Cell__title, div.filter-grid__option, .web_ui__Text__text')]
            .filter(el => {
                const txt = (el.innerText || el.textContent || '').trim().toLowerCase();
                return targets.some(t => txt === t || txt.startsWith(t));
            });
            
        if (leaves.length > 0) {
            const leaf = leaves[0];
            // Encontrar el elemento interactivo más cercano
            const clickable = leaf.closest('[role="checkbox"], [role="option"], .filter-grid__option, button') || leaf;
            clickable.click();
            return `leaf match: ${leaf.innerText}`;
        }
        return null;
    }""")
    if res:
        _log(f"#size OK (JS click exacto): {res!r}", log_fn)
        _cerrar_desplegables_vinted(page, log_fn)
        return True

    # Fallback Playwright en la lista visible
    for texto in TALLAS_VINTED:
        for sel in (
            "div[role='checkbox']",
            ".filter-grid__option",
            "motion\\:div[role='button']",
            "li.web_ui__Item__item",
            "[role='option']",
            ".web_ui__Cell__title"
        ):
            try:
                loc = page.locator(sel).filter(has_text=texto)
                if loc.count() > 0:
                    loc.first.click(force=True)
                    _human_sleep(500, 100)
                    _log(f"#size OK (playwright): {texto!r}", log_fn)
                    _cerrar_desplegables_vinted(page, log_fn)
                    return True
            except Exception:
                continue

    # Fallback supremo: si no encuentra "Talla única", coge la primera que recomiende
    _log("#size: Ninguna talla única coincide, seleccionando primera opción disponible...", log_fn)
    if _elegir_primera_opcion(page, log_fn, field_id="size"):
        _cerrar_desplegables_vinted(page, log_fn)
        return True

    _cerrar_desplegables_vinted(page, log_fn)
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
        'label[data-testid="package_type_selector_1"]',       # Wrapper label
        'label[for="package_type_selector_1"]',              # For attribute wrapper
        '[data-testid="package_type_selector_1--input"]',   # radio input directo
        '#package_type_selector_1',                          # ID directo
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
            _log(f"Paquete pequeño OK (selector: {sel})", log_fn)
            return True
        except Exception:
            continue
    _log("Paquete no seleccionado (no crítico)", log_fn)
    return False


def _rellenar_isbn(page, isbn: str, log_fn=None) -> bool:
    if not isbn:
        return True
    
    loc = page.locator("input#isbn, input[name='isbn'], [data-testid='isbn']").first
    try:
        if loc.count() > 0 and loc.is_visible(timeout=1_500):
            _log(f"Rellenando ISBN: {isbn}...", log_fn)
            loc.scroll_into_view_if_needed()
            loc.click(force=True)
            loc.fill("")
            loc.fill(isbn)
            page.keyboard.press("Tab")
            _human_sleep(400, 150)
            return True
    except Exception as e:
        _log(f"No se pudo rellenar el ISBN (no crítico): {e}", log_fn)
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

            cat_ok = _seleccionar_categoria(page, producto, log_fn)
            marca_ok = _seleccionar_marca(page, producto, log_fn)
            plat_ok = _seleccionar_plataforma(page, producto, log_fn)
            cond_ok = _seleccionar_condicion(page, producto.get("estado_vinted", ""), log_fn=log_fn)
            color_ok = _seleccionar_color(page, log_fn)
            talla_ok = _seleccionar_talla(page, log_fn)
            _seleccionar_clasificacion(page, producto, log_fn)
            _rellenar_isbn(page, str(producto.get("isbn", "")), log_fn)

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
                raise RuntimeError(
                    f"Condición no seleccionada en Vinted (esperado: {producto.get('estado_vinted') or VINTED_CONDICION_PUBLICACION})"
                )
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
