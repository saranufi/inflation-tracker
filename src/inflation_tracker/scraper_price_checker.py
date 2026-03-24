from __future__ import annotations

import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from html import unescape
from html.parser import HTMLParser
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from inflation_tracker.models import Product, ProductPriceReport, RetailerProductUrl, SourcePrice


_META_PRICE_KEYS = (
    "product:price:amount",
    "og:price:amount",
    "twitter:data1",
    "price",
)
_META_CURRENCY_KEYS = (
    "product:price:currency",
    "og:price:currency",
    "currency",
)
_JSON_PRICE_KEYS = ("price", "lowPrice")
_CURRENCY_ALIASES = {
    "KWD": {"KWD", "KD", "D.K", "د.ك", "دك"},
}


class HtmlFetcher(Protocol):
    def fetch(self, url: str) -> str:
        raise NotImplementedError


@dataclass(slots=True, frozen=True)
class ExtractedPrice:
    amount: Decimal
    currency: str | None = None


class UrlLibHtmlFetcher:
    def __init__(self, *, timeout_seconds: float = 20.0) -> None:
        self.timeout_seconds = timeout_seconds

    def fetch(self, url: str) -> str:
        request = Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                return response.read().decode(charset, errors="replace")
        except HTTPError as exc:
            raise ValueError(f"HTTP {exc.code} while fetching {url}") from exc
        except URLError as exc:
            raise ValueError(f"Failed to fetch {url}: {exc.reason}") from exc


