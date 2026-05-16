import os
import certifi
os.environ['SSL_CERT_FILE'] = certifi.where()

import undetected_chromedriver as uc
import time
import pickle

driver = uc.Chrome()
driver.get("https://www.vinted.es/member/signup/select_type?ref_url=%2F")

print("Inicia sesión manualmente en la ventana que se ha abierto. Cuando veas tu perfil, pulsa Enter aquí.")
input("Pulsa Enter para guardar las cookies...")

cookies = driver.get_cookies()
with open("vinted_cookies.pkl", "wb") as f:
    pickle.dump(cookies, f)
print("Cookies guardadas en vinted_cookies.pkl")

driver.quit()