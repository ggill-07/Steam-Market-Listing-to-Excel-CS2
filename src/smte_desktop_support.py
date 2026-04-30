from __future__ import annotations

import argparse
import json
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

import steam_market_to_excel as sme
import third_party_market_support as tpms

APP_DATA_DIR = Path("app_data")
AUTOCOMPLETE_CACHE_PATH = APP_DATA_DIR / "market_name_autocomplete_cache.json"
DESKTOP_SETTINGS_PATH = APP_DATA_DIR / "desktop_app_settings.json"
DESKTOP_QUERY_QUEUE_PATH = APP_DATA_DIR / "desktop_query_queue.json"
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
    wear: Optional[str] = None
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
    combine_case_exports: bool = False
    enable_third_party_support: bool = False
    third_party_provider: str = tpms.PROVIDER_SKINPORT


@dataclass
class QueryExecutionResult:
    query: DesktopQuery
    fetch_result: sme.FetchResult
    matched_dataframe: pd.DataFrame
    display_dataframe: pd.DataFrame


@dataclass
class QueryValidationResult:
    query: DesktopQuery
    is_valid: bool
    status_text: str


def describe_runtime_provider_mode(settings: DesktopSettings) -> str:
    if not settings.enable_third_party_support:
        return "Steam only"
    provider_definition = tpms.get_provider_definition(settings.third_party_provider)
    return f"Steam + {provider_definition.display_name} groundwork"


def ensure_app_data_dir() -> Path:
    APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
    return APP_DATA_DIR


def strip_wear_suffix(market_hash_name: str) -> str:
    market_hash_name = sme.normalize_market_hash_name_input(market_hash_name)
    for wear_name in WEAR_OPTIONS:
        suffix = f" ({wear_name})"
        if market_hash_name.endswith(suffix):
            return market_hash_name[: -len(suffix)]
    return market_hash_name


def extract_wear_name(market_hash_name: str) -> Optional[str]:
    market_hash_name = sme.normalize_market_hash_name_input(market_hash_name)
    for wear_name in WEAR_OPTIONS:
        suffix = f" ({wear_name})"
        if market_hash_name.endswith(suffix):
            return wear_name
    return None


def build_market_hash_name(base_name: str, wear_name: Optional[str]) -> str:
    normalized_base_name = strip_wear_suffix(base_name.strip())
    if not wear_name:
        return normalized_base_name
    return f"{normalized_base_name} ({wear_name})"


def build_query_label(query: DesktopQuery) -> str:
    return build_market_hash_name(query.base_name, query.wear)


def _normalize_item_name_for_match(item_name: str) -> str:
    normalized_item_name = sme.normalize_market_hash_name_input(item_name.strip())
    return sme.normalize_market_hash_name_input(strip_wear_suffix(normalized_item_name)).casefold()


def query_matches_suggestion(query: DesktopQuery, suggestion: MarketSuggestion) -> bool:
    normalized_query_base = _normalize_item_name_for_match(query.base_name)
    normalized_suggestion_base = sme.normalize_market_hash_name_input(suggestion.base_name).casefold()
    normalized_suggestion_example = _normalize_item_name_for_match(suggestion.example_hash_name)

    if normalized_query_base not in {normalized_suggestion_base, normalized_suggestion_example}:
        return False

    if query.wear is None:
        return not suggestion.wears

    return query.wear in suggestion.wears


def validate_query_against_market(
    query: DesktopQuery,
    autocomplete_cache: MarketAutocompleteCache,
) -> QueryValidationResult:
    suggestions = autocomplete_cache.fetch_and_cache_suggestions(query.base_name)
    is_valid = any(query_matches_suggestion(query, suggestion) for suggestion in suggestions)
    if is_valid:
        return QueryValidationResult(
            query=query,
            is_valid=True,
            status_text="Valid",
        )
    return QueryValidationResult(
        query=query,
        is_valid=False,
        status_text="Not found",
    )


