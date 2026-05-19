from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Callable, Optional

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

from config import (
    ERRORES_DIR,
    ESTADOS_WALLAPOP_VALIDOS,
    WALLAPOP_ESTADO_PUBLICACION,
    WALLAPOP_STATE_PATH,
    WALLAPOP_UPLOAD_URL,
)
from app.publishers.form_audit import PublishAudit, raise_if_not_verified

SUMMARY_MAX = 50


def _log(msg: str, log_fn: Optional[Callable[[str], None]] = None) -> None:
    print(f"  [wallapop] {msg}")
    if log_fn:
        log_fn(msg)


def _cerrar_modales(page, log_fn=None) -> None:
    """Cierra modales que bloquean el formulario (p. ej. Protección Wallapop)."""
    for texto in ("Entendido", "Aceptar", "Cerrar", "Más tarde", "No, gracias"):
        try:
            btn = page.get_by_role("button", name=re.compile(texto, re.I))
            if btn.count() > 0 and btn.first.is_visible(timeout=500):
                btn.first.click()
                _log(f"Modal cerrado: {texto}", log_fn)
                time.sleep(0.8)
        except Exception:
            pass


def _click_continuar(page, timeout: int = 15_000, log_fn=None) -> None:
    _log(f"Esperando Continuar (máx {timeout // 1000}s)...", log_fn)
    page.wait_for_selector(
        "button:has-text('Continuar'):not([disabled])",
        timeout=timeout,
    )
    page.locator("button:has-text('Continuar'):not([disabled])").first.click()


def _rellenar_summary(page, titulo: str) -> None:
    loc = page.locator("input#summary")
    loc.wait_for(state="visible", timeout=10_000)
    loc.click()
    loc.fill("")
    loc.fill(titulo)
    page.dispatch_event("input#summary", "input")
    page.keyboard.press("Tab")
    time.sleep(0.8)


def _leer_valor_dropdown_wallapop(page, testid: str) -> str:
    """Lee el texto mostrado en un walla-dropdown (Estado, Categoría…)."""
    return page.evaluate(
        """(testid) => {
            const dd = document.querySelector(`walla-dropdown[data-testid="${testid}"]`)
                || document.querySelector(`[data-testid="${testid}"]`);
            if (!dd) return '';
            const vis = dd.querySelector(
                'input.sc-walla-text-input, input[type="text"]:not([type="hidden"])'
            );
            if (vis && vis.value) return vis.value.trim();
            const hidden = document.querySelector(`input#${testid}, input[name="${testid}"]`)
                || dd.querySelector('input[type="hidden"]');
            if (hidden && hidden.value) return String(hidden.value).trim();
            return '';
        }""",
        testid,
    ) or ""


def _leer_input_id(page, field_id: str) -> str:
    loc = page.locator(f"input#{field_id}")
    if loc.count() == 0:
        return ""
    try:
        return (loc.first.input_value() or "").strip()
    except Exception:
        return ""


def _categoria_wallapop_ok(page) -> bool:
    """True si Wallapop ya autocompletó la categoría (hoja o campo visible)."""
    return bool(
        page.evaluate(
            """() => {
                const leaf = document.querySelector('input[name="category_leaf_id"]');
                if (leaf && leaf.value) return true;
                const cat = document.querySelector('input#category');
                if (cat && cat.value) return true;
                for (const inp of document.querySelectorAll('input[type="text"]')) {
                    const lbl = inp.getAttribute('aria-label') || '';
                    if (lbl.includes('Categoría') && inp.value.trim()) return true;
                }
                return false;
            }"""
        )
    )


def _esperar_formulario_detalles(page, log_fn=None) -> None:
    page.wait_for_selector('input#title[name="title"]', state="visible", timeout=60_000)
    _log("Formulario de detalles visible — esperando autocompletado…", log_fn)
    time.sleep(3)


