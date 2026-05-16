# uploader_wallapop.py
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
import time

def _click_continuar(page, timeout=15000):
    page.wait_for_selector("button:has-text('Continuar'):not([disabled])", timeout=timeout)
    page.locator("button:has-text('Continuar'):not([disabled])").click()

def subir_wallapop(producto, state_path="wallapop_state.json", slow_mo=300):
    """
    producto: dict con keys
      - titulo, descripcion, precio (num/str), categoria (p.ej 'Ropa > Camisetas'),
        estado (p.ej 'Nuevo' / 'Como nuevo' / 'En buen estado'...),
        localizacion (ciudad o dirección), fotos ('ruta1;ruta2;...')
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=slow_mo)
        context = browser.new_context(storage_state=state_path)
        page = context.new_page()

        # Ir a subir producto (ya logueado por storage_state)
        page.goto("https://es.wallapop.com/app/catalog/upload", wait_until="domcontentloaded")

        try:

            # Espera y pulsa en "Algo que ya no necesito"
            page.wait_for_selector("text=Algo que ya no necesito", timeout=15000)
            page.click("text=Algo que ya no necesito")

            # Paso 1: Resumen
            page.fill("#summary", producto["titulo"])
            page.get_by_text("Continuar").click()

            # ===== Paso 2: Fotos =====
            # Espera a que aparezca la zona de fotos
            page.wait_for_selector(".DropAreaZone__wrapper", timeout=15000)

            fotos = [f.strip() for f in str(producto["fotos"]).split(";") if f.strip()]
            # Suele haber un input file oculto; si no, coge el primero disponible
            file_input = page.locator("input[type='file']")
            if file_input.count() == 0:
                # fallback por si el input tarda en montarse
                page.wait_for_selector("input[type='file']", timeout=15000)
                file_input = page.locator("input[type='file']")
            # subir todas a la vez si el input lo permite; si no, una a una
            try:
                file_input.first.set_input_files(fotos)
            except PWTimeout:
                for f in fotos:
                    file_input.first.set_input_files(f)
                    time.sleep(0.5)

            _click_continuar(page)

            # Paso 3: Categoría
            # ===== Paso 3: Categoría =====
            page.wait_for_selector("[aria-label='Categoría y subcategoría']", timeout=15000)
            page.locator("[aria-label='Categoría y subcategoría']").click()

            # Espera a que carguen las sugerencias
            page.wait_for_selector(".walla-dropdown__floating-area", timeout=10000)

            # Haz click en el primer item dentro de "Categorías sugeridas"
            sugerida = page.locator(".walla-dropdown__floating-area walla-dropdown-item").first
            sugerida.click()

            # ===== Paso 4: Detalles =====
            page.wait_for_selector("#title", timeout=15000)
            page.fill("#title", producto["titulo"])
            page.fill("#description", producto["descripcion"])
            time.sleep(0.5)

            # ---- Estado ----
            # Abrir dropdown de estado
            estado_dropdown = page.locator('div[aria-label="Estado*"]')
            estado_dropdown.click()

            # Esperar que las opciones estén visibles
            for _ in range(10):
                opciones = page.locator('.walla-dropdown__floating-area li[role="option"]')
                if opciones.count() > 0:
                    break
                time.sleep(0.5)

            # Buscar opción "Como nuevo" y click
            for i in range(opciones.count()):
                text = opciones.nth(i).inner_text()
                if "Como nuevo" in text:
                    opciones.nth(i).scroll_into_view_if_needed()
                    opciones.nth(i).click()
                    break

            # ---- Precio ----
            page.fill("#sale_price", str(producto["precio"]))

            # ---- Peso (radio button 0-1 kg) ----
            # ===== Seleccionar peso: 0 a 1 kg =====
            peso_opciones = page.locator('input.walla-radio__input')
            for i in range(peso_opciones.count()):
                aria = peso_opciones.nth(i).get_attribute('aria-label')
                if aria == "Delivery Option 0":  # corresponde a 0 a 1 kg
                    peso_opciones.nth(i).scroll_into_view_if_needed()
                    peso_opciones.nth(i).click()
                    break

            # ---- Localización ---- Ya lo pilla automaticamente solo
            #page.fill("#location", str(producto.get("localizacion", "45004, Toledo")))
            #time.sleep(1)
            #page.keyboard.press("ArrowDown")
            #page.keyboard.press("Enter")

            # ===== Publicar =====
            page.wait_for_selector("text=Subir producto", timeout=10000)
            page.locator("text=Subir producto").click()

            time.sleep(5)

        except Exception as e:
            page.screenshot(path="error_wallapop.png", full_page=True)
            with open("error_wallapop.html", "w", encoding="utf-8") as f:
                f.write(page.content())
            raise e
        finally:
            browser.close()