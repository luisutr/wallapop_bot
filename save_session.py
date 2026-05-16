# save_session.py
from playwright.sync_api import sync_playwright

STATE_FILE = "wallapop_state.json"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    # nuevo contexto “limpio”
    context = browser.new_context()
    page = context.new_page()
    page.goto("https://es.wallapop.com/app/")
    print("\n👉 Inicia sesión en la ventana que se ha abierto.")
    print("   Cuando ya estés logueado (veas tu perfil arriba a la derecha), vuelve aquí y pulsa Enter.")
    input("   Pulsa Enter para guardar la sesión... ")

    # guarda cookies + localStorage
    context.storage_state(path=STATE_FILE)
    print(f"✅ Sesión guardada en {STATE_FILE}")
    browser.close()
