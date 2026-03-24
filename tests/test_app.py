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
from inflation_tracker.openai_price_checker import OpenAIPriceChecker


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
            self.assertIsNone(products[0].source)

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
                                "source": {"type": "manual", "price": 2.75},
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            app = InflationTrackerApp(str(config_path), str(data_dir))
            snapshots = app.collect()

            self.assertEqual(len(snapshots), 1)
            self.assertTrue((data_dir / "price_history.jsonl").exists())
            self.assertTrue((data_dir / "latest_prices.json").exists())

    def test_collect_requires_configured_source(self) -> None:
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
                        ]
                    }
                ),
                encoding="utf-8",
            )

            app = InflationTrackerApp(str(config_path), str(data_dir))

            with self.assertRaisesRegex(ValueError, "has no source configured"):
                app.collect()

    def test_parser_accepts_shared_options_after_subcommand(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            ["collect", "--config", "config/products.json", "--data-dir", "data"]
        )

        self.assertEqual(args.command, "collect")
        self.assertEqual(args.config, "config/products.json")
        self.assertEqual(args.data_dir, "data")

    def test_parser_supports_check_prices_command(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["check-prices", "--config", "config/products.json"])

        self.assertEqual(args.command, "check-prices")

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

    def test_openai_price_checker_parses_three_quotes_and_average(self) -> None:
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
                            "product_url": "https://example-b.test/product",
                            "price": 0.55,
                            "currency": "KWD",
                        },
                        {
                            "store_name": "Store C",
                            "product_url": "https://example-c.test/product",
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

    def test_iter_price_checks_continues_after_error(self) -> None:
        products = load_products(Path("config/products.json"))[:2]

        class DummyChecker:
            def __init__(self) -> None:
                self.calls = 0

            def check_product(self, product):  # type: ignore[no-untyped-def]
                self.calls += 1
                if self.calls == 1:
                    return SimpleNamespace(
                        product=product,
                        quotes=(),
                        average_price=Decimal("1.000"),
                    )
                raise ValueError("temporary failure")

        app = InflationTrackerApp("config/products.json", "data")
        outcomes = list(app.iter_price_checks(products=products, checker=DummyChecker()))

        self.assertEqual(len(outcomes), 2)
        self.assertIsNotNone(outcomes[0].report)
        self.assertIsNone(outcomes[0].error)
        self.assertIsNone(outcomes[1].report)
        self.assertEqual(outcomes[1].error, "temporary failure")


if __name__ == "__main__":
    unittest.main()
