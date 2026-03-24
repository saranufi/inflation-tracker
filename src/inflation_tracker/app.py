from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from pathlib import Path

from inflation_tracker.config import load_products
from inflation_tracker.models import PriceSnapshot, Product
from inflation_tracker.models import ProductPriceCheckOutcome, ProductPriceReport
from inflation_tracker.openai_price_checker import OpenAIPriceChecker
from inflation_tracker.scraper_price_checker import RetailerScraperPriceChecker
from inflation_tracker.storage import SnapshotStorage


class InflationTrackerApp:
    def __init__(self, config_path: str, data_dir: str) -> None:
        self.config_path = config_path
        self.data_dir = data_dir

    def list_products(self) -> list[Product]:
        return load_products(self.config_path)

    def build_openai_price_checker(self) -> OpenAIPriceChecker:
        return OpenAIPriceChecker()

    def build_scraper_price_checker(self) -> RetailerScraperPriceChecker:
        return RetailerScraperPriceChecker()

    def build_price_checker(self, method: str) -> OpenAIPriceChecker | RetailerScraperPriceChecker:
        if method == "scrape":
            return self.build_scraper_price_checker()
        if method == "openai":
            return self.build_openai_price_checker()
        raise ValueError(f"Unsupported price discovery method '{method}'.")

    def check_prices(self, *, method: str = "scrape") -> list[ProductPriceReport]:
        return [
            outcome.report
            for outcome in self.iter_price_checks(method=method)
            if outcome.report is not None
        ]

    def iter_price_checks(
        self,
        *,
        method: str = "scrape",
        products: Iterable[Product] | None = None,
        checker: OpenAIPriceChecker | RetailerScraperPriceChecker | None = None,
    ) -> Iterator[ProductPriceCheckOutcome]:
        product_list = list(products) if products is not None else load_products(self.config_path)
        price_checker = checker or self.build_price_checker(method)

        for product in product_list:
            try:
                yield ProductPriceCheckOutcome(
                    product=product,
                    report=price_checker.check_product(product),
                )
            except Exception as exc:
                yield ProductPriceCheckOutcome(product=product, error=str(exc))

    def collect(self, *, method: str = "scrape") -> list[PriceSnapshot]:
        products = load_products(self.config_path)
        storage = SnapshotStorage(self.data_dir)
        checker = self.build_price_checker(method)
        snapshots: list[PriceSnapshot] = []

        for product in products:
            report = checker.check_product(product)
            snapshots.append(
                PriceSnapshot.create(
                    report=report,
                    collection_method=method,
                )
            )

        storage.append(snapshots)
        return snapshots

    def write_discovered_catalog_from_reports(
        self,
        *,
        reports: Iterable[ProductPriceReport],
        output_path: str | Path,
    ) -> Path:
        discovered_urls = {
            report.product.id: tuple(quote.product_url for quote in report.quotes)
            for report in reports
        }
        return self._write_discovered_catalog(
            discovered_urls_by_product_id=discovered_urls,
            output_path=output_path,
        )

    def write_discovered_catalog_from_snapshots(
        self,
        *,
        snapshots: Iterable[PriceSnapshot],
        output_path: str | Path,
    ) -> Path:
        discovered_urls = {
            snapshot.product_id: tuple(quote.product_url for quote in snapshot.quotes)
            for snapshot in snapshots
        }
        return self._write_discovered_catalog(
            discovered_urls_by_product_id=discovered_urls,
            output_path=output_path,
        )

    def _write_discovered_catalog(
        self,
        *,
        discovered_urls_by_product_id: dict[str, tuple[str, ...]],
        output_path: str | Path,
    ) -> Path:
        config_data = json.loads(Path(self.config_path).read_text(encoding="utf-8"))
        products = self.list_products()
        default_currency = config_data.get("currency", "USD")

        payload: dict[str, object] = {
            "currency": default_currency,
            "products": [],
        }
        if "market" in config_data:
            payload["market"] = config_data["market"]

        serialized_products: list[dict[str, object]] = []
        for product in products:
            product_payload: dict[str, object] = {
                "id": product.id,
                "name": product.name,
                "category": product.category,
                "retailer_urls": list(discovered_urls_by_product_id.get(product.id, ())),
            }
            if product.currency != default_currency:
                product_payload["currency"] = product.currency
            serialized_products.append(product_payload)

        payload["products"] = serialized_products

        destination = Path(output_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(payload, indent=2, ensure_ascii=True),
            encoding="utf-8",
        )
        return destination
