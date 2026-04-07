#!/usr/bin/env python3
"""Export Steam Community Market CS2 listings to an Excel file.

This script crawls all listing pages (10 listings per page) for a given CS2 market
hash name, resolves each listing's inspect link, fetches float metadata, and writes
an Excel sheet with:
- float and wear
- paint seed
- page number
- price
- sticker presence
"""

from __future__ import annotations

import argparse
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import quote

import pandas as pd
import requests

STEAM_APP_ID = 730
STEAM_CONTEXT_ID = 2
PAGE_SIZE = 10
DEFAULT_STEAM_PAGE_DELAY = 1.0
DEFAULT_FLOAT_API_DELAY = 0.3
DEFAULT_STEAM_RETRIES = 5


@dataclass
class ListingRow:
    listing_id: str
    asset_id: str
    page: int
    price: float
    currency: str
    float_value: Optional[float]
    wear: Optional[str]
    paint_seed: Optional[int]
    has_stickers: Optional[bool]
    sticker_count: Optional[int]
    inspect_link: Optional[str]


def get_wear_from_float(float_value: Optional[float]) -> Optional[str]:
    if float_value is None:
        return None
    if float_value < 0.07:
        return "Factory New"
    if float_value < 0.15:
        return "Minimal Wear"
    if float_value < 0.38:
        return "Field-Tested"
    if float_value < 0.45:
        return "Well-Worn"
    return "Battle-Scarred"


def normalize_inspect_link(raw_link: str, listing_id: str, asset_id: str) -> str:
    return raw_link.replace("%listingid%", listing_id).replace("%assetid%", asset_id)


def steam_render_page(
    session: requests.Session,
    market_hash_name: str,
    start: int,
    currency: int,
    country: str,
    language: str,
    max_retries: int = DEFAULT_STEAM_RETRIES,
) -> Dict[str, Any]:
    encoded_name = quote(market_hash_name, safe="")
    url = f"https://steamcommunity.com/market/listings/{STEAM_APP_ID}/{encoded_name}/render/"
    params = {
        "start": start,
        "count": PAGE_SIZE,
        "currency": currency,
        "language": language,
        "country": country,
        "format": "json",
    }
    attempt = 0

    while True:
        response = session.get(url, params=params, timeout=25)
        if response.status_code != 429:
            response.raise_for_status()
            payload = response.json()
            if not payload.get("success", False):
                raise RuntimeError(
                    f"Steam render endpoint returned unsuccessful response for start={start}"
                )
            return payload

        attempt += 1
        if attempt > max_retries:
            raise requests.HTTPError(
                f"Steam rate limited the render endpoint after {max_retries} retries for start={start}",
                response=response,
            )

        retry_after = response.headers.get("Retry-After")
        try:
            wait_seconds = float(
                retry_after) if retry_after is not None else 0.0
        except ValueError:
            wait_seconds = 0.0

        wait_seconds = max(wait_seconds, min(5 * attempt, 30))
        print(
            f"Steam rate limited page starting at {start}. "
            f"Waiting {wait_seconds:.1f}s before retry {attempt}/{max_retries}..."
        )
        time.sleep(wait_seconds)


def extract_inspect_link(asset_payload: Dict[str, Any], listing_id: str, asset_id: str) -> Optional[str]:
    for key in ("market_actions", "actions"):
        actions = asset_payload.get(key) or []
        for action in actions:
            link = action.get("link")
            if isinstance(link, str) and "%assetid%" in link:
                return normalize_inspect_link(link, listing_id=listing_id, asset_id=asset_id)
    return None


def fetch_float_metadata(session: requests.Session, inspect_link: str) -> Dict[str, Any]:
    # Community endpoint used by multiple CS float tools.
    api_url = "https://api.csgofloat.com/"
    response = session.get(api_url, params={"url": inspect_link}, timeout=25)
    response.raise_for_status()
    data = response.json()

    item_info = data.get("iteminfo", {})
    float_value = item_info.get("floatvalue")
    if float_value is not None:
        try:
            float_value = float(float_value)
        except (TypeError, ValueError):
            float_value = None

    paint_seed = item_info.get("paintseed")
    if paint_seed is not None:
        try:
            paint_seed = int(paint_seed)
        except (TypeError, ValueError):
            paint_seed = None

    stickers = item_info.get("stickers")
    if isinstance(stickers, list):
        has_stickers = len(stickers) > 0
        sticker_count = len(stickers)
    else:
        has_stickers = None
        sticker_count = None

    return {
        "float_value": float_value,
        "paint_seed": paint_seed,
        "has_stickers": has_stickers,
        "sticker_count": sticker_count,
    }


