from pathlib import Path

BASE_DIR = Path(__file__).parent

LOTE_DIR       = BASE_DIR / "lote"
PROCESADOS_DIR = BASE_DIR / "procesados"
SESIONES_DIR   = BASE_DIR / "sesiones"
ERRORES_DIR    = BASE_DIR / "errores"

WALLAPOP_STATE_PATH = SESIONES_DIR / "wallapop_state.json"
VINTED_COOKIES_PATH = SESIONES_DIR / "vinted_cookies.pkl"

# ── Configuración personal ──────────────────────────────────────────────────
LOCALIZACION = "Toledo"

# Se publica al X% del mínimo encontrado (0.95 = 5% más barato que el mínimo)
PRECIO_DESCUENTO = 0.95
# Precio por defecto si no se encuentra ningún resultado de búsqueda
PRECIO_FALLBACK = 10.0

# ── Estado del producto ─────────────────────────────────────────────────────
# Valores válidos en meta.json → "estado": "<clave>"
ESTADO_DEFAULT = "como_nuevo"

ESTADO_WALLAPOP: dict[str, str] = {
    "nuevo":       "Nuevo",
    "como_nuevo":  "Como nuevo",
    "buen_estado": "En buen estado",
    "bueno":       "Bueno",
    "aceptable":   "Se acepta",
}

ESTADO_VINTED: dict[str, str] = {
    "nuevo":       "Nuevo sin etiquetas",
    "como_nuevo":  "Nuevo sin etiquetas",
    "buen_estado": "Muy bueno",
    "bueno":       "Bueno",
    "aceptable":   "Satisfactorio",
}

# ── Videojuegos ─────────────────────────────────────────────────────────────
PEGI_DEFAULT = "PEGI 18"

# ── URLs ────────────────────────────────────────────────────────────────────
WALLAPOP_UPLOAD_URL = "https://es.wallapop.com/app/catalog/upload"
VINTED_UPLOAD_URL   = "https://www.vinted.es/items/new"

# ── Imágenes ────────────────────────────────────────────────────────────────
EXTENSIONES_IMAGEN: frozenset[str] = frozenset({".jpg", ".jpeg", ".png", ".webp"})

# ── Plataformas de publicación disponibles ──────────────────────────────────
PLATAFORMAS_DESTINO: list[str] = ["wallapop", "vinted"]
