# Inflation Tracker

Python project for tracking a fixed catalog of products over time.

## What this scaffold includes

- A small CLI for loading a product catalog and collecting price snapshots
- Direct retailer-page scraping from predefined product URLs
- Three price-discovery modes: OpenAI search, scrape+OpenAI analysis, and scrape+local-LLM analysis
- Per-retailer output with fallback URLs and `No Match` reporting
- JSONL storage for historical price records
- Docker and Docker Compose support

## Project layout

```text
.
├── config/
│   └── products.json
├── data/
├── src/inflation_tracker/
│   ├── cli.py
│   ├── app.py
│   ├── config.py
│   ├── models.py
│   ├── openai_price_checker.py
│   ├── page_price_analyzers.py
│   ├── scraper_price_checker.py
│   └── storage.py
└── tests/
```

## Product catalog

Each product can define up to 3 fixed retailer product URLs.
`retailer_urls` accepts either objects with `retailer_name` and `url`, or plain URL strings where the retailer name is inferred from the domain.

For the scrape-based methods, configured URLs are treated as human-verified product pages.
That means the scraper will trust the URL and focus on extracting the displayed price even if
the retailer page title does not exactly match the catalog name.

Example product entry:

```json
{
  "market": "Kuwait",
  "currency": "KWD",
  "products": [
    {
      "id": "almarai-fresh-milk-1l",
      "name": "Almarai Fresh Milk 1L",
      "category": "dairy",
      "retailer_urls": [
        {
          "retailer_name": "Retailer A",
          "url": "https://example.com/product-page"
        },
        {
          "retailer_name": "Retailer B",
          "url": "https://example.com/product-page"
        },
        {
          "retailer_name": "Retailer C",
          "url": "https://example.com/product-page"
        }
      ]
    }
  ]
}
```

Shorthand is also valid:

```json
{
  "id": "almarai-fresh-milk-1l",
  "name": "Almarai Fresh Milk 1L",
  "category": "dairy",
  "retailer_urls": [
    "https://gcc.luluhypermarket.com/en-kw/almarai-fresh-milk-full-fat-1-litre/p/7549",
    "https://kuwait.grandhyper.com/Almarai-Fresh-Milk-Full-Fat-1Ltr",
    "https://www.talabat.com/kuwait/talabat-mart/product/almarai-fresh-milk/s/example"
  ]
}
```

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
python -m inflation_tracker list-products --config config/products.json
python -m inflation_tracker check-prices --config config/products.json --method scrape-openai
python -m inflation_tracker collect --config config/products.json --method scrape-openai
python -m unittest discover -s tests
```

## Price discovery modes

- `openai`: OpenAI performs the search, returns 1 to 3 KWD quotes from different domains, and can export the discovered retailer URLs to a `products.json`-compatible file.
- `scrape-openai`: the app fetches the configured retailer pages from `retailer_urls` and asks OpenAI to extract the price from each page.
- `scrape-local-llm`: the app fetches the configured retailer pages from `retailer_urls` and asks your local Ollama model to extract the price from each page.

Both scrape-based modes require each product to have at least one configured `retailer_urls` entry.
The default catalog ships with empty arrays so you can fill in the URLs gradually.
Scrape-based modes always use the URLs in your config file exactly as written.

To use either OpenAI-based mode, put your key in `config/openai.json`:

```json
{
  "api_key": "your_key_here",
  "model": "gpt-5-mini",
  "reasoning_effort": "low",
  "location": {
    "country": "KW",
    "city": "Kuwait City",
    "region": "Al Asimah",
    "timezone": "Asia/Kuwait"
  }
}
```

Then run:

```bash
python -m inflation_tracker check-prices --config config/products.json --method openai
python -m inflation_tracker collect --config config/products.json --method openai
python -m inflation_tracker check-prices --config config/products.json --method scrape-openai
python -m inflation_tracker collect --config config/products.json --method scrape-openai
```

When `--method openai` is used, the app also writes a products.json-compatible file at
`data/openai_discovered_products.json` by default. Override that path with `--catalog-output`.
The generated file contains the successful `retailer_urls` found by OpenAI so you can review it
and replace your main `config/products.json` if you want to switch to scrape-based collection.

The OpenAI discovery flow:

- accepts 1 to 3 quotes per product
- keeps only quotes priced in `KWD`
- ignores quotes in other currencies
- filters blocked domains such as `carrefourkuwait.com`, `ananinja.com`, `supermarket.kanbkam.com`, and `kanbkam.com`

If you do not want to commit secrets, create `config/openai.local.json` instead. The code prefers that file over `config/openai.json`, and it is ignored by git.

To use your local Ollama model for page analysis, edit `config/local_llm.json`:

```json
{
  "base_url": "http://localhost:11434",
  "model": "gpt-oss:20b",
  "temperature": 0.1,
  "num_ctx": 16384
}
```

Then run:

```bash
python -m inflation_tracker check-prices --config config/products.json --method scrape-local-llm
python -m inflation_tracker collect --config config/products.json --method scrape-local-llm
```

## CLI output

`check-prices` prints each retailer attempt separately. If one URL fails, the next configured
URL is still tried. When a page fetch or analysis does not produce a usable price, the output
includes the retailer name and URL so you can inspect the failed page directly.

Example:

```text
AlWazzan Fine Sugar 5kg
  Talabat: No Match | https://www.talabat.com/kuwait/talabat-mart/product/al-wazzan-sugar-5kg/s/908815
  Lulu Hypermarket: 1.350 KWD | https://gcc.luluhypermarket.com/ar-kw/al-wazzan-premium-quality-sugar-5-kg/p/439239/
  Average: 1.350 KWD
```

## Run with Docker

```bash
docker build -t inflation-tracker .
docker run --rm \
  -v "$(pwd)/config:/app/config" \
  -v "$(pwd)/data:/app/data" \
  inflation-tracker
```

Or with Compose:

```bash
docker compose up --build
```

## Next steps

- Populate `retailer_urls` with the three fixed URLs you want to track per product
- Replace JSONL storage with SQLite or Postgres if you need querying
- Schedule regular collections with cron, GitHub Actions, or a job runner
