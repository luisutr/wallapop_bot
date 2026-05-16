from __future__ import annotations

from typing import Optional


def buscar_precio_wallapop(titulo: str, max_items: int = 20) -> Optional[float]:
    """
    Devuelve el precio mínimo encontrado en Wallapop para el título dado.
    Usa la librería wallapy (API no oficial).
    Retorna None si no hay resultados o hay un error de conexión.
    """
    try:
        from wallapy import check_wallapop  # type: ignore

        results = check_wallapop(
            product_name=titulo,
            max_total_items=max_items,
            order_by="price_low_to_high",
        )
        if not results:
            return None

        prices = [
            float(r["price"])
            for r in results
            if r.get("price") not in (None, "", 0)
        ]
        return min(prices) if prices else None

    except Exception as exc:
        print(f"  [wallapop_pricer] No se pudo obtener precio: {exc}")
        return None
