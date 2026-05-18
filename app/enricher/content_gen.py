from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from config import ESTADO_WALLAPOP, ESTADO_VINTED, PEGI_DEFAULT
from .identifier import InfoProducto
from .rules.categories import CATEGORIAS_WALLAPOP, CATEGORIAS_VINTED
from .rules.templates import generar_descripcion

# Wallapop acepta hasta 60 caracteres en el título
_MAX_TITULO = 60


@dataclass
class ContenidoProducto:
    titulo_wallapop: str
    titulo_vinted: str
    descripcion_wallapop: str
    descripcion_vinted: str
    categoria_wallapop: str
    categoria_vinted: str
    plataforma_vinted: Optional[str]
    pegi: str
    estado_wallapop: str
    estado_vinted: str
    marca: Optional[str] = None


def generar_contenido(
    info: InfoProducto,
    estado_key: str,
    tipo_override: Optional[str] = None,
    titulo_override: Optional[str] = None,
    descripcion_override: Optional[str] = None,
    pegi_override: Optional[str] = None,
) -> ContenidoProducto:
    tipo = tipo_override or info.tipo
    plataforma = info.plataforma

    # ── Títulos ──────────────────────────────────────────────────────────────
    if titulo_override:
        titulo = titulo_override[:_MAX_TITULO]
    elif plataforma:
        titulo = f"{info.nombre_base} {plataforma['abrev']}"[:_MAX_TITULO]
    else:
        titulo = info.nombre_base[:_MAX_TITULO]

    # ── Categorías ───────────────────────────────────────────────────────────
    categoria_wallapop = CATEGORIAS_WALLAPOP.get(tipo, CATEGORIAS_WALLAPOP["otro"])
    categoria_vinted   = CATEGORIAS_VINTED.get(tipo, CATEGORIAS_VINTED["otro"])

    # ── Plataforma para Vinted ────────────────────────────────────────────────
    plataforma_vinted = (
        plataforma["vinted"] if plataforma and tipo == "videojuego" else None
    )

    # ── Estado ───────────────────────────────────────────────────────────────
    estado_wallapop = ESTADO_WALLAPOP.get(estado_key, "En buen estado")
    estado_vinted   = ESTADO_VINTED.get(estado_key, "Nuevo sin etiquetas")

    # ── Descripciones ─────────────────────────────────────────────────────────
    plataforma_nombre = plataforma["nombre"] if plataforma else ""

    descripcion_wallapop = descripcion_override or generar_descripcion(
        titulo_completo=titulo,
        tipo=tipo,
        estado_key=estado_key,
        plataforma_nombre=plataforma_nombre,
        para_wallapop=True,
    )
    descripcion_vinted = descripcion_override or generar_descripcion(
        titulo_completo=titulo,
        tipo=tipo,
        estado_key=estado_key,
        plataforma_nombre=plataforma_nombre,
        para_wallapop=False,
    )

    return ContenidoProducto(
        titulo_wallapop=titulo,
        titulo_vinted=titulo,
        descripcion_wallapop=descripcion_wallapop,
        descripcion_vinted=descripcion_vinted,
        categoria_wallapop=categoria_wallapop,
        categoria_vinted=categoria_vinted,
        plataforma_vinted=plataforma_vinted,
        pegi=pegi_override or PEGI_DEFAULT,
        estado_wallapop=estado_wallapop,
        estado_vinted=estado_vinted,
        marca=info.marca,
    )
