#!/usr/bin/env python3
"""
Perego Cars — Local Verification Tool
Run this locally to check if your live inventory matches AutoScout24.
"""
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import CACHE_FILE
from fetcher import fetch_listings
from html_generator import format_chf


def main():
    print("Checking AutoScout24 for current inventory...")
    live = fetch_listings()

    if not live:
        print("ERROR: Could not fetch listings.")
        sys.exit(1)

    # Load cached version
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            cached = json.load(f)
    else:
        print("No cached inventory found. Run scrape.py first.")
        sys.exit(1)

    live_map = {item["id"]: item for item in live}
    cached_map = {item["id"]: item for item in cached}

    live_ids = set(live_map.keys())
    cached_ids = set(cached_map.keys())

    added = live_ids - cached_ids
    removed = cached_ids - live_ids
    price_changes = []

    for lid in live_ids & cached_ids:
        if live_map[lid]["price"] != cached_map[lid]["price"]:
            price_changes.append((lid, cached_map[lid]["price"], live_map[lid]["price"]))

    print(f"\n{'=' * 50}")
    print(f"  VERIFICATION — {len(live)} on AutoScout vs {len(cached)} on site")
    print(f"{'=' * 50}")

    if not added and not removed and not price_changes:
        print("  ✓ Everything matches. No update needed.")
    else:
        if added:
            print(f"\n  ⚠ {len(added)} NEW car(s) not on your site:")
            for lid in added:
                car = live_map[lid]
                print(f"    + {car['make']} {car['model']} — {format_chf(car['price'])}")
        if removed:
            print(f"\n  ⚠ {len(removed)} car(s) SOLD (still on site):")
            for lid in removed:
                car = cached_map[lid]
                print(f"    - {car['make']} {car['model']} — {format_chf(car['price'])}")
        if price_changes:
            print(f"\n  ⚠ {len(price_changes)} PRICE change(s):")
            for lid, old_p, new_p in price_changes:
                car = live_map[lid]
                print(f"    ~ {car['make']} {car['model']}: {format_chf(old_p)} -> {format_chf(new_p)}")

        print(f"\n  → Run 'python3 scrape.py' to update.")

    print(f"{'=' * 50}\n")


if __name__ == "__main__":
    main()
