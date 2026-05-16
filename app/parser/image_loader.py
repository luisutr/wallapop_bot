from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from config import EXTENSIONES_IMAGEN, LOTE_DIR, PLATAFORMAS_DESTINO, ESTADO_DEFAULT


@dataclass
class ProductoLote:
    slug: str
    carpeta: Path
    imagenes: list[Path]
    meta: dict = field(default_factory=dict)

    @property
    def nombre_legible(self) -> str:
        return self.slug.replace("_", " ").title()

    @property
    def publicar_en(self) -> list[str]:
        return self.meta.get("publicar_en", PLATAFORMAS_DESTINO)

    @property
    def estado(self) -> str:
        return self.meta.get("estado", ESTADO_DEFAULT)

    @property
    def precio_manual(self) -> Optional[float]:
        v = self.meta.get("precio_manual")
        return float(v) if v is not None else None

    @property
    def pegi_override(self) -> Optional[str]:
        return self.meta.get("pegi")

    @property
    def titulo_override(self) -> Optional[str]:
        return self.meta.get("titulo")

    @property
    def descripcion_override(self) -> Optional[str]:
        return self.meta.get("descripcion")


def cargar_lote(lote_dir: Path = LOTE_DIR) -> list[ProductoLote]:
    """
    Escanea lote/ y devuelve una lista de ProductoLote.
    Cada subcarpeta es un producto; las imágenes dentro son sus fotos.
    Un fichero meta.json opcional dentro de la carpeta permite sobrescribir campos.
    """
    lote_dir.mkdir(parents=True, exist_ok=True)
    productos: list[ProductoLote] = []

    for carpeta in sorted(lote_dir.iterdir()):
        if not carpeta.is_dir() or carpeta.name.startswith("."):
            continue

        imagenes = sorted(
            f for f in carpeta.iterdir()
            if f.is_file() and f.suffix.lower() in EXTENSIONES_IMAGEN
        )
        if not imagenes:
            continue

        meta: dict = {}
        meta_file = carpeta / "meta.json"
        if meta_file.exists():
            try:
                with open(meta_file, encoding="utf-8") as f:
                    meta = json.load(f)
            except (json.JSONDecodeError, OSError):
                pass

        productos.append(ProductoLote(
            slug=carpeta.name,
            carpeta=carpeta,
            imagenes=imagenes,
            meta=meta,
        ))

    return productos
