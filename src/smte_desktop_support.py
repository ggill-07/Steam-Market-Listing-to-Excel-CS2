from __future__ import annotations

import argparse
import json
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

import steam_market_to_excel as sme

APP_DATA_DIR = Path("app_data")
AUTOCOMPLETE_CACHE_PATH = APP_DATA_DIR / "market_name_autocomplete_cache.json"
DESKTOP_SETTINGS_PATH = APP_DATA_DIR / "desktop_app_settings.json"
AUTOCOMPLETE_MIN_CHARS = 2
AUTOCOMPLETE_PAGE_SIZE = 25
WEAR_OPTIONS = [
    "Factory New",
    "Minimal Wear",
    "Field-Tested",
    "Well-Worn",
    "Battle-Scarred",
]
DEFAULT_DESKTOP_PAGE_DELAY = 0.5
DEFAULT_DESKTOP_PAUSE_BETWEEN_QUERIES = 2.0
DEFAULT_DESKTOP_LIMIT = 250


@dataclass
class MarketSuggestion:
    base_name: str
    example_hash_name: str
    wears: List[str] = field(default_factory=list)


@dataclass
class DesktopQuery:
    base_name: str
    wear: str
    max_float: Optional[float] = None
    max_price: Optional[float] = None
    paint_seed: Optional[int] = None
    has_stickers: bool = False
    no_stickers: bool = False
    min_sticker_count: Optional[int] = None
    max_sticker_count: Optional[int] = None
    sort_by: List[str] = field(default_factory=lambda: ["price"])
    descending: bool = False
    limit: int = DEFAULT_DESKTOP_LIMIT


@dataclass
class DesktopSettings:
    currency: int = 1
    country: str = "US"
    language: str = "english"
    steam_page_delay: float = DEFAULT_DESKTOP_PAGE_DELAY
    steam_max_retries: int = sme.DEFAULT_STEAM_RETRIES
    pause_between_queries: float = DEFAULT_DESKTOP_PAUSE_BETWEEN_QUERIES
    continue_on_error: bool = True


@dataclass
class QueryExecutionResult:
    query: DesktopQuery
    fetch_result: sme.FetchResult
    matched_dataframe: pd.DataFrame
    display_dataframe: pd.DataFrame


def ensure_app_data_dir() -> Path:
    APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
    return APP_DATA_DIR


def strip_wear_suffix(market_hash_name: str) -> str:
    for wear_name in WEAR_OPTIONS:
        suffix = f" ({wear_name})"
        if market_hash_name.endswith(suffix):
            return market_hash_name[: -len(suffix)]
    return market_hash_name


def extract_wear_name(market_hash_name: str) -> Optional[str]:
    for wear_name in WEAR_OPTIONS:
        suffix = f" ({wear_name})"
        if market_hash_name.endswith(suffix):
            return wear_name
    return None


def build_market_hash_name(base_name: str, wear_name: str) -> str:
    normalized_base_name = strip_wear_suffix(base_name.strip())
    return f"{normalized_base_name} ({wear_name})"


def build_query_label(query: DesktopQuery) -> str:
    return build_market_hash_name(query.base_name, query.wear)


def create_query_from_form(
    *,
    base_name: str,
    wear_name: str,
    max_float_text: str,
    max_price_text: str,
    paint_seed_text: str,
    has_stickers: bool,
    no_stickers: bool,
    min_sticker_count_text: str,
    max_sticker_count_text: str,
    sort_by: List[str],
    descending: bool,
    limit_text: str,
) -> DesktopQuery:
    normalized_base_name = strip_wear_suffix(base_name.strip())
    if not normalized_base_name:
        raise ValueError("Item name is required")
    if wear_name not in WEAR_OPTIONS:
        raise ValueError("At least one valid wear must be selected")
    if has_stickers and no_stickers:
        raise ValueError("Choose either has stickers or no stickers, not both")

    def parse_optional_float(raw_text: str, field_name: str) -> Optional[float]:
        text = raw_text.strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError as exc:
            raise ValueError(f"{field_name} must be a number") from exc

    def parse_optional_int(raw_text: str, field_name: str) -> Optional[int]:
        text = raw_text.strip()
        if not text:
            return None
        try:
            return int(text)
        except ValueError as exc:
            raise ValueError(f"{field_name} must be a whole number") from exc

    limit_text = limit_text.strip()
    if not limit_text:
        limit = DEFAULT_DESKTOP_LIMIT
    else:
        try:
            limit = int(limit_text)
        except ValueError as exc:
            raise ValueError("Limit must be a whole number") from exc
        if limit <= 0:
            raise ValueError("Limit must be greater than zero")

    normalized_sort_by = [column.strip() for column in sort_by if column.strip()]
    if not normalized_sort_by:
        normalized_sort_by = ["price"]

    return DesktopQuery(
        base_name=normalized_base_name,
        wear=wear_name,
        max_float=parse_optional_float(max_float_text, "Max float"),
        max_price=parse_optional_float(max_price_text, "Max price"),
        paint_seed=parse_optional_int(paint_seed_text, "Paint seed"),
        has_stickers=has_stickers,
        no_stickers=no_stickers,
        min_sticker_count=parse_optional_int(min_sticker_count_text, "Min sticker count"),
        max_sticker_count=parse_optional_int(max_sticker_count_text, "Max sticker count"),
        sort_by=normalized_sort_by,
        descending=descending,
        limit=limit,
    )


