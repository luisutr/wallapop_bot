"""
setup_sesiones.py
=================
Ejecuta este script para guardar/renovar tus sesiones de Wallapop y Vinted.
Las sesiones se guardan en la carpeta sesiones/ y son necesarias para publicar.

Uso:
    source venv/bin/activate
    python setup_sesiones.py              # Guarda ambas sesiones
    python setup_sesiones.py wallapop     # Solo Wallapop
    python setup_sesiones.py vinted       # Solo Vinted
"""
import sys
from app.auth.wallapop_session import guardar_sesion_wallapop
from app.auth.vinted_session import guardar_sesion_vinted


def main():
    args = set(sys.argv[1:])

    if not args or "wallapop" in args:
        print("=" * 50)
        print("WALLAPOP")
        print("=" * 50)
        guardar_sesion_wallapop()

    if not args or "vinted" in args:
        print("=" * 50)
        print("VINTED")
        print("=" * 50)
        guardar_sesion_vinted()

    print("\n✓ Sesiones guardadas. Ya puedes ejecutar: python -m app.cli")


if __name__ == "__main__":
    main()
