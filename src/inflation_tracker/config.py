from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlparse

from inflation_tracker.models import Product, ProductSource, RetailerProductUrl


def load_products(config_path: str | Path) -> list[Product]:
    path = Path(config_path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    products: list[Product] = []
    default_currency = raw.get("currency", "USD")

    for item in raw.get("products", []):
        source_data = item.get("source")
        retailer_data = item.get("retailer_urls", item.get("retailers", []))
        source = None
        retailer_urls: list[RetailerProductUrl] = []

        if source_data is not None:
            price = source_data.get("price")
            source = ProductSource(
                type=source_data["type"],
                price=Decimal(str(price)) if price is not None else None,
                url=source_data.get("url"),
            )

        if retailer_data is None:
            retailer_data = []
        if not isinstance(retailer_data, list):
            raise ValueError(
                f"Product '{item['id']}' has invalid 'retailer_urls'; expected a list."
            )
        if len(retailer_data) > 3:
            raise ValueError(
                f"Product '{item['id']}' has {len(retailer_data)} retailer URLs; maximum is 3."
            )

        for retailer in retailer_data:
            retailer_name = ""
            retailer_url = ""

            if isinstance(retailer, str):
                retailer_url = retailer.strip()
                retailer_name = _retailer_name_from_url(retailer_url)
            elif isinstance(retailer, dict):
                retailer_name = str(
                    retailer.get("retailer_name", retailer.get("name", ""))
                ).strip()
                retailer_url = str(retailer.get("url", "")).strip()
                if retailer_url and not retailer_name:
                    retailer_name = _retailer_name_from_url(retailer_url)
            else:
                raise ValueError(
                    f"Product '{item['id']}' has an invalid retailer entry; expected a URL string or object."
                )

            if not retailer_name or not retailer_url:
                raise ValueError(
                    f"Product '{item['id']}' has a retailer entry missing a valid URL."
                )
            retailer_urls.append(
                RetailerProductUrl(
                    retailer_name=retailer_name,
                    url=retailer_url,
                )
            )

        products.append(
            Product(
                id=item["id"],
                name=item["name"],
                category=item.get("category", "uncategorized"),
                currency=item.get("currency", default_currency),
                retailer_urls=tuple(retailer_urls),
                source=source,
            )
        )

    return products


def _retailer_name_from_url(url: str) -> str:
    hostname = urlparse(url).netloc.lower()
    if hostname.startswith("www."):
        hostname = hostname[4:]

    known_names = {
        "carrefourkuwait.com": "Carrefour Kuwait",
        "gcc.luluhypermarket.com": "Lulu Hypermarket",
        "grandhyper.com": "Grand Hyper",
        "kuwait.grandhyper.com": "Grand Hyper",
        "talabat.com": "Talabat",
        "ananinja.com": "Ana Ninja",
    }
    for domain, retailer_name in known_names.items():
        if hostname == domain or hostname.endswith(f".{domain}"):
            return retailer_name

    first_label = hostname.split(".", 1)[0].replace("-", " ").strip()
    if not first_label:
        return "Retailer"
    return first_label.title()
