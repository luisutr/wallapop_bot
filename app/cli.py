from __future__ import annotations

import shutil
import sys
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.progress import track
from rich.prompt import Confirm, Prompt
from rich.table import Table

from config import (
    ERRORES_DIR,
    LOTE_DIR,
    PLATAFORMAS_DESTINO,
    PRECIO_DESCUENTO,
    PRECIO_FALLBACK,
    PROCESADOS_DIR,
    VINTED_COOKIES_PATH,
    WALLAPOP_STATE_PATH,
)
from app.enricher.content_gen import ContenidoProducto, generar_contenido
from app.enricher.identifier import identificar
from app.enricher.rules.categories import TIPOS_DISPONIBLES
from app.parser.image_loader import ProductoLote, cargar_lote
from app.pricing.vinted_pricer import buscar_precio_vinted
from app.pricing.wallapop_pricer import buscar_precio_wallapop
from app.publishers.vinted import subir_vinted
from app.publishers.wallapop import subir_wallapop

console = Console()


# ── Utilidades de pantalla ────────────────────────────────────────────────────

def _encabezado() -> None:
    console.print(Panel.fit(
        "[bold magenta]Wallapop & Vinted Bot[/bold magenta]\n"
        "[dim]Publicación automática de productos en lote[/dim]",
        border_style="magenta",
    ))


def _tabla_resumen(datos: list[dict]) -> None:
    tabla = Table(title="Productos a publicar", show_lines=True, expand=True)
    tabla.add_column("#",          style="dim",           width=3,  justify="right")
    tabla.add_column("Producto",   style="bold",          min_width=20)
    tabla.add_column("Tipo",       style="cyan",          width=12)
    tabla.add_column("Wallapop",   style="green",         width=10, justify="right")
    tabla.add_column("Vinted",     style="green",         width=10, justify="right")
    tabla.add_column("Precio €",   style="bold yellow",   width=10, justify="right")
    tabla.add_column("Publicar en", style="magenta",      width=20)
    tabla.add_column("Estado",     style="white",         width=12)

    for i, p in enumerate(datos, 1):
        c: ContenidoProducto = p["contenido"]
        tabla.add_row(
            str(i),
            c.titulo_wallapop,
            p["tipo_final"],
            f"{p['precio_wallapop']:.2f}" if p["precio_wallapop"] else "—",
            f"{p['precio_vinted']:.2f}"   if p["precio_vinted"]   else "—",
            f"{p['precio_final']:.2f}",
            ", ".join(p["lote"].publicar_en),
            c.estado_wallapop,
        )
    console.print(tabla)


# ── Interacción con el usuario ────────────────────────────────────────────────

def _verificar_sesiones() -> None:
    """Comprueba si existen sesiones guardadas y ofrece crearlas."""
    ok_w = WALLAPOP_STATE_PATH.exists()
    ok_v = VINTED_COOKIES_PATH.exists()

    if not ok_w:
        console.print("[yellow]⚠  No hay sesión de Wallapop guardada.[/yellow]")
        if Confirm.ask("¿Iniciar sesión en Wallapop ahora?", default=True):
            from app.auth.wallapop_session import guardar_sesion_wallapop
            guardar_sesion_wallapop()

    if not ok_v:
        console.print("[yellow]⚠  No hay sesión de Vinted guardada.[/yellow]")
        if Confirm.ask("¿Iniciar sesión en Vinted ahora?", default=True):
            from app.auth.vinted_session import guardar_sesion_vinted
            guardar_sesion_vinted()


def _preguntar_tipo(slug: str, info) -> str:
    """Pregunta al usuario qué tipo de producto es cuando no se puede determinar."""
    console.print(
        f"\n[yellow]No puedo determinar el tipo de:[/yellow] [bold]{slug}[/bold]\n"
        f"  Detecté [italic]{info.tipo}[/italic] con confianza "
        f"[bold]{info.confianza:.0%}[/bold].\n"
        "Elige el tipo correcto:"
    )
    for i, tipo in enumerate(TIPOS_DISPONIBLES, 1):
        console.print(f"  [cyan]{i:>2}[/cyan]. {tipo}")

    while True:
        resp = Prompt.ask("Número", default="1")
        try:
            idx = int(resp) - 1
            if 0 <= idx < len(TIPOS_DISPONIBLES):
                return TIPOS_DISPONIBLES[idx]
        except ValueError:
            pass
        console.print("[red]Opción no válida, elige un número de la lista.[/red]")


