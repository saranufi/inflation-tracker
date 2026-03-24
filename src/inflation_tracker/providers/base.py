from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal

from inflation_tracker.models import Product


class PriceProvider(ABC):
    @abstractmethod
    def fetch_price(self, product: Product) -> Decimal:
        raise NotImplementedError