def _abrir_dropdown_wallapop(page, testid: str, label_fragment: str = "") -> bool:
    """
    Abre walla-dropdown clicando su trigger real:
      div.walla-dropdown__inner-input[role="button"][slot="floating-area-target-element"]
    Este div está en el LIGHT DOM dentro de walla-floating-area.
    El host walla-dropdown y el input[type=text] con tabindex=-1 NO son el trigger.
    Devuelve True si el flotante quedó abierto (aria-expanded=true).
    """
    opened = page.evaluate(
        """(testid) => {
            const dd = document.querySelector(`walla-dropdown[data-testid="${testid}"]`)
                    || document.querySelector(`[data-testid="${testid}"]`);
            if (!dd) return false;
            // Trigger real: div.walla-dropdown__inner-input[role="button"]
            const trigger =
                dd.querySelector('div.walla-dropdown__inner-input[role="button"]')
                || dd.querySelector('[role="button"][slot="floating-area-target-element"]')
                || dd.querySelector('[role="button"]');
            if (!trigger) return false;
            trigger.scrollIntoView({ block: 'center' });
            trigger.focus();
            trigger.click();
            return trigger.getAttribute('aria-expanded') !== 'false';
        }""",
        testid,
    )
    time.sleep(0.7)

    # Verificar que el flotante quedó abierto
    expanded = page.evaluate(
        """(testid) => {
            const dd = document.querySelector(`walla-dropdown[data-testid="${testid}"]`);
            if (!dd) return false;
            const trigger = dd.querySelector('div.walla-dropdown__inner-input[role="button"]');
            return trigger ? trigger.getAttribute('aria-expanded') === 'true' : false;
        }""",
        testid,
    )
    if expanded:
        return True

    # Fallback Playwright con force=True sobre el trigger div
    try:
        loc = page.locator(
            f'walla-dropdown[data-testid="{testid}"] '
            'div.walla-dropdown__inner-input[role="button"]'
        )
        if loc.count() > 0:
            loc.first.scroll_into_view_if_needed()
            loc.first.click(force=True)
            time.sleep(0.7)
            return True
    except Exception:
        pass
    return False


def _click_opcion_wallapop(page, texto: str, log_fn=None) -> bool:
    """
    Elige una opción del desplegable Stencil por aria-label exacto.
    Usa JS directo porque Playwright a veces falla en web components con Shadow DOM.
    """
    texto = texto.strip()

    # 1) JS directo: busca por aria-label y dispara el click con todos los eventos
    ok = page.evaluate(
        """(objetivo) => {
            const item = document.querySelector(
                `walla-dropdown-item[role="option"][aria-label="${objetivo}"]`
            );
            if (!item) return false;
            item.scrollIntoView({ block: 'center' });
            // Disparar eventos completos para que Stencil/Angular reaccionen
            ['mousedown', 'mouseup', 'click'].forEach(evt =>
                item.dispatchEvent(new MouseEvent(evt, { bubbles: true, cancelable: true }))
            );
            // También el div interior por si el listener está ahí
            const inner = item.querySelector('div.sc-walla-dropdown-item, div');
            if (inner) {
                ['mousedown', 'mouseup', 'click'].forEach(evt =>
                    inner.dispatchEvent(new MouseEvent(evt, { bubbles: true, cancelable: true }))
                );
            }
            return true;
        }""",
        texto,
    )
    if ok:
        time.sleep(0.4)
        _log(f"Opción click JS: {texto!r}", log_fn)
        return True

    # 2) Fallback Playwright con force=True (ignora pointer-events)
    for sel in (
        f'walla-dropdown-item[role="option"][aria-label="{texto}"]',
        "walla-dropdown-item[role='option']",
        ".walla-dropdown__floating-area [role='option']",
    ):
        opts = page.locator(sel)
        for i in range(min(opts.count(), 10)):
            el = opts.nth(i)
            try:
                aria = (el.get_attribute("aria-label") or "").strip()
                if sel.endswith("[role='option']") and aria != texto:
                    continue
                el.scroll_into_view_if_needed()
                el.click(force=True)
                time.sleep(0.4)
                _log(f"Opción click PW: {texto!r}", log_fn)
                return True
            except Exception:
                continue
    return False


def _cerrar_dropdown_abierto(page) -> None:
    try:
        page.keyboard.press("Escape")
        time.sleep(0.2)
    except Exception:
        pass


def _abrir_y_primera_sugerencia(page, field_id: str, log_fn=None) -> bool:
    inp = page.locator(f"input#{field_id}")
    if inp.count() == 0 or not inp.first.is_visible(timeout=1_500):
        return False
    inp.first.scroll_into_view_if_needed()
    inp.first.click()
    time.sleep(1.2)
    items = page.locator(
        ".walla-dropdown__floating-area walla-dropdown-item, "
        "walla-dropdown-item[role='option']"
    )
    if items.count() > 0:
        items.first.click()
        time.sleep(0.4)
        _log(f"#{field_id} → 1ª sugerencia", log_fn)
        return bool(_leer_input_id(page, field_id))
    page.keyboard.press("ArrowDown")
    time.sleep(0.2)
    page.keyboard.press("Enter")
    time.sleep(0.4)
    return bool(_leer_input_id(page, field_id))