def build_fetch_namespace(query: DesktopQuery, settings: DesktopSettings) -> argparse.Namespace:
    return argparse.Namespace(
        market_hash_name=build_query_label(query),
        output=None,
        currency=settings.currency,
        country=settings.country,
        language=settings.language,
        steam_page_delay=settings.steam_page_delay,
        steam_max_retries=settings.steam_max_retries,
        min_float=None,
        max_float=query.max_float,
        min_price=None,
        max_price=query.max_price,
        wear=query.wear,
        paint_seed=query.paint_seed,
        has_stickers=query.has_stickers,
        no_stickers=query.no_stickers,
        min_sticker_count=query.min_sticker_count,
        max_sticker_count=query.max_sticker_count,
        sort_by=query.sort_by,
        descending=query.descending,
        show=False,
        limit=query.limit,
        columns=None,
    )


def execute_desktop_query(query: DesktopQuery, settings: DesktopSettings) -> QueryExecutionResult:
    fetch_args = build_fetch_namespace(query, settings)
    dataframe = sme.fetch_market_dataframe(fetch_args, fetch_args.market_hash_name)
    fetch_result = sme.sync_market_dataframe(
        dataframe=dataframe,
        market_hash_name=fetch_args.market_hash_name,
        output_name=None,
        update_latest=True,
    )
    matched_dataframe = sme.dataframe_matches_inline_query(fetch_result.dataframe, fetch_args)
    display_dataframe = sme.build_show_dataframe(
        matched_dataframe,
        columns=None,
        limit=query.limit,
    )
    return QueryExecutionResult(
        query=query,
        fetch_result=fetch_result,
        matched_dataframe=matched_dataframe,
        display_dataframe=display_dataframe,
    )


class MarketAutocompleteCache:
    def __init__(self, cache_path: Path = AUTOCOMPLETE_CACHE_PATH) -> None:
        self.cache_path = cache_path
        self._lock = threading.Lock()
        self._cache = self._load_cache()

    def _load_cache(self) -> Dict[str, List[Dict[str, Any]]]:
        if not self.cache_path.exists():
            return {}
        try:
            return json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_cache(self) -> None:
        ensure_app_data_dir()
        self.cache_path.write_text(json.dumps(self._cache, indent=2), encoding="utf-8")

    def get_cached_suggestions(self, query_text: str) -> List[MarketSuggestion]:
        normalized_query = query_text.strip().lower()
        if len(normalized_query) < AUTOCOMPLETE_MIN_CHARS:
            return []
        with self._lock:
            raw_results = self._cache.get(normalized_query, [])
        return [
            MarketSuggestion(
                base_name=item["base_name"],
                example_hash_name=item["example_hash_name"],
                wears=list(item.get("wears", [])),
            )
            for item in raw_results
        ]

    def fetch_and_cache_suggestions(self, query_text: str) -> List[MarketSuggestion]:
        normalized_query = query_text.strip()
        if len(normalized_query) < AUTOCOMPLETE_MIN_CHARS:
            return []

        session = sme.create_requests_session()
        response = session.get(
            "https://steamcommunity.com/market/search/render/",
            params={
                "query": normalized_query,
                "start": 0,
                "count": AUTOCOMPLETE_PAGE_SIZE,
                "search_descriptions": 0,
                "sort_column": "popular",
                "sort_dir": "desc",
                "appid": sme.STEAM_APP_ID,
                "norender": 1,
            },
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        raw_results = payload.get("results", [])

        by_base_name: Dict[str, MarketSuggestion] = {}
        for raw_item in raw_results:
            asset_description = raw_item.get("asset_description") or {}
            hash_name = str(raw_item.get("hash_name") or asset_description.get("market_hash_name") or "").strip()
            if not hash_name:
                continue

            base_name = str(asset_description.get("market_bucket_group_name") or strip_wear_suffix(hash_name)).strip()
            wear_name = extract_wear_name(hash_name)
            suggestion = by_base_name.get(base_name)
            if suggestion is None:
                suggestion = MarketSuggestion(
                    base_name=base_name,
                    example_hash_name=hash_name,
                    wears=[],
                )
                by_base_name[base_name] = suggestion

            if wear_name and wear_name not in suggestion.wears:
                suggestion.wears.append(wear_name)

        suggestions = sorted(
            by_base_name.values(),
            key=lambda suggestion: suggestion.base_name.lower(),
        )

        with self._lock:
            self._cache[normalized_query.lower()] = [
                {
                    "base_name": suggestion.base_name,
                    "example_hash_name": suggestion.example_hash_name,
                    "wears": suggestion.wears,
                }
                for suggestion in suggestions
            ]
            self._save_cache()

        return suggestions


def load_desktop_settings(settings_path: Path = DESKTOP_SETTINGS_PATH) -> DesktopSettings:
    if not settings_path.exists():
        return DesktopSettings()
    try:
        raw_data = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return DesktopSettings()

    valid_fields = {field.name for field in DesktopSettings.__dataclass_fields__.values()}
    filtered_data = {key: value for key, value in raw_data.items() if key in valid_fields}
    return DesktopSettings(**filtered_data)


def save_desktop_settings(settings: DesktopSettings, settings_path: Path = DESKTOP_SETTINGS_PATH) -> Path:
    ensure_app_data_dir()
    settings_path.write_text(json.dumps(asdict(settings), indent=2), encoding="utf-8")
    return settings_path
