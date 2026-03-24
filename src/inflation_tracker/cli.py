from __future__ import annotations

import argparse
from pathlib import Path

from inflation_tracker.app import InflationTrackerApp


def add_shared_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--config",
        default="config/products.json",
        help="Path to the product catalog JSON file.",
    )
    parser.add_argument(
        "--data-dir",
        default="data",
        help="Directory used to store collected price history.",
    )


def build_parser() -> argparse.ArgumentParser:
    shared = argparse.ArgumentParser(add_help=False)
    add_shared_arguments(shared)

    parser = argparse.ArgumentParser(
        prog="inflation-tracker",
        description="Track prices for a predefined catalog of products.",
        parents=[shared],
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser(
        "list-products",
        help="Print configured products.",
        parents=[shared],
    )
    subparsers.add_parser(
        "collect",
        help="Collect price snapshots and persist them.",
        parents=[shared],
    )
    subparsers.add_parser(
        "check-prices",
        help="Use OpenAI web search to fetch 3 prices and an average for each product.",
        parents=[shared],
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    app = InflationTrackerApp(
        config_path=str(Path(args.config)),
        data_dir=str(Path(args.data_dir)),
    )

    if args.command == "list-products":
        for product in app.list_products():
            source_type = product.source.type if product.source else "-"
            print(
                f"{product.id}\t{product.name}\t{product.category}\t"
                f"{product.currency}\t{source_type}"
            )
        return 0

    if args.command == "collect":
        try:
            snapshots = app.collect()
        except ValueError as exc:
            parser.exit(1, f"Error: {exc}\n")
        print(f"Collected {len(snapshots)} price snapshot(s).")
        for snapshot in snapshots:
            print(
                f"{snapshot.product_id}\t{snapshot.price}\t"
                f"{snapshot.currency}\t{snapshot.captured_at.isoformat()}"
            )
        return 0

    if args.command == "check-prices":
        try:
            products = app.list_products()
            checker = app.build_openai_price_checker()
        except RuntimeError as exc:
            parser.exit(1, f"Error: {exc}\n")

        print(
            f"Checking {len(products)} product(s). Results will print as they return.\n",
            flush=True,
        )

        success_count = 0
        error_count = 0

        for outcome in app.iter_price_checks(products=products, checker=checker):
            print(outcome.product.name, flush=True)

            if outcome.error is not None:
                error_count += 1
                print(f"  Error: {outcome.error}", flush=True)
                print(flush=True)
                continue

            report = outcome.report
            if report is None:
                error_count += 1
                print("  Error: No report returned.", flush=True)
                print(flush=True)
                continue

            success_count += 1
            for quote in report.quotes:
                print(
                    f"  {quote.store_name}: {quote.price} {quote.currency} | "
                    f"{quote.product_url}",
                    flush=True,
                )
            print(
                f"  Average: {report.average_price} {report.product.currency}",
                flush=True,
            )
            print(flush=True)

        print(
            f"Completed {len(products)} product(s): {success_count} succeeded, {error_count} failed.",
            flush=True,
        )
        return 0

    parser.error(f"Unknown command: {args.command}")
    return 2
