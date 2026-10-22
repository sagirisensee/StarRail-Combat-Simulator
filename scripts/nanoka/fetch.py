"""
Nanoka 4.6 Data Fetcher
Downloads raw snapshot from https://static.nanoka.cc/hsr/4.6/
Version locked to 4.6 (Official Live Release).
"""

import asyncio
import json
import os
import sys
from pathlib import Path
import urllib.request

BASE_URL = "https://static.nanoka.cc/hsr/4.6"
VERSION = "4.6"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
RAW_DIR = ROOT_DIR / "data" / "nanoka" / "raw" / VERSION
MANIFEST_DIR = ROOT_DIR / "data" / "nanoka" / "manifests"


def download_json_sync(url: str, output_path: Path, refresh: bool = False) -> dict | None:
    if output_path.exists() and not refresh:
        try:
            with open(output_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            content = resp.read()
            data = json.loads(content.decode("utf-8"))
            output_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = output_path.with_suffix(".tmp")
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            temp_path.replace(output_path)
            return data
    except Exception as e:
        print(f"[ERROR] Failed to fetch {url}: {e}", file=sys.stderr)
        return None


async def download_json_async(semaphore: asyncio.Semaphore, url: str, output_path: Path, refresh: bool = False):
    async with semaphore:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, download_json_sync, url, output_path, refresh)


async def main():
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)

    print(f"=== Fetching Nanoka HSR Version {VERSION} ===")

    # 1. Fetch index tables
    relicset_url = f"{BASE_URL}/relicset.json"
    relicset_path = RAW_DIR / "relicset.json"
    relicset_data = download_json_sync(relicset_url, relicset_path)
    if not relicset_data:
        raise RuntimeError("Failed to fetch relicset.json")
    print(f"✓ relicset.json fetched: {len(relicset_data)} sets")

    lightcone_url = f"{BASE_URL}/lightcone.json"
    lightcone_path = RAW_DIR / "lightcone.json"
    lightcone_data = download_json_sync(lightcone_url, lightcone_path)
    if not lightcone_data:
        raise RuntimeError("Failed to fetch lightcone.json")
    print(f"✓ lightcone.json fetched: {len(lightcone_data)} lightcones")

    character_url = f"{BASE_URL}/character.json"
    character_path = RAW_DIR / "character.json"
    character_data = download_json_sync(character_url, character_path)
    if not character_data:
        raise RuntimeError("Failed to fetch character.json")
    print(f"✓ character.json fetched: {len(character_data)} characters")

    # 2. Concurrently fetch all lightcone and character details in zh
    sem = asyncio.Semaphore(10)
    tasks = []

    lc_ids = list(lightcone_data.keys())
    lc_detail_dir = RAW_DIR / "zh" / "lightcone"
    for lc_id in lc_ids:
        u = f"{BASE_URL}/zh/lightcone/{lc_id}.json"
        p = lc_detail_dir / f"{lc_id}.json"
        tasks.append(download_json_async(sem, u, p))

    char_ids = list(character_data.keys())
    char_detail_dir = RAW_DIR / "zh" / "character"
    for char_id in char_ids:
        u = f"{BASE_URL}/zh/character/{char_id}.json"
        p = char_detail_dir / f"{char_id}.json"
        tasks.append(download_json_async(sem, u, p))

    print(f"Fetching {len(lc_ids)} lightcone details and {len(char_ids)} character details...")
    await asyncio.gather(*tasks)

    # 3. Create Manifest
    manifest = {
        "source_version": VERSION,
        "source_base_url": BASE_URL,
        "locale": "zh",
        "schema_version": 1,
        "expected_counts": {
            "relic_sets": len(relicset_data),
            "lightcones": len(lightcone_data),
            "characters": len(character_data),
        },
        "lightcone_ids": sorted(lc_ids),
        "character_ids": sorted(char_ids),
    }

    manifest_path = MANIFEST_DIR / f"{VERSION}.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f"✓ Manifest written to {manifest_path}")
    print("=== Fetch complete ===")


if __name__ == "__main__":
    asyncio.run(main())
