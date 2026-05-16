from __future__ import annotations

from typing import Optional


def buscar_precio_vinted(titulo: str) -> Optional[float]:
    """
    Devuelve el precio mínimo encontrado en Vinted.es para el título dado.
    Usa la librería vinted_scraper (gestión automática de cookies).
    Retorna None si no hay resultados o hay un error de conexión.
    """
    try:
        from vinted_scraper import VintedScraper  # type: ignore

        scraper = VintedScraper("https://www.vinted.es")
        items = scraper.search({
            "search_text": titulo,
            "order": "price_low_to_high",
        })
        if not items:
            return None

        prices: list[float] = []
        for item in items:
            try:
                price = float(item.price)
                if price > 0:
                    prices.append(price)
            except (TypeError, ValueError, AttributeError):
                continue

        return min(prices) if prices else None

    except Exception as exc:
        print(f"  [vinted_pricer] No se pudo obtener precio: {exc}")
        return None
