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
import subprocess
import sys
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
    isbn: str = ""

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
    # Deprecado: la lectura ahora se realiza a través del lector de csv estándar
    return None


def leer_csv_inventario(csv_path: Path) -> list[ProductoCSV]:
    """Lee todas las filas del CSV utilizando el módulo csv estándar."""
    import csv
    productos: list[ProductoCSV] = []
    slugs_usados: dict[str, int] = {}

    try:
        texto = csv_path.read_text(encoding="utf-8-sig")
    except Exception:
        texto = csv_path.read_text(encoding="latin1")

    reader = csv.reader(texto.splitlines())
    header = next(reader, None)  # Saltar cabecera

    for row in reader:
        if not row or not row[0].strip():
            continue
        # Evitar procesar cabecera secundaria si se duplicó
        if row[0].lower().startswith("producto") or row[0].lower().startswith("titulo"):
            continue

        titulo = row[0].strip()
        imgs_raw = row[1].strip() if len(row) > 1 else ""
        precio_raw = row[2].strip() if len(row) > 2 else "0"
        isbn = row[3].strip() if len(row) > 3 else ""

        try:
            precio = _parsear_precio(precio_raw)
        except Exception:
            precio = 0.0

        # Parsear imágenes (separadas por comas, punto y coma o espacios)
        imagenes = [
            img.strip()
            for img in re.split(r"[,;]\s*", imgs_raw)
            if img.strip()
            and any(ext in img.lower() for ext in (".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".heic", ".heif"))
        ]
        if not list(imagenes) and imgs_raw:
            imagenes = [imgs_raw.strip()]

        slug = _slug_desde_titulo_o_imagen(titulo, imagenes[0] if imagenes else "")

        # Garantizar slug único
        base = slug
        if base in slugs_usados:
            slugs_usados[base] += 1
            slug = f"{base}_{slugs_usados[base]}"
        else:
            slugs_usados[base] = 0

        productos.append(
            ProductoCSV(
                titulo=titulo,
                precio=precio,
                imagenes=list(imagenes),
                slug=slug,
                isbn=isbn,
            )
        )

    return productos


def convert_heic_to_jpg(src_path: Path, dest_path: Path) -> bool:
    """Convierte una imagen HEIC/HEIF a JPG. Retorna True si tiene éxito."""
    # Intentar usar la herramienta nativa sips de macOS ya que es sumamente rápida y preinstalada
    if sys.platform == "darwin":
        try:
            subprocess.run(
                ["sips", "-s", "format", "jpeg", str(src_path), "--out", str(dest_path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True
            )
            if dest_path.exists():
                return True
        except Exception:
            pass

    # Alternativa/Fallback: usar pillow_heif si está disponible
    try:
        from PIL import Image
        import pillow_heif
        pillow_heif.register_heif_opener()
        img = Image.open(src_path)
        img.convert("RGB").save(dest_path, "JPEG")
        return True
    except Exception:
        pass

    return False


def resolver_imagenes(productos: list[ProductoCSV], carpeta_imagenes: Path) -> None:
    """Busca cada imagen en la carpeta (incluyendo subcarpetas) y rellena encontradas/faltantes."""
    carpeta_imagenes = carpeta_imagenes.resolve()
    indice: dict[str, Path] = {}
    
    # Extensiones a buscar: las estándar + HEIC/HEIF
    extensiones_busqueda = list(EXTENSIONES_IMAGEN) + [".heic", ".heif"]
    
    # Búsqueda recursiva para indexar imágenes de subcarpetas (como "converted")
    for ext in extensiones_busqueda:
        for f in carpeta_imagenes.rglob(f"*{ext}"):
            if f.is_file():
                indice[f.name.lower()] = f
        for f in carpeta_imagenes.rglob(f"*{ext.upper()}"):
            if f.is_file():
                indice[f.name.lower()] = f

    for p in productos:
        p.imagenes_encontradas = []
        p.imagenes_faltantes = []
        for nombre in p.imagenes:
            path = None
            path_obj = Path(nombre)
            # Si el original es HEIC/HEIF, buscar primero si ya existe versión convertida (.jpg, .png, etc.)
            if path_obj.suffix.lower() in (".heic", ".heif"):
                for ext in EXTENSIONES_IMAGEN:
                    posible_nombre = f"{path_obj.stem}{ext}".lower()
                    path = indice.get(posible_nombre)
                    if path:
                        break
            
            # Si no existe versión convertida, buscar el archivo original (incluyendo HEIC)
            if not path:
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
            if ext in (".heic", ".heif"):
                # Convertir HEIC a JPG dinámicamente
                dest_img = dest / f"{i:02d}.jpg"
                exito = convert_heic_to_jpg(img_path, dest_img)
                if not exito:
                    # Fallback si falla: copiar original
                    shutil.copy2(img_path, dest / f"{i:02d}{ext}")
            else:
                shutil.copy2(img_path, dest / f"{i:02d}{ext}")

        meta = {
            "titulo": p.titulo,
            "precio_manual": p.precio,
            "estado": estado,
            "publicar_en": publicar_en,
        }
        if getattr(p, "isbn", ""):
            meta["isbn"] = p.isbn

        with open(dest / "meta.json", "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)

        importados += 1

    return importados, omitidos, errores
