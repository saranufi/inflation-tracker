from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from inflation_tracker.models import PriceSnapshot


class SnapshotStorage:
    def __init__(self, data_dir: str | Path) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.history_path = self.data_dir / "price_history.jsonl"
        self.latest_path = self.data_dir / "latest_prices.json"

    def append(self, snapshots: list[PriceSnapshot]) -> None:
        if not snapshots:
            return

        with self.history_path.open("a", encoding="utf-8") as handle:
            for snapshot in snapshots:
                handle.write(json.dumps(self._serialize(snapshot), ensure_ascii=True))
                handle.write("\n")

        latest_payload = {
            snapshot.product_id: self._serialize(snapshot) for snapshot in snapshots
        }
        self.latest_path.write_text(
            json.dumps(latest_payload, indent=2, ensure_ascii=True),
            encoding="utf-8",
        )

    @staticmethod
    def _serialize(snapshot: PriceSnapshot) -> dict[str, object]:
        payload = asdict(snapshot)
        payload["price"] = str(snapshot.price)
        payload["captured_at"] = SnapshotStorage._format_datetime(snapshot.captured_at)
        return payload

    @staticmethod
    def _format_datetime(value: datetime) -> str:
        return value.isoformat()
