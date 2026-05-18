from __future__ import annotations

from config import ESTADO_WALLAPOP, ESTADO_VINTED

TEMPLATES: dict[str, str] = {
    "videojuego": (
        "{titulo_completo}.\n\n"
        "Estado: {estado_texto}. Funciona perfectamente.\n"
        "Caja incluida en buen estado. Envío disponible.\n\n"
        "No incluye DLC descargables."
    ),
    "calzado": (
        "{titulo_completo}.\n\n"
        "Estado: {estado_texto}. Poco uso, en perfecto estado.\n"
        "Talla: ver título. Sin deformaciones ni desgaste visible.\n"
        "Envío disponible."
    ),
    "ropa_hombre": (
        "{titulo_completo}.\n\n"
        "Estado: {estado_texto}. Muy pocas veces usada.\n"
        "Talla: ver título. Sin manchas ni desperfectos.\n"
        "Envío disponible."
    ),
    "ropa_mujer": (
        "{titulo_completo}.\n\n"
        "Estado: {estado_texto}. Muy pocas veces usada.\n"
        "Talla: ver título. Sin manchas ni desperfectos.\n"
        "Envío disponible."
    ),
    "movil": (
        "{titulo_completo}.\n\n"
        "Estado: {estado_texto}. Funciona perfectamente.\n"
        "Sin golpes ni grietas en pantalla. Batería en buen estado.\n"
        "Se puede probar antes de comprar. Envío disponible."
    ),
    "electronica": (
        "{titulo_completo}.\n\n"
        "Estado: {estado_texto}. Funciona perfectamente.\n"
        "Se puede probar antes de comprar.\n"
        "Envío disponible."
    ),
    "libro": (
        "{titulo_completo}.\n\n"
        "Estado: {estado_texto}. Sin marcas ni subrayados.\n"
        "Envío disponible."
    ),
    "pelicula": (
        "{titulo_completo}.\n\n"
        "Estado: {estado_texto}. Disco sin rayones, imagen perfecta.\n"
        "Caja original incluida. Envío disponible."
    ),
    "musica": (
        "{titulo_completo}.\n\n"
        "Estado: {estado_texto}. Sin saltos, sonido perfecto.\n"
        "Envío disponible."
    ),
    "deporte": (
        "{titulo_completo}.\n\n"
        "Estado: {estado_texto}. Poco uso.\n"
        "Envío disponible."
    ),
    "hogar": (
        "{titulo_completo}.\n\n"
        "Estado: {estado_texto}.\n"
        "Recogida en mano preferiblemente. Envío consultar."
    ),
    "juguete": (
        "{titulo_completo}.\n\n"
        "Estado: {estado_texto}. Completo, sin piezas faltantes.\n"
        "Envío disponible."
    ),
    "otro": (
        "{titulo_completo}.\n\n"
        "Estado: {estado_texto}.\n"
        "Envío disponible."
    ),
}


def generar_descripcion(
    titulo_completo: str,
    tipo: str,
    estado_key: str,
    plataforma_nombre: str = "",
    para_wallapop: bool = True,
) -> str:
    template = TEMPLATES.get(tipo, TEMPLATES["otro"])
    estado_map = ESTADO_WALLAPOP if para_wallapop else ESTADO_VINTED
    default = "En buen estado" if para_wallapop else "Bueno"
    estado_texto = estado_map.get(estado_key, default)
    return template.format(
        titulo_completo=titulo_completo,
        plataforma=plataforma_nombre,
        estado_texto=estado_texto,
    )
