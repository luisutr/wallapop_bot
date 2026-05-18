from __future__ import annotations

import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.progress import track
from rich.prompt import Confirm, Prompt
from rich.table import Table
from rich import box

from config import (
    ERRORES_DIR,
    LOTE_DIR,
    PLATAFORMAS_DESTINO,
    PRECIO_DESCUENTO,
    PRECIO_FALLBACK,
    PROCESADOS_DIR,
    VINTED_COOKIES_PATH,
    VINTED_STATE_PATH,
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


# ── Helpers de pantalla ───────────────────────────────────────────────────────

def _encabezado() -> None:
    console.print(Panel.fit(
        "[bold magenta]Wallapop & Vinted Bot[/bold magenta]\n"
        "[dim]Publicación automática de productos en lote[/dim]",
        border_style="magenta",
    ))


def _estado_sesion(path: Path) -> tuple[str, str]:
    """Devuelve (icono, texto) con el estado de un fichero de sesión."""
    if not path.exists():
        return "[red]✗[/red]", "[red]Sin sesión[/red]"
    mtime = datetime.fromtimestamp(path.stat().st_mtime)
    hace = datetime.now() - mtime
    dias = hace.days
    if dias == 0:
        edad = "hoy"
    elif dias == 1:
        edad = "ayer"
    else:
        edad = f"hace {dias} días"
    color = "green" if dias < 7 else "yellow" if dias < 14 else "red"
    return f"[{color}]✓[/{color}]", f"[{color}]Guardada ({edad})[/{color}]"


def _panel_sesiones() -> None:
    """Muestra el estado de las sesiones en un panel."""
    ico_w, txt_w = _estado_sesion(WALLAPOP_STATE_PATH)
    # Para Vinted usamos el .json (preferido) o el .pkl
    vinted_path = VINTED_STATE_PATH if VINTED_STATE_PATH.exists() else VINTED_COOKIES_PATH
    ico_v, txt_v = _estado_sesion(vinted_path)

    tabla = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
    tabla.add_column("Plataforma", style="bold", width=12)
    tabla.add_column("Estado")
    tabla.add_row(f"{ico_w}  Wallapop", txt_w)
    tabla.add_row(f"{ico_v}  Vinted",   txt_v)

    console.print(Panel(tabla, title="[bold]Sesiones[/bold]", border_style="dim", expand=False))


# ── Menú de sesiones ──────────────────────────────────────────────────────────

def _menu_sesiones() -> None:
    """Submenú de gestión de sesiones."""
    while True:
        console.print()
        _panel_sesiones()
        console.print("\n[bold]Gestión de sesiones[/bold]")
        console.print("  [cyan]1[/cyan]. Renovar sesión Wallapop")
        console.print("  [cyan]2[/cyan]. Renovar sesión Vinted")
        console.print("  [cyan]3[/cyan]. Renovar ambas")
        console.print("  [cyan]0[/cyan]. Volver al menú principal")

        opcion = Prompt.ask("Opción", choices=["0", "1", "2", "3"], default="0")

        if opcion == "0":
            return

        if opcion in ("1", "3"):
            from app.auth.wallapop_session import guardar_sesion_wallapop
            guardar_sesion_wallapop()

        if opcion in ("2", "3"):
            from app.auth.vinted_session import guardar_sesion_vinted
            guardar_sesion_vinted()

        console.print("[green]✓ Hecho.[/green]")


# ── Menú de productos pendientes (procesados) ─────────────────────────────────

def _menu_procesados() -> None:
    """Muestra los productos ya publicados."""
    PROCESADOS_DIR.mkdir(exist_ok=True)
    items = [d for d in sorted(PROCESADOS_DIR.iterdir()) if d.is_dir()]
    if not items:
        console.print("[dim]No hay productos publicados todavía.[/dim]")
        return
    tabla = Table(title="Productos publicados", box=box.SIMPLE_HEAVY)
    tabla.add_column("#", style="dim", width=4, justify="right")
    tabla.add_column("Slug", style="bold")
    tabla.add_column("Fecha", style="dim")
    for i, d in enumerate(items, 1):
        mtime = datetime.fromtimestamp(d.stat().st_mtime).strftime("%d/%m/%Y %H:%M")
        tabla.add_row(str(i), d.name, mtime)
    console.print(tabla)


# ── Menú principal ────────────────────────────────────────────────────────────

def _menu_principal() -> None:
    """Bucle del menú principal de la aplicación."""
    _encabezado()

    while True:
        console.print()
        _panel_sesiones()

        lote = cargar_lote()
        n_lote = len(lote)
        n_proc = len([d for d in PROCESADOS_DIR.iterdir() if d.is_dir()]) if PROCESADOS_DIR.exists() else 0

        console.print(
            f"\n[bold]Menú principal[/bold]  "
            f"[dim]Lote: {n_lote} producto(s) · Publicados: {n_proc}[/dim]"
        )
        console.print("  [cyan bold]1[/cyan bold]. 🚀  Publicar lote")
        console.print("  [cyan bold]2[/cyan bold]. 🔑  Gestionar sesiones")
        console.print("  [cyan bold]3[/cyan bold]. 📋  Ver productos publicados")
        console.print("  [cyan bold]0[/cyan bold]. ❌  Salir")

        opcion = Prompt.ask("Opción", choices=["0", "1", "2", "3"], default="1")

        if opcion == "0":
            console.print("\n[dim]Hasta luego.[/dim]")
            break
        elif opcion == "1":
            if n_lote == 0:
                console.print(
                    "[yellow]No hay productos en lote/.\n"
                    "Añade subcarpetas con imágenes dentro de la carpeta lote/.[/yellow]"
                )
            else:
                _flujo_publicar(lote)
        elif opcion == "2":
            _menu_sesiones()
        elif opcion == "3":
            _menu_procesados()
            Prompt.ask("\n[dim]Pulsa Enter para volver[/dim]", default="")


# ── Flujo de publicación ──────────────────────────────────────────────────────

def _tabla_resumen(datos: list[dict]) -> None:
    tabla = Table(title="Productos a publicar", show_lines=True, expand=True)
    tabla.add_column("#",           style="dim",         width=3,  justify="right")
    tabla.add_column("Producto",    style="bold",         min_width=22)
    tabla.add_column("Tipo",        style="cyan",         width=12)
    tabla.add_column("€ Wpp",       style="green",        width=8,  justify="right")
    tabla.add_column("€ Vint",      style="green",        width=8,  justify="right")
    tabla.add_column("€ Final",     style="bold yellow",  width=8,  justify="right")
    tabla.add_column("Publicar en", style="magenta",      width=18)
    tabla.add_column("Estado",      style="white",        width=12)

    for i, p in enumerate(datos, 1):
        c: ContenidoProducto = p["contenido"]
        tabla.add_row(
            str(i),
            c.titulo_wallapop,
            p["tipo_final"],
            f"{p['precio_wallapop']:.2f}" if p["precio_wallapop"] else "—",
            f"{p['precio_vinted']:.2f}"   if p["precio_vinted"]   else "—",
            f"{p['precio_final']:.2f}",
            ", ".join(p["publicar_en"]),
            c.estado_wallapop,
        )
    console.print(tabla)


def _preguntar_tipo(slug: str, info) -> str:
    console.print(
        f"\n[yellow]No puedo determinar el tipo de:[/yellow] [bold]{slug}[/bold]\n"
        f"  Detecté [italic]{info.tipo}[/italic] con confianza "
        f"[bold]{info.confianza:.0%}[/bold].\n"
        "  Elige el tipo correcto:"
    )
    for i, tipo in enumerate(TIPOS_DISPONIBLES, 1):
        console.print(f"    [cyan]{i:>2}[/cyan]. {tipo}")
    while True:
        resp = Prompt.ask("Número", default="1")
        try:
            idx = int(resp) - 1
            if 0 <= idx < len(TIPOS_DISPONIBLES):
                return TIPOS_DISPONIBLES[idx]
        except ValueError:
            pass
        console.print("[red]Opción no válida.[/red]")


def _seleccionar_plataformas() -> list[str]:
    console.print("\n[bold]¿En qué plataformas publicar?[/bold]")
    console.print("  [cyan]1[/cyan]. Ambas (Wallapop + Vinted)  [dim](por defecto)[/dim]")
    console.print("  [cyan]2[/cyan]. Solo Wallapop")
    console.print("  [cyan]3[/cyan]. Solo Vinted")
    resp = Prompt.ask("Opción", choices=["1", "2", "3"], default="1")
    return {"1": ["wallapop", "vinted"], "2": ["wallapop"], "3": ["vinted"]}[resp]


def _editar_producto(p: dict) -> dict:
    c: ContenidoProducto = p["contenido"]
    console.print(f"\n[bold]Editando:[/bold] {c.titulo_wallapop}")
    nuevo_titulo = Prompt.ask("Título", default=c.titulo_wallapop)
    if nuevo_titulo != c.titulo_wallapop:
        c.titulo_wallapop = c.titulo_vinted = nuevo_titulo
    nuevo_precio = Prompt.ask("Precio (€)", default=str(p["precio_final"]))
    try:
        p["precio_final"] = round(float(nuevo_precio), 2)
    except ValueError:
        console.print("[red]Precio no válido, se mantiene el anterior.[/red]")
    return p


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
    return round(min(candidatos) * PRECIO_DESCUENTO, 2) if candidatos else PRECIO_FALLBACK


def _flujo_publicar(lote: list[ProductoLote]) -> None:
    plataformas_global = _seleccionar_plataformas()

    # ── Paso 1: Identificar y generar contenido ───────────────────────────────
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
        publicar_en = (
            lote_item.publicar_en
            if "publicar_en" in lote_item.meta
            else plataformas_global
        )
        datos.append({
            "lote":            lote_item,
            "info":            info,
            "contenido":       contenido,
            "tipo_final":      tipo_final,
            "publicar_en":     publicar_en,
            "precio_wallapop": None,
            "precio_vinted":   None,
            "precio_final":    PRECIO_FALLBACK,
        })

    # ── Paso 2: Buscar precios ────────────────────────────────────────────────
    console.print("\n[bold]Buscando precios mínimos...[/bold]")
    for p in track(datos, description="Buscando..."):
        lote_item: ProductoLote = p["lote"]
        if lote_item.precio_manual is not None:
            p["precio_final"] = lote_item.precio_manual
            continue
        titulo = p["contenido"].titulo_wallapop
        if "wallapop" in p["publicar_en"]:
            p["precio_wallapop"] = buscar_precio_wallapop(titulo)
        if "vinted" in p["publicar_en"]:
            p["precio_vinted"] = buscar_precio_vinted(titulo)
        p["precio_final"] = _calcular_precio(
            p["precio_wallapop"], p["precio_vinted"], p["publicar_en"]
        )

    # ── Paso 3: Revisar ───────────────────────────────────────────────────────
    console.print()
    _tabla_resumen(datos)

    console.print(
        "\n[bold]¿Qué hacemos?[/bold]  "
        "[cyan]s[/cyan] publicar todo · [cyan]e[/cyan] editar producto · [cyan]n[/cyan] cancelar"
    )
    accion = Prompt.ask("Acción", choices=["s", "e", "n"], default="s")

    if accion == "n":
        console.print("[dim]Cancelado.[/dim]")
        return

    if accion == "e":
        num = Prompt.ask("Número de producto a editar", default="1")
        try:
            datos[int(num) - 1] = _editar_producto(datos[int(num) - 1])
        except (ValueError, IndexError):
            console.print("[red]Número no válido.[/red]")
        console.print()
        _tabla_resumen(datos)
        if not Confirm.ask("¿Publicar ahora?", default=True):
            return

    # ── Paso 4: Publicar ──────────────────────────────────────────────────────
    PROCESADOS_DIR.mkdir(parents=True, exist_ok=True)
    ERRORES_DIR.mkdir(parents=True, exist_ok=True)
    resultados: dict[str, list[str]] = {"ok": [], "error": []}

    for p in datos:
        lote_item: ProductoLote = p["lote"]
        c: ContenidoProducto    = p["contenido"]
        fotos = [str(f) for f in lote_item.imagenes]
        errores_producto: list[str] = []

        for plataforma in p["publicar_en"]:
            console.print(f"\n[bold]→ {plataforma.capitalize()}:[/bold] {c.titulo_wallapop}")
            try:
                if plataforma == "wallapop":
                    subir_wallapop({
                        "slug":         lote_item.slug,
                        "titulo":       c.titulo_wallapop,
                        "descripcion":  c.descripcion_wallapop,
                        "precio":       p["precio_final"],
                        "estado_texto": c.estado_wallapop,
                        "fotos":        fotos,
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
                        "marca":             c.marca,
                        "fotos":             fotos,
                    })
                console.print(f"  [green]✓ Publicado en {plataforma}[/green]")
                resultados["ok"].append(f"{lote_item.slug} → {plataforma}")

            except RuntimeError as exc:
                console.print(f"  [red]✗ Error en {plataforma}: {exc}[/red]")
                resultados["error"].append(f"{lote_item.slug} → {plataforma}")
                errores_producto.append(plataforma)

        if not errores_producto:
            dest = PROCESADOS_DIR / lote_item.slug
            if not dest.exists():
                shutil.move(str(lote_item.carpeta), str(dest))
                console.print(f"  [dim]→ Movido a procesados/[/dim]")
        else:
            console.print(
                f"  [yellow]⚠ Se queda en lote/ "
                f"(errores en: {', '.join(errores_producto)})[/yellow]"
            )

    # ── Resumen final ─────────────────────────────────────────────────────────
    console.print()
    if resultados["ok"]:
        console.print(f"[bold green]✓ Publicados ({len(resultados['ok'])}):[/bold green]")
        for r in resultados["ok"]:
            console.print(f"  [green]·[/green] {r}")
    if resultados["error"]:
        console.print(f"\n[bold red]✗ Con errores ({len(resultados['error'])}):[/bold red]")
        for r in resultados["error"]:
            console.print(f"  [red]·[/red] {r}")
        console.print(f"  [dim]Revisa capturas en {ERRORES_DIR}[/dim]")

    Prompt.ask("\n[dim]Pulsa Enter para volver al menú[/dim]", default="")


# ── Punto de entrada ──────────────────────────────────────────────────────────

def run() -> None:
    _menu_principal()


if __name__ == "__main__":
    run()
