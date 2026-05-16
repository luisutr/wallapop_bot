from __future__ import annotations

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


def identificar(slug: str) -> InfoProducto:
    """
    Convierte un slug de carpeta (ej. "doom_3_ps3") en un InfoProducto
    con tipo detectado, nombre limpio y datos de plataforma.
    """
    tokens = slug.lower().split("_")
    plataforma = detectar_plataforma(tokens)
    tipo, confianza = detectar_tipo(tokens, plataforma_detectada=plataforma is not None)

    # Tokens que corresponden a la plataforma se excluyen del nombre base
    excluir = frozenset(t for t in tokens if t in PLATFORM_KEYWORDS)
    nombre_base = _reconstruir_nombre(tokens, excluir)

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
    )