def _seleccionar_plataformas_global() -> list[str]:
    """Permite elegir a qué plataformas publicar (global para todo el lote)."""
    console.print("\n[bold]¿En qué plataformas quieres publicar?[/bold]")
    console.print("  [cyan]1[/cyan]. Ambas (Wallapop + Vinted)  [dim](por defecto)[/dim]")
    console.print("  [cyan]2[/cyan]. Solo Wallapop")
    console.print("  [cyan]3[/cyan]. Solo Vinted")
    resp = Prompt.ask("Opción", choices=["1", "2", "3"], default="1")
    mapping = {
        "1": ["wallapop", "vinted"],
        "2": ["wallapop"],
        "3": ["vinted"],
    }
    return mapping[resp]


def _editar_producto(p: dict) -> dict:
    """Permite editar precio y título de un producto antes de publicar."""
    c: ContenidoProducto = p["contenido"]
    console.print(f"\n[bold]Editando:[/bold] {c.titulo_wallapop}")

    nuevo_titulo = Prompt.ask("Título", default=c.titulo_wallapop)
    if nuevo_titulo != c.titulo_wallapop:
        c.titulo_wallapop = nuevo_titulo
        c.titulo_vinted   = nuevo_titulo

    nuevo_precio = Prompt.ask("Precio (€)", default=str(p["precio_final"]))
    try:
        p["precio_final"] = round(float(nuevo_precio), 2)
    except ValueError:
        console.print("[red]Precio no válido, se mantiene el anterior.[/red]")

    return p


# ── Lógica de precios ─────────────────────────────────────────────────────────

def _calcular_precio(
    precio_w: Optional[float],
    precio_v: Optional[float],
    publicar_en: list[str],
) -> float:
    candidatos: list[float] = []
    if "wallapop" in publicar_en and precio_w:
        candidatos.append(precio_w)
    if "vinted"   in publicar_en and precio_v:
        candidatos.append(precio_v)
    if not candidatos:
        return PRECIO_FALLBACK
    return round(min(candidatos) * PRECIO_DESCUENTO, 2)


# ── Flujo principal ───────────────────────────────────────────────────────────

