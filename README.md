# Inflation Tracker

Python project for tracking a fixed catalog of products over time.

## What this scaffold includes

- A small CLI for loading a product catalog and collecting price snapshots
- Direct retailer-page scraping from predefined product URLs
- Three price-discovery modes: OpenAI search, scrape+OpenAI analysis, and scrape+local-LLM analysis
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
The CLI supports three methods:
- `openai`: OpenAI searches the web and can write discovered `retailer_urls` back out to a file.
- `scrape-openai`: the app fetches the configured retailer pages and OpenAI extracts the price from the page content.
- `scrape-local-llm`: the app fetches the configured retailer pages and your local Ollama model extracts the price from the page content.

`retailer_urls` accepts either objects with `retailer_name` and `url`, or plain URL strings where the retailer name is inferred from the domain.

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

Both scrape-based modes require each product to have at least one configured `retailer_urls` entry.
The default catalog ships with empty arrays so you can fill in the URLs gradually.

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
The generated file contains the successful `retailer_urls` found by OpenAI and excludes
`carrefourkuwait.com` results. The OpenAI flow accepts 1 to 3 quotes per product and
keeps only quotes priced in `KWD`; other currencies are ignored.

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