class RetailerScraperPriceChecker:
    def __init__(self, *, fetcher: HtmlFetcher | None = None) -> None:
        self.fetcher = fetcher or UrlLibHtmlFetcher()

    def check_products(self, products: list[Product]) -> list[ProductPriceReport]:
        return [self.check_product(product) for product in products]

    def check_product(self, product: Product) -> ProductPriceReport:
        if not product.retailer_urls:
            raise ValueError(
                f"Product '{product.id}' has no retailer URLs configured. "
                "Add 1 to 3 'retailer_urls' entries to use scraper mode."
            )

        quotes = tuple(
            self._scrape_retailer_price(product=product, retailer=retailer)
            for retailer in product.retailer_urls
        )
        return ProductPriceReport(product=product, quotes=quotes)

    def _scrape_retailer_price(
        self,
        *,
        product: Product,
        retailer: RetailerProductUrl,
    ) -> SourcePrice:
        html = self.fetcher.fetch(retailer.url)
        extracted = self._extract_price_from_html(
            html=html,
            expected_currency=product.currency,
        )
        return SourcePrice(
            store_name=retailer.retailer_name,
            product_url=retailer.url,
            price=extracted.amount,
            currency=extracted.currency or product.currency,
        )

    def _extract_price_from_html(
        self,
        *,
        html: str,
        expected_currency: str,
    ) -> ExtractedPrice:
        parser = _RetailerPageParser()
        parser.feed(html)

        extracted = self._extract_from_json_ld(
            blocks=parser.json_ld_blocks,
            expected_currency=expected_currency,
        )
        if extracted is None:
            extracted = self._extract_from_meta_tags(
                meta_tags=parser.meta_tags,
                expected_currency=expected_currency,
            )
        if extracted is None:
            extracted = self._extract_from_text(
                html=html,
                expected_currency=expected_currency,
            )
        if extracted is None:
            raise ValueError("Could not find a price in the retailer page.")

        if extracted.currency is not None:
            normalized = self._normalize_currency(extracted.currency)
            expected = self._normalize_currency(expected_currency)
            if normalized != expected:
                raise ValueError(
                    f"Expected currency {expected_currency}, found {extracted.currency}."
                )

        return ExtractedPrice(
            amount=extracted.amount,
            currency=self._normalize_currency(extracted.currency or expected_currency),
        )

    def _extract_from_json_ld(
        self,
        *,
        blocks: list[str],
        expected_currency: str,
    ) -> ExtractedPrice | None:
        for block in blocks:
            block = block.strip()
            if not block:
                continue
            try:
                payload = json.loads(block)
            except json.JSONDecodeError:
                continue

            extracted = self._walk_json_ld(
                node=payload,
                expected_currency=expected_currency,
            )
            if extracted is not None:
                return extracted
        return None

    def _walk_json_ld(
        self,
        *,
        node: object,
        expected_currency: str,
    ) -> ExtractedPrice | None:
        if isinstance(node, list):
            for item in node:
                extracted = self._walk_json_ld(
                    node=item,
                    expected_currency=expected_currency,
                )
                if extracted is not None:
                    return extracted
            return None

        if not isinstance(node, dict):
            return None

        currency = self._coerce_string(
            node.get("priceCurrency") or node.get("pricecurrency") or node.get("currency")
        )
        for key in _JSON_PRICE_KEYS:
            if key in node:
                amount = self._coerce_decimal(node[key])
                if amount is not None and self._currency_matches(
                    detected_currency=currency,
                    expected_currency=expected_currency,
                ):
                    return ExtractedPrice(amount=amount, currency=currency)

        for value in node.values():
            extracted = self._walk_json_ld(
                node=value,
                expected_currency=expected_currency,
            )
            if extracted is not None:
                return extracted
        return None

    def _extract_from_meta_tags(
        self,
        *,
        meta_tags: dict[str, str],
        expected_currency: str,
    ) -> ExtractedPrice | None:
        currency = None
        for key in _META_CURRENCY_KEYS:
            if key in meta_tags:
                currency = meta_tags[key]
                break

        for key in _META_PRICE_KEYS:
            if key not in meta_tags:
                continue
            amount = self._coerce_decimal(meta_tags[key])
            if amount is not None and self._currency_matches(
                detected_currency=currency,
                expected_currency=expected_currency,
            ):
                return ExtractedPrice(amount=amount, currency=currency)
        return None

    def _extract_from_text(
        self,
        *,
        html: str,
        expected_currency: str,
    ) -> ExtractedPrice | None:
        normalized_currency = self._normalize_currency(expected_currency)
        aliases = _CURRENCY_ALIASES.get(normalized_currency, {normalized_currency})
        currency_pattern = "|".join(re.escape(alias) for alias in sorted(aliases))
        patterns = [
            re.compile(
                rf"(?i)(?P<currency>{currency_pattern})\s*(?P<amount>\d[\d,]*(?:\.\d+)?)"
            ),
            re.compile(
                rf"(?i)(?P<amount>\d[\d,]*(?:\.\d+)?)\s*(?P<currency>{currency_pattern})"
            ),
            re.compile(
                r'(?i)"(?:price|sale_price|final_price|regular_price)"\s*:\s*"?(?P<amount>\d[\d,]*(?:\.\d+)?)"?'
            ),
        ]

        text = unescape(html)
        for pattern in patterns:
            match = pattern.search(text)
            if match is None:
                continue
            amount = self._coerce_decimal(match.group("amount"))
            currency = match.groupdict().get("currency")
            if amount is not None and self._currency_matches(
                detected_currency=currency,
                expected_currency=expected_currency,
            ):
                return ExtractedPrice(amount=amount, currency=currency or expected_currency)
        return None

    @staticmethod
    def _coerce_string(value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _coerce_decimal(value: object) -> Decimal | None:
        if value is None:
            return None

        text = str(value).strip()
        if not text:
            return None

        text = unescape(text)
        text = re.sub(r"[^0-9,.\-]", "", text)
        if not text:
            return None

        if text.count(",") and text.count("."):
            if text.rfind(",") > text.rfind("."):
                text = text.replace(".", "")
                text = text.replace(",", ".")
            else:
                text = text.replace(",", "")
        elif text.count(",") == 1 and text.count(".") == 0:
            text = text.replace(",", ".")
        elif text.count(",") > 1 and text.count(".") == 0:
            text = text.replace(",", "")
        else:
            text = text.replace(",", "")

        try:
            return Decimal(text)
        except InvalidOperation:
            return None

    @staticmethod
    def _normalize_currency(value: str) -> str:
        upper_value = str(value).strip().upper()
        for canonical, aliases in _CURRENCY_ALIASES.items():
            if upper_value == canonical or upper_value in {alias.upper() for alias in aliases}:
                return canonical
        return upper_value

    def _currency_matches(
        self,
        *,
        detected_currency: str | None,
        expected_currency: str,
    ) -> bool:
        if detected_currency is None:
            return True
        return self._normalize_currency(detected_currency) == self._normalize_currency(
            expected_currency
        )


class _RetailerPageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta_tags: dict[str, str] = {}
        self.json_ld_blocks: list[str] = []
        self._current_script_type: str | None = None
        self._script_chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {name.lower(): value for name, value in attrs if value is not None}
        if tag.lower() == "meta":
            key = (attr_map.get("property") or attr_map.get("name") or "").lower()
            content = attr_map.get("content")
            if key and content:
                self.meta_tags[key] = content.strip()
            return

        if tag.lower() == "script":
            script_type = attr_map.get("type", "").lower()
            if "ld+json" in script_type:
                self._current_script_type = script_type
                self._script_chunks = []

    def handle_data(self, data: str) -> None:
        if self._current_script_type is not None:
            self._script_chunks.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "script" or self._current_script_type is None:
            return
        self.json_ld_blocks.append("".join(self._script_chunks))
        self._current_script_type = None
        self._script_chunks = []