def create_query_from_form(
    *,
    base_name: str,
    wear_name: Optional[str],
    item_has_no_wear: bool,
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
    if item_has_no_wear:
        wear_name = None
        has_stickers = False
        no_stickers = False
        min_sticker_count_text = ""
        max_sticker_count_text = ""
    elif wear_name not in WEAR_OPTIONS:
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

    max_float = parse_optional_float(max_float_text, "Max float")
    if item_has_no_wear and max_float is not None:
        raise ValueError("Max float only applies to wear-based items")

    return DesktopQuery(
        base_name=normalized_base_name,
        wear=wear_name,
        max_float=max_float,
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
    supports_wear = query.wear is not None
    return argparse.Namespace(
        market_hash_name=build_query_label(query),
        output=None,
        currency=settings.currency,
        country=settings.country,
        language=settings.language,
        steam_page_delay=settings.steam_page_delay,
        steam_max_retries=settings.steam_max_retries,
        min_float=None,
        max_float=query.max_float if supports_wear else None,
        min_price=None,
        max_price=query.max_price,
        wear=query.wear,
        paint_seed=query.paint_seed,
        has_stickers=query.has_stickers if supports_wear else False,
        no_stickers=query.no_stickers if supports_wear else False,
        min_sticker_count=query.min_sticker_count if supports_wear else None,
        max_sticker_count=query.max_sticker_count if supports_wear else None,
        sort_by=query.sort_by,
        descending=query.descending,
        show=False,
        limit=query.limit,
        columns=None,
    )


def resolve_desktop_output_name(query: DesktopQuery, settings: DesktopSettings) -> Optional[str]:
    market_hash_name = build_query_label(query)
    if query.wear is None and settings.combine_case_exports:
        if sme.classify_market_item_export_subdir(market_hash_name) == sme.CASE_EXPORT_SUBDIR:
            return str(Path(sme.CASE_EXPORT_SUBDIR) / "all_cases.xlsx")
    return None


def filter_result_dataframe_to_query(
    dataframe: pd.DataFrame,
    query: DesktopQuery,
) -> pd.DataFrame:
    if dataframe.empty:
        return dataframe.copy()

    market_hash_name = build_query_label(query)
    if "market_hash_name" in dataframe.columns:
        normalized_market_names = dataframe["market_hash_name"].map(
            lambda value: sme.normalize_market_hash_name_input(str(value).strip())
            if pd.notna(value)
            else ""
        )
        matching_dataframe = dataframe[normalized_market_names == market_hash_name]
        if not matching_dataframe.empty:
            return matching_dataframe.copy()

    return dataframe.copy()


def _build_query_execution_result(
    query: DesktopQuery,
    settings: DesktopSettings,
    fetch_result: sme.FetchResult,
) -> QueryExecutionResult:
    fetch_args = build_fetch_namespace(query, settings)
    query_scoped_dataframe = filter_result_dataframe_to_query(fetch_result.dataframe, query)
    matched_dataframe = sme.dataframe_matches_inline_query(query_scoped_dataframe, fetch_args)
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


def execute_desktop_query(query: DesktopQuery, settings: DesktopSettings) -> QueryExecutionResult:
    fetch_args = build_fetch_namespace(query, settings)
    dataframe = sme.fetch_market_dataframe(fetch_args, fetch_args.market_hash_name)
    fetch_result = sme.sync_market_dataframe(
        dataframe=dataframe,
        market_hash_name=fetch_args.market_hash_name,
        output_name=resolve_desktop_output_name(query, settings),
        update_latest=True,
    )
    return _build_query_execution_result(
        query=query,
        settings=settings,
        fetch_result=fetch_result,
    )


def apply_manual_price_override(
    query: DesktopQuery,
    settings: DesktopSettings,
    new_price: float,
    *,
    output_path: Optional[Path] = None,
) -> QueryExecutionResult:
    market_hash_name = build_query_label(query)
    resolved_output_path = output_path or sme.resolve_output_path(
        str(sme.DEFAULT_OUTPUT_DIR / Path(sme.default_fetch_output_name(market_hash_name)))
    )
    updated_dataframe = sme.update_latest_no_wear_snapshot_price(
        output_path=resolved_output_path,
        market_hash_name=market_hash_name,
        new_price=new_price,
    )
    fetch_result = sme.FetchResult(
        market_hash_name=market_hash_name,
        output_path=resolved_output_path,
        dataframe=updated_dataframe,
        change_summary=None,
        summary_override=(
            f"Manually updated the latest saved price for {market_hash_name} "
            f"to ${new_price:.2f} in {resolved_output_path}"
        ),
    )
    return _build_query_execution_result(
        query=query,
        settings=settings,
        fetch_result=fetch_result,
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
        raw_query = query_text.strip()
        normalized_query = sme.normalize_market_hash_name_input(raw_query)
        if len(raw_query) < AUTOCOMPLETE_MIN_CHARS:
            return []

        stattrak_requested = bool(sme.STATTRAK_PREFIX_PATTERN.match(raw_query))
        query_candidates: List[str] = []
        for candidate in (
            raw_query,
            normalized_query,
            sme.STATTRAK_PREFIX_PATTERN.sub("", raw_query).strip() if stattrak_requested else "",
        ):
            if candidate and candidate not in query_candidates:
                query_candidates.append(candidate)

        session = sme.create_requests_session()
        raw_results: List[Dict[str, Any]] = []
        try:
            for candidate in query_candidates:
                response = session.get(
                    "https://steamcommunity.com/market/search/render/",
                    params={
                        "query": candidate,
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
                candidate_results = payload.get("results", [])
                if stattrak_requested:
                    candidate_results = [
                        item
                        for item in candidate_results
                        if "StatTrak" in str(
                            item.get("hash_name")
                            or (item.get("asset_description") or {}).get("market_hash_name")
                            or ""
                        )
                    ]
                raw_results.extend(candidate_results)
        finally:
            sme.close_requests_session(session)

        by_base_name: Dict[str, MarketSuggestion] = {}
        for raw_item in raw_results:
            asset_description = raw_item.get("asset_description") or {}
            hash_name = str(raw_item.get("hash_name") or asset_description.get("market_hash_name") or "").strip()
            if not hash_name:
                continue

            base_name = strip_wear_suffix(hash_name).strip()
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
            serialized_suggestions = [
                {
                    "base_name": suggestion.base_name,
                    "example_hash_name": suggestion.example_hash_name,
                    "wears": suggestion.wears,
                }
                for suggestion in suggestions
            ]
            for cache_key in {raw_query.lower(), normalized_query.lower()}:
                self._cache[cache_key] = serialized_suggestions
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


def load_desktop_query_queue(queue_path: Path = DESKTOP_QUERY_QUEUE_PATH) -> List[DesktopQuery]:
    if not queue_path.exists():
        return []
    try:
        raw_items = json.loads(queue_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    if not isinstance(raw_items, list):
        return []

    valid_fields = {field.name for field in DesktopQuery.__dataclass_fields__.values()}
    queries: List[DesktopQuery] = []
    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            continue
        filtered_item = {key: value for key, value in raw_item.items() if key in valid_fields}
        try:
            query = DesktopQuery(**filtered_item)
        except TypeError:
            continue
        if not query.sort_by:
            query.sort_by = ["price"]
        queries.append(query)
    return queries


def save_desktop_query_queue(
    queries: List[DesktopQuery],
    queue_path: Path = DESKTOP_QUERY_QUEUE_PATH,
) -> Path:
    ensure_app_data_dir()
    queue_path.write_text(
        json.dumps([asdict(query) for query in queries], indent=2),
        encoding="utf-8",
    )
    return queue_path
