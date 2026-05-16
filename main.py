# main.py
import pandas as pd
from uploader_wallapop import subir_wallapop

def run(csv_path="productos.csv"):
    df = pd.read_csv(csv_path)
    for idx, row in df.iterrows():
        producto = {
            "titulo": row["titulo"],
            "descripcion": row["descripcion"],
            "precio": row["precio"],
            "categoria": row["categoria"],
            "estado": row["estado"],
            "localizacion": row["localizacion"],
            "fotos": row["fotos"],
        }
        print(f"\n=== Publicando {idx+1}/{len(df)}: {producto['titulo']} ===")
        subir_wallapop(producto)

if __name__ == "__main__":
    run("productos.csv")
