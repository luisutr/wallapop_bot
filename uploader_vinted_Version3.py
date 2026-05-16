# uploader_vinted_debug.py
# pip install playwright pandas certifi
# luego: playwright install chromium

import os, time, pickle, certifi
from pathlib import Path
import pandas as pd
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
import random

CSV_PATH = "productosV.csv"
COOKIES_PKL = "vinted_cookies.pkl"
UPLOAD_URL = "https://www.vinted.es/items/new"



def human_sleep(base=1000, variation=500):
    """Espera un tiempo aleatorio entre base ± variation (ms)."""
    time.sleep((base + random.randint(-variation, variation)) / 1000)

def _map_cookie_samesite(v):
    if v is None:
        return "Lax"
    v = str(v).strip().lower()
    if v in ["no_restriction", "none"]:
        return "None"
    if v in ["lax"]:
        return "Lax"
    if v in ["strict"]:
        return "Strict"
    return "Lax"

def _load_cookies_for_playwright(pickle_path: str):
    with open(pickle_path, "rb") as f:
        raw = pickle.load(f)
    cookies = []
    for c in raw:
        try:
            cookies.append({
                "name": c["name"],
                "value": c["value"],
                "domain": c.get("domain") or ".vinted.es",
                "path": c.get("path", "/"),
                "expires": int(c.get("expiry", 0) or 0),
                "httpOnly": bool(c.get("httpOnly", False)),
                "secure": bool(c.get("secure", True)),
                "sameSite": _map_cookie_samesite(c.get("sameSite"))
            })
        except Exception:
            continue
    return cookies

def click_dropdown_and_pick(page, input_id: str, value_text: str, timeout=15000):
    try:
        print(f"🔹 Seleccionando dropdown {input_id} -> {value_text}")
        page.locator(f"#{input_id}").click()
        if input_id == "category":
            srch = page.locator("#catalog-search-input")
            if srch.count() > 0:
                srch.fill(value_text)
                human_sleep(3000, 1000)
        option = page.locator("div[role='button'] div.web_ui__Cell__title").filter(has_text=value_text).first
        if option.count() == 0:
            option = page.locator(f"//li//span[normalize-space()='{value_text}']").first
        option.wait_for(state="visible", timeout=timeout)
        option.click()
        print(f"✅ {input_id} seleccionado")
    except PWTimeout:
        print(f"⚠️ Timeout seleccionando {input_id}, intentando fallback")
        page.locator(f"#{input_id}").click()
        page.keyboard.press("Enter")

def search_list_and_pick(page, input_id: str, value_text: str, timeout=15000):
    try:
        print(f"🔹 Buscando en input {input_id} -> {value_text}")
        inp = page.locator(f"#{input_id}")
        inp.click()
        inp.fill(value_text)
        human_sleep(3000, 1000)
        option = page.locator("div[role='button'] div.web_ui__Cell__title").filter(has_text=value_text).first
        if option.count() == 0:
            inp.press("Enter")
        else:
            option.wait_for(state="visible", timeout=timeout)
            option.click()
        print(f"✅ {input_id} seleccionado")
    except PWTimeout:
        print(f"⚠️ Timeout buscando {input_id}, fallback a Enter")
        page.locator(f"#{input_id}").press("Enter")

def select_condition(page, desired_text):
    # Alias para textos que no coinciden exactamente
    alias_map = {
        "Como nuevo": "Nuevo con etiquetas",
        "Nuevo": "Nuevo sin etiquetas",
        "Muy bueno": "Muy bueno",
        "Bueno": "Bueno",
        "Satisfactorio": "Satisfactorio"
    }
    text_to_click = alias_map.get(desired_text, desired_text)

    try:
        # 1️⃣ Click en el input para abrir el dropdown
        page.locator("input#condition").click()

        # 2️⃣ Esperar a que aparezcan las opciones
        page.wait_for_selector(f"div.web_ui__Cell__title:text('{text_to_click}')", timeout=8000)

        # 3️⃣ Click en la opción correcta
        page.locator(f"div.web_ui__Cell__title:text('{text_to_click}')").first.click()
        print(f"✅ Seleccionado condition -> {text_to_click}")

    except Exception as e:
        print(f"⚠️ Timeout o error seleccionando condition '{desired_text}': {e}")


def subir_un_producto(page, row, index):
    try:
        print(f"\n=== Publicando {index+1}: {row['titulo']} ===")

        # ---------- Fotos ----------
        rutas = [str(Path(p).expanduser().resolve()) for p in str(row["imagenes"]).replace("|", ";").split(";") if
                 p.strip()]

        # localizamos el input aunque esté oculto
        file_input = page.locator("input[data-testid='add-photos-input']").first
        file_input.set_input_files(rutas)  # Playwright ignora que esté hidden

        # Espera a que Vinted autocompletar título/desc desde la foto (tarda unos segundos)
        human_sleep(3000, 1000)

        # ---------- Resto de campos ----------
        page.locator("#title").fill(str(row["titulo"]))
        page.locator("#description").fill(str(row["descripcion"]))
        page.locator("#price").fill(str(row["precio"]))
        human_sleep(3000, 1000)

        click_dropdown_and_pick(page, "category", str(row["categoria"]))
        search_list_and_pick(page, "video_game_platform", str(row["plataforma"]))
        click_dropdown_and_pick(page, "video_game_rating", str(row["clasificacion"]))
        select_condition(page, str(row["estado"]))
        human_sleep(3000, 1000)

        print("🚀 Subiendo artículo...")
        page.locator("button[data-testid='upload-form-save-button']").click()
        human_sleep(3000, 1000)
        print("✅ Artículo subido correctamente")

    except Exception as e:
        print(f"❌ Error subiendo '{row['titulo']}': {e}")
        page.screenshot(path=f"error_{index}.png", full_page=True)
        with open(f"error_{index}.html", "w", encoding="utf-8") as f:
            f.write(page.content())


def main():
    df = pd.read_csv(CSV_PATH)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=150)
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        )

        # Cookies
        cookies = _load_cookies_for_playwright(COOKIES_PKL)
        if cookies:
            context.add_cookies(cookies)

        page = context.new_page()
        page.goto(UPLOAD_URL, wait_until="domcontentloaded")
        human_sleep(3000, 1000)
        page.goto(UPLOAD_URL, wait_until="domcontentloaded")

        for i, row in df.iterrows():
            try:
                page.wait_for_selector("input[data-testid='add-photos-input']", state="attached", timeout=20000)
                subir_un_producto(page, row, i)
                human_sleep(3000, 1000)
            except Exception as e:
                print(f"❌ Error general en artículo '{row['titulo']}': {e}")
                page.screenshot(path=f"general_error_{i}.png", full_page=True)
                with open(f"general_error_{i}.html", "w", encoding="utf-8") as f:
                    f.write(page.content())
                # recargar editor
                page.goto(UPLOAD_URL, wait_until="domcontentloaded")

        context.close()
        browser.close()

if __name__ == "__main__":
    os.environ["SSL_CERT_FILE"] = certifi.where()
    main()
