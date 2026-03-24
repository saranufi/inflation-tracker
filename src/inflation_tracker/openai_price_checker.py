from __future__ import annotations

import json
from decimal import Decimal
from types import ModuleType
from pathlib import Path
from urllib.parse import urlparse

from inflation_tracker.models import Product, ProductPriceReport, SourcePrice


class OpenAIPriceChecker:
    def __init__(
        self,
        *,
        client: object | None = None,
        settings_path: str | Path = "config/openai.json",
        model: str | None = None,
        reasoning_effort: str | None = None,
    ) -> None:
        self.settings_path = Path(settings_path)
        settings = self._load_settings(self.settings_path)
        location = settings["location"]
        self.api_key = str(settings["api_key"])
        self.model = model or str(settings.get("model", "gpt-5-mini"))
        self.reasoning_effort = reasoning_effort or str(
            settings.get("reasoning_effort", "low")
        )
        self.country = str(location["country"])
        self.city = str(location["city"])
        self.region = str(location["region"])
        self.timezone = str(location["timezone"])
        self.client = client or self._build_client()

    def check_products(self, products: list[Product]) -> list[ProductPriceReport]:
        return [self.check_product(product) for product in products]

    def check_product(self, product: Product) -> ProductPriceReport:
        response = self.client.responses.create(
            model=self.model,
            reasoning={"effort": self.reasoning_effort},
            tools=[
                {
                    "type": "web_search",
                    "user_location": {
                        "type": "approximate",
                        "country": self.country,
                        "city": self.city,
                        "region": self.region,
                        "timezone": self.timezone,
                    },
                }
            ],
            tool_choice="auto",
            input=[
                {
                    "role": "system",
                    "content": (
                        "You are a price lookup assistant. Use web search to find current "
                        "prices for the exact product and package size requested. "
                        "Return JSON only. Prefer direct product pages, use three different "
                        "domains, and do not invent prices."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Find 3 current prices in {product.currency} for '{product.name}' "
                        f"in {self.country}. Match the exact size/variant as closely as possible. "
                        "Return exactly 3 quotes from different sources."
                    ),
                },
            ],
            text={"format": self._response_format()},
        )
        payload = json.loads(response.output_text)
        return self._build_report(product, payload)

    def _build_report(self, product: Product, payload: dict[str, object]) -> ProductPriceReport:
        raw_quotes = payload.get("quotes")
        if not isinstance(raw_quotes, list) or len(raw_quotes) != 3:
            raise ValueError(f"OpenAI did not return exactly 3 quotes for '{product.name}'.")

        quotes: list[SourcePrice] = []
        domains: set[str] = set()

        for raw_quote in raw_quotes:
            if not isinstance(raw_quote, dict):
                raise ValueError(f"Invalid quote payload returned for '{product.name}'.")

            currency = str(raw_quote["currency"]).upper()
            if currency != product.currency.upper():
                raise ValueError(
                    f"Expected {product.currency} prices for '{product.name}', got {currency}."
                )

            url = str(raw_quote["product_url"])
            domain = urlparse(url).netloc.lower()
            if not domain:
                raise ValueError(f"Invalid URL returned for '{product.name}': {url}")
            domains.add(domain)

            quotes.append(
                SourcePrice(
                    store_name=str(raw_quote["store_name"]),
                    product_url=url,
                    price=Decimal(str(raw_quote["price"])),
                    currency=currency,
                )
            )

        if len(domains) != 3:
            raise ValueError(
                f"OpenAI did not return 3 distinct source domains for '{product.name}'."
            )

        return ProductPriceReport(product=product, quotes=tuple(quotes))

    def _build_client(self) -> object:
        openai_module = self._load_openai_module()
        return openai_module.OpenAI(api_key=self.api_key)

    @staticmethod
    def _load_openai_module() -> ModuleType:
        try:
            import openai
        except ImportError as exc:
            raise RuntimeError(
                "The 'openai' package is not installed. Run 'pip install -e .' after updating dependencies."
            ) from exc
        return openai

    @staticmethod
    def _response_format() -> dict[str, object]:
        return {
            "type": "json_schema",
            "name": "product_price_quotes",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "product_name": {"type": "string"},
                    "quotes": {
                        "type": "array",
                        "minItems": 3,
                        "maxItems": 3,
                        "items": {
                            "type": "object",
                            "properties": {
                                "store_name": {"type": "string"},
                                "product_url": {"type": "string"},
                                "price": {"type": "number"},
                                "currency": {"type": "string"},
                            },
                            "required": [
                                "store_name",
                                "product_url",
                                "price",
                                "currency",
                            ],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["product_name", "quotes"],
                "additionalProperties": False,
            },
        }

    @staticmethod
    def _load_settings(settings_path: Path) -> dict[str, object]:
        candidate_paths = [settings_path]
        local_override = settings_path.with_name("openai.local.json")
        if local_override != settings_path:
            candidate_paths.insert(0, local_override)

        selected_path: Path | None = None
        for candidate in candidate_paths:
            if candidate.exists():
                selected_path = candidate
                break

        if selected_path is None:
            raise RuntimeError(
                "OpenAI config file not found. Create 'config/openai.json' or 'config/openai.local.json'."
            )

        settings = json.loads(selected_path.read_text(encoding="utf-8"))
        api_key = str(settings.get("api_key", "")).strip()
        if not api_key or api_key == "replace-with-your-openai-api-key":
            raise RuntimeError(
                f"Set a real OpenAI API key in '{selected_path.as_posix()}'."
            )

        location = settings.get("location")
        if not isinstance(location, dict):
            raise RuntimeError(
                f"OpenAI config '{selected_path.as_posix()}' is missing the 'location' object."
            )

        required_location_keys = {"country", "city", "region", "timezone"}
        missing_location_keys = [
            key for key in required_location_keys if not str(location.get(key, "")).strip()
        ]
        if missing_location_keys:
            missing = ", ".join(sorted(missing_location_keys))
            raise RuntimeError(
                f"OpenAI config '{selected_path.as_posix()}' is missing location fields: {missing}."
            )

        return settings
