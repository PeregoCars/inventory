#!/usr/bin/env python3
"""
Perego Cars Inventory Generator
================================
Scrapes AutoScout24 HCI listings and generates static HTML pages.

Usage:
    python3 scrape.py           # Full scrape + generate
    python3 scrape.py --force   # Regenerate even if no changes
"""
import sys
import os
import json
import logging
import shutil
import hashlib
from datetime import datetime

# Ensure imports work from any working directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import OUTPUT_DIR, IMAGES_DIR, SOLD_IMAGES_DIR, DETAIL_DIR, CACHE_FILE, LOG_DIR, CUSTOM_JSON, CUSTOM_IMAGES_DIR, SOLD_JSON, MANUAL_JSON, MANUAL_IMAGES_DIR
from fetcher import fetch_listings
from image_handler import download_images, download_sold_images, cleanup_old_images, make_slug
from html_generator import generate_grid_html, generate_detail_pages, generate_sold_detail_pages, format_chf


def setup_logging():
    os.makedirs(LOG_DIR, exist_ok=True)
    log_file = os.path.join(LOG_DIR, "scrape.log")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def load_cache():
    """Load cached inventory from previous run."""
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_cache(listings):
    """Save current inventory to cache."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(listings, f, ensure_ascii=False, indent=2, default=str)


def detect_changes(old_listings, new_listings):
    """Compare inventories. Returns (added, removed, price_changes)."""
    old_map = {item["id"]: item for item in old_listings}
    new_map = {item["id"]: item for item in new_listings}

    added = [new_map[lid] for lid in new_map if lid not in old_map]
    removed = [old_map[lid] for lid in old_map if lid not in new_map]

    price_changes = []
    for lid in new_map:
        if lid in old_map and new_map[lid]["price"] != old_map[lid]["price"]:
            price_changes.append({
                "listing": new_map[lid],
                "old_price": old_map[lid]["price"],
                "new_price": new_map[lid]["price"],
            })

    return added, removed, price_changes


def load_sold():
    """Load sold cars archive."""
    if os.path.exists(SOLD_JSON):
        with open(SOLD_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_sold(sold):
    """Save sold cars archive."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(SOLD_JSON, "w", encoding="utf-8") as f:
        json.dump(sold, f, ensure_ascii=False, indent=2, default=str)


def archive_removed(removed, sold):
    """Move removed listings to sold archive with date stamp."""
    sold_ids = {str(s.get("id")) for s in sold}
    for car in removed:
        if str(car.get("id")) not in sold_ids:
            preserve_sold_images(car)
            car["sold_date"] = datetime.now().strftime("%Y-%m-%d")
            sold.append(car)
            sold_ids.add(str(car.get("id")))
    return sold


def preserve_sold_images(car):
    """Copy a just-sold car's active images before active image cleanup removes them."""
    os.makedirs(SOLD_IMAGES_DIR, exist_ok=True)
    for img_file in car.get("local_images", []):
        src = os.path.join(IMAGES_DIR, img_file)
        dest = os.path.join(SOLD_IMAGES_DIR, img_file)
        if os.path.exists(src) and not os.path.exists(dest):
            shutil.copy2(src, dest)


def repair_sold_images(sold):
    """Restore missing sold image files from saved AutoScout URLs when possible."""
    repaired = 0
    for car in sold:
        local_images = car.get("local_images", [])
        has_missing = any(
            not os.path.exists(os.path.join(SOLD_IMAGES_DIR, img_file))
            for img_file in local_images
        )
        can_add_more = len(car.get("images", [])) > len(local_images)
        if (has_missing or can_add_more) and car.get("images"):
            new_local_images = download_sold_images(car)
            if new_local_images:
                car["local_images"] = new_local_images
                repaired += 1
    return repaired


def remove_active_from_sold(sold, active_listings):
    """Remove cars from sold archive if they are currently active again."""
    active_ids = {str(car.get("id")) for car in active_listings}
    cleaned = [car for car in sold if str(car.get("id")) not in active_ids]
    removed_count = len(sold) - len(cleaned)
    return cleaned, removed_count


def print_summary(listings, added, removed, price_changes):
    """Print a human-readable summary."""
    print("\n" + "=" * 50)
    print(f"  PEREGO CARS — Inventaire {datetime.now().strftime('%d.%m.%Y')}")
    print("=" * 50)

    if added:
        for car in added:
            print(f"  + NOUVEAU : {car['make']} {car['model']} ({car['year']}) — {format_chf(car['price'])}")
    if removed:
        for car in removed:
            print(f"  - VENDU   : {car['make']} {car['model']} ({car['year']})")
    if price_changes:
        for pc in price_changes:
            car = pc["listing"]
            print(f"  ~ PRIX    : {car['make']} {car['model']} ({format_chf(pc['old_price'])} -> {format_chf(pc['new_price'])})")
    if not added and not removed and not price_changes:
        print("  Aucun changement detecte.")

    print(f"\n  Total : {len(listings)} vehicules en inventaire")
    print("=" * 50 + "\n")


# Showroom photo that AutoScout24 listings carry (usually in 2nd position).
# Useful on AutoScout24, redundant on peregocars.com: left out of the site galleries.
SHOWROOM_PHOTO_MD5 = {
    "b1e41cb769304ce76421d5f7a8add035",
    "cc1c2cee76366f1f7ea9d534705ce78e",
}


def drop_showroom_photo(local_images):
    kept = []
    for name in local_images:
        try:
            with open(os.path.join(IMAGES_DIR, name), "rb") as f:
                if hashlib.md5(f.read()).hexdigest() in SHOWROOM_PHOTO_MD5:
                    continue
        except OSError:
            pass
        kept.append(name)
    return kept