def _asegurar_desplegables_wallapop(page, log_fn=None) -> None:
    """
    Deja que Wallapop autocomplete categoría/plataforma.
    Solo abre el desplegable y elige la 1ª opción si el campo sigue vacío.
    """
    if _categoria_wallapop_ok(page):
        _log("Categoría ya autorellenada por Wallapop", log_fn)
    elif page.locator("input#category").count() > 0:
        if not _leer_input_id(page, "category"):
            time.sleep(2)
            if not _leer_input_id(page, "category"):
                _abrir_y_primera_sugerencia(page, "category", log_fn)

    if page.locator("input#video_game_platform").count() == 0:
        return
    if _leer_input_id(page, "video_game_platform"):
        _log("#video_game_platform ya autorellenado", log_fn)
        return
    time.sleep(1.5)
    if not _leer_input_id(page, "video_game_platform"):
        _abrir_y_primera_sugerencia(page, "video_game_platform", log_fn)


def _estado_wallapop_objetivo(estado_texto: str) -> str:
    t = (estado_texto or "").strip()
    if t in ESTADOS_WALLAPOP_VALIDOS:
        return t
    if t.lower() == "bueno":
        return WALLAPOP_ESTADO_PUBLICACION
    return WALLAPOP_ESTADO_PUBLICACION


def _aria_selected_ok(page, objetivo: str) -> bool:
    """True si walla-dropdown-item con el label correcto tiene aria-selected=true."""
    return page.evaluate(
        """(obj) => {
            for (const item of document.querySelectorAll(
                'walla-dropdown-item[role="option"]'
            )) {
                if (item.getAttribute('aria-label') === obj
                        && item.getAttribute('aria-selected') === 'true') {
                    return true;
                }
            }
            return false;
        }""",
        objetivo,
    )


def _leer_condition_hidden(page) -> str:
    """Lee input.walla-dropdown__inner-input__hidden-input#condition via JS (type=hidden)."""
    return page.evaluate(
        """() => {
            const inp = document.querySelector(
                'input.walla-dropdown__inner-input__hidden-input#condition, '
                + 'input#condition[type="hidden"]'
            );
            return inp ? (inp.value || '') : '';
        }"""
    ) or ""


def _estado_aplicado(page, objetivo: str) -> bool:
    """
    Verifica si el estado ya está correctamente seleccionado.
    Los walla-dropdown-item tienen aria-selected accesible incluso con el dropdown cerrado.
    """
    # Criterio 1: aria-selected="true" en el item concreto (más fiable, funciona en abierto y cerrado)
    if _aria_selected_ok(page, objetivo):
        return True
    # Criterio 2: aria-label del trigger contiene el texto (p.ej. "Estado*, En buen estado")
    label_ok = page.evaluate(
        """(obj) => {
            const trigger = document.querySelector(
                'walla-dropdown[data-testid="condition"] [role="button"]'
            );
            if (!trigger) return false;
            const lbl = trigger.getAttribute('aria-label') || '';
            return lbl.toLowerCase().includes(obj.toLowerCase());
        }""",
        objetivo,
    )
    if label_ok:
        return True
    # Criterio 3: hidden input tiene valor distinto de vacío
    # (solo como último recurso; no verifica si coincide con objetivo)
    return bool(_leer_condition_hidden(page))


def _cerrar_dropdown_condition(page) -> None:
    """Cierra el dropdown de estado sin perder la selección (clic en título o Tab)."""
    try:
        # Clic en el título del formulario (fuera del dropdown, no en Escape)
        tit = page.locator('input#title[name="title"]')
        if tit.count() > 0 and tit.first.is_visible(timeout=500):
            tit.first.click(force=True)
            time.sleep(0.5)
            return
    except Exception:
        pass
    try:
        page.keyboard.press("Tab")
        time.sleep(0.3)
    except Exception:
        pass


