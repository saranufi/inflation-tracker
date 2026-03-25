from __future__ import annotations

import json
import re
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from inflation_tracker.models import Product, RetailerProductUrl
from inflation_tracker.openai_price_checker import OpenAIPriceChecker
from inflation_tracker.scraper_price_checker import ExtractedPrice


_RELAXED_MATCHING_GUIDANCE = (
    "Treat the page as a valid match when the brand, product type, and package size align, "
    "even if the retailer title is not an exact string match. Minor naming differences, "
    "word order changes, punctuation changes, and closely related variant wording are acceptable. "
    "For example, a requested product like 'Almarai Natural Honey 500g' can still match a page "
    "title like 'Almarai Polyflora Honey, 500g' if the page evidence strongly suggests it is the "
    "same branded 500g honey product. Only reject the match when the brand, product type, size, "
    "or variant clearly conflicts."
)
_CONFIGURED_URL_TRUST_GUIDANCE = (
    "The retailer URL was manually configured and human-verified for this product. "
    "Assume the priced item on the page is the requested product, even if the page title, "
    "variant wording, or naming style differs from the configured product name. "
    "Do not reject the page because of a name mismatch. Focus on extracting the current "
    "displayed selling price from the page."
)


class OpenAIPagePriceAnalyzer:
    def __init__(
        self,
        *,
        client: object | None = None,
        settings_path: str | Path = "config/openai.json",
        model: str | None = None,
        reasoning_effort: str | None = None,
    ) -> None:
        self.settings_path = Path(settings_path)
        settings = OpenAIPriceChecker._load_settings(self.settings_path)
        self.api_key = str(settings["api_key"])
        self.model = model or str(settings.get("model", "gpt-5-mini"))
        self.reasoning_effort = reasoning_effort or str(
            settings.get("reasoning_effort", "low")
        )
        self.client = client

    def analyze(
        self,
        *,
        product: Product,
        retailer: RetailerProductUrl,
        html: str,
    ) -> ExtractedPrice:
        page_context = _build_page_context(html)
        client = self.client or self._build_client()
        self.client = client
        response = client.responses.create(
            model=self.model,
            reasoning={"effort": self.reasoning_effort},
            input=[
                {
                    "role": "system",
                    "content": (
                        "You extract product prices from a retailer page that has already "
                        "been fetched. Return JSON only. Do not browse the web. "
                        "The retailer URL is already trusted as the correct product page. "
                        f"{_RELAXED_MATCHING_GUIDANCE} "
                        f"{_CONFIGURED_URL_TRUST_GUIDANCE}"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Retailer: {retailer.retailer_name}\n"
                        f"URL: {retailer.url}\n"
                        f"Product: {product.name}\n"
                        f"Expected currency: {product.currency}\n\n"
                        f"{page_context}"
                    ),
                },
            ],
            text={"format": _page_response_format()},
        )
        payload = json.loads(response.output_text)
        return _build_extracted_price(product=product, payload=payload)

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


class LocalLLMPagePriceAnalyzer:
    def __init__(
        self,
        *,
        settings_path: str | Path = "config/local_llm.json",
        endpoint: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        num_ctx: int | None = None,
    ) -> None:
        self.settings_path = Path(settings_path)
        settings = self._load_settings(self.settings_path)
        self.endpoint = endpoint or str(settings.get("base_url", "http://localhost:11434")).rstrip("/")
        self.model = model or str(settings.get("model", "gpt-oss:20b"))
        self.temperature = (
            float(settings.get("temperature", 0.1))
            if temperature is None
            else temperature
        )
        configured_num_ctx = settings.get("num_ctx")
        self.num_ctx = (
            int(configured_num_ctx)
            if num_ctx is None and configured_num_ctx is not None
            else num_ctx
        )

    def analyze(
        self,
        *,
        product: Product,
        retailer: RetailerProductUrl,
        html: str,
    ) -> ExtractedPrice:
        page_context = _build_page_context(html)
        payload = {
            "model": self.model,
            "stream": False,
            "format": "json",
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You extract product prices from a retailer page that has already "
                        "been fetched. Return JSON only. Do not browse the web. "
                        "The retailer URL is already trusted as the correct product page. "
                        f"{_RELAXED_MATCHING_GUIDANCE} "
                        f"{_CONFIGURED_URL_TRUST_GUIDANCE}"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Retailer: {retailer.retailer_name}\n"
                        f"URL: {retailer.url}\n"
                        f"Product: {product.name}\n"
                        f"Expected currency: {product.currency}\n\n"
                        f"{page_context}\n\n"
                        'Return JSON in this shape: {"matched_product": true|false, "price": number|null, "currency": string|null}.'
                    ),
                },
            ],
            "options": {
                "temperature": self.temperature,
            },
        }
        if self.num_ctx is not None:
            payload["options"]["num_ctx"] = self.num_ctx

        request = Request(
            f"{self.endpoint}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=60) as response:
                response_payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise RuntimeError(f"Ollama returned HTTP {exc.code}.") from exc
        except URLError as exc:
            raise RuntimeError(f"Could not reach Ollama: {exc.reason}") from exc

        message = response_payload.get("message")
        if not isinstance(message, dict):
            raise RuntimeError("Ollama response is missing the 'message' object.")
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("Ollama response did not contain JSON content.")

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Ollama did not return valid JSON.") from exc
        return _build_extracted_price(product=product, payload=parsed)

    @staticmethod
    def _load_settings(settings_path: Path) -> dict[str, object]:
        if not settings_path.exists():
            raise RuntimeError(
                "Local LLM config file not found. Create 'config/local_llm.json'."
            )
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        model = str(settings.get("model", "")).strip()
        if not model:
            raise RuntimeError(
                f"Local LLM config '{settings_path.as_posix()}' is missing 'model'."
            )
        return settings


def _build_page_context(html: str) -> str:
    normalized_html = re.sub(r"\s+", " ", html).strip()
    html_excerpt = normalized_html[:12000]

    snippets: list[str] = []
    snippet_pattern = re.compile(
        r"(?i).{0,90}(?:price|kwd|kd|د\.ك|offer|sale_price|regular_price).{0,90}"
    )
    for match in snippet_pattern.finditer(normalized_html):
        snippet = match.group(0).strip()
        if snippet in snippets:
            continue
        snippets.append(snippet)
        if len(snippets) == 15:
            break

    snippet_block = "\n".join(f"- {snippet}" for snippet in snippets) or "- none"
    return (
        "Page excerpt:\n"
        f"{html_excerpt}\n\n"
        "Potential price-related snippets:\n"
        f"{snippet_block}"
    )


def _build_extracted_price(
    *,
    product: Product,
    payload: dict[str, object],
) -> ExtractedPrice:
    raw_price = payload.get("price")
    if raw_price is None:
        raise ValueError(f"No price was identified for '{product.name}'.")

    raw_currency = payload.get("currency")
    currency = str(raw_currency).strip().upper() if raw_currency is not None else ""
    if currency and currency != product.currency.upper():
        raise ValueError(
            f"Expected {product.currency} for '{product.name}', got {currency}."
        )

    return ExtractedPrice(
        amount=Decimal(str(raw_price)),
        currency=currency or product.currency,
    )


def _page_response_format() -> dict[str, object]:
    return {
        "type": "json_schema",
        "name": "page_price_analysis",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "matched_product": {"type": "boolean"},
                "price": {
                    "type": ["number", "null"],
                },
                "currency": {
                    "type": ["string", "null"],
                },
            },
            "required": ["matched_product", "price", "currency"],
            "additionalProperties": False,
        },
    }
