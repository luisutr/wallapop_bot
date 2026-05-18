# Wallapop & Vinted Bot

Publicación automática de lotes de productos en Wallapop y Vinted.

---

## Instalación

```bash
# Activar el entorno virtual
source venv/bin/activate

# Instalar dependencias
pip install -r requirements.txt

# Instalar navegador Playwright (solo la primera vez)
playwright install chromium
```

---

## Estructura de carpetas

```
wallapop_bot/
├── lote/               ← Pon aquí tus productos (una carpeta por producto)
├── procesados/         ← Se mueven aquí tras publicarse con éxito
├── sesiones/           ← Sesiones de Wallapop y Vinted (NO compartir)
├── errores/            ← Capturas de error si algo falla
├── app/                ← Código fuente
└── config.py           ← Tu configuración (ciudad, descuento de precio, etc.)
```

---

## Cómo añadir productos

Crea una subcarpeta dentro de `lote/` con el nombre del producto en formato slug
(minúsculas, palabras separadas por `_`). Dentro pon las imágenes ordenadas por nombre.

**Ejemplos de nombres de carpeta:**

```
lote/
  doom_3_ps3/           → Doom 3 PS3
  fifa_24_ps5/          → FIFA 24 PS5
  nike_air_max_talla_42_blancas/
  iphone_14_128gb_negro/
  camara_canon_eos_1200d/
  libro_harrypotter_piedra_filosofal/
  camiseta_hombre_talla_l_azul/
```

**Plataformas de videojuego reconocidas automáticamente en el slug:**
`ps1 ps2 ps3 ps4 ps5 psp psvita xbox xbox360 xboxone xboxseries
switch wiiu wii gamecube gc n64 nes snes ds 3ds gba gbc gb pc steam`

---

## Opciones avanzadas: meta.json

Puedes crear un fichero `meta.json` dentro de la carpeta del producto para
sobrescribir cualquier campo generado automáticamente:

```json
{
  "publicar_en": ["wallapop"],
  "estado": "buen_estado",
  "precio_manual": 12.50,
  "pegi": "PEGI 12",
  "titulo": "Título personalizado",
  "descripcion": "Descripción personalizada completa."
}
```

**Valores válidos para `estado`:**

| Clave         | Wallapop          | Vinted                |
|---------------|-------------------|-----------------------|
| `nuevo`       | Nuevo             | Nuevo sin etiquetas   |
| `como_nuevo`  | Como nuevo        | Nuevo sin etiquetas   |
| `bueno` / `buen_estado` | En buen estado | Bueno |
| `aceptable` | En condiciones aceptables | Satisfactorio |
| `sin_abrir` | Sin abrir | — |
| `en_su_caja` | En su caja | — |
| `dado_todo` | Lo ha dado todo | — |

Slugs con `mando`, `gamepad`, etc. se clasifican como **accesorio_consola** → categoría Vinted **Mandos** (no Juegos).
En videojuegos reales, si aparece «Clasificación de contenidos»: **AO – Solo adultos**; plataforma: primera sugerencia si no hay match.

**Valores válidos para `publicar_en`:** `["wallapop"]`, `["vinted"]`, `["wallapop", "vinted"]`

---

## Uso

### Primera vez: guardar sesiones

```bash
source venv/bin/activate
python -m app.cli
```

Si no hay sesión guardada, la app abrirá el navegador para que inicies sesión.

### Publicar un lote

```bash
source venv/bin/activate
python -m app.cli
```

La app:
1. Escanea `lote/` y detecta los productos
2. Genera título, descripción y categoría automáticamente
3. Busca el precio mínimo actual en Wallapop y Vinted
4. Te muestra una tabla resumen para revisar
5. Publica en las plataformas seleccionadas
6. Mueve las carpetas publicadas a `procesados/`

---

## Configuración personal (`config.py`)

Edita estos valores al inicio del fichero:

```python
LOCALIZACION     = "Toledo"   # Tu ciudad
PRECIO_DESCUENTO = 0.95       # Publica al 95% del precio mínimo encontrado
PRECIO_FALLBACK  = 10.0       # Precio por defecto si no hay resultados
ESTADO_DEFAULT   = "como_nuevo"
PEGI_DEFAULT     = "PEGI 18"
```

---

## Seguridad

Los ficheros `sesiones/wallapop_state.json` y `sesiones/vinted_cookies.pkl`
contienen tus tokens de sesión. **No los compartas ni subas a ningún repositorio.**
