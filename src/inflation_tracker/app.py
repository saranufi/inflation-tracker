from __future__ import annotations

from collections.abc import Iterable, Iterator

from inflation_tracker.config import load_products
from inflation_tracker.models import PriceSnapshot, Product
from inflation_tracker.models import ProductPriceCheckOutcome, ProductPriceReport
from inflation_tracker.openai_price_checker import OpenAIPriceChecker
from inflation_tracker.providers.base import PriceProvider
from inflation_tracker.providers.manual import ManualPriceProvider
from inflation_tracker.storage import SnapshotStorage


class InflationTrackerApp:
    def __init__(self, config_path: str, data_dir: str) -> None:
        self.config_path = config_path
        self.data_dir = data_dir

    def list_products(self) -> list[Product]:
        return load_products(self.config_path)

    def build_openai_price_checker(self) -> OpenAIPriceChecker:
        return OpenAIPriceChecker()

    def check_prices(self) -> list[ProductPriceReport]:
        return [
            outcome.report
            for outcome in self.iter_price_checks()
            if outcome.report is not None
        ]

    def iter_price_checks(
        self,
        *,
        products: Iterable[Product] | None = None,
        checker: OpenAIPriceChecker | None = None,
    ) -> Iterator[ProductPriceCheckOutcome]:
        product_list = list(products) if products is not None else load_products(self.config_path)
        price_checker = checker or self.build_openai_price_checker()

        for product in product_list:
            try:
                yield ProductPriceCheckOutcome(
                    product=product,
                    report=price_checker.check_product(product),
                )
            except Exception as exc:
                yield ProductPriceCheckOutcome(product=product, error=str(exc))

    def collect(self) -> list[PriceSnapshot]:
        products = load_products(self.config_path)
        storage = SnapshotStorage(self.data_dir)
        snapshots: list[PriceSnapshot] = []

        for product in products:
            provider = self._build_provider(product)
            price = provider.fetch_price(product)
            snapshots.append(PriceSnapshot.create(product=product, price=price))

        storage.append(snapshots)
        return snapshots

    @staticmethod
    def _build_provider(product: Product) -> PriceProvider:
        if product.source is None:
            raise ValueError(
                f"Product '{product.id}' has no source configured. "
                "The catalog is metadata-only, so add a provider source before collecting prices."
            )
        if product.source.type == "manual":
            return ManualPriceProvider()
        raise ValueError(
            f"Unsupported source type '{product.source.type}' for product '{product.id}'."
        )
