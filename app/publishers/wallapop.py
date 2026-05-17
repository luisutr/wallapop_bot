from __future__ import annotations

import time
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

from config import WALLAPOP_STATE_PATH, WALLAPOP_UPLOAD_URL, ERRORES_DIR


def _click_continuar(page, timeout: int = 15_000) -> None:
    page.wait_for_selector("button:has-text('Continuar'):not([disabled])", timeout=timeout)
    page.locator("button:has-text('Continuar'):not([disabled])").click()


def subir_wallapop(producto: dict, slow_mo: int = 300) -> bool:
    """
    Publica un producto en Wallapop usando Playwright.

    producto dict keys:
        slug          str          Identificador del producto (para logs/errores)
        titulo        str          Título del anuncio (máx. 60 chars)
        descripcion   str          Descripción completa
        precio        float        Precio de venta
        estado_texto  str          Texto de estado tal como aparece en Wallapop
                                   ej. "Como nuevo", "Nuevo", "Bueno"…
        fotos         list[str]    Rutas absolutas a las imágenes

    Retorna True si se publicó con éxito, lanza RuntimeError en caso de fallo.
    """
    if not WALLAPOP_STATE_PATH.exists():
        raise RuntimeError(
            "No hay sesión de Wallapop guardada. "
            "Ejecuta la opción 'Guardar sesión Wallapop' primero."
        )

    ERRORES_DIR.mkdir(parents=True, exist_ok=True)
    slug = producto.get("slug", "producto")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=slow_mo)
        context = browser.new_context(storage_state=str(WALLAPOP_STATE_PATH))
        page = context.new_page()
        page.goto(WALLAPOP_UPLOAD_URL, wait_until="domcontentloaded")

        try:
            # Elegir tipo "Algo que ya no necesito"
            page.wait_for_selector("text=Algo que ya no necesito", timeout=15_000)
            page.click("text=Algo que ya no necesito")

            # Paso 1 – Título (campo summary)
            page.fill("#summary", producto["titulo"])
            page.get_by_text("Continuar").click()

            # Paso 2 – Fotos
            page.wait_for_selector("input[type='file']", state="attached", timeout=20_000)
            fotos = [str(Path(f).resolve()) for f in producto["fotos"]]
            file_input = page.locator("input[type='file']")
            try:
                # set_input_files works on hidden elements
                file_input.first.set_input_files(fotos)
            except PWTimeout:
                for f in fotos:
                    file_input.first.set_input_files(f)
                    time.sleep(0.5)
            _click_continuar(page, timeout=45_000)

            # Paso 3 – Categoría (primera sugerida por Wallapop basándose en el título)
            page.wait_for_selector("[aria-label='Categoría y subcategoría']", timeout=15_000)
            page.locator("[aria-label='Categoría y subcategoría']").click()
            page.wait_for_selector(".walla-dropdown__floating-area", timeout=10_000)
            page.locator(".walla-dropdown__floating-area walla-dropdown-item").first.click()

            # Paso 4 – Detalles
            page.wait_for_selector("#title", timeout=15_000)
            page.fill("#title", producto["titulo"])
            page.fill("#description", producto["descripcion"])
            time.sleep(0.5)

            # Estado
            estado_texto = producto.get("estado_texto", "Como nuevo")
            # Buscar el nuevo componente walla-text-input o el label directamente
            estado_dropdown = page.locator("label:has-text('Estado*')")
            if estado_dropdown.count() == 0:
                estado_dropdown = page.locator('div[aria-label="Estado*"]')
            estado_dropdown.first.click()
            
            time.sleep(1) # Esperar animación
            try:
                opcion = page.get_by_text(estado_texto, exact=True)
                if opcion.count() > 0:
                    opcion.first.click()
                else:
                    page.locator(f"text='{estado_texto}'").first.click()
            except Exception:
                pass

            # Precio
            precio_loc = page.locator("#sale_price")
            precio_loc.click()
            precio_loc.fill(str(round(producto["precio"], 2)))
            page.keyboard.press("Tab") # Para que registre el cambio

            # Peso: primera opción (0–1 kg)
            for i in range(page.locator('input.walla-radio__input').count()):
                radio = page.locator('input.walla-radio__input').nth(i)
                if radio.get_attribute("aria-label") == "Delivery Option 0":
                    radio.scroll_into_view_if_needed()
                    radio.click()
                    break

            # Publicar
            page.wait_for_selector("text=Subir producto", timeout=10_000)
            page.locator("text=Subir producto").click()
            time.sleep(5)
            return True

        except Exception as exc:
            error_dir = ERRORES_DIR / f"wallapop_{slug}"
            error_dir.mkdir(exist_ok=True)
            page.screenshot(path=str(error_dir / "error.png"), full_page=True)
            with open(error_dir / "error.html", "w", encoding="utf-8") as f:
                f.write(page.content())
            raise RuntimeError(f"Error publicando '{slug}' en Wallapop: {exc}") from exc

        finally:
            browser.close()
