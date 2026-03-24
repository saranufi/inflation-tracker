from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from inflation_tracker.models import Product, ProductSource


def load_products(config_path: str | Path) -> list[Product]:
    path = Path(config_path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    products: list[Product] = []
    default_currency = raw.get("currency", "USD")

    for item in raw.get("products", []):
        source_data = item.get("source")
        source = None

        if source_data is not None:
            price = source_data.get("price")
            source = ProductSource(
                type=source_data["type"],
                price=Decimal(str(price)) if price is not None else None,
                url=source_data.get("url"),
            )

        products.append(
            Product(
                id=item["id"],
                name=item["name"],
                category=item.get("category", "uncategorized"),
                currency=item.get("currency", default_currency),
                source=source,
            )
        )

    return products
