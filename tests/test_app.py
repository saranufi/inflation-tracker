from __future__ import annotations

import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from inflation_tracker.app import InflationTrackerApp
from inflation_tracker.cli import build_parser
from inflation_tracker.config import load_products
from inflation_tracker.models import ProductPriceReport, RetailerProductUrl, SourcePrice
from inflation_tracker.openai_price_checker import OpenAIPriceChecker
from inflation_tracker.scraper_price_checker import RetailerScraperPriceChecker


class InflationTrackerAppTests(unittest.TestCase):
    def test_load_products_supports_metadata_only_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "products.json"
            config_path.write_text(
                json.dumps(
                    {
                        "market": "Kuwait",
                        "currency": "KWD",
                        "products": [
                            {
                                "id": "apple-red-usa-1kg",
                                "name": "Apple Red USA 1 kg",
                                "category": "produce",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            products = load_products(config_path)

            self.assertEqual(len(products), 1)
            self.assertEqual(products[0].currency, "KWD")
            self.assertEqual(products[0].retailer_urls, ())
            self.assertIsNone(products[0].source)

    def test_load_products_parses_up_to_three_retailer_urls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "products.json"
            config_path.write_text(
                json.dumps(
                    {
                        "currency": "KWD",
                        "products": [
                            {
                                "id": "milk-1l",
                                "name": "Milk 1L",
                                "category": "dairy",
                                "retailer_urls": [
                                    {
                                        "retailer_name": "Store A",
                                        "url": "https://example-a.test/milk",
                                    },
                                    {
                                        "retailer_name": "Store B",
                                        "url": "https://example-b.test/milk",
                                    },
                                    {
                                        "retailer_name": "Store C",
                                        "url": "https://example-c.test/milk",
                                    },
                                ],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            products = load_products(config_path)

            self.assertEqual(len(products[0].retailer_urls), 3)
            self.assertEqual(products[0].retailer_urls[1].retailer_name, "Store B")

    def test_load_products_accepts_url_string_shorthand(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "products.json"
            config_path.write_text(
                json.dumps(
                    {
                        "currency": "KWD",
                        "products": [
                            {
                                "id": "milk-1l",
                                "name": "Milk 1L",
                                "category": "dairy",
                                "retailer_urls": [
                                    "https://www.carrefourkuwait.com/mafkwt/en/full-fat-milk/almarai-fresh-milk-ff-1l/p/105292",
                                    "https://gcc.luluhypermarket.com/en-kw/almarai-fresh-milk-full-fat-1-litre/p/7549",
                                ],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            products = load_products(config_path)

            self.assertEqual(len(products[0].retailer_urls), 2)
            self.assertEqual(
                products[0].retailer_urls[0].retailer_name,
                "Carrefour Kuwait",
            )
            self.assertEqual(
                products[0].retailer_urls[1].retailer_name,
                "Lulu Hypermarket",
            )

    def test_load_products_rejects_more_than_three_retailer_urls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "products.json"
            config_path.write_text(
                json.dumps(
                    {
                        "currency": "KWD",
                        "products": [
                            {
                                "id": "milk-1l",
                                "name": "Milk 1L",
                                "retailer_urls": [
                                    {"retailer_name": "A", "url": "https://a.test"},
                                    {"retailer_name": "B", "url": "https://b.test"},
                                    {"retailer_name": "C", "url": "https://c.test"},
                                    {"retailer_name": "D", "url": "https://d.test"},
                                ],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "maximum is 3"):
                load_products(config_path)

    def test_collect_persists_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            config_path = tmp_path / "products.json"
            data_dir = tmp_path / "data"

            config_path.write_text(
                json.dumps(
                    {
                        "products": [
                            {
                                "id": "rice-5kg",
                                "name": "Rice 5kg",
                                "category": "groceries",
                                "currency": "KWD",
                                "retailer_urls": [
                                    {
                                        "retailer_name": "Store A",
                                        "url": "https://example-a.test/rice",
                                    },
                                    {
                                        "retailer_name": "Store B",
                                        "url": "https://example-b.test/rice",
                                    },
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            app = InflationTrackerApp(str(config_path), str(data_dir))
            app.build_price_checker = lambda method: DummyChecker()  # type: ignore[method-assign]

            snapshots = app.collect()

            self.assertEqual(len(snapshots), 1)
            self.assertEqual(snapshots[0].price, Decimal("2.875"))
            self.assertEqual(snapshots[0].quote_count, 2)
            self.assertTrue((data_dir / "price_history.jsonl").exists())
            self.assertTrue((data_dir / "latest_prices.json").exists())

    def test_collect_requires_retailer_urls_for_scrape_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            config_path = tmp_path / "products.json"
            data_dir = tmp_path / "data"

            config_path.write_text(
                json.dumps(
                    {
                        "currency": "KWD",
                        "products": [
                            {
                                "id": "tomato-kuwait-1kg",
                                "name": "Tomato Kuwait 1 kg",
                                "category": "produce",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            app = InflationTrackerApp(str(config_path), str(data_dir))

            with self.assertRaisesRegex(ValueError, "no retailer URLs configured"):
                app.collect()

    def test_write_discovered_catalog_from_reports_creates_products_json_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            config_path = tmp_path / "products.json"
            output_path = tmp_path / "generated-products.json"

            config_path.write_text(
                json.dumps(
                    {
                        "market": "Kuwait",
                        "currency": "KWD",
                        "products": [
                            {
                                "id": "milk-1l",
                                "name": "Milk 1L",
                                "category": "dairy",
                            },
                            {
                                "id": "rice-5kg",
                                "name": "Rice 5kg",
                                "category": "pantry",
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            app = InflationTrackerApp(str(config_path), str(tmp_path / "data"))
            product = app.list_products()[0]
            report = ProductPriceReport(
                product=product,
                quotes=(
                    SourcePrice(
                        store_name="Lulu Hypermarket",
                        product_url="https://gcc.luluhypermarket.com/en-kw/milk/p/1",
                        price=Decimal("0.450"),
                        currency="KWD",
                    ),
                    SourcePrice(
                        store_name="Grand Hyper",
                        product_url="https://kuwait.grandhyper.com/milk",
                        price=Decimal("0.470"),
                        currency="KWD",
                    ),
                    SourcePrice(
                        store_name="Talabat",
                        product_url="https://www.talabat.com/kuwait/item/milk",
                        price=Decimal("0.500"),
                        currency="KWD",
                    ),
                ),
            )

            app.write_discovered_catalog_from_reports(
                reports=[report],
                output_path=output_path,
            )

            payload = json.loads(output_path.read_text(encoding="utf-8"))

            self.assertEqual(payload["market"], "Kuwait")
            self.assertEqual(payload["currency"], "KWD")
            self.assertEqual(len(payload["products"]), 2)
            self.assertEqual(
                payload["products"][0]["retailer_urls"],
                [
                    "https://gcc.luluhypermarket.com/en-kw/milk/p/1",
                    "https://kuwait.grandhyper.com/milk",
                    "https://www.talabat.com/kuwait/item/milk",
                ],
            )
            self.assertEqual(payload["products"][1]["retailer_urls"], [])

    def test_parser_accepts_shared_options_after_subcommand(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "collect",
                "--config",
                "config/products.json",
                "--data-dir",
                "data",
                "--method",
                "openai",
                "--catalog-output",
                "data/generated.json",
            ]
        )

        self.assertEqual(args.command, "collect")
        self.assertEqual(args.config, "config/products.json")
        self.assertEqual(args.data_dir, "data")
        self.assertEqual(args.method, "openai")
        self.assertEqual(args.catalog_output, "data/generated.json")

    def test_parser_supports_check_prices_command(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "check-prices",
                "--config",
                "config/products.json",
                "--method",
                "scrape",
            ]
        )

        self.assertEqual(args.command, "check-prices")
        self.assertEqual(args.method, "scrape")

    def test_openai_settings_load_local_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_dir = Path(tmp_dir)
            (config_dir / "openai.json").write_text(
                json.dumps(
                    {
                        "api_key": "replace-with-your-openai-api-key",
                        "model": "gpt-5-mini",
                        "reasoning_effort": "low",
                        "location": {
                            "country": "KW",
                            "city": "Kuwait City",
                            "region": "Al Asimah",
                            "timezone": "Asia/Kuwait",
                        },
                    }
                ),
                encoding="utf-8",
            )
            (config_dir / "openai.local.json").write_text(
                json.dumps(
                    {
                        "api_key": "test-key",
                        "model": "gpt-5-mini",
                        "reasoning_effort": "low",
                        "location": {
                            "country": "KW",
                            "city": "Kuwait City",
                            "region": "Al Asimah",
                            "timezone": "Asia/Kuwait",
                        },
                    }
                ),
                encoding="utf-8",
            )

            fake_client = SimpleNamespace(
                responses=SimpleNamespace(create=lambda **_: None)
            )
            checker = OpenAIPriceChecker(
                client=fake_client, settings_path=config_dir / "openai.json"
            )

            self.assertEqual(checker.api_key, "test-key")

    def test_openai_price_checker_parses_three_kuwait_quotes_and_average(self) -> None:
        product = load_products(Path("config/products.json"))[0]
        fake_response = SimpleNamespace(
            output_text=json.dumps(
                {
                    "product_name": product.name,
                    "quotes": [
                        {
                            "store_name": "Store A",
                            "product_url": "https://example-a.test/product",
                            "price": 0.45,
                            "currency": "KWD",
                        },
                        {
                            "store_name": "Store B",
                            "product_url": "https://gcc.luluhypermarket.com/en-kw/product",
                            "price": 0.55,
                            "currency": "KWD",
                        },
                        {
                            "store_name": "Store C",
                            "product_url": "https://www.talabat.com/kuwait/product",
                            "price": 0.60,
                            "currency": "KWD",
                        },
                    ],
                }
            )
        )
        fake_client = SimpleNamespace(
            responses=SimpleNamespace(create=lambda **_: fake_response)
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            settings_path = Path(tmp_dir) / "openai.json"
            settings_path.write_text(
                json.dumps(
                    {
                        "api_key": "test-key",
                        "model": "gpt-5-mini",
                        "reasoning_effort": "low",
                        "location": {
                            "country": "KW",
                            "city": "Kuwait City",
                            "region": "Al Asimah",
                            "timezone": "Asia/Kuwait",
                        },
                    }
                ),
                encoding="utf-8",
            )

            checker = OpenAIPriceChecker(
                client=fake_client, settings_path=settings_path
            )
            report = checker.check_product(product)

            self.assertEqual(len(report.quotes), 3)
            self.assertEqual(report.average_price, Decimal("0.533"))

    def test_openai_price_checker_accepts_two_kuwait_quotes(self) -> None:
        product = load_products(Path("config/products.json"))[0]
        fake_response = SimpleNamespace(
            output_text=json.dumps(
                {
                    "product_name": product.name,
                    "quotes": [
                        {
                            "store_name": "Store A",
                            "product_url": "https://gcc.luluhypermarket.com/en-kw/product-a",
                            "price": 0.45,
                            "currency": "KWD",
                        },
                        {
                            "store_name": "Store B",
                            "product_url": "https://kuwait.grandhyper.com/product-b",
                            "price": 0.55,
                            "currency": "KWD",
                        },
                    ],
                }
            )
        )
        fake_client = SimpleNamespace(
            responses=SimpleNamespace(create=lambda **_: fake_response)
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            settings_path = Path(tmp_dir) / "openai.json"
            settings_path.write_text(
                json.dumps(
                    {
                        "api_key": "test-key",
                        "model": "gpt-5-mini",
                        "reasoning_effort": "low",
                        "location": {
                            "country": "KW",
                            "city": "Kuwait City",
                            "region": "Al Asimah",
                            "timezone": "Asia/Kuwait",
                        },
                    }
                ),
                encoding="utf-8",
            )

            checker = OpenAIPriceChecker(
                client=fake_client, settings_path=settings_path
            )
            report = checker.check_product(product)

            self.assertEqual(len(report.quotes), 2)
            self.assertEqual(report.average_price, Decimal("0.500"))

    def test_openai_price_checker_ignores_blocked_carrefour_domain(self) -> None:
        product = load_products(Path("config/products.json"))[0]
        fake_response = SimpleNamespace(
            output_text=json.dumps(
                {
                    "product_name": product.name,
                    "quotes": [
                        {
                            "store_name": "Carrefour Kuwait",
                            "product_url": "https://www.carrefourkuwait.com/mafkwt/en/product/p/123",
                            "price": 0.45,
                            "currency": "KWD",
                        },
                        {
                            "store_name": "Store B",
                            "product_url": "https://gcc.luluhypermarket.com/en-kw/product",
                            "price": 0.55,
                            "currency": "KWD",
                        },
                        {
                            "store_name": "Store C",
                            "product_url": "https://kuwait.grandhyper.com/product",
                            "price": 0.60,
                            "currency": "KWD",
                        },
                    ],
                }
            )
        )
        fake_client = SimpleNamespace(
            responses=SimpleNamespace(create=lambda **_: fake_response)
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            settings_path = Path(tmp_dir) / "openai.json"
            settings_path.write_text(
                json.dumps(
                    {
                        "api_key": "test-key",
                        "model": "gpt-5-mini",
                        "reasoning_effort": "low",
                        "location": {
                            "country": "KW",
                            "city": "Kuwait City",
                            "region": "Al Asimah",
                            "timezone": "Asia/Kuwait",
                        },
                    }
                ),
                encoding="utf-8",
            )

            checker = OpenAIPriceChecker(
                client=fake_client, settings_path=settings_path
            )

            report = checker.check_product(product)

            self.assertEqual(len(report.quotes), 2)
            self.assertEqual(
                [quote.store_name for quote in report.quotes],
                ["Store B", "Store C"],
            )

    def test_openai_price_checker_ignores_non_kwd_quote(self) -> None:
        product = load_products(Path("config/products.json"))[0]
        fake_response = SimpleNamespace(
            output_text=json.dumps(
                {
                    "product_name": product.name,
                    "quotes": [
                        {
                            "store_name": "Store A",
                            "product_url": "https://www.some-store.qa/product",
                            "price": 0.45,
                            "currency": "QAR",
                        },
                        {
                            "store_name": "Store B",
                            "product_url": "https://gcc.luluhypermarket.com/en-kw/product",
                            "price": 0.55,
                            "currency": "KWD",
                        },
                        {
                            "store_name": "Store C",
                            "product_url": "https://kuwait.grandhyper.com/product",
                            "price": 0.60,
                            "currency": "KWD",
                        }
                    ],
                }
            )
        )
        fake_client = SimpleNamespace(
            responses=SimpleNamespace(create=lambda **_: fake_response)
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            settings_path = Path(tmp_dir) / "openai.json"
            settings_path.write_text(
                json.dumps(
                    {
                        "api_key": "test-key",
                        "model": "gpt-5-mini",
                        "reasoning_effort": "low",
                        "location": {
                            "country": "KW",
                            "city": "Kuwait City",
                            "region": "Al Asimah",
                            "timezone": "Asia/Kuwait",
                        },
                    }
                ),
                encoding="utf-8",
            )

            checker = OpenAIPriceChecker(
                client=fake_client, settings_path=settings_path
            )

            report = checker.check_product(product)

            self.assertEqual(len(report.quotes), 2)
            self.assertEqual(report.average_price, Decimal("0.575"))

    def test_openai_price_checker_fails_when_no_kwd_quotes_remain(self) -> None:
        product = load_products(Path("config/products.json"))[0]
        fake_response = SimpleNamespace(
            output_text=json.dumps(
                {
                    "product_name": product.name,
                    "quotes": [
                        {
                            "store_name": "Store A",
                            "product_url": "https://www.some-store.qa/product",
                            "price": 1.20,
                            "currency": "QAR",
                        }
                    ],
                }
            )
        )
        fake_client = SimpleNamespace(
            responses=SimpleNamespace(create=lambda **_: fake_response)
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            settings_path = Path(tmp_dir) / "openai.json"
            settings_path.write_text(
                json.dumps(
                    {
                        "api_key": "test-key",
                        "model": "gpt-5-mini",
                        "reasoning_effort": "low",
                        "location": {
                            "country": "KW",
                            "city": "Kuwait City",
                            "region": "Al Asimah",
                            "timezone": "Asia/Kuwait",
                        },
                    }
                ),
                encoding="utf-8",
            )

            checker = OpenAIPriceChecker(
                client=fake_client, settings_path=settings_path
            )

            with self.assertRaisesRegex(ValueError, "did not return any valid KWD quotes"):
                checker.check_product(product)

    def test_scraper_price_checker_extracts_json_ld_price(self) -> None:
        product = load_products(Path("config/products.json"))[0]
        product = product.__class__(
            id=product.id,
            name=product.name,
            category=product.category,
            currency=product.currency,
            retailer_urls=(
                RetailerProductUrl(
                    retailer_name="Store A",
                    url="https://example.test/product",
                ),
            ),
            source=product.source,
        )
        html = """
        <html>
          <head>
            <script type="application/ld+json">
              {
                "@context": "https://schema.org",
                "@type": "Product",
                "name": "Milk 1L",
                "offers": {
                  "@type": "Offer",
                  "priceCurrency": "KWD",
                  "price": "1.250"
                }
              }
            </script>
          </head>
        </html>
        """
        checker = RetailerScraperPriceChecker(fetcher=StaticHtmlFetcher(html))

        report = checker.check_product(product)

        self.assertEqual(report.quotes[0].price, Decimal("1.250"))
        self.assertEqual(report.average_price, Decimal("1.250"))

    def test_iter_price_checks_continues_after_error(self) -> None:
        products = load_products(Path("config/products.json"))[:2]

        app = InflationTrackerApp("config/products.json", "data")
        outcomes = list(app.iter_price_checks(products=products, checker=DummyChecker()))

        self.assertEqual(len(outcomes), 2)
        self.assertIsNotNone(outcomes[0].report)
        self.assertIsNone(outcomes[0].error)
        self.assertIsNone(outcomes[1].report)
        self.assertEqual(outcomes[1].error, "temporary failure")


class DummyChecker:
    def __init__(self) -> None:
        self.calls = 0

    def check_product(self, product):  # type: ignore[no-untyped-def]
        self.calls += 1
        if self.calls == 1:
            return ProductPriceReport(
                product=product,
                quotes=(
                    SourcePrice(
                        store_name="Store A",
                        product_url="https://example-a.test/product",
                        price=Decimal("2.500"),
                        currency=product.currency,
                    ),
                    SourcePrice(
                        store_name="Store B",
                        product_url="https://example-b.test/product",
                        price=Decimal("3.250"),
                        currency=product.currency,
                    ),
                ),
            )
        raise ValueError("temporary failure")


class StaticHtmlFetcher:
    def __init__(self, html: str) -> None:
        self.html = html

    def fetch(self, url: str) -> str:
        return self.html


if __name__ == "__main__":
    unittest.main()