def run(plataformas_override: Optional[list[str]] = None) -> None:
    _encabezado()
    _verificar_sesiones()

    console.print(f"\n[bold]Escaneando:[/bold] {LOTE_DIR}")
    lote = cargar_lote()

    if not lote:
        console.print(
            "[yellow]No hay productos en lote/.\n"
            "Crea una subcarpeta por producto y añade sus imágenes dentro.[/yellow]"
        )
        return

    console.print(f"[green]Encontrados {len(lote)} productos.[/green]")

    # Selección global de plataformas (se puede sobreescribir por meta.json)
    plataformas_global = plataformas_override or _seleccionar_plataformas_global()

    # ── Paso 1: Identificar y generar contenido ────────────────────────────
    console.print("\n[bold]Analizando productos...[/bold]")
    datos: list[dict] = []

    for lote_item in lote:
        info = identificar(lote_item.slug)

        tipo_final = info.tipo
        if info.requiere_confirmacion:
            tipo_final = _preguntar_tipo(lote_item.slug, info)

        contenido = generar_contenido(
            info=info,
            estado_key=lote_item.estado,
            tipo_override=tipo_final,
            titulo_override=lote_item.titulo_override,
            descripcion_override=lote_item.descripcion_override,
            pegi_override=lote_item.pegi_override,
        )

        # Respeta publicar_en del meta.json; si no existe usa la selección global
        publicar_en = (
            lote_item.publicar_en
            if "publicar_en" in lote_item.meta
            else plataformas_global
        )

        datos.append({
            "lote":           lote_item,
            "info":           info,
            "contenido":      contenido,
            "tipo_final":     tipo_final,
            "publicar_en":    publicar_en,
            "precio_wallapop": None,
            "precio_vinted":   None,
            "precio_final":    PRECIO_FALLBACK,
        })

    # ── Paso 2: Buscar precios ─────────────────────────────────────────────
    console.print("\n[bold]Buscando precios mínimos en las plataformas...[/bold]")

    for p in track(datos, description="Buscando..."):
        lote_item: ProductoLote = p["lote"]
        titulo = p["contenido"].titulo_wallapop

        if lote_item.precio_manual is not None:
            p["precio_final"] = lote_item.precio_manual
            continue

        if "wallapop" in p["publicar_en"]:
            p["precio_wallapop"] = buscar_precio_wallapop(titulo)
        if "vinted" in p["publicar_en"]:
            p["precio_vinted"] = buscar_precio_vinted(titulo)

        p["precio_final"] = _calcular_precio(
            p["precio_wallapop"],
            p["precio_vinted"],
            p["publicar_en"],
        )

    # ── Paso 3: Revisar y confirmar ────────────────────────────────────────
    console.print()
    _tabla_resumen(datos)

    console.print(
        "\n[bold]¿Qué hacemos?[/bold]  "
        "[cyan]s[/cyan] publicar · [cyan]e[/cyan] editar producto · [cyan]n[/cyan] cancelar"
    )
    accion = Prompt.ask("Acción", choices=["s", "e", "n"], default="s")

    if accion == "n":
        console.print("Cancelado.")
        return

    if accion == "e":
        num = Prompt.ask("Número de producto a editar", default="1")
        try:
            idx = int(num) - 1
            datos[idx] = _editar_producto(datos[idx])
        except (ValueError, IndexError):
            console.print("[red]Número no válido.[/red]")

        console.print()
        _tabla_resumen(datos)
        if not Confirm.ask("¿Publicar ahora?", default=True):
            return

    # ── Paso 4: Publicar ──────────────────────────────────────────────────
    PROCESADOS_DIR.mkdir(parents=True, exist_ok=True)
    ERRORES_DIR.mkdir(parents=True, exist_ok=True)

    resultados: dict[str, list[str]] = {"ok": [], "error": []}

    for p in datos:
        lote_item: ProductoLote = p["lote"]
        c: ContenidoProducto     = p["contenido"]
        fotos = [str(f) for f in lote_item.imagenes]

        for plataforma in p["publicar_en"]:
            console.print(
                f"\n[bold]→ Publicando en {plataforma}:[/bold] {c.titulo_wallapop}"
            )
            try:
                if plataforma == "wallapop":
                    subir_wallapop({
                        "slug":        lote_item.slug,
                        "titulo":      c.titulo_wallapop,
                        "descripcion": c.descripcion_wallapop,
                        "precio":      p["precio_final"],
                        "estado_texto": c.estado_wallapop,
                        "fotos":       fotos,
                    })
                elif plataforma == "vinted":
                    subir_vinted({
                        "slug":              lote_item.slug,
                        "titulo":            c.titulo_vinted,
                        "descripcion":       c.descripcion_vinted,
                        "precio":            p["precio_final"],
                        "estado_vinted":     c.estado_vinted,
                        "categoria_vinted":  c.categoria_vinted,
                        "plataforma_vinted": c.plataforma_vinted,
                        "pegi":              c.pegi,
                        "tipo":              p["tipo_final"],
                        "fotos":             fotos,
                    })

                console.print(f"  [green]✓ Publicado en {plataforma}[/green]")
                resultados["ok"].append(f"{lote_item.slug} → {plataforma}")

            except RuntimeError as exc:
                console.print(f"  [red]✗ Error en {plataforma}: {exc}[/red]")
                resultados["error"].append(f"{lote_item.slug} → {plataforma}")

        # Mover carpeta a procesados/ cuando todos los intentos han terminado
        dest = PROCESADOS_DIR / lote_item.slug
        if not dest.exists():
            shutil.move(str(lote_item.carpeta), str(dest))
            console.print(f"  [dim]→ Movido a procesados/{lote_item.slug}[/dim]")

    # ── Resumen final ──────────────────────────────────────────────────────
    console.print()
    if resultados["ok"]:
        console.print(
            f"[bold green]✓ Publicados con éxito ({len(resultados['ok'])}):[/bold green]"
        )
        for r in resultados["ok"]:
            console.print(f"  [green]·[/green] {r}")

    if resultados["error"]:
        console.print(
            f"\n[bold red]✗ Con errores ({len(resultados['error'])}):[/bold red]"
        )
        for r in resultados["error"]:
            console.print(f"  [red]·[/red] {r}")
        console.print(f"  [dim]Revisa capturas en {ERRORES_DIR}[/dim]")

    console.print("\n[bold]Proceso completado.[/bold]")


if __name__ == "__main__":
    run()
