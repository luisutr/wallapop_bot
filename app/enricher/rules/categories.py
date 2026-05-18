from __future__ import annotations

# ── Texto de categoría que aparece en cada plataforma ───────────────────────

# Wallapop: el bot rellena el campo summary/title y Wallapop auto-sugiere
# la categoría. Usamos el texto de la primera sugerencia.
# Este mapa solo se usa para mostrar info al usuario en la tabla resumen.
CATEGORIAS_WALLAPOP: dict[str, str] = {
    "accesorio_consola": "Electrónica",
    "videojuego":  "Videojuegos",
    "ropa_hombre": "Ropa y accesorios > Hombre",
    "ropa_mujer":  "Ropa y accesorios > Mujer",
    "calzado":     "Ropa y accesorios > Calzado",
    "movil":       "Electrónica > Móviles",
    "electronica": "Electrónica",
    "libro":       "Libros, películas y música > Libros",
    "pelicula":    "Libros, películas y música > Películas",
    "musica":      "Libros, películas y música > Música",
    "deporte":     "Deporte y ocio",
    "hogar":       "Hogar y jardín",
    "juguete":     "Juguetes y bebés",
    "otro":        "Otros",
}

# Vinted: texto exacto del dropdown #category
CATEGORIAS_VINTED: dict[str, str] = {
    "accesorio_consola": "Mandos",
    "videojuego":  "Juegos",
    "ropa_hombre": "Ropa de hombre",
    "ropa_mujer":  "Ropa de mujer",
    "calzado":     "Calzado",
    "movil":       "Teléfonos y accesorios",
    "electronica": "Electrónica",
    "libro":       "Libros",
    "pelicula":    "Películas",
    "musica":      "Música",
    "deporte":     "Deportes y exterior",
    "hogar":       "Hogar",
    "juguete":     "Juguetes",
    "otro":        "Otros",
}

# Tipos disponibles (usado en CLI para la pregunta manual)
TIPOS_DISPONIBLES: list[str] = list(CATEGORIAS_WALLAPOP.keys())

# Mandos, volantes, etc. — prioridad sobre «videojuego» si hay token ps2/ps3…
ACCESORIO_CONSOLA_KEYWORDS: frozenset[str] = frozenset({
    "mando", "mandos", "controller", "gamepad", "joystick",
    "volante", "wheel", "wiimote", "nunchuk", "arcade",
})

# ── Keywords por tipo ────────────────────────────────────────────────────────
CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "accesorio_consola": list(ACCESORIO_CONSOLA_KEYWORDS),
    "videojuego": [
        "ps1", "ps2", "ps3", "ps4", "ps5", "psp", "psvita", "vita",
        "xbox", "xbox360", "xboxone", "xboxseries",
        "switch", "wiiu", "wii", "gamecube", "gc",
        "n64", "nes", "snes", "ds", "3ds", "gba", "gbc", "gb",
        "pc", "steam",
        "juego", "game", "videojuego",
    ],
    "movil": [
        "iphone", "samsung", "xiaomi", "huawei", "oppo", "realme",
        "movil", "telefono", "smartphone",
    ],
    "electronica": [
        "ordenador", "portatil", "laptop", "tablet", "ipad",
        "camara", "auriculares", "altavoz", "tv", "television",
        "monitor", "teclado", "raton", "consola", "router",
        "disco", "ssd", "ram", "gpu", "cpu", "impresora",
    ],
    "calzado": [
        "zapatillas", "zapatos", "botas", "sandalias", "chanclas",
        "tacones", "deportivas", "sneakers",
        "nike", "adidas", "converse", "vans", "puma", "reebok",
        "new", "balance", "jordan", "yeezy",
    ],
    "ropa_hombre": [
        "camiseta", "camisa", "pantalon", "vaquero", "jeans",
        "shorts", "jersey", "sudadera", "chaqueta", "abrigo",
        "cazadora", "polo", "traje", "corbata", "talla", "hombre", "chico",
    ],
    "ropa_mujer": [
        "vestido", "falda", "blusa", "top", "leggings",
        "mujer", "chica", "señora",
    ],
    "libro": ["libro", "novela", "comics", "comic", "manga", "bd"],
    "pelicula": ["bluray", "blu", "ray", "dvd", "pelicula", "serie"],
    "musica": ["cd", "vinilo", "disco", "album", "single"],
    "deporte": [
        "bicicleta", "bici", "pelota", "raqueta",
        "pesas", "mancuernas", "gym", "fitness", "esqui", "surf",
    ],
    "hogar": [
        "sofa", "mesa", "silla", "lampara", "cuadro",
        "espejo", "alfombra", "cama", "armario",
    ],
    "juguete": [
        "lego", "figura", "muñeca", "juguete", "peluche", "puzzle",
        "gijoe", "heman", "motu", "playmobil", "funko", "hasbro", "mattel",
        "bandai", "transformer", "starwars", "marvel", "dc", "ninja",
        "hotwheel", "hotwheels", "matchbox",
    ],
}


def detectar_tipo(tokens: list[str], plataforma_detectada: bool = False) -> tuple[str, float]:
    """
    Devuelve (tipo, confianza).
    confianza: 1.0 = certeza, 0.0 = desconocido.
    """
    if any(t in ACCESORIO_CONSOLA_KEYWORDS for t in tokens):
        return "accesorio_consola", 1.0

    if plataforma_detectada:
        juego_kw = set(CATEGORY_KEYWORDS["videojuego"])
        if any(t in juego_kw for t in tokens):
            return "videojuego", 1.0
        # p.ej. doom_3_ps3 sin palabra «mando» → videojuego
        return "videojuego", 0.85

    scores: dict[str, int] = {}
    for tipo, keywords in CATEGORY_KEYWORDS.items():
        matches = sum(1 for t in tokens if t in keywords)
        if matches:
            scores[tipo] = matches

    if not scores:
        return "otro", 0.0

    mejor = max(scores, key=lambda k: scores[k])
    confianza = min(scores[mejor] / max(len(tokens), 1) * 2, 1.0)
    return mejor, confianza
