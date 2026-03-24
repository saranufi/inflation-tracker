FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV APP_CONFIG=/app/config/products.json
ENV APP_DATA_DIR=/app/data

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY config ./config

RUN pip install --no-cache-dir .

RUN mkdir -p /app/data

CMD ["python", "-m", "inflation_tracker", "list-products", "--config", "/app/config/products.json", "--data-dir", "/app/data"]
