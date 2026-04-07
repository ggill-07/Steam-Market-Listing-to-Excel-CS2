#!/usr/bin/env python3
"""Beginner-friendly explained version of steam_market_to_excel.py.

This file is meant for learning.

It keeps the same behavior as the main program, but the comments and docstrings
are written for someone who is still getting comfortable with Python.

Program flow in very plain English:
1. main() reads the command line arguments you typed.
2. main() creates a web session.
3. main() calls iter_listings() to collect listing rows.
4. iter_listings() asks Steam for one page of listings at a time.
5. For each listing, iter_listings() tries to find an inspect link.
6. If an inspect link exists, iter_listings() asks the float API for more data.
7. iter_listings() creates a ListingRow object for each listing.
8. rows_to_dataframe() turns those rows into a table.
9. pandas saves the table to Excel.

If the program is "not working", these are the most likely places to inspect:
- steam_render_page(): Steam may block, rate-limit, or change its response.
- extract_inspect_link(): the inspect link may not exist in the place we expect.
- fetch_float_metadata(): the float API may be down or may return different data.
- iter_listings(): Steam's JSON structure may have changed.

Good beginner strategy for debugging:
1. Run the program on one item.
2. Add a small print() in the function you are investigating.
3. Print one variable at a time.
4. Rerun and see where the data stops looking correct.
"""

# This import changes how type hints are handled internally.
# You do not need to understand it deeply right now.
# It mainly helps type hints behave a bit more nicely.
from __future__ import annotations

# argparse helps us build command-line programs.
# It is what lets the script understand things like:
# python script.py "item name" --country US
import argparse

# time gives us functions related to time.
# We use time.sleep(...) to pause between web requests.
import time

# dataclass is a decorator used to make simple classes for storing data.
from dataclasses import dataclass

# These imports are all type hints.
# Type hints help describe what kind of data a function expects or returns.
from typing import Any, Dict, Iterable, List, Optional

# quote(...) turns text into a URL-safe form.
# Example: spaces become %20.
from urllib.parse import quote

# pandas is a library for working with tables.
# We use it so saving to Excel is easy.
import pandas as pd

# requests is a library for sending HTTP requests to websites and APIs.
import requests


# Steam uses the app id 730 for Counter-Strike.
STEAM_APP_ID = 730

# Steam inventory data is also grouped by "context id".
# For CS2 items, context 2 is the one we want here.
STEAM_CONTEXT_ID = 2

# Steam returns 10 listings per page from the endpoint we are using.
PAGE_SIZE = 10

# These delays help us avoid hammering Steam or the float API too quickly.
DEFAULT_STEAM_PAGE_DELAY = 1.0
DEFAULT_FLOAT_API_DELAY = 0.3

# If Steam replies with HTTP 429 ("Too Many Requests"),
# we will retry this many times before giving up.
DEFAULT_STEAM_RETRIES = 5


