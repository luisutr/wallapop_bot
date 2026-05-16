import os
import tkinter as tk
from tkinter import filedialog, messagebox

# GUI para gestionar y subir productos a Wallapop y Vinted
class WallapopBotGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Wallapop & Vinted Bot GUI")
        self.root.geometry("600x400")

        # Lista de productos cargados
        self.products = []

        # Configuración inicial
        self.create_widgets()

    def create_widgets(self):
        # Título principal
        tk.Label(self.root, text="Wallapop & Vinted Bot", font=("Helvetica", 16)).pack(pady=10)

        # Botón para añadir fotos
        tk.Button(self.root, text="Añadir Producto (Fotos)", command=self.add_product).pack(pady=5)

        # Lista de productos cargados
        self.product_listbox = tk.Listbox(self.root, width=70, height=10)
        self.product_listbox.pack(pady=10)

        # Botón para iniciar publicación
        tk.Button(self.root, text="Publicar Productos", command=self.publish_products).pack(pady=5)

    def add_product(self):
        # Seleccionar fotos para un producto
        files = filedialog.askopenfilenames(title="Seleccionar Imágenes", filetypes=[("Imágenes", "*.png;*.jpg;*.jpeg")])
        if files:
            product_name = os.path.basename(files[0]).split(".")[0]  # Nombre basado en la primera imagen
            self.products.append({"name": product_name, "images": files})
            self.product_listbox.insert(tk.END, f"{product_name} - {len(files)} imagen(es)")

    def publish_products(self):
        if not self.products:
            messagebox.showwarning("Sin Productos", "No hay productos cargados para publicar.")
            return

        # Simular publicación
        for product in self.products:
            print(f"Publicando {product['name']} con {len(product['images'])} imágenes...")

        messagebox.showinfo("Publicación Completa", "¡Productos publicados exitosamente!")
        self.products.clear()
        self.product_listbox.delete(0, tk.END)

if __name__ == "__main__":
    root = tk.Tk()
    app = WallapopBotGUI(root)
    root.mainloop()