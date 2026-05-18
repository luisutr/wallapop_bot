"""
Importa productos desde inventario_articulos.csv + carpeta de imágenes.

Formato esperado (por fila):
  Título del producto, imagen1.jpg, imagen2.jpg, ..., 9€
El precio es siempre el último campo y termina en €.
"""
from __future__ import annotations

import json
import re
import shutil
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from config import LOTE_DIR, EXTENSIONES_IMAGEN

PRICE_TAIL_RE = re.compile(r",\s*(\d+(?:[.,]\d+)?)\s*€\s*$", re.IGNORECASE)
IMG_SUFFIX_RE = re.compile(r"_(\d+)$")


@dataclass
class ProductoCSV:
    titulo: str
    precio: float
    imagenes: list[str]  # nombres de archivo
    slug: str = ""
    imagenes_encontradas: list[Path] = field(default_factory=list)
    imagenes_faltantes: list[str] = field(default_factory=list)

    @property
    def listo(self) -> bool:
        return bool(self.imagenes_encontradas) and not self.imagenes_faltantes


def _slug_desde_titulo_o_imagen(titulo: str, primera_imagen: str) -> str:
    """Genera slug único a partir del nombre de la primera imagen (sin _1) o del título."""
    if primera_imagen:
        base = Path(primera_imagen).stem
        base = IMG_SUFFIX_RE.sub("", base)
        slug = base.lower()
    else:
        slug = titulo.lower()
    slug = unicodedata.normalize("NFD", slug)
    slug = "".join(c for c in slug if unicodedata.category(c) != "Mn")
    slug = re.sub(r"[^a-z0-9]+", "_", slug).strip("_")
    return slug[:80] or "producto"


def _parsear_precio(texto: str) -> float:
    t = texto.strip().replace("€", "").replace(",", ".").strip()
    return float(t)


def parsear_linea_csv(linea: str) -> ProductoCSV | None:
    """Parsea una línea del CSV de inventario."""
    linea = linea.strip()
    if not linea or linea.lower().startswith("producto"):
        return None

    m = PRICE_TAIL_RE.search(linea)
    if not m:
        return None

    precio = _parsear_precio(m.group(1))
    resto = linea[: m.start()].strip()

    # Título = hasta la primera coma (fuera de comillas iniciales)
    if resto.startswith('"'):
        # "titulo con, coma", imgs...
        pass

    primera_coma = resto.find(",")
    if primera_coma < 0:
        return None

    titulo = resto[:primera_coma].strip().strip('"')
    imgs_raw = resto[primera_coma + 1 :].strip().strip('"')

    imagenes = [
        img.strip().strip('"')
        for img in re.split(r",\s*", imgs_raw)
        if img.strip()
        and any(ext in img.lower() for ext in (".jpg", ".jpeg", ".png", ".webp"))
    ]
    # Si el split falló (una sola imagen sin extensión detectada)
    if not imagenes and imgs_raw:
        imagenes = [imgs_raw.strip()]

    slug = _slug_desde_titulo_o_imagen(titulo, imagenes[0] if imagenes else "")

    return ProductoCSV(
        titulo=titulo,
        precio=precio,
        imagenes=imagenes,
        slug=slug,
    )


def leer_csv_inventario(csv_path: Path) -> list[ProductoCSV]:
    """Lee todas las filas del CSV."""
    texto = csv_path.read_text(encoding="utf-8-sig")
    productos: list[ProductoCSV] = []
    slugs_usados: dict[str, int] = {}

    for linea in texto.splitlines():
        p = parsear_linea_csv(linea)
        if not p:
            continue
        # Slugs únicos
        base = p.slug
        if base in slugs_usados:
            slugs_usados[base] += 1
            p.slug = f"{base}_{slugs_usados[base]}"
        else:
            slugs_usados[base] = 0
        productos.append(p)

    return productos


def resolver_imagenes(productos: list[ProductoCSV], carpeta_imagenes: Path) -> None:
    """Busca cada imagen en la carpeta y rellena encontradas/faltantes."""
    carpeta_imagenes = carpeta_imagenes.resolve()
    indice: dict[str, Path] = {}
    for f in carpeta_imagenes.iterdir():
        if f.is_file() and f.suffix.lower() in EXTENSIONES_IMAGEN:
            indice[f.name.lower()] = f

    for p in productos:
        p.imagenes_encontradas = []
        p.imagenes_faltantes = []
        for nombre in p.imagenes:
            path = indice.get(nombre.lower())
            if path:
                p.imagenes_encontradas.append(path)
            else:
                p.imagenes_faltantes.append(nombre)


def importar_a_lote(
    productos: list[ProductoCSV],
    *,
    estado: str = "bueno",
    publicar_en: list[str] | None = None,
    sobrescribir: bool = False,
    lote_dir: Path = LOTE_DIR,
) -> tuple[int, int, list[str]]:
    """
    Copia imágenes a lote/<slug>/ y crea meta.json.
    Devuelve (importados_ok, omitidos, errores).
    """
    lote_dir.mkdir(parents=True, exist_ok=True)
    publicar_en = publicar_en or ["wallapop", "vinted"]
    importados = 0
    omitidos = 0
    errores: list[str] = []

    for p in productos:
        if not p.listo:
            omitidos += 1
            errores.append(
                f"{p.titulo}: faltan imágenes {', '.join(p.imagenes_faltantes)}"
            )
            continue

        dest = lote_dir / p.slug
        if dest.exists():
            if not sobrescribir:
                omitidos += 1
                errores.append(f"{p.slug}: ya existe (usa sobrescribir)")
                continue
            shutil.rmtree(dest)

        dest.mkdir(parents=True, exist_ok=True)

        for i, img_path in enumerate(sorted(p.imagenes_encontradas), 1):
            ext = img_path.suffix.lower()
            shutil.copy2(img_path, dest / f"{i:02d}{ext}")

        meta = {
            "titulo": p.titulo,
            "precio_manual": p.precio,
            "estado": estado,
            "publicar_en": publicar_en,
        }
        with open(dest / "meta.json", "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)

        importados += 1

    return importados, omitidos, errores
