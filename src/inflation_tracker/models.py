from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP


@dataclass(slots=True, frozen=True)
class ProductSource:
    type: str
    price: Decimal | None = None
    url: str | None = None


@dataclass(slots=True, frozen=True)
class Product:
    id: str
    name: str
    category: str
    currency: str
    source: ProductSource | None = None


@dataclass(slots=True, frozen=True)
class PriceSnapshot:
    product_id: str
    product_name: str
    category: str
    currency: str
    price: Decimal
    captured_at: datetime
    source_type: str | None

    @classmethod
    def create(
        cls,
        *,
        product: Product,
        price: Decimal,
        captured_at: datetime | None = None,
    ) -> "PriceSnapshot":
        return cls(
            product_id=product.id,
            product_name=product.name,
            category=product.category,
            currency=product.currency,
            price=price,
            captured_at=captured_at or datetime.now(tz=timezone.utc),
            source_type=product.source.type if product.source else None,
        )


@dataclass(slots=True, frozen=True)
class SourcePrice:
    store_name: str
    product_url: str
    price: Decimal
    currency: str


@dataclass(slots=True, frozen=True)
class ProductPriceReport:
    product: Product
    quotes: tuple[SourcePrice, ...]

    @property
    def average_price(self) -> Decimal:
        total = sum((quote.price for quote in self.quotes), start=Decimal("0"))
        average = total / Decimal(len(self.quotes))
        return average.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


@dataclass(slots=True, frozen=True)
class ProductPriceCheckOutcome:
    product: Product
    report: ProductPriceReport | None = None
    error: str | None = None