def iter_listings(
    session: requests.Session,
    market_hash_name: str,
    currency: int,
    country: str,
    language: str,
    steam_page_delay: float = DEFAULT_STEAM_PAGE_DELAY,
    float_api_delay: float = DEFAULT_FLOAT_API_DELAY,
    steam_max_retries: int = DEFAULT_STEAM_RETRIES,
) -> Iterable[ListingRow]:
    start = 0
    total_count: Optional[int] = None

    while total_count is None or start < total_count:
        payload = steam_render_page(
            session=session,
            market_hash_name=market_hash_name,
            start=start,
            currency=currency,
            country=country,
            language=language,
            max_retries=steam_max_retries,
        )
        total_count = int(payload.get("total_count", 0))

        listing_info = payload.get("listinginfo", {})
        if not listing_info:
            break

        assets = payload.get("assets", {}).get(
            str(STEAM_APP_ID), {}).get(str(STEAM_CONTEXT_ID), {})

        page_number = (start // PAGE_SIZE) + 1
        for listing_id, listing in listing_info.items():
            asset = listing.get("asset") or {}
            asset_id = str(asset.get("id", ""))
            asset_payload = assets.get(asset_id, {})

            inspect_link = extract_inspect_link(
                asset_payload, listing_id=listing_id, asset_id=asset_id)

            price_cents = (listing.get("converted_price") or listing.get("price") or 0) + (
                listing.get("converted_fee") or listing.get("fee") or 0
            )
            price = float(price_cents) / 100.0

            float_value = None
            paint_seed = None
            has_stickers = None
            sticker_count = None

            if inspect_link:
                try:
                    metadata = fetch_float_metadata(session, inspect_link)
                    float_value = metadata["float_value"]
                    paint_seed = metadata["paint_seed"]
                    has_stickers = metadata["has_stickers"]
                    sticker_count = metadata["sticker_count"]
                except Exception:
                    # Keep row even if external float service fails for this listing.
                    pass

                # Keep request pace reasonable for external API rate limits.
                time.sleep(float_api_delay)

            yield ListingRow(
                listing_id=listing_id,
                asset_id=asset_id,
                page=page_number,
                price=price,
                currency=str(listing.get("currencyid", currency)),
                float_value=float_value,
                wear=get_wear_from_float(float_value),
                paint_seed=paint_seed,
                has_stickers=has_stickers,
                sticker_count=sticker_count,
                inspect_link=inspect_link,
            )

        start += PAGE_SIZE
        # Be nice to Steam and avoid hammering listing pages.
        time.sleep(steam_page_delay)


def rows_to_dataframe(rows: List[ListingRow]) -> pd.DataFrame:
    records = []
    for row in rows:
        records.append(
            {
                "listing_id": row.listing_id,
                "asset_id": row.asset_id,
                "page": row.page,
                "price": row.price,
                "currency": row.currency,
                "float": row.float_value,
                "wear": row.wear,
                "paint_seed": row.paint_seed,
                "has_stickers": row.has_stickers,
                "sticker_count": row.sticker_count,
                "inspect_link": row.inspect_link,
            }
        )
    return pd.DataFrame.from_records(records)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scrape Steam Community Market listings for a CS2 item and export to Excel."
    )
    parser.add_argument(
        "market_hash_name",
        help='Exact Steam market hash name, e.g. "AK-47 | Redline (Field-Tested)"',
    )
    parser.add_argument(
        "-o", "--output", default="steam_listings.xlsx", help="Output Excel filename")
    parser.add_argument("--currency", type=int, default=1,
                        help="Steam currency ID (default: 1 for USD)")
    parser.add_argument("--country", default="US",
                        help="Steam country code (default: US)")
    parser.add_argument("--language", default="english",
                        help="Steam language (default: english)")
    parser.add_argument(
        "--steam-page-delay",
        type=float,
        default=DEFAULT_STEAM_PAGE_DELAY,
        help="Seconds to wait between Steam listing page requests (default: 1.0)",
    )
    parser.add_argument(
        "--float-api-delay",
        type=float,
        default=DEFAULT_FLOAT_API_DELAY,
        help="Seconds to wait between float API requests (default: 0.3)",
    )
    parser.add_argument(
        "--steam-max-retries",
        type=int,
        default=DEFAULT_STEAM_RETRIES,
        help="How many times to retry a Steam page after HTTP 429 (default: 5)",
    )

    args = parser.parse_args()

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        }
    )

    rows = list(
        iter_listings(
            session=session,
            market_hash_name=args.market_hash_name,
            currency=args.currency,
            country=args.country,
            language=args.language,
            steam_page_delay=args.steam_page_delay,
            float_api_delay=args.float_api_delay,
            steam_max_retries=args.steam_max_retries,
        )
    )

    df = rows_to_dataframe(rows)
    df.to_excel(args.output, index=False)

    print(f"Exported {len(df)} listings to {args.output}")


if __name__ == "__main__":
    main()