def _seleccionar_estado(page, estado_texto: str, log_fn=None) -> bool:
    """
    Selecciona estado en walla-dropdown[data-testid=condition].
    El click funciona y pone aria-selected=true; después cierra el dropdown
    con clic exterior para que Angular actualice el formulario.
    """
    objetivo = _estado_wallapop_objetivo(estado_texto)
    _log(f"Estado → {objetivo!r}", log_fn)
    _cerrar_modales(page, log_fn)

    if _estado_aplicado(page, objetivo):
        _log(f"Estado ya OK: {objetivo}", log_fn)
        return True

    abierto = _abrir_dropdown_wallapop(page, "condition", "Estado")
    if not abierto:
        _log("Flotante no se abrió — reintentando con Playwright…", log_fn)
        # Segundo intento: locator Playwright sobre el trigger div
        try:
            trig = page.locator(
                'walla-dropdown[data-testid="condition"] '
                'div.walla-dropdown__inner-input[role="button"]'
            )
            if trig.count() > 0:
                trig.first.scroll_into_view_if_needed()
                trig.first.click(force=True)
                time.sleep(1.0)
        except Exception:
            pass

    try:
        page.wait_for_selector(
            "walla-dropdown-item[role='option']",
            timeout=5_000,
        )
    except PWTimeout:
        _log("No aparecieron opciones de estado", log_fn)
        return False

    time.sleep(0.5)
    clicked = _click_opcion_wallapop(page, objetivo, log_fn)
    if clicked:
        time.sleep(0.6)
        # Cerrar con clic exterior para que Angular/Stencil dispare el evento de cambio
        _cerrar_dropdown_condition(page)
        time.sleep(0.5)
        if _estado_aplicado(page, objetivo):
            _log(f"Estado confirmado: {objetivo}", log_fn)
            return True
        # Segunda comprobación: aria-selected puede persistir aunque el dropdown esté cerrado
        if _aria_selected_ok(page, objetivo):
            _log(f"Estado aria-selected OK: {objetivo}", log_fn)
            return True

    # Fallback: teclado (Tab al dropdown + ArrowDown hasta el item + Enter)
    _log("Fallback teclado para estado…", log_fn)
    _abrir_dropdown_wallapop(page, "condition", "Estado")
    time.sleep(0.8)
    opciones = list(ESTADOS_WALLAPOP_VALIDOS)
    try:
        idx = opciones.index(objetivo)
    except ValueError:
        idx = 4  # "En buen estado" es la 5ª (índice 4)
    for _ in range(idx + 1):
        page.keyboard.press("ArrowDown")
        time.sleep(0.15)
    page.keyboard.press("Enter")
    time.sleep(0.6)
    _cerrar_dropdown_condition(page)
    time.sleep(0.4)
    if _estado_aplicado(page, objetivo):
        _log(f"Estado OK (teclado): {objetivo}", log_fn)
        return True

    disponibles = page.evaluate(
        """() => [...document.querySelectorAll(
            'walla-dropdown-item[role="option"]'
        )].map(i => i.getAttribute('aria-label')).filter(Boolean)"""
    )
    _log(f"FALLO estado. Opciones: {disponibles}", log_fn)
    return False


def _locator_precio_wallapop(page):
    """Wallapop usa #price_amount (no #sale_price) en el formulario actual."""
    for sel in (
        "input#price_amount",
        'input[name="price_amount"]',
        "input#sale_price",
    ):
        loc = page.locator(sel)
        if loc.count() > 0:
            try:
                if loc.first.is_visible(timeout=1_500):
                    return loc.first
            except Exception:
                continue
    return page.locator("input#price_amount")


