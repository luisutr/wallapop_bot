"""
GUI para Wallapop & Vinted Bot.
Gestiona el lote, sesiones y publicación sin salir de la ventana.
"""
from __future__ import annotations

import json
import os
import shutil
import threading
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, scrolledtext, ttk

from config import (
    LOTE_DIR,
    LOGS_DIR,
    PROCESADOS_DIR,
    VINTED_COOKIES_PATH,
    VINTED_STATE_PATH,
    WALLAPOP_STATE_PATH,
)
from pathlib import Path

from app.parser.image_loader import cargar_lote
from app.parser.csv_importer import (
    leer_csv_inventario,
    resolver_imagenes,
    importar_a_lote,
)
from app.enricher.identifier import identificar
from app.enricher.content_gen import generar_contenido
from app.publishers.wallapop import subir_wallapop
from app.publishers.vinted import subir_vinted

DEFAULT_IMPORT_DIR = Path(__file__).parent / "iloveimg-converted"


def _sesion_ok(path: os.PathLike) -> tuple[bool, str]:
    p = os.fspath(path)
    if not os.path.exists(p):
        return False, "Sin sesión"
    mtime = datetime.fromtimestamp(os.path.getmtime(p))
    dias = (datetime.now() - mtime).days
    edad = "hoy" if dias == 0 else f"hace {dias}d"
    return True, f"OK ({edad})"


class WallapopBotGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Wallapop & Vinted Bot")
        self.root.geometry("820x860")
        self.root.minsize(700, 650)

        self.fotos_paths: list[str] = []
        self._publicando = False
        self._csv_path: Path | None = None
        self._img_dir: Path | None = None
        self._lote_slugs: list[str] = []
        if DEFAULT_IMPORT_DIR.is_dir():
            csv_default = DEFAULT_IMPORT_DIR / "inventario_articulos.csv"
            if csv_default.exists():
                self._csv_path = csv_default
                self._img_dir = DEFAULT_IMPORT_DIR

        os.makedirs(LOTE_DIR, exist_ok=True)
        self._build_ui()
        self.refresh_product_list()
        self._refresh_session_labels()

    # ── UI ───────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        main = ttk.Frame(self.root, padding=8)
        main.pack(fill=tk.BOTH, expand=True)

        # ── Sesiones ──────────────────────────────────────────────────────────
        ses = ttk.LabelFrame(main, text="Sesiones", padding=8)
        ses.pack(fill=tk.X, pady=(0, 6))

        row_s = ttk.Frame(ses)
        row_s.pack(fill=tk.X)

        self.lbl_wallapop_ses = ttk.Label(row_s, text="Wallapop: …", width=22)
        self.lbl_wallapop_ses.pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(row_s, text="🔑 Guardar Wallapop", command=self._save_wallapop_session).pack(
            side=tk.LEFT, padx=4
        )

        self.lbl_vinted_ses = ttk.Label(row_s, text="Vinted: …", width=22)
        self.lbl_vinted_ses.pack(side=tk.LEFT, padx=(16, 8))
        ttk.Button(row_s, text="🔑 Guardar Vinted", command=self._save_vinted_session).pack(
            side=tk.LEFT, padx=4
        )

        # ── Importar CSV ──────────────────────────────────────────────────────
        imp = ttk.LabelFrame(main, text="Importar lote desde CSV + imágenes", padding=8)
        imp.pack(fill=tk.X, pady=6)

        row_i1 = ttk.Frame(imp)
        row_i1.pack(fill=tk.X, pady=2)
        ttk.Button(row_i1, text="📄 Elegir CSV…", command=self._elegir_csv, width=14).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        self.lbl_csv = ttk.Label(row_i1, text="(ninguno)", foreground="gray")
        self.lbl_csv.pack(side=tk.LEFT, fill=tk.X, expand=True)

        row_i2 = ttk.Frame(imp)
        row_i2.pack(fill=tk.X, pady=2)
        ttk.Button(row_i2, text="📁 Carpeta imágenes…", command=self._elegir_carpeta_imgs, width=16).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        self.lbl_img_dir = ttk.Label(row_i2, text="(ninguna)", foreground="gray")
        self.lbl_img_dir.pack(side=tk.LEFT, fill=tk.X, expand=True)

        row_i3 = ttk.Frame(imp)
        row_i3.pack(fill=tk.X, pady=4)
        ttk.Label(row_i3, text="Estado import:").pack(side=tk.LEFT)
        self.imp_estado_var = tk.StringVar(value="bueno")
        ttk.Combobox(
            row_i3, textvariable=self.imp_estado_var,
            values=["bueno", "como_nuevo", "nuevo", "buen_estado", "aceptable", "sin_abrir", "en_su_caja"],
            state="readonly", width=12,
        ).pack(side=tk.LEFT, padx=4)
        ttk.Label(row_i3, text="(W: En buen estado)", font=("", 9), foreground="gray").pack(side=tk.LEFT)
        ttk.Label(row_i3, text="Plataformas:").pack(side=tk.LEFT, padx=(12, 0))
        self.imp_plat_var = tk.StringVar(value="ambas")
        ttk.Combobox(
            row_i3, textvariable=self.imp_plat_var,
            values=["ambas", "wallapop", "vinted"], state="readonly", width=10,
        ).pack(side=tk.LEFT, padx=4)
        self.imp_sobrescribir = tk.BooleanVar(value=False)
        ttk.Checkbutton(row_i3, text="Sobrescribir", variable=self.imp_sobrescribir).pack(
            side=tk.LEFT, padx=8
        )

        row_i4 = ttk.Frame(imp)
        row_i4.pack(fill=tk.X, pady=4)
        ttk.Button(
            row_i4, text="👁 Vista previa CSV", command=self._vista_previa_csv
        ).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(
            row_i4, text="📥 Cargar en lote/", command=self._importar_csv_a_lote
        ).pack(side=tk.LEFT, padx=4)

        self._actualizar_labels_import()

        # ── Añadir producto manual ────────────────────────────────────────────
        add = ttk.LabelFrame(main, text="Añadir producto manual (opcional)", padding=8)
        add.pack(fill=tk.X, pady=6)

        ttk.Label(add, text="Nombre carpeta (slug):").grid(row=0, column=0, sticky=tk.W, pady=2)
        self.slug_var = tk.StringVar()
        ttk.Entry(add, textvariable=self.slug_var, width=42).grid(
            row=0, column=1, columnspan=2, sticky=tk.W, padx=5, pady=2
        )

        ttk.Label(add, text="Fotos:").grid(row=1, column=0, sticky=tk.W, pady=2)
        self.lbl_fotos = ttk.Label(add, text="0 seleccionadas")
        self.lbl_fotos.grid(row=1, column=1, sticky=tk.W, padx=5)
        ttk.Button(add, text="Seleccionar…", command=self.select_photos).grid(row=1, column=2, padx=5)

        ttk.Label(add, text="Plataformas:").grid(row=2, column=0, sticky=tk.W, pady=2)
        self.plat_var = tk.StringVar(value="ambas")
        ttk.Combobox(
            add, textvariable=self.plat_var,
            values=["ambas", "wallapop", "vinted"], state="readonly", width=12,
        ).grid(row=2, column=1, sticky=tk.W, padx=5)

        ttk.Label(add, text="Estado:").grid(row=3, column=0, sticky=tk.W, pady=2)
        self.estado_var = tk.StringVar(value="bueno")
        ttk.Combobox(
            add, textvariable=self.estado_var,
            values=["bueno", "como_nuevo", "nuevo", "buen_estado", "aceptable", "sin_abrir", "en_su_caja"],
            state="readonly", width=14,
        ).grid(row=3, column=1, sticky=tk.W, padx=5)

        ttk.Label(add, text="Precio € (opc.):").grid(row=4, column=0, sticky=tk.W, pady=2)
        self.precio_var = tk.StringVar()
        ttk.Entry(add, textvariable=self.precio_var, width=10).grid(row=4, column=1, sticky=tk.W, padx=5)

        ttk.Label(add, text="Título (opc.):").grid(row=5, column=0, sticky=tk.W, pady=2)
        self.titulo_var = tk.StringVar()
        ttk.Entry(add, textvariable=self.titulo_var, width=42).grid(
            row=5, column=1, columnspan=2, sticky=tk.W, padx=5
        )

        ttk.Button(add, text="💾 Guardar en lote/", command=self.save_product).grid(
            row=6, column=0, columnspan=3, pady=8
        )

        # ── Lista lote ────────────────────────────────────────────────────────
        lst = ttk.LabelFrame(main, text="Productos pendientes (lote/)", padding=8)
        lst.pack(fill=tk.BOTH, expand=True, pady=6)

        self.listbox = tk.Listbox(lst, height=8, selectmode=tk.SINGLE, font=("Menlo", 10))
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb = ttk.Scrollbar(lst, orient=tk.VERTICAL, command=self.listbox.yview)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.listbox.config(yscrollcommand=sb.set)

        row_a = ttk.Frame(main)
        row_a.pack(fill=tk.X, pady=4)
        ttk.Button(row_a, text="🔄 Actualizar", command=self.refresh_product_list).pack(side=tk.LEFT, padx=4)
        ttk.Button(row_a, text="🗑 Borrar", command=self.delete_selected).pack(side=tk.LEFT, padx=4)
        ttk.Button(row_a, text="📋 Ver logs", command=self._open_logs_folder).pack(side=tk.LEFT, padx=4)

        self.plat_pub_var = tk.StringVar(value="ambas")
        ttk.Label(row_a, text="Publicar en:").pack(side=tk.RIGHT, padx=(8, 2))
        ttk.Combobox(
            row_a, textvariable=self.plat_pub_var,
            values=["ambas", "wallapop", "vinted"], state="readonly", width=10,
        ).pack(side=tk.RIGHT)
        self.btn_publicar = ttk.Button(
            row_a, text="🚀 PUBLICAR LOTE", command=self.publish_lote
        )
        self.btn_publicar.pack(side=tk.RIGHT, padx=8)

        # ── Log ───────────────────────────────────────────────────────────────
        log_f = ttk.LabelFrame(main, text="Registro", padding=4)
        log_f.pack(fill=tk.BOTH, expand=True, pady=(4, 0))
        self.log_text = scrolledtext.ScrolledText(log_f, height=10, state=tk.DISABLED, font=("Menlo", 10))
        self.log_text.pack(fill=tk.BOTH, expand=True)

    def _open_logs_folder(self) -> None:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        import subprocess
        import sys
        path = str(LOGS_DIR.resolve())
        if sys.platform == "darwin":
            subprocess.run(["open", path], check=False)
        elif sys.platform == "win32":
            subprocess.run(["explorer", path], check=False)
        else:
            subprocess.run(["xdg-open", path], check=False)

    def _log(self, msg: str) -> None:
        def _append():
            self.log_text.config(state=tk.NORMAL)
            self.log_text.insert(tk.END, msg + "\n")
            self.log_text.see(tk.END)
            self.log_text.config(state=tk.DISABLED)
        self.root.after(0, _append)

    def _refresh_session_labels(self) -> None:
        ok_w, txt_w = _sesion_ok(WALLAPOP_STATE_PATH)
        vinted_path = VINTED_STATE_PATH if VINTED_STATE_PATH.exists() else VINTED_COOKIES_PATH
        ok_v, txt_v = _sesion_ok(vinted_path)
        self.lbl_wallapop_ses.config(
            text=f"Wallapop: {txt_w}",
            foreground="#2e7d32" if ok_w else "#c62828",
        )
        self.lbl_vinted_ses.config(
            text=f"Vinted: {txt_v}",
            foreground="#2e7d32" if ok_v else "#c62828",
        )

    # ── Sesiones (en hilo + diálogo) ─────────────────────────────────────────

    def _save_wallapop_session(self) -> None:
        self._run_session_save("wallapop")

    def _save_vinted_session(self) -> None:
        self._run_session_save("vinted")

    def _run_session_save(self, plataforma: str) -> None:
        event = threading.Event()

        def worker():
            try:
                if plataforma == "wallapop":
                    from app.auth.wallapop_session import guardar_sesion_wallapop
                    guardar_sesion_wallapop(wait_fn=event.wait)
                else:
                    from app.auth.vinted_session import guardar_sesion_vinted
                    guardar_sesion_vinted(wait_fn=event.wait)
                self.root.after(0, lambda: self._on_session_done(plataforma, None))
            except Exception as exc:
                self.root.after(0, lambda: self._on_session_done(plataforma, exc))

        self._log(f"Abriendo navegador para {plataforma}…")
        threading.Thread(target=worker, daemon=True).start()
        self._show_session_dialog(plataforma, event)

    def _show_session_dialog(self, plataforma: str, event: threading.Event) -> None:
        win = tk.Toplevel(self.root)
        win.title(f"Sesión {plataforma.capitalize()}")
        win.geometry("400x160")
        win.transient(self.root)
        win.grab_set()

        nombre = (
            "Wallapop (Chrome sin detección de bots)"
            if plataforma == "wallapop"
            else "Vinted (Chrome sin detección de bots)"
        )
        ttk.Label(
            win,
            text=f"Se ha abierto el navegador.\n\n"
                 f"Inicia sesión en {nombre}.\n"
                 f"Cuando veas tu perfil, pulsa el botón de abajo.",
            justify=tk.CENTER,
        ).pack(pady=16, padx=12)

        def confirmar():
            event.set()
            win.destroy()

        ttk.Button(win, text="✓ Ya he iniciado sesión", command=confirmar).pack(pady=8)

    def _on_session_done(self, plataforma: str, error: Exception | None) -> None:
        self._refresh_session_labels()
        if error:
            self._log(f"✗ Error sesión {plataforma}: {error}")
            messagebox.showerror("Error", str(error))
        else:
            self._log(f"✓ Sesión {plataforma} guardada.")
            messagebox.showinfo("Listo", f"Sesión de {plataforma} guardada correctamente.")

    # ── Importar CSV ───────────────────────────────────────────────────────────

    def _actualizar_labels_import(self) -> None:
        if self._csv_path and self._csv_path.exists():
            self.lbl_csv.config(text=str(self._csv_path.name), foreground="black")
        else:
            self.lbl_csv.config(text="(ninguno)", foreground="gray")
        if self._img_dir and self._img_dir.is_dir():
            self.lbl_img_dir.config(text=str(self._img_dir), foreground="black")
        else:
            self.lbl_img_dir.config(text="(ninguna)", foreground="gray")

    def _elegir_csv(self) -> None:
        inicial = str(self._csv_path.parent) if self._csv_path else str(DEFAULT_IMPORT_DIR)
        path = filedialog.askopenfilename(
            title="CSV de inventario",
            initialdir=inicial,
            filetypes=[("CSV", "*.csv"), ("Todos", "*.*")],
        )
        if path:
            self._csv_path = Path(path)
            if not self._img_dir or not self._img_dir.is_dir():
                self._img_dir = self._csv_path.parent
            self._actualizar_labels_import()

    def _elegir_carpeta_imgs(self) -> None:
        inicial = str(self._img_dir) if self._img_dir else str(DEFAULT_IMPORT_DIR)
        path = filedialog.askdirectory(title="Carpeta con las imágenes", initialdir=inicial)
        if path:
            self._img_dir = Path(path)
            self._actualizar_labels_import()

    def _cargar_productos_csv(self):
        if not self._csv_path or not self._csv_path.exists():
            raise FileNotFoundError("Selecciona un archivo CSV.")
        if not self._img_dir or not self._img_dir.is_dir():
            raise FileNotFoundError("Selecciona la carpeta de imágenes.")
        productos = leer_csv_inventario(self._csv_path)
        resolver_imagenes(productos, self._img_dir)
        return productos

    def _vista_previa_csv(self) -> None:
        try:
            productos = self._cargar_productos_csv()
        except Exception as exc:
            messagebox.showerror("Error", str(exc))
            return

        ok = sum(1 for p in productos if p.listo)
        faltan = [p for p in productos if not p.listo]
        total_precio = sum(p.precio for p in productos if p.listo)

        lineas = [
            f"Productos en CSV: {len(productos)}",
            f"Listos para importar: {ok}",
            f"Valor total (aprox.): {total_precio:.0f}€",
            "",
        ]
        for p in productos[:12]:
            estado = "✓" if p.listo else "✗"
            n = len(p.imagenes_encontradas)
            lineas.append(f"{estado} {p.precio:.0f}€ | {n} foto(s) | {p.titulo[:45]}")
        if len(productos) > 12:
            lineas.append(f"… y {len(productos) - 12} más")

        if faltan:
            lineas.append("\n⚠ Con imágenes faltantes:")
            for p in faltan[:5]:
                lineas.append(f"  • {p.titulo}: {', '.join(p.imagenes_faltantes)}")

        messagebox.showinfo("Vista previa", "\n".join(lineas))

    def _importar_csv_a_lote(self) -> None:
        try:
            productos = self._cargar_productos_csv()
        except Exception as exc:
            messagebox.showerror("Error", str(exc))
            return

        ok_count = sum(1 for p in productos if p.listo)
        if ok_count == 0:
            messagebox.showwarning("Aviso", "Ningún producto tiene todas sus imágenes.")
            return

        if not messagebox.askyesno(
            "Confirmar importación",
            f"¿Copiar {ok_count} producto(s) a lote/?\n\n"
            f"Estado: {self.imp_estado_var.get()}\n"
            f"Plataformas: {self.imp_plat_var.get()}",
        ):
            return

        plats = (
            ["wallapop", "vinted"] if self.imp_plat_var.get() == "ambas"
            else [self.imp_plat_var.get()]
        )
        importados, omitidos, errores = importar_a_lote(
            productos,
            estado=self.imp_estado_var.get(),
            publicar_en=plats,
            sobrescribir=self.imp_sobrescribir.get(),
        )

        self._log(f"Importación: {importados} OK, {omitidos} omitidos")
        for e in errores[:10]:
            self._log(f"  ⚠ {e}")

        self.refresh_product_list()
        messagebox.showinfo(
            "Importación completada",
            f"Importados: {importados}\nOmitidos: {omitidos}\n\n"
            "Revisa la lista y pulsa «PUBLICAR LOTE» cuando quieras subir.",
        )

    # ── Lote manual ────────────────────────────────────────────────────────────

    def select_photos(self) -> None:
        try:
            files = filedialog.askopenfilenames(
                title="Seleccionar imágenes",
                filetypes=[("Imágenes", "*.png *.jpg *.jpeg *.webp"), ("Todos", "*.*")],
            )
            if files:
                self.fotos_paths = list(files)
                self.lbl_fotos.config(text=f"{len(self.fotos_paths)} seleccionadas")
        except Exception as exc:
            messagebox.showerror("Error", str(exc))

    def save_product(self) -> None:
        slug = self.slug_var.get().strip().lower().replace(" ", "_")
        slug = slug.replace(".", "").replace("-", "_")
        if not slug:
            messagebox.showwarning("Aviso", "Indica un nombre para la carpeta (slug).")
            return
        if not self.fotos_paths:
            messagebox.showwarning("Aviso", "Selecciona al menos una foto.")
            return

        product_dir = os.path.join(LOTE_DIR, slug)
        if os.path.exists(product_dir):
            if not messagebox.askyesno("Confirmar", f"¿Sobrescribir '{slug}'?"):
                return
            shutil.rmtree(product_dir)
        os.makedirs(product_dir, exist_ok=True)

        for i, foto in enumerate(self.fotos_paths, 1):
            ext = os.path.splitext(foto)[1].lower() or ".jpg"
            shutil.copy2(foto, os.path.join(product_dir, f"{i:02d}{ext}"))

        meta: dict = {}
        if self.plat_var.get() != "ambas":
            meta["publicar_en"] = [self.plat_var.get()]
        if self.estado_var.get() != "como_nuevo":
            meta["estado"] = self.estado_var.get()
        if self.precio_var.get().strip():
            try:
                meta["precio_manual"] = float(self.precio_var.get().strip().replace(",", "."))
            except ValueError:
                messagebox.showwarning("Aviso", "Precio no válido, se ignorará.")
        if self.titulo_var.get().strip():
            meta["titulo"] = self.titulo_var.get().strip()
        if meta:
            with open(os.path.join(product_dir, "meta.json"), "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2, ensure_ascii=False)

        messagebox.showinfo("OK", f"Guardado en lote/{slug}/")
        self.slug_var.set("")
        self.fotos_paths = []
        self.lbl_fotos.config(text="0 seleccionadas")
        self.precio_var.set("")
        self.titulo_var.set("")
        self.refresh_product_list()

    def refresh_product_list(self) -> None:
        self.listbox.delete(0, tk.END)
        self._lote_slugs = []
        if not os.path.isdir(LOTE_DIR):
            return
        total = 0
        for item in sorted(os.listdir(LOTE_DIR)):
            path = os.path.join(LOTE_DIR, item)
            if not os.path.isdir(path) or item.startswith("."):
                continue
            n = len([
                f for f in os.listdir(path)
                if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))
            ])
            precio_txt = ""
            titulo_txt = ""
            meta_path = os.path.join(path, "meta.json")
            if os.path.isfile(meta_path):
                try:
                    with open(meta_path, encoding="utf-8") as f:
                        meta = json.load(f)
                    if meta.get("precio_manual") is not None:
                        precio_txt = f"{meta['precio_manual']:.0f}€"
                    if meta.get("titulo"):
                        titulo_txt = meta["titulo"][:42]
                except Exception:
                    pass
            linea = f"{precio_txt:>5} | {n}f | {titulo_txt or item}"
            self.listbox.insert(tk.END, linea)
            self._lote_slugs.append(item)
            total += 1
        self.root.title(f"Wallapop & Vinted Bot — {total} en lote")

    def delete_selected(self) -> None:
        sel = self.listbox.curselection()
        if not sel:
            return
        slug = self._lote_slugs[sel[0]]
        if messagebox.askyesno("Confirmar", f"¿Borrar '{slug}'?"):
            shutil.rmtree(os.path.join(LOTE_DIR, slug), ignore_errors=True)
            self.refresh_product_list()

    # ── Publicar ───────────────────────────────────────────────────────────────

    def publish_lote(self) -> None:
        if self._publicando:
            messagebox.showinfo("Aviso", "Ya hay una publicación en curso.")
            return

        lote = cargar_lote()
        if not lote:
            messagebox.showwarning("Aviso", "No hay productos en lote/.")
            return

        plat = self.plat_pub_var.get()
        plataformas = (
            ["wallapop", "vinted"] if plat == "ambas"
            else [plat]
        )

        ok_w, _ = _sesion_ok(WALLAPOP_STATE_PATH)
        ok_v, _ = _sesion_ok(
            VINTED_STATE_PATH if VINTED_STATE_PATH.exists() else VINTED_COOKIES_PATH
        )
        if "wallapop" in plataformas and not ok_w:
            messagebox.showerror("Sesión", "Guarda primero la sesión de Wallapop.")
            return
        if "vinted" in plataformas and not ok_v:
            messagebox.showerror("Sesión", "Guarda primero la sesión de Vinted.")
            return

        if not messagebox.askyesno(
            "Confirmar publicación",
            f"¿Publicar {len(lote)} producto(s) en {', '.join(plataformas)}?\n\n"
            "Recomendado: prueba primero con 1 producto antes del lote completo.\n"
            "Se abrirá el navegador automáticamente.",
        ):
            return

        self._publicando = True
        self.btn_publicar.config(state=tk.DISABLED)
        self._log("——— Inicio publicación ———")

        threading.Thread(
            target=self._publish_worker,
            args=(lote, plataformas),
            daemon=True,
        ).start()

    def _publish_worker(self, lote, plataformas: list[str]) -> None:
        log = self._log
        errores: list[str] = []

        try:
            for item in lote:
                info = identificar(item.slug)
                tipo = info.tipo
                contenido = generar_contenido(
                    info,
                    item.estado,
                    tipo_override=tipo,
                    titulo_override=item.titulo_override,
                    descripcion_override=item.descripcion_override,
                    pegi_override=item.pegi_override,
                )
                publicar_en = (
                    item.publicar_en
                    if "publicar_en" in item.meta
                    else plataformas
                )
                precio = item.precio_manual if item.precio_manual is not None else 9.0
                fotos = [str(f) for f in item.imagenes]
                fallos_prod: list[str] = []

                log(f"\n▶ {contenido.titulo_wallapop} ({precio}€)")

                if "wallapop" in publicar_en:
                    try:
                        subir_wallapop({
                            "slug": item.slug,
                            "titulo": contenido.titulo_wallapop,
                            "descripcion": contenido.descripcion_wallapop,
                            "precio": precio,
                            "estado_texto": contenido.estado_wallapop,
                            "fotos": fotos,
                        }, log_fn=log)
                    except Exception as exc:
                        log(f"✗ Wallapop: {exc}")
                        log(f"  → Revisa logs/ y errores/ para detalle de campos")
                        fallos_prod.append("wallapop")
                        errores.append(f"{item.slug} → wallapop")

                if "vinted" in publicar_en:
                    try:
                        subir_vinted({
                            "slug": item.slug,
                            "titulo": contenido.titulo_vinted,
                            "descripcion": contenido.descripcion_vinted,
                            "precio": precio,
                            "estado_vinted": contenido.estado_vinted,
                            "categoria_vinted": contenido.categoria_vinted,
                            "plataforma_vinted": contenido.plataforma_vinted,
                            "pegi": contenido.pegi,
                            "tipo": tipo,
                            "marca": contenido.marca,
                            "fotos": fotos,
                        }, log_fn=log)
                    except Exception as exc:
                        log(f"✗ Vinted: {exc}")
                        log(f"  → Revisa logs/ (report.json + resumen.txt)")
                        fallos_prod.append("vinted")
                        errores.append(f"{item.slug} → vinted")

                if not fallos_prod:
                    dest = os.path.join(PROCESADOS_DIR, item.slug)
                    os.makedirs(PROCESADOS_DIR, exist_ok=True)
                    if not os.path.exists(dest):
                        shutil.move(str(item.carpeta), dest)
                    log(f"→ Movido a procesados/{item.slug}")

            log("\n——— Fin ———")
            if errores:
                self.root.after(
                    0,
                    lambda: messagebox.showwarning(
                        "Completado con errores",
                        "\n".join(errores),
                    ),
                )
            else:
                self.root.after(0, lambda: messagebox.showinfo("Listo", "Lote publicado."))
        finally:
            self.root.after(0, self._publish_done)

    def _publish_done(self) -> None:
        self._publicando = False
        self.btn_publicar.config(state=tk.NORMAL)
        self.refresh_product_list()


if __name__ == "__main__":
    root = tk.Tk()
    style = ttk.Style()
    if "clam" in style.theme_names():
        style.theme_use("clam")
    WallapopBotGUI(root)
    root.mainloop()