# @dataclass is a decorator.
# A decorator is a special Python feature that modifies or enhances something.
# Here it makes our class easier to use as a plain data container.
@dataclass
class ListingRow:
    """A single row of final listing data.

    A dataclass is a convenient way to store related values together.
    You can think of it like a simple container with named fields.
    """

    # Each line below defines one field stored in the object.
    # The colon is used for a type hint.
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
    """Convert a float value into a human-readable wear name.

    Example:
    - 0.03 -> Factory New
    - 0.10 -> Minimal Wear
    - 0.20 -> Field-Tested
    """

    # Optional[float] means the value can be:
    # - a float
    # - None
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
    """Fill in the placeholder values inside Steam's inspect link template.

    Steam often gives links containing special placeholder text like:
    - %listingid%
    - %assetid%

    This function swaps those placeholders with the real values for one listing.
    """

    # str.replace(old, new) creates a new string.
    # Here we do two replacements in one line.
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
    """Fetch one page of listings from Steam.

    Parameters:
    - session: a requests session used for HTTP calls
    - market_hash_name: the exact Steam item name
    - start: which listing offset to begin from
    - currency/country/language: request settings sent to Steam
    - max_retries: how many times to retry if Steam rate-limits us

    Returns:
    - a Python dictionary made from Steam's JSON response

    If you think the program is failing early, this is one of the first places
    to inspect, because everything starts with the Steam market response.
    """

    # quote(...) URL-encodes the item name.
    # This matters because spaces and special characters cannot safely be placed
    # into a URL without being converted first.
    encoded_name = quote(market_hash_name, safe="")

    # This is an f-string.
    # It lets us insert Python values directly into a string.
    url = f"https://steamcommunity.com/market/listings/{STEAM_APP_ID}/{encoded_name}/render/"

    # This dictionary becomes the URL query string.
    # Example:
    # ?start=0&count=10&currency=1...
    params = {
        "start": start,
        "count": PAGE_SIZE,
        "currency": currency,
        "language": language,
        "country": country,
        "format": "json",
    }

    # This variable counts how many retries we have used.
    attempt = 0

    # while True means "keep looping until we return, break, or raise an error".
    while True:
        # session.get(...) sends an HTTP GET request.
        # timeout=25 means "do not wait forever".
        response = session.get(url, params=params, timeout=25)

        # A 429 status code means Steam is telling us to slow down.
        if response.status_code != 429:
            # raise_for_status() means:
            # "If the server replied with a bad HTTP status code, stop here."
            response.raise_for_status()

            # .json() converts JSON text from the server into a Python object,
            # usually a dictionary.
            payload = response.json()

            # .get("success", False) means:
            # - try to read the "success" key
            # - if it does not exist, use False instead
            if not payload.get("success", False):
                raise RuntimeError(
                    f"Steam render endpoint returned unsuccessful response for start={start}"
                )

            # return ends the function immediately and sends the payload back.
            return payload

        # If we reach this point, Steam gave us a 429 and we need to retry.
        attempt += 1

        if attempt > max_retries:
            raise requests.HTTPError(
                f"Steam rate limited the render endpoint after {max_retries} retries for start={start}",
                response=response,
            )

        # Headers are extra pieces of metadata sent with the response.
        # Retry-After may tell us how many seconds Steam wants us to wait.
        retry_after = response.headers.get("Retry-After")

        try:
            # Convert Retry-After into a float if possible.
            wait_seconds = float(
                retry_after) if retry_after is not None else 0.0
        except ValueError:
            # If the value is missing or not a number, fall back to 0 for now.
            wait_seconds = 0.0

        # If Steam does not tell us a useful wait time, use a simple backoff:
        # wait longer on each retry, but cap the wait at 30 seconds.
        wait_seconds = max(wait_seconds, min(5 * attempt, 30))

        print(
            f"Steam rate limited page starting at {start}. "
            f"Waiting {wait_seconds:.1f}s before retry {attempt}/{max_retries}..."
        )
        time.sleep(wait_seconds)


def extract_inspect_link(asset_payload: Dict[str, Any], listing_id: str, asset_id: str) -> Optional[str]:
    """Find and build an inspect link from Steam's asset data.

    Steam may store inspect links inside either:
    - market_actions
    - actions

    We look through both places and return the first usable inspect link.

    If your script is getting rows but no float data, this function is a very
    good place to debug.
    """

    for key in ("market_actions", "actions"):
        # .get(key) safely reads a dictionary value.
        # "or []" means "if the value is missing or empty, use an empty list".
        actions = asset_payload.get(key) or []

        # Loop through each action in that list.
        for action in actions:
            # action should be a dictionary, so .get("link") tries to read
            # its "link" value safely.
            link = action.get("link")

            # We only care about the special link template that contains
            # the asset placeholder.
            if isinstance(link, str) and "%assetid%" in link:
                return normalize_inspect_link(link, listing_id=listing_id, asset_id=asset_id)

    return None