def _rellenar_precio(page, precio: float, log_fn=None) -> bool:
    """
    Wallapop: el label «Precio*» intercepta clics en #price_amount.
    Usamos JS + label/force como respaldo.
    """
    _log(f"Precio → {precio}€", log_fn)
    loc = _locator_precio_wallapop(page)
    loc.wait_for(state="visible", timeout=10_000)
    loc.scroll_into_view_if_needed()
    _cerrar_modales(page, log_fn)

    texto = str(int(precio)) if precio == int(precio) else f"{precio:.2f}".replace(".", ",")
    valor_js = int(precio) if precio == int(precio) else precio

    ok = page.evaluate(
        """(valor) => {
            const el = document.getElementById('price_amount');
            if (!el) return false;
            el.focus();
            el.value = String(valor);
            el.dispatchEvent(new InputEvent('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
            el.dispatchEvent(new FocusEvent('blur', { bubbles: true }));
            return el.value.replace(',', '.').includes(String(valor));
        }""",
        valor_js,
    )

    if not ok:
        label = page.locator('label[for="price_amount"]')
        if label.count() > 0:
            label.first.click(force=True)
        else:
            loc.click(force=True)
        loc.fill("", force=True)
        loc.type(texto, delay=40)
        page.keyboard.press("Tab")
        time.sleep(0.4)

    if not (loc.input_value() or "").strip():
        loc.click(force=True)
        loc.fill(texto, force=True)
        page.dispatch_event("input#price_amount", "input")
        page.keyboard.press("Tab")
        time.sleep(0.4)

    invalid = loc.get_attribute("aria-invalid")
    val = (loc.input_value() or "").strip()
    ok = str(int(precio)) in val.replace(",", ".") or f"{precio:.0f}" in val
    if ok and invalid != "true":
        _log(f"Precio OK: {val!r}", log_fn)
    elif ok:
        _log(f"Precio en campo ({val!r}) pero aria-invalid=true — Tab extra", log_fn)
        page.keyboard.press("Tab")
        time.sleep(0.3)
        ok = (loc.get_attribute("aria-invalid") or "false") != "true"
    else:
        _log(f"FALLO precio — DOM tiene {val!r}, invalid={invalid}", log_fn)
    return ok


def _rellenar_detalles(page, titulo: str, descripcion: str, log_fn=None) -> None:
    """
    Rellena título y descripción SOLO si Wallapop los dejó vacíos.
    Si ya tienen contenido (auto-generado por Wallapop), se respeta.
    """
    _cerrar_modales(page, log_fn)
    tit = page.locator('input#title[name="title"]')
    tit.wait_for(state="visible", timeout=10_000)

    # Título: solo rellenar si está vacío
    val_tit = (tit.first.input_value() or "").strip()
    if not val_tit:
        tit.first.click()
        tit.first.fill(titulo)
        page.dispatch_event('input#title[name="title"]', "input")
        _log(f"Título rellenado: {titulo!r}", log_fn)
    else:
        _log(f"Título ya tiene valor (Wallapop): {val_tit!r} — se respeta", log_fn)

    # Descripción: solo rellenar si está vacía
    desc = page.locator("textarea#description").first
    if desc.count() == 0:
        desc = page.locator("input#description").first
    val_desc = ""
    try:
        val_desc = (desc.input_value() or "").strip()
    except Exception:
        pass
    if not val_desc:
        desc.click()
        desc.fill(descripcion)
        page.dispatch_event("textarea#description", "input")
        _log("Descripción rellenada", log_fn)
    else:
        _log("Descripción ya tiene valor (Wallapop) — se respeta", log_fn)

    time.sleep(0.3)


def _seleccionar_peso(page, log_fn=None) -> bool:
    """Paquete pequeño: radio 0-1 kg (Delivery Option 0)."""
    # Selectores válidos (sin #0 que es CSS inválido)
    for sel in (
        'input[aria-label="Delivery Option 0"][value="0"]',
        'input.walla-radio__input[aria-label="Delivery Option 0"]',
        'input[aria-label="Delivery Option 0"]',
        'input.walla-radio__input[id="0"]',
    ):
        try:
            radio = page.locator(sel)
        except Exception:
            continue
        if radio.count() == 0:
            continue
        try:
            radio.first.scroll_into_view_if_needed()
            if not radio.first.is_checked(timeout=500):
                radio.first.check(force=True)
            if radio.first.is_checked(timeout=1_000):
                _log("Peso: 0-1 kg (Delivery Option 0)", log_fn)
                return True
        except Exception:
            try:
                radio.first.click(force=True)
                time.sleep(0.3)
                if radio.first.is_checked(timeout=800):
                    _log("Peso: 0-1 kg (click)", log_fn)
                    return True
            except Exception:
                continue
    # Último recurso: JS directo
    ok = page.evaluate(
        """() => {
            for (const r of document.querySelectorAll('input.walla-radio__input, input[type="radio"]')) {
                if (r.getAttribute('aria-label') === 'Delivery Option 0'
                    || r.getAttribute('value') === '0' && r.name === '0') {
                    r.click();
                    return r.checked;
                }
            }
            return false;
        }"""
    )
    if ok:
        _log("Peso: 0-1 kg (JS)", log_fn)
        return True
    _log("FALLO peso — no se marcó Delivery Option 0", log_fn)
    return False


