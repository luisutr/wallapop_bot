from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Optional

from .rules.platforms import detectar_plataforma, PLATFORM_KEYWORDS
from .rules.categories import detectar_tipo


@dataclass
class InfoProducto:
    slug: str
    tokens: list[str]
    nombre_base: str            # Nombre limpio sin código de plataforma
    tipo: str                   # "videojuego", "ropa_hombre", etc.
    plataforma: Optional[dict[str, str]]  # Solo si es videojuego
    confianza: float            # 0.0 – 1.0
    requiere_confirmacion: bool
    marca: Optional[str] = None  # Marca detectada (Nike, Hasbro, Apple…)


# Marcas conocidas: token del slug → nombre comercial correcto
_MARCAS: dict[str, str] = {
    # Juguetes
    "hasbro": "Hasbro", "mattel": "Mattel", "lego": "LEGO",
    "playmobil": "Playmobil", "bandai": "Bandai", "funko": "Funko",
    "gijoe": "Hasbro",   # GI Joe es de Hasbro
    "gi": None,          # "gi" solo no es marca (puede ser GI Joe)
    "heman": "Mattel",   # He-Man es Masters of the Universe de Mattel
    "motu": "Mattel",
    # Ropa / calzado
    "nike": "Nike", "adidas": "Adidas", "puma": "Puma",
    "reebok": "Reebok", "converse": "Converse", "vans": "Vans",
    "zara": "Zara", "hm": "H&M",
    # Electrónica
    "apple": "Apple", "samsung": "Samsung", "sony": "Sony",
    "xiaomi": "Xiaomi", "huawei": "Huawei", "lg": "LG",
    "nintendo": "Nintendo", "microsoft": "Microsoft",
    "playstation": "Sony", "ps1": "Sony", "ps2": "Sony", "ps3": "Sony",
    "ps4": "Sony", "ps5": "Sony", "psp": "Sony",
    "mcfun": "McFun",
}

# Partículas que no aportan información y se eliminan del nombre base
_PALABRAS_IGNORAR: frozenset[str] = frozenset({
    "de", "la", "el", "los", "las", "un", "una", "y", "e", "con", "para",
})

# Grafía correcta de marcas y términos técnicos habituales en slugs
_CAPITALIZACION_ESPECIAL: dict[str, str] = {
    "iphone": "iPhone", "ipad": "iPad", "imac": "iMac", "macbook": "MacBook",
    "airpods": "AirPods", "samsung": "Samsung", "xiaomi": "Xiaomi",
    "huawei": "Huawei", "oppo": "OPPO", "nike": "Nike", "adidas": "Adidas",
    "lego": "LEGO", "playstation": "PlayStation",
    "gijoe": "GI Joe", "heman": "He-Man", "motu": "MOTU",
    "funko": "Funko", "playmobil": "Playmobil",
    "gb": "GB", "tb": "TB", "mb": "MB", "ram": "RAM", "ssd": "SSD",
    "hdd": "HDD", "hdmi": "HDMI", "usb": "USB", "wifi": "WiFi",
    "bluetooth": "Bluetooth", "4k": "4K", "8k": "8K",
    "pegi": "PEGI",
}


def _reconstruir_nombre(tokens: list[str], excluir: frozenset[str]) -> str:
    palabras = [t for t in tokens if t not in excluir and t not in _PALABRAS_IGNORAR]
    resultado = []
    for p in palabras:
        if p in _CAPITALIZACION_ESPECIAL:
            resultado.append(_CAPITALIZACION_ESPECIAL[p])
        elif p.isnumeric():
            resultado.append(p)
        else:
            resultado.append(p.capitalize())
    return " ".join(resultado)


def _normalizar_slug(slug: str) -> str:
    """
    Convierte un slug de carpeta en una cadena normalizada para el tokenizador.
    Maneja puntos, guiones, tildes y otros caracteres especiales.
    Ejemplos:
      "g.i._joe_skystorm"  → "gi joe skystorm"
      "he-man_horse"       → "he man horse"
      "helicóptero"        → "helicoptero"
    """
    # Quitar tildes (normalización Unicode NFD → eliminar diacríticos)
    sin_tildes = "".join(
        c for c in unicodedata.normalize("NFD", slug)
        if unicodedata.category(c) != "Mn"
    )
    # Reemplazar puntos y guiones por espacios (luego se separará por _)
    limpio = re.sub(r"[.\-]", "_", sin_tildes)
    # Colapsar múltiples guiones bajos
    limpio = re.sub(r"_+", "_", limpio).strip("_")
    return limpio


def identificar(slug: str) -> InfoProducto:
    """
    Convierte un slug de carpeta (ej. "doom_3_ps3") en un InfoProducto
    con tipo detectado, nombre limpio y datos de plataforma.
    Acepta slugs con puntos, guiones y tildes (ej. "g.i._joe", "he-man", "helicóptero").
    """
    slug_norm = _normalizar_slug(slug)
    tokens = [t for t in slug_norm.lower().split("_") if t]
    plataforma = detectar_plataforma(tokens)
    tipo, confianza = detectar_tipo(tokens, plataforma_detectada=plataforma is not None)

    # Tokens que corresponden a la plataforma se excluyen del nombre base
    excluir = frozenset(t for t in tokens if t in PLATFORM_KEYWORDS)
    nombre_base = _reconstruir_nombre(tokens, excluir)

    # Detectar marca conocida
    marca: Optional[str] = None
    for token in tokens:
        if token in _MARCAS and _MARCAS[token]:
            marca = _MARCAS[token]
            break

    # Solo pregunta si no hubo ningún keyword que apunte a un tipo concreto
    requiere_confirmacion = tipo == "otro" or confianza < 0.25

    return InfoProducto(
        slug=slug,
        tokens=tokens,
        nombre_base=nombre_base,
        tipo=tipo,
        plataforma=plataforma,
        confianza=confianza,
        requiere_confirmacion=requiere_confirmacion,
        marca=marca,
    )
