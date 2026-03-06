"""
Perego Cars Inventory Tool — HTML Generator
Renders listing grid and detail pages from templates.
"""
import os
import re
import logging
from datetime import datetime
from urllib.parse import quote

from config import (
    TEMPLATES_DIR, IMAGES_DIR, IMAGE_BASE_URL, WHATSAPP_NUMBER, SITE_URL,
    GITHUB_PAGES_URL, FUEL_TYPE_FR, TRANSMISSION_FR, BODY_TYPE_FR,
)
from image_handler import make_slug

logger = logging.getLogger(__name__)


# ── Formatting Helpers ──

def format_chf(price):
    """Format price Swiss style: 235000 -> CHF 235'000.--"""
    if not price:
        return "Prix sur demande"
    s = str(int(price))
    groups = []
    while s:
        groups.append(s[-3:])
        s = s[:-3]
    formatted = "'".join(reversed(groups))
    return f"CHF {formatted}.--"


def format_km(mileage):
    """Format mileage Swiss style: 12000 -> 12'000"""
    if not mileage:
        return "0"
    s = str(int(mileage))
    groups = []
    while s:
        groups.append(s[-3:])
        s = s[:-3]
    return "'".join(reversed(groups))


def translate(value, mapping):
    """Translate an enum value using a mapping dict."""
    if not value:
        return ""
    # Try exact match, then lowercase, then return raw
    return mapping.get(value, mapping.get(value.lower(), value.replace("_", " ").title()))


def _read_template(name):
    """Read a template file from the templates directory."""
    path = os.path.join(TEMPLATES_DIR, name)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _render(template, context):
    """Simple template rendering: replace {{key}} with values."""
    result = template
    for key, value in context.items():
        result = result.replace("{{" + key + "}}", str(value))
    return result


# ── Grid Page ──

def generate_grid_html(listings):
    """Generate the full listing grid HTML block."""
    card_tpl = _read_template("car_card.html")
    grid_tpl = _read_template("grid_block.html")

    cards_html = []
    for listing in listings:
        slug = make_slug(listing["make"], listing["model"], listing["id"])
        local_images = listing.get("local_images", [])
        thumb = f"{IMAGE_BASE_URL}/{local_images[0]}" if local_images else ""

        card = _render(card_tpl, {
            "detail_url": f"{GITHUB_PAGES_URL}/detail/{slug}.html",
            "image_url": thumb,
            "make": listing["make"],
            "make_upper": listing["make"].upper(),
            "model": listing["model"],
            "year": listing["year"] if listing["year"] else "Neuf",
            "mileage_fmt": format_km(listing["mileage"]),
            "price_fmt": format_chf(listing["price"]),
        })
        cards_html.append(card)

    grid = _render(grid_tpl, {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "count": str(len(listings)),
        "car_cards": "\n".join(cards_html),
    })

    logger.info(f"Generated grid with {len(listings)} cards")
    return grid


# ── Detail Pages ──

def generate_detail_pages(listings):
    """Generate individual detail pages. Returns {slug: html} dict."""
    detail_tpl = _read_template("detail_page.html")
    pages = {}

    for listing in listings:
        slug = make_slug(listing["make"], listing["model"], listing["id"])
        local_images = listing.get("local_images", [])

        # Main image
        main_img = f"{IMAGE_BASE_URL}/{local_images[0]}" if local_images else ""

        # Thumbnail images (skip first, it's the main)
        thumbs_html = ""
        for img_file in local_images[1:]:
            thumbs_html += f'            <img class="pcd-thumb" src="{IMAGE_BASE_URL}/{img_file}" alt="{listing["make"]} {listing["model"]}" loading="lazy">\n'

        # Spec rows
        specs = []
        if listing["year"]:
            specs.append(("Annee", str(listing["year"])))
        if listing["mileage"]:
            specs.append(("Kilometrage", f"{format_km(listing['mileage'])} km"))
        if listing["horsepower"]:
            specs.append(("Puissance", f"{listing['horsepower']} ch"))
        if listing["fuel_type"]:
            specs.append(("Carburant", translate(listing["fuel_type"], FUEL_TYPE_FR)))
        if listing["transmission"]:
            specs.append(("Transmission", translate(listing["transmission"], TRANSMISSION_FR)))
        if listing["body_type"]:
            specs.append(("Carrosserie", translate(listing["body_type"], BODY_TYPE_FR)))

        spec_rows_html = ""
        for label, value in specs:
            spec_rows_html += f'            <div class="pcd-spec-row"><span class="pcd-spec-label">{label}</span><span class="pcd-spec-value">{value}</span></div>\n'

        # WhatsApp pre-filled message
        wa_msg = quote(
            f"Bonjour, je suis interesse(e) par votre {listing['make']} {listing['model']}"
            f" ({listing['year']}) a {format_chf(listing['price'])}. "
            f"Est-il toujours disponible ?"
        )

        # Teaser block
        teaser_block = ""
        if listing.get("teaser"):
            teaser_block = f'<div class="pcd-teaser">{listing["teaser"]}</div>'

        page = _render(detail_tpl, {
            "make": listing["make"],
            "make_upper": listing["make"].upper(),
            "model": listing["model"],
            "full_name": listing.get("full_name", f"{listing['make']} {listing['model']}"),
            "year": str(listing["year"]) if listing["year"] else "Neuf",
            "mileage_fmt": format_km(listing["mileage"]),
            "price_fmt": format_chf(listing["price"]),
            "main_image": main_img,
            "thumbnail_images": thumbs_html,
            "spec_rows": spec_rows_html,
            "whatsapp_number": WHATSAPP_NUMBER,
            "whatsapp_msg": wa_msg,
            "listing_url": listing["listing_url"],
            "grid_url": f"{GITHUB_PAGES_URL}/grid.html",
            "teaser_block": teaser_block,
        })

        pages[slug] = page

    logger.info(f"Generated {len(pages)} detail pages")
    return pages