def load_manual_listings(as24_ids):
    """Cars shown on the site only (manual_listings.json). An AutoScout24 listing with the same id wins."""
    if not os.path.exists(MANUAL_JSON):
        return []
    with open(MANUAL_JSON, "r", encoding="utf-8") as f:
        entries = json.load(f)
    out = []
    for e in entries:
        lid = str(e.get("id", "")).strip()
        if not lid or lid in as24_ids:
            continue
        car = {"make": "", "model": "", "full_name": "", "price": 0, "mileage": 0, "year": 0,
               "horsepower": 0, "fuel_type": None, "transmission": None, "body_type": "",
               "teaser": "", **e, "id": lid, "images": [], "listing_url": "", "manual": True}
        if not car["full_name"]:
            car["full_name"] = f"{car['make']} {car['model']}".strip()
        out.append(car)
    return out


def copy_manual_images(listing):
    """manual-images/<id>/* (sorted) -> docs/images/<slug>-NN.ext; returns local filenames."""
    src = os.path.join(MANUAL_IMAGES_DIR, listing["id"])
    if not os.path.isdir(src):
        return []
    slug = make_slug(listing["make"], listing["model"], listing["id"])
    files = sorted(f for f in os.listdir(src) if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp")))
    local = []
    for i, name in enumerate(files):
        ext = name.rsplit(".", 1)[1].lower().replace("jpeg", "jpg")
        dest = f"{slug}-{i + 1:02d}.{ext}"
        shutil.copyfile(os.path.join(src, name), os.path.join(IMAGES_DIR, dest))
        local.append(dest)
    return local


def main():
    setup_logging()
    logger = logging.getLogger(__name__)
    logger.info("=" * 50)
    logger.info("Starting inventory scrape")

    force = "--force" in sys.argv

    # 1. Fetch listings
    print("Fetching listings from AutoScout24...")
    listings = fetch_listings()

    if not listings:
        print("ERROR: No listings found. Check logs for details.")
        logger.error("No listings found — aborting")
        sys.exit(1)

    print(f"Found {len(listings)} listings")

    manual = load_manual_listings({str(l["id"]) for l in listings})
    if manual:
        listings.extend(manual)
        print(f"Added {len(manual)} site-only listings (manual_listings.json)")

    # 2. Check for changes
    old_listings = load_cache()
    added, removed, price_changes = detect_changes(old_listings, listings)

    if not force and not added and not removed and not price_changes and old_listings:
        print_summary(listings, added, removed, price_changes)
        print("No changes — skipping regeneration. Use --force to regenerate anyway.")
        return

    print_summary(listings, added, removed, price_changes)

    # 3. Download images
    print("Downloading images...")
    os.makedirs(IMAGES_DIR, exist_ok=True)
    for listing in listings:
        listing["local_images"] = copy_manual_images(listing) if listing.get("manual") else download_images(listing)
        listing["local_images"] = drop_showroom_photo(listing["local_images"])
        count = len(listing["local_images"])
        if count:
            print(f"  {listing['make']} {listing['model']}: {count} images")

    # 4. Load custom data
    custom_data = {}
    if os.path.exists(CUSTOM_JSON):
        with open(CUSTOM_JSON, "r", encoding="utf-8") as f:
            custom_data = json.load(f)
        print(f"Loaded custom data for {len(custom_data)} cars")

    os.makedirs(CUSTOM_IMAGES_DIR, exist_ok=True)

    # 5. Archive sold cars, and self-heal stale sold entries.
    sold = load_sold()
    sold, restored_count = remove_active_from_sold(sold, listings)

    if restored_count:
        print(f"Removed {restored_count} active cars from sold archive")

    if removed:
        sold = archive_removed(removed, sold)
        print(f"Archived {len(removed)} sold cars (total sold: {len(sold)})")

    repaired_sold_images = repair_sold_images(sold)
    if repaired_sold_images:
        print(f"Repaired sold images for {repaired_sold_images} cars")

    if restored_count or removed or repaired_sold_images:
        save_sold(sold)

    # 6. Generate HTML
    print("Generating HTML pages...")
    os.makedirs(DETAIL_DIR, exist_ok=True)

    grid_html = generate_grid_html(listings)
    detail_pages = generate_detail_pages(listings, custom_data)

    # Generate sold detail pages (VENDU badge, no buy CTAs, cross-sell to active stock)
    sold_pages = generate_sold_detail_pages(sold, listings, custom_data)

    # 7. Write output
    grid_path = os.path.join(OUTPUT_DIR, "grid.html")
    with open(grid_path, "w", encoding="utf-8") as f:
        f.write(grid_html)

    for slug, html in detail_pages.items():
        detail_path = os.path.join(DETAIL_DIR, f"{slug}.html")
        with open(detail_path, "w", encoding="utf-8") as f:
            f.write(html)

    for slug, html in sold_pages.items():
        detail_path = os.path.join(DETAIL_DIR, f"{slug}.html")
        with open(detail_path, "w", encoding="utf-8") as f:
            f.write(html)

    # 8. Save cache
    save_cache(listings)

    # 9. Cleanup old images (don't clean sold car images)
    cleanup_old_images(listings)

    # 10. Done
    sold_count = len(sold_pages)
    print(f"\nOutput ready in: {OUTPUT_DIR}")
    print(f"  grid.html          — paste into HighLevel cars-for-sale page")
    print(f"  detail/*.html      — {len(detail_pages)} active + {sold_count} sold pages")
    print(f"  images/            — all car photos")
    logger.info(f"Done: 1 grid + {len(detail_pages)} detail + {sold_count} sold pages")


if __name__ == "__main__":
    main()
