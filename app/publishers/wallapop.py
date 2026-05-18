from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Callable, Optional

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

from config import WALLAPOP_STATE_PATH, WALLAPOP_UPLOAD_URL, ERRORES_DIR
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
            const dd = document.querySelector(`[data-testid="${testid}"]`);
            if (!dd) return '';
            const inp = dd.querySelector('input.sc-walla-text-input, input[type="text"]');
            if (inp && inp.value) return inp.value;
            const hidden = dd.querySelector('input[type="hidden"]');
            if (hidden && hidden.value) return hidden.value;
            const label = dd.getAttribute('aria-label') || '';
            return label;
        }""",
        testid,
    ) or ""


def _seleccionar_estado(page, estado_texto: str, log_fn=None) -> bool:
    """
    Selecciona estado por aria-label exacto en walla-dropdown-item.
    Opciones Wallapop: Sin abrir, En su caja, Nuevo, Como nuevo,
    En buen estado, En condiciones aceptables, Lo ha dado todo.
    """
    from config import ESTADOS_WALLAPOP_VALIDOS

    _log(f"Estado → {estado_texto!r}", log_fn)
    _cerrar_modales(page, log_fn)

    cond = page.locator('[data-testid="condition"]')
    cond.wait_for(state="visible", timeout=10_000)
    cond.scroll_into_view_if_needed()
    cond.click()
    time.sleep(1.2)

    # 1) aria-label exacto
    exact = page.locator(f'walla-dropdown-item[aria-label="{estado_texto}"]')
    if exact.count() > 0:
        exact.first.click()
        time.sleep(0.4)
        _log(f"Estado OK (exacto): {estado_texto}", log_fn)
        return True

    # 2) Recorrer opciones válidas de Wallapop
    opciones = page.locator('walla-dropdown-item[role="option"]')
    for i in range(opciones.count()):
        aria = (opciones.nth(i).get_attribute("aria-label") or "").strip()
        if aria == estado_texto:
            opciones.nth(i).click()
            _log(f"Estado OK: {aria}", log_fn)
            return True

    # 3) Fallback: «En buen estado» si pedían algo inexistente como «Bueno»
    if estado_texto.lower() == "bueno":
        return _seleccionar_estado(page, "En buen estado", log_fn)

    # 4) JS con lista oficial
    ok = page.evaluate(
        """(estado) => {
            for (const item of document.querySelectorAll('walla-dropdown-item[role="option"]')) {
                if (item.getAttribute('aria-label') === estado) {
                    item.click();
                    return estado;
                }
            }
            return null;
        }""",
        estado_texto,
    )
    if ok:
        _log(f"Estado OK (JS): {ok}", log_fn)
        return True

    disponibles = page.evaluate(
        """() => [...document.querySelectorAll('walla-dropdown-item[role="option"]')]
            .map(i => i.getAttribute('aria-label')).filter(Boolean)"""
    )
    _log(f"FALLO estado. Opciones en pantalla: {disponibles}", log_fn)
    _log(f"Valores válidos: {list(ESTADOS_WALLAPOP_VALIDOS)}", log_fn)
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
        loc.fill(texto, force=True)
        page.keyboard.press("Tab")
        time.sleep(0.3)

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
    """Rellena título y descripción usando input# (evita span#title del modal)."""
    _cerrar_modales(page, log_fn)
    tit = page.locator('input#title[name="title"]')
    tit.wait_for(state="visible", timeout=10_000)
    tit.click()
    tit.fill(titulo)
    page.dispatch_event('input#title[name="title"]', "input")

    desc = page.locator("textarea#description, input#description").first
    desc.click()
    desc.fill(descripcion)
    page.dispatch_event("textarea#description", "input")
    time.sleep(0.3)


def _seleccionar_peso(page, log_fn=None) -> None:
    radio = page.locator('input[aria-label="Delivery Option 0"]')
    if radio.count() > 0:
        radio.first.click()
        _log("Peso: 0-1 kg", log_fn)
        return
    page.locator("input.walla-radio__input").first.click()


def _seleccionar_categoria(page, log_fn=None) -> None:
    cat = page.locator('[aria-label="Categoría y subcategoría"]')
    cat.wait_for(state="visible", timeout=15_000)
    cat.click()
    time.sleep(2)
    items = page.locator(".walla-dropdown__floating-area walla-dropdown-item")
    if items.count() > 0:
        items.first.click()
        _log("Categoría seleccionada", log_fn)


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
    estado_texto = producto.get("estado_texto", "En buen estado")
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

            _seleccionar_categoria(page, log_fn)
            time.sleep(1)
            _cerrar_modales(page, log_fn)

            # Paso detalles — selectores estrictos input#
            page.wait_for_selector('input#title[name="title"]', state="visible", timeout=15_000)
            _rellenar_detalles(page, titulo, str(producto["descripcion"]), log_fn)

            estado_ok = _seleccionar_estado(page, estado_texto, log_fn)
            precio_ok = _rellenar_precio(page, precio, log_fn)
            _seleccionar_peso(page, log_fn)

            audit.snapshot(page, "despues_rellenar_detalles", {
                "estado_ok": estado_ok,
                "precio_ok": precio_ok,
            })

            if not estado_ok:
                raise RuntimeError(f"Estado no aplicado en Wallapop (esperado: {estado_texto})")
            if not precio_ok:
                raise RuntimeError(f"Precio no aplicado en Wallapop (esperado: {precio}€)")

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