def fetch_float_metadata(session: requests.Session, inspect_link: str) -> Dict[str, Any]:
    """Fetch extra data for one listing from the float API.

    The float API can tell us things like:
    - float value
    - paint seed
    - sticker list

    We convert some values into cleaner Python types before returning them.

    If inspect links look correct but float data is missing, debug here.
    """

    # This is the base URL for the float API.
    api_url = "https://api.csgofloat.com/"

    # We send the inspect link as a query parameter named "url".
    response = session.get(api_url, params={"url": inspect_link}, timeout=25)

    # Stop if the HTTP response itself was bad.
    response.raise_for_status()

    # Turn the JSON response into a Python dictionary.
    data = response.json()

    # iteminfo is where the API keeps the data we care about.
    # If iteminfo is missing, we use {} so the program does not crash here.
    item_info = data.get("iteminfo", {})

    # The API may give us a string or another type, so we try to convert it
    # into a float. If conversion fails, we store None instead.
    float_value = item_info.get("floatvalue")
    if float_value is not None:
        try:
            float_value = float(float_value)
        except (TypeError, ValueError):
            float_value = None

    # Same idea for paint seed: convert it to an integer if possible.
    paint_seed = item_info.get("paintseed")
    if paint_seed is not None:
        try:
            paint_seed = int(paint_seed)
        except (TypeError, ValueError):
            paint_seed = None

    # Some items have a "stickers" list. Some do not.
    stickers = item_info.get("stickers")

    # If stickers is a list, we can count how many stickers the item has.
    if isinstance(stickers, list):
        has_stickers = len(stickers) > 0
        sticker_count = len(stickers)
    else:
        has_stickers = None
        sticker_count = None

    # Return one dictionary holding the cleaned values.
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
    """Yield listing rows one at a time.

    "Yield" means this function is a generator.
    Instead of building the full result immediately, it produces one row at a
    time as it loops through Steam pages.

    This is the main "workhorse" function of the program.
    If you want to understand the whole scraper, this is the most important
    function to read slowly.
    """

    # start is the listing offset sent to Steam.
    # start=0 means "begin at the first listing".
    start = 0

    # We do not know the total number of listings until Steam tells us.
    total_count: Optional[int] = None

    # We keep going until we know the total number of listings
    # and have moved past the last page.
    while total_count is None or start < total_count:
        # Ask Steam for one page of listing data.
        payload = steam_render_page(
            session=session,
            market_hash_name=market_hash_name,
            start=start,
            currency=currency,
            country=country,
            language=language,
            max_retries=steam_max_retries,
        )

        # total_count tells us how many listings exist in total.
        # int(...) forces the value to be an integer.
        total_count = int(payload.get("total_count", 0))

        # listinginfo is the main chunk containing listing-by-listing data.
        listing_info = payload.get("listinginfo", {})
        if not listing_info:
            break

        # Steam nests asset data quite deeply, so we drill down carefully.
        # We convert the constants to strings because the JSON keys are strings.
        assets = payload.get("assets", {}).get(
            str(STEAM_APP_ID), {}
        ).get(str(STEAM_CONTEXT_ID), {})

        # // means integer division.
        # Example: if start is 20 and page size is 10, page_number becomes 3.
        page_number = (start // PAGE_SIZE) + 1

        # .items() gives us both the key and the value from a dictionary.
        for listing_id, listing in listing_info.items():
            # listing_id is the dictionary key.
            # listing is the dictionary value for that key.
            asset = listing.get("asset") or {}

            # Convert asset id to a string to keep types consistent.
            asset_id = str(asset.get("id", ""))
            asset_payload = assets.get(asset_id, {})

            inspect_link = extract_inspect_link(
                asset_payload,
                listing_id=listing_id,
                asset_id=asset_id,
            )

            # Steam prices are usually stored as whole-number cents,
            # so 150 means $1.50.
            #
            # Some responses use converted_price/converted_fee.
            # Others use price/fee.
            # We try both so the script works in more cases.
            price_cents = (listing.get("converted_price") or listing.get("price") or 0) + (
                listing.get("converted_fee") or listing.get("fee") or 0
            )
            # Convert cents into dollars.
            price = float(price_cents) / 100.0

            # Start with "unknown" values.
            # If later steps fail, the row can still be saved.
            float_value = None
            paint_seed = None
            has_stickers = None
            sticker_count = None

            if inspect_link:
                try:
                    # Ask the float API for extra info about this one item.
                    metadata = fetch_float_metadata(session, inspect_link)

                    # Read values back out of the metadata dictionary.
                    float_value = metadata["float_value"]
                    paint_seed = metadata["paint_seed"]
                    has_stickers = metadata["has_stickers"]
                    sticker_count = metadata["sticker_count"]
                except Exception:
                    # We still keep the row even if the float API fails.
                    #
                    # This is helpful because it means:
                    # "a float API problem should not destroy the whole export".
                    pass

                # Slow down slightly between float API calls.
                time.sleep(float_api_delay)

            # yield sends one ListingRow back to the caller.
            # This is like saying:
            # "Here is the next finished row. I can make more later."
            #
            # This is different from return:
            # - return ends the whole function
            # - yield gives back one value, then the function can continue later
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

        # Move to the next page of Steam results.
        # Because PAGE_SIZE is 10, the next page starts 10 listings later.
        start += PAGE_SIZE

        # Slow down slightly between Steam page requests.
        time.sleep(steam_page_delay)


def rows_to_dataframe(rows: List[ListingRow]) -> pd.DataFrame:
    """Turn our list of ListingRow objects into a pandas DataFrame.

    A DataFrame is basically a table with rows and columns.
    This is what makes it easy to export the data to Excel.
    """

    # We will build a normal Python list of dictionaries first.
    # Then pandas will turn that list into a DataFrame.
    records = []

    for row in rows:
        # Append one dictionary per row.
        # Each key in the dictionary will become a column name.
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

    # pandas turns the list of dictionaries into a table-like object.
    return pd.DataFrame.from_records(records)


def main() -> None:
    """Parse command-line arguments, run the scrape, and save the Excel file.

    If you are tracing the program from start to finish, this is the best
    function to begin with.
    """

    # Create an ArgumentParser object.
    # This object defines what arguments the user can type in the terminal.
    parser = argparse.ArgumentParser(
        description="Scrape Steam Community Market listings for a CS2 item and export to Excel."
    )

    # This is a positional argument.
    # Positional arguments do not need -- before them.
    parser.add_argument(
        "market_hash_name",
        help='Exact Steam market hash name, e.g. "AK-47 | Redline (Field-Tested)"',
    )

    # These are optional arguments because they begin with - or --.
    parser.add_argument(
        "-o",
        "--output",
        default="steam_listings.xlsx",
        help="Output Excel filename",
    )
    parser.add_argument(
        "--currency",
        type=int,
        default=1,
        help="Steam currency ID (default: 1 for USD)",
    )
    parser.add_argument(
        "--country",
        default="US",
        help="Steam country code (default: US)",
    )
    parser.add_argument(
        "--language",
        default="english",
        help="Steam language (default: english)",
    )
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

    # parse_args() reads the command you typed in the terminal.
    args = parser.parse_args()

    # requests.Session() creates a reusable HTTP session object.
    # Using one session is cleaner than setting everything up from scratch
    # for every request.
    session = requests.Session()

    # Headers are extra pieces of information sent with each request.
    # User-Agent tells the site what kind of client is making the request.
    # Some sites respond better when the request looks browser-like.
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        }
    )

    # iter_listings() is a generator, so list(...) forces it to run fully and
    # collect every row into a normal list.
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

    # Turn the list of rows into a pandas table.
    df = rows_to_dataframe(rows)

    # Save that table as an Excel file.
    # index=False means "do not write pandas row numbers as a separate column".
    df.to_excel(args.output, index=False)

    print(f"Exported {len(df)} listings to {args.output}")


# This special check means:
# "Only run main() if this file was executed directly."
# If the file is imported into another file, main() will not run automatically.
if __name__ == "__main__":
    main()
