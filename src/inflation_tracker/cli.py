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


def add_price_method_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--method",
        choices=("scrape", "openai"),
        default="scrape",
        help="Price discovery method: scrape configured retailer URLs or use OpenAI web search.",
    )


def add_catalog_output_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--catalog-output",
        default="data/openai_discovered_products.json",
        help=(
            "When --method openai is used, write a products.json-compatible catalog "
            "with the successful retailer URLs to this path."
        ),
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
    collect_parser = subparsers.add_parser(
        "collect",
        help="Collect price snapshots and persist them.",
        parents=[shared],
    )
    add_price_method_argument(collect_parser)
    add_catalog_output_argument(collect_parser)

    check_prices_parser = subparsers.add_parser(
        "check-prices",
        help="Fetch product prices and print quotes with an average.",
        parents=[shared],
    )
    add_price_method_argument(check_prices_parser)
    add_catalog_output_argument(check_prices_parser)
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
            print(
                f"{product.id}\t{product.name}\t{product.category}\t"
                f"{product.currency}\t{len(product.retailer_urls)}"
            )
        return 0

    if args.command == "collect":
        try:
            snapshots = app.collect(method=args.method)
        except Exception as exc:
            parser.exit(1, f"Error: {exc}\n")

        exported_catalog_path = None
        if args.method == "openai":
            exported_catalog_path = app.write_discovered_catalog_from_snapshots(
                snapshots=snapshots,
                output_path=str(Path(args.catalog_output)),
            )

        print(f"Collected {len(snapshots)} price snapshot(s).")
        for snapshot in snapshots:
            print(
                f"{snapshot.product_id}\t{snapshot.price}\t"
                f"{snapshot.currency}\t{snapshot.collection_method}\t"
                f"{snapshot.quote_count}\t{snapshot.captured_at.isoformat()}"
            )
        if exported_catalog_path is not None:
            print(
                f"Wrote OpenAI-discovered catalog to {exported_catalog_path.as_posix()}."
            )
        return 0

    if args.command == "check-prices":
        try:
            products = app.list_products()
            checker = app.build_price_checker(args.method)
        except (RuntimeError, ValueError) as exc:
            parser.exit(1, f"Error: {exc}\n")

        print(
            f"Checking {len(products)} product(s) with '{args.method}'. Results will print as they return.\n",
            flush=True,
        )

        success_count = 0
        error_count = 0
        successful_reports = []

        for outcome in app.iter_price_checks(
            method=args.method,
            products=products,
            checker=checker,
        ):
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
            successful_reports.append(report)
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

        if args.method == "openai":
            exported_catalog_path = app.write_discovered_catalog_from_reports(
                reports=successful_reports,
                output_path=str(Path(args.catalog_output)),
            )
            print(
                f"Wrote OpenAI-discovered catalog to {exported_catalog_path.as_posix()}.\n",
                flush=True,
            )

        print(
            f"Completed {len(products)} product(s): {success_count} succeeded, {error_count} failed.",
            flush=True,
        )
        return 0

    parser.error(f"Unknown command: {args.command}")
    return 2
