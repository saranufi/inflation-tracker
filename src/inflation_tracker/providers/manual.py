from __future__ import annotations

from decimal import Decimal

from inflation_tracker.models import Product
from inflation_tracker.providers.base import PriceProvider


class ManualPriceProvider(PriceProvider):
    """Provider used for bootstrapping the project with fixed prices."""

    def fetch_price(self, product: Product) -> Decimal:
        if product.source is None or product.source.price is None:
            raise ValueError(f"Manual product '{product.id}' is missing a source price.")
        return product.source.price
