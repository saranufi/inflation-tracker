from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP


@dataclass(slots=True, frozen=True)
class RetailerProductUrl:
    retailer_name: str
    url: str


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
    retailer_urls: tuple[RetailerProductUrl, ...] = ()
    source: ProductSource | None = None


@dataclass(slots=True, frozen=True)
class PriceSnapshot:
    product_id: str
    product_name: str
    category: str
    currency: str
    price: Decimal
    captured_at: datetime
    collection_method: str
    quote_count: int
    quotes: tuple["SourcePrice", ...]

    @classmethod
    def create(
        cls,
        *,
        report: "ProductPriceReport",
        collection_method: str,
        captured_at: datetime | None = None,
    ) -> "PriceSnapshot":
        return cls(
            product_id=report.product.id,
            product_name=report.product.name,
            category=report.product.category,
            currency=report.product.currency,
            price=report.average_price,
            captured_at=captured_at or datetime.now(tz=timezone.utc),
            collection_method=collection_method,
            quote_count=len(report.quotes),
            quotes=report.quotes,
        )


@dataclass(slots=True, frozen=True)
class SourcePrice:
    store_name: str
    product_url: str
    price: Decimal
    currency: str


@dataclass(slots=True, frozen=True)
class PriceAttempt:
    store_name: str
    product_url: str
    price: Decimal | None = None
    currency: str | None = None
    error: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.error is None and self.price is not None


@dataclass(slots=True, frozen=True)
class ProductPriceReport:
    product: Product
    quotes: tuple[SourcePrice, ...]
    attempts: tuple[PriceAttempt, ...] = ()

    @property
    def display_attempts(self) -> tuple[PriceAttempt, ...]:
        if self.attempts:
            return self.attempts
        return tuple(
            PriceAttempt(
                store_name=quote.store_name,
                product_url=quote.product_url,
                price=quote.price,
                currency=quote.currency,
            )
            for quote in self.quotes
        )

    @property
    def average_price(self) -> Decimal:
        if not self.quotes:
            raise ValueError(f"No quotes were collected for '{self.product.name}'.")
        total = sum((quote.price for quote in self.quotes), start=Decimal("0"))
        average = total / Decimal(len(self.quotes))
        return average.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


@dataclass(slots=True, frozen=True)
class ProductPriceCheckOutcome:
    product: Product
    report: ProductPriceReport | None = None
    error: str | None = None
