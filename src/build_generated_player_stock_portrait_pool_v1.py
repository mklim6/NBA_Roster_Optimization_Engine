from __future__ import annotations

import csv
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "generated_player_stock_portraits"
MANIFEST = OUT / "manifest.csv"

API = "https://api.pexels.com/v1/search"
QUERIES = (
    "young man portrait headshot",
    "male portrait headshot",
    "diverse men portrait",
)
TARGET = 120


def slug(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_-]+", "-", value.strip())
    return value.strip("-") or "portrait"


def fetch_json(url: str, key: str) -> dict:
    request = urllib.request.Request(
        url,
        headers={"Authorization": key},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def download(url: str, target: Path) -> None:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "NBA-Franchise-Mode-Stock-Portrait-Setup/1.0"},
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        target.write_bytes(response.read())


def main() -> int:
    key = os.environ.get("PEXELS_API_KEY", "").strip()
    if not key:
        print(
            "PEXELS_API_KEY is not set. Create a free Pexels API key, "
            "set it in this terminal, then run this script again."
        )
        return 2

    OUT.mkdir(parents=True, exist_ok=True)

    seen: set[int] = set()
    rows: list[dict[str, str]] = []

    for query in QUERIES:
        page = 1
        while len(rows) < TARGET and page <= 4:
            params = urllib.parse.urlencode(
                {
                    "query": query,
                    "orientation": "portrait",
                    "size": "medium",
                    "per_page": 80,
                    "page": page,
                }
            )
            payload = fetch_json(f"{API}?{params}", key)
            photos = payload.get("photos", [])
            if not photos:
                break

            for photo in photos:
                photo_id = int(photo.get("id", 0) or 0)
                if photo_id <= 0 or photo_id in seen:
                    continue

                src = photo.get("src", {}) or {}
                image_url = (
                    src.get("medium")
                    or src.get("portrait")
                    or src.get("large")
                )
                if not image_url:
                    continue

                photographer = str(photo.get("photographer", "")).strip()
                source_url = str(photo.get("url", "")).strip()
                ext = ".jpg"
                filename = f"pexels_{photo_id}{ext}"
                target = OUT / filename

                print(
                    f"[{len(rows)+1:03d}/{TARGET}] "
                    f"Downloading Pexels photo {photo_id}..."
                )
                try:
                    download(image_url, target)
                except Exception as exc:
                    print("  skipped:", exc)
                    continue

                seen.add(photo_id)
                rows.append(
                    {
                        "portrait_id": f"pexels-{photo_id}",
                        "file": filename,
                        "photographer": photographer,
                        "source": "Pexels",
                        "source_url": source_url,
                        "license": "Pexels License",
                    }
                )

                if len(rows) >= TARGET:
                    break

            page += 1

        if len(rows) >= TARGET:
            break

    if len(rows) < 20:
        raise RuntimeError(
            f"Only {len(rows)} usable portraits downloaded. "
            "The stock pool was not installed."
        )

    with MANIFEST.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "portrait_id",
                "file",
                "photographer",
                "source",
                "source_url",
                "license",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    print()
    print(f"Installed {len(rows)} stock portraits.")
    print("Manifest:", MANIFEST)
    print()
    print(
        "Generated players are mapped deterministically by player_id. "
        "The app does not infer or store race/ethnicity metadata."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
