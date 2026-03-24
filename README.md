# Inflation Tracker

Skeleton Python project for tracking the prices of predefined products over time.

## What this scaffold includes

- A small CLI for loading a product catalog and collecting price snapshots
- A standard-library-only runtime
- JSONL storage for historical price records
- Docker and Docker Compose support
- A provider interface so real scrapers or APIs can be added later

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
│   ├── providers/
│   │   ├── base.py
│   │   └── manual.py
│   └── storage.py
└── tests/
```

## Product catalog

The default catalog is metadata-only. It defines which products to track without storing prices in the JSON file.
Later you can add providers for retailer APIs, HTML scraping, or browser automation.

Example product entry:

```json
{
  "market": "Kuwait",
  "currency": "KWD",
  "products": [
    {
      "id": "almarai-fresh-milk-1l",
      "name": "Almarai Fresh Milk 1L",
      "category": "dairy"
    }
  ]
}
```

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
python -m inflation_tracker list-products --config config/products.json
python -m unittest discover -s tests
```

`collect` still works for products that have a configured `source`, but the default catalog intentionally omits pricing data and provider configuration.

To use OpenAI for price checks, put your key in `config/openai.json`:

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
python -m inflation_tracker check-prices --config config/products.json
```

If you do not want to commit secrets, create `config/openai.local.json` instead. The code prefers that file over `config/openai.json`, and it is ignored by git.

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

- Add real providers under `src/inflation_tracker/providers/`
- Replace JSONL storage with SQLite or Postgres if you need querying
- Schedule regular collections with cron, GitHub Actions, or a job runner
