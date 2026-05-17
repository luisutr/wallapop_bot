import os
import json
import shutil
import subprocess
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

# GUI para gestionar y subir productos a Wallapop y Vinted con la nueva arquitectura
LOTE_DIR = "lote"

class WallapopBotGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Wallapop & Vinted Bot GUI")
        self.root.geometry("700x650")
        
        self.create_widgets()
        self.refresh_product_list()

    def create_widgets(self):
        main_frame = ttk.Frame(self.root, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # -- Sección de añadir producto --
        add_frame = ttk.LabelFrame(main_frame, text="Añadir Nuevo Producto", padding=10)
        add_frame.pack(fill=tk.X, pady=5)

        ttk.Label(add_frame, text="Nombre (Slug p.ej. juego_ps4_fifa):").grid(row=0, column=0, sticky=tk.W, pady=2)
        self.slug_var = tk.StringVar()
        ttk.Entry(add_frame, textvariable=self.slug_var, width=40).grid(row=0, column=1, sticky=tk.W, pady=2, padx=5)

        self.fotos_paths = []
        ttk.Label(add_frame, text="Fotos seleccionadas: 0").grid(row=1, column=0, sticky=tk.W, pady=2)
        self.lbl_fotos = ttk.Label(add_frame, text="")
        self.lbl_fotos.grid(row=1, column=1, sticky=tk.W, pady=2, padx=5)
        ttk.Button(add_frame, text="Seleccionar Fotos...", command=self.select_photos).grid(row=1, column=2, padx=5)

        # Opciones avanzadas (meta.json)
        ttk.Label(add_frame, text="Plataformas:").grid(row=2, column=0, sticky=tk.W, pady=2)
        self.plat_var = tk.StringVar(value="ambas")
        plat_combo = ttk.Combobox(add_frame, textvariable=self.plat_var, values=["ambas", "wallapop", "vinted"], state="readonly")
        plat_combo.grid(row=2, column=1, sticky=tk.W, pady=2, padx=5)

        ttk.Label(add_frame, text="Estado:").grid(row=3, column=0, sticky=tk.W, pady=2)
        self.estado_var = tk.StringVar(value="como_nuevo")
        estado_combo = ttk.Combobox(add_frame, textvariable=self.estado_var, values=["nuevo", "como_nuevo", "buen_estado", "bueno", "aceptable"], state="readonly")
        estado_combo.grid(row=3, column=1, sticky=tk.W, pady=2, padx=5)

        ttk.Label(add_frame, text="Precio manual (€) (opcional):").grid(row=4, column=0, sticky=tk.W, pady=2)
        self.precio_var = tk.StringVar()
        ttk.Entry(add_frame, textvariable=self.precio_var, width=15).grid(row=4, column=1, sticky=tk.W, pady=2, padx=5)

        ttk.Label(add_frame, text="Título personalizado (opcional):").grid(row=5, column=0, sticky=tk.W, pady=2)
        self.titulo_var = tk.StringVar()
        ttk.Entry(add_frame, textvariable=self.titulo_var, width=40).grid(row=5, column=1, sticky=tk.W, pady=2, padx=5)

        ttk.Button(add_frame, text="💾 Guardar Producto en Lote", command=self.save_product).grid(row=6, column=0, columnspan=3, pady=10)

        # -- Sección de Lista de Lote --
        list_frame = ttk.LabelFrame(main_frame, text="Productos en Lote (Pendientes)", padding=10)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        self.listbox = tk.Listbox(list_frame, height=8)
        self.listbox.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)
        
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.listbox.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.listbox.config(yscrollcommand=scrollbar.set)

        # -- Botones de acción --
        action_frame = ttk.Frame(main_frame, padding=10)
        action_frame.pack(fill=tk.X, pady=5)

        ttk.Button(action_frame, text="🔄 Actualizar Lista", command=self.refresh_product_list).pack(side=tk.LEFT, padx=5)
        ttk.Button(action_frame, text="🗑 Borrar Seleccionado", command=self.delete_selected).pack(side=tk.LEFT, padx=5)
        
        ttk.Button(action_frame, text="🚀 PUBLICAR LOTE (Abrir Terminal)", command=self.run_bot).pack(side=tk.RIGHT, padx=5)

    def select_photos(self):
        # En macOS, algunas versiones de Tkinter fallan si se juntan extensiones con punto y coma.
        # Es más seguro separarlas por espacio o no usar filtro estricto.
        try:
            files = filedialog.askopenfilenames(
                title="Seleccionar Imágenes", 
                filetypes=[("Imágenes", "*.png *.jpg *.jpeg *.webp"), ("Todos los archivos", "*.*")]
            )
            if files:
                self.fotos_paths = list(files)
                self.lbl_fotos.config(text=f"{len(self.fotos_paths)} fotos seleccionadas")
        except Exception as e:
            messagebox.showerror("Error", f"Error al abrir el selector: {e}")

    def save_product(self):
        slug = self.slug_var.get().strip().lower().replace(" ", "_")
        if not slug:
            messagebox.showwarning("Aviso", "Debes indicar un nombre (slug).")
            return
        if not self.fotos_paths:
            messagebox.showwarning("Aviso", "Debes seleccionar al menos una foto.")
            return
            
        product_dir = os.path.join(LOTE_DIR, slug)
        if os.path.exists(product_dir):
            if not messagebox.askyesno("Aviso", f"El producto '{slug}' ya existe en el lote. ¿Sobrescribir?"):
                return
            shutil.rmtree(product_dir)
            
        os.makedirs(product_dir, exist_ok=True)
        
        for i, foto_path in enumerate(self.fotos_paths, 1):
            ext = os.path.splitext(foto_path)[1]
            dest = os.path.join(product_dir, f"{i:02d}{ext}")
            shutil.copy2(foto_path, dest)
            
        meta = {}
        if self.plat_var.get() != "ambas":
            meta["publicar_en"] = [self.plat_var.get()]
        if self.estado_var.get() != "como_nuevo":
            meta["estado"] = self.estado_var.get()
        if self.precio_var.get().strip():
            try:
                meta["precio_manual"] = float(self.precio_var.get().strip().replace(",", "."))
            except:
                pass
        if self.titulo_var.get().strip():
            meta["titulo"] = self.titulo_var.get().strip()
            
        if meta:
            with open(os.path.join(product_dir, "meta.json"), "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=4, ensure_ascii=False)
                
        messagebox.showinfo("Éxito", f"Producto '{slug}' guardado en lote/")
        
        self.slug_var.set("")
        self.fotos_paths = []
        self.lbl_fotos.config(text="")
        self.precio_var.set("")
        self.titulo_var.set("")
        self.refresh_product_list()

    def refresh_product_list(self):
        self.listbox.delete(0, tk.END)
        os.makedirs(LOTE_DIR, exist_ok=True)
        for item in sorted(os.listdir(LOTE_DIR)):
            item_path = os.path.join(LOTE_DIR, item)
            if os.path.isdir(item_path):
                fotos_count = len([f for f in os.listdir(item_path) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))])
                has_meta = "meta.json" in os.listdir(item_path)
                meta_str = " [+meta]" if has_meta else ""
                self.listbox.insert(tk.END, f"{item} ({fotos_count} fotos){meta_str}")

    def delete_selected(self):
        sel = self.listbox.curselection()
        if not sel:
            return
        item_text = self.listbox.get(sel[0])
        slug = item_text.split(" ")[0]
        if messagebox.askyesno("Confirmar", f"¿Borrar el producto '{slug}' del lote?"):
            shutil.rmtree(os.path.join(LOTE_DIR, slug))
            self.refresh_product_list()

    def run_bot(self):
        import platform
        cwd = os.getcwd()
        sys_os = platform.system()
        
        try:
            if sys_os == "Darwin":  # macOS
                script = f'''
                tell application "Terminal"
                    activate
                    do script "cd \\"{cwd}\\" && source venv/bin/activate && python -m app.cli"
                end tell
                '''
                subprocess.run(["osascript", "-e", script], check=True)
            elif sys_os == "Windows":  # Windows
                # En windows activamos el entorno virtual (venv\\Scripts\\activate) y corremos app.cli
                cmd = f'cd /d "{cwd}" && call venv\\Scripts\\activate && python -m app.cli'
                subprocess.Popen(["start", "cmd", "/k", cmd], shell=True)
            else:  # Linux
                # Intento genérico para Linux (gnome-terminal, xterm, etc)
                cmd = f"cd '{cwd}' && source venv/bin/activate && python -m app.cli; exec bash"
                subprocess.Popen(["gnome-terminal", "--", "bash", "-c", cmd])
                
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo abrir la terminal automáticamente: {e}\\n\\nPara publicar, abre la terminal manualmente y ejecuta 'python -m app.cli'")

if __name__ == "__main__":
    root = tk.Tk()
    style = ttk.Style()
    if 'clam' in style.theme_names():
        style.theme_use('clam')
    app = WallapopBotGUI(root)
    root.mainloop()