def subir_wallapop(
    producto: dict,
    slow_mo: int = 300,
    log_fn: Optional[Callable[[str], None]] = None,
) -> bool:
    if not WALLAPOP_STATE_PATH.exists():
        raise RuntimeError("No hay sesión de Wallapop guardada.")

    ERRORES_DIR.mkdir(parents=True, exist_ok=True)
    slug = producto.get("slug", "producto")
    titulo = str(producto["titulo"])[:SUMMARY_MAX]
    audit = PublishAudit("wallapop", slug, producto, log_fn=log_fn)
    estado_texto = _estado_wallapop_objetivo(
        producto.get("estado_texto", WALLAPOP_ESTADO_PUBLICACION)
    )
    precio = float(producto["precio"])

    _log(f"Publicando: {titulo}", log_fn)
    claimed_ok = False
    exc_msg: str | None = None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=slow_mo)
        context = browser.new_context(storage_state=str(WALLAPOP_STATE_PATH))
        page = context.new_page()
        page.goto(WALLAPOP_UPLOAD_URL, wait_until="domcontentloaded")

        try:
            page.wait_for_selector("text=Algo que ya no necesito", timeout=15_000)
            page.click("text=Algo que ya no necesito")

            _rellenar_summary(page, titulo)
            try:
                _click_continuar(page, timeout=20_000, log_fn=log_fn)
            except PWTimeout:
                page.get_by_text("Continuar", exact=True).click()

            page.wait_for_selector("input[type='file']", state="attached", timeout=20_000)
            fotos = [str(Path(f).resolve()) for f in producto["fotos"]]
            page.locator("input[type='file']").first.set_input_files(fotos)
            time.sleep(2)
            _click_continuar(page, timeout=180_000, log_fn=log_fn)

            _esperar_formulario_detalles(page, log_fn)
            _cerrar_modales(page, log_fn)

            _rellenar_detalles(page, titulo, str(producto["descripcion"]), log_fn)
            _asegurar_desplegables_wallapop(page, log_fn)

            estado_ok = _seleccionar_estado(page, estado_texto, log_fn)
            precio_ok = _rellenar_precio(page, precio, log_fn)
            peso_ok = _seleccionar_peso(page, log_fn)

            audit.snapshot(page, "despues_rellenar_detalles", {
                "estado_ok": estado_ok,
                "precio_ok": precio_ok,
                "peso_ok": peso_ok,
            })

            if not estado_ok:
                raise RuntimeError(f"Estado no aplicado en Wallapop (esperado: {estado_texto})")
            if not precio_ok:
                raise RuntimeError(f"Precio no aplicado en Wallapop (esperado: {precio}€)")
            if not peso_ok:
                raise RuntimeError("Peso/envío no seleccionado (0-1 kg)")

            pre = audit.check_before_submit(page)
            if not pre["ok"]:
                _log("⚠ Revisa campos en logs/pre_submit", log_fn)

            _cerrar_modales(page, log_fn)
            page.locator("text=Subir producto").first.click()
            time.sleep(2)
            _cerrar_modales(page, log_fn)

            verify = audit.verify_after_submit(page, wait_ms=12_000)
            if _locator_precio_wallapop(page).is_visible(timeout=2_000):
                raise RuntimeError(
                    "Wallapop: el formulario sigue visible tras enviar "
                    "(estado/precio u otro campo no válido)."
                )
            raise_if_not_verified(audit, verify)

            claimed_ok = True
            _log("✓ Publicado y verificado en Wallapop.", log_fn)
            audit.finalize(True, None, verify)
            return True

        except Exception as exc:
            exc_msg = str(exc)
            try:
                audit.snapshot(page, "error", screenshot=True)
                d = ERRORES_DIR / f"wallapop_{slug}"
                d.mkdir(exist_ok=True)
                page.screenshot(path=str(d / "error.png"), full_page=True)
            except Exception:
                pass
            raise RuntimeError(f"Wallapop — {slug}: {exc}") from exc
        finally:
            if not claimed_ok:
                audit.finalize(claimed_ok, exc_msg)
            browser.close()
