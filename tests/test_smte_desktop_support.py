"""Tests for the desktop app support layer.

These focus on the non-GUI logic so we can confidently evolve the app without
depending on a live window for every check.
"""

from __future__ import annotations

import json
import shutil
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import steam_market_to_excel as sme
import smte_desktop
import smte_desktop_support as sds


def make_workspace_temp_dir(name: str) -> Path:
    temp_dir = PROJECT_ROOT / "tests" / "_tmp_runtime" / name
    if temp_dir.exists():
        shutil.rmtree(temp_dir, ignore_errors=True)
    temp_dir.mkdir(parents=True, exist_ok=True)
    return temp_dir


class TestDesktopSupportHelpers(unittest.TestCase):
    def test_strip_wear_suffix_removes_known_wear(self):
        self.assertEqual(
            sds.strip_wear_suffix("AK-47 | Safari Mesh (Minimal Wear)"),
            "AK-47 | Safari Mesh",
        )

    def test_extract_wear_name_reads_known_wear(self):
        self.assertEqual(
            sds.extract_wear_name("MP5-SD | Neon Squeezer (Field-Tested)"),
            "Field-Tested",
        )

    def test_build_market_hash_name_appends_selected_wear(self):
        self.assertEqual(
            sds.build_market_hash_name("AK-47 | Safari Mesh", "Minimal Wear"),
            "AK-47 | Safari Mesh (Minimal Wear)",
        )

    def test_build_market_hash_name_normalizes_stattrak_alias(self):
        self.assertEqual(
            sds.build_market_hash_name("StatTrack AK-47 | Redline", "Field-Tested"),
            "StatTrak\u2122 AK-47 | Redline (Field-Tested)",
        )

    def test_build_market_hash_name_supports_no_wear_items(self):
        self.assertEqual(
            sds.build_market_hash_name("Sticker | Crown (Foil)", None),
            "Sticker | Crown (Foil)",
        )

    def test_create_query_from_form_parses_values(self):
        result = sds.create_query_from_form(
            base_name="AK-47 | Safari Mesh",
            wear_name="Minimal Wear",
            item_has_no_wear=False,
            max_float_text="0.11",
            max_price_text="1.25",
            paint_seed_text="123",
            has_stickers=True,
            no_stickers=False,
            min_sticker_count_text="1",
            max_sticker_count_text="4",
            sort_by=["price"],
            descending=False,
            limit_text="150",
        )

        self.assertEqual(result.base_name, "AK-47 | Safari Mesh")
        self.assertEqual(result.wear, "Minimal Wear")
        self.assertEqual(result.max_float, 0.11)
        self.assertEqual(result.max_price, 1.25)
        self.assertEqual(result.paint_seed, 123)
        self.assertTrue(result.has_stickers)
        self.assertEqual(result.min_sticker_count, 1)
        self.assertEqual(result.max_sticker_count, 4)
        self.assertEqual(result.sort_by, ["price"])
        self.assertEqual(result.limit, 150)

    def test_create_query_from_form_normalizes_stattrak_alias(self):
        result = sds.create_query_from_form(
            base_name="StatTrack AK-47 | Redline",
            wear_name="Field-Tested",
            item_has_no_wear=False,
            max_float_text="",
            max_price_text="",
            paint_seed_text="",
            has_stickers=False,
            no_stickers=False,
            min_sticker_count_text="",
            max_sticker_count_text="",
            sort_by=["price"],
            descending=False,
            limit_text="100",
        )

        self.assertEqual(result.base_name, "StatTrak\u2122 AK-47 | Redline")

    def test_create_query_from_form_supports_no_wear_items(self):
        result = sds.create_query_from_form(
            base_name="Sticker | Crown (Foil)",
            wear_name=None,
            item_has_no_wear=True,
            max_float_text="",
            max_price_text="12.50",
            paint_seed_text="",
            has_stickers=True,
            no_stickers=False,
            min_sticker_count_text="2",
            max_sticker_count_text="4",
            sort_by=["price"],
            descending=False,
            limit_text="100",
        )

        self.assertEqual(result.base_name, "Sticker | Crown (Foil)")
        self.assertIsNone(result.wear)
        self.assertEqual(result.max_price, 12.5)
        self.assertFalse(result.has_stickers)
        self.assertFalse(result.no_stickers)
        self.assertIsNone(result.min_sticker_count)
        self.assertIsNone(result.max_sticker_count)

    def test_create_query_from_form_rejects_float_for_no_wear_items(self):
        with self.assertRaisesRegex(ValueError, "Max float only applies to wear-based items"):
            sds.create_query_from_form(
                base_name="Sticker | Crown (Foil)",
                wear_name=None,
                item_has_no_wear=True,
                max_float_text="0.11",
                max_price_text="",
                paint_seed_text="",
                has_stickers=False,
                no_stickers=False,
                min_sticker_count_text="",
                max_sticker_count_text="",
                sort_by=["price"],
                descending=False,
                limit_text="100",
            )

    def test_create_query_from_form_rejects_conflicting_sticker_modes(self):
        with self.assertRaisesRegex(ValueError, "either has stickers or no stickers"):
            sds.create_query_from_form(
                base_name="AK-47 | Safari Mesh",
                wear_name="Minimal Wear",
                item_has_no_wear=False,
                max_float_text="",
                max_price_text="",
                paint_seed_text="",
                has_stickers=True,
                no_stickers=True,
                min_sticker_count_text="",
                max_sticker_count_text="",
                sort_by=["price"],
                descending=False,
                limit_text="100",
            )

    def test_build_fetch_namespace_matches_core_filter_shape(self):
        query = sds.DesktopQuery(
            base_name="AK-47 | Safari Mesh",
            wear="Minimal Wear",
            max_float=0.11,
            sort_by=["price"],
            limit=200,
        )
        settings = sds.DesktopSettings(steam_page_delay=0.5)

        result = sds.build_fetch_namespace(query, settings)

        self.assertEqual(result.market_hash_name, "AK-47 | Safari Mesh (Minimal Wear)")
        self.assertEqual(result.max_float, 0.11)
        self.assertEqual(result.sort_by, ["price"])
        self.assertEqual(result.limit, 200)
        self.assertEqual(result.steam_page_delay, 0.5)

    def test_build_fetch_namespace_ignores_sticker_filters_for_no_wear_items(self):
        query = sds.DesktopQuery(
            base_name="Gallery Case",
            wear=None,
            max_price=2.5,
            has_stickers=True,
            no_stickers=True,
            min_sticker_count=1,
            max_sticker_count=3,
            sort_by=["price"],
            limit=50,
        )
        settings = sds.DesktopSettings()

        result = sds.build_fetch_namespace(query, settings)

        self.assertFalse(result.has_stickers)
        self.assertFalse(result.no_stickers)
        self.assertIsNone(result.min_sticker_count)
        self.assertIsNone(result.max_sticker_count)
        self.assertIsNone(result.max_float)

    def test_query_matches_suggestion_supports_no_wear_and_wear_queries(self):
        sticker_query = sds.DesktopQuery(base_name="Sticker | Crown (Foil)", wear=None)
        sticker_suggestion = sds.MarketSuggestion(
            base_name="Sticker | Crown (Foil)",
            example_hash_name="Sticker | Crown (Foil)",
            wears=[],
        )
        skin_query = sds.DesktopQuery(base_name="AK-47 | Safari Mesh", wear="Minimal Wear")
        skin_suggestion = sds.MarketSuggestion(
            base_name="AK-47 | Safari Mesh",
            example_hash_name="AK-47 | Safari Mesh (Minimal Wear)",
            wears=["Minimal Wear", "Field-Tested"],
        )

        self.assertTrue(sds.query_matches_suggestion(sticker_query, sticker_suggestion))
        self.assertTrue(sds.query_matches_suggestion(skin_query, skin_suggestion))
        self.assertFalse(sds.query_matches_suggestion(sds.DesktopQuery(base_name="AK-47 | Safari Mesh", wear="Factory New"), skin_suggestion))

    def test_validate_query_against_market_marks_missing_items(self):
        cache = Mock()
        cache.fetch_and_cache_suggestions.return_value = [
            sds.MarketSuggestion(
                base_name="Gallery Case",
                example_hash_name="Gallery Case",
                wears=[],
            )
        ]

        valid_result = sds.validate_query_against_market(
            sds.DesktopQuery(base_name="Gallery Case", wear=None),
            cache,
        )
        invalid_result = sds.validate_query_against_market(
            sds.DesktopQuery(base_name="Typo Case", wear=None),
            cache,
        )

        self.assertTrue(valid_result.is_valid)
        self.assertEqual(valid_result.status_text, "Valid")
        self.assertFalse(invalid_result.is_valid)
        self.assertEqual(invalid_result.status_text, "Not found")

    def test_save_and_load_desktop_settings_round_trip(self):
        temp_dir = make_workspace_temp_dir("desktop_settings")
        settings_path = temp_dir / "desktop_app_settings.json"
        original = sds.DesktopSettings(
            steam_page_delay=1.0,
            steam_max_retries=7,
            pause_between_queries=4.5,
            continue_on_error=False,
            combine_case_exports=True,
        )

        sds.save_desktop_settings(original, settings_path=settings_path)
        loaded = sds.load_desktop_settings(settings_path=settings_path)

        self.assertEqual(loaded.steam_page_delay, 1.0)
        self.assertEqual(loaded.steam_max_retries, 7)
        self.assertEqual(loaded.pause_between_queries, 4.5)
        self.assertFalse(loaded.continue_on_error)
        self.assertTrue(loaded.combine_case_exports)

    def test_save_and_load_desktop_query_queue_round_trip(self):
        temp_dir = make_workspace_temp_dir("desktop_query_queue")
        queue_path = temp_dir / "desktop_query_queue.json"
        original_queries = [
            sds.DesktopQuery(
                base_name="AK-47 | Safari Mesh",
                wear="Minimal Wear",
                max_float=0.11,
                sort_by=["price"],
                limit=1000,
            ),
            sds.DesktopQuery(
                base_name="MP5-SD | Neon Squeezer",
                wear="Field-Tested",
                max_float=0.26,
                max_price=2.5,
                sort_by=["price"],
                descending=True,
                limit=500,
            ),
        ]

        sds.save_desktop_query_queue(original_queries, queue_path=queue_path)
        loaded_queries = sds.load_desktop_query_queue(queue_path=queue_path)

        self.assertEqual(len(loaded_queries), 2)
        self.assertEqual(loaded_queries[0].base_name, "AK-47 | Safari Mesh")
        self.assertEqual(loaded_queries[0].wear, "Minimal Wear")
        self.assertEqual(loaded_queries[0].max_float, 0.11)
        self.assertEqual(loaded_queries[1].base_name, "MP5-SD | Neon Squeezer")
        self.assertEqual(loaded_queries[1].wear, "Field-Tested")
        self.assertEqual(loaded_queries[1].max_price, 2.5)
        self.assertTrue(loaded_queries[1].descending)


class TestAutocompleteCache(unittest.TestCase):
    def test_get_cached_suggestions_returns_empty_for_short_query(self):
        temp_dir = make_workspace_temp_dir("autocomplete_cache_short")
        cache = sds.MarketAutocompleteCache(temp_dir / "cache.json")

        self.assertEqual(cache.get_cached_suggestions("A"), [])

    @patch("smte_desktop_support.sme.create_requests_session")
    def test_fetch_and_cache_suggestions_deduplicates_base_names(self, mocked_create_session):
        temp_dir = make_workspace_temp_dir("autocomplete_cache_fetch")
        cache = sds.MarketAutocompleteCache(temp_dir / "cache.json")

        fake_response = Mock()
        fake_response.raise_for_status = Mock()
        fake_response.json.return_value = {
            "results": [
                {
                    "hash_name": "AK-47 | Safari Mesh (Minimal Wear)",
                    "asset_description": {
                        "market_hash_name": "AK-47 | Safari Mesh (Minimal Wear)",
                        "market_bucket_group_name": "AK-47 | Safari Mesh",
                    },
                },
                {
                    "hash_name": "AK-47 | Safari Mesh (Field-Tested)",
                    "asset_description": {
                        "market_hash_name": "AK-47 | Safari Mesh (Field-Tested)",
                        "market_bucket_group_name": "AK-47 | Safari Mesh",
                    },
                },
            ]
        }

        fake_session = Mock()
        fake_session.get.return_value = fake_response
        mocked_create_session.return_value = fake_session

        suggestions = cache.fetch_and_cache_suggestions("AK-47 | Safari Mesh")

        self.assertEqual(len(suggestions), 1)
        self.assertEqual(suggestions[0].base_name, "AK-47 | Safari Mesh")
        self.assertEqual(sorted(suggestions[0].wears), ["Field-Tested", "Minimal Wear"])
        self.assertTrue((temp_dir / "cache.json").exists())

    @patch("smte_desktop_support.sme.create_requests_session")
    def test_fetch_and_cache_suggestions_preserves_stattrak_and_no_wear_items(self, mocked_create_session):
        temp_dir = make_workspace_temp_dir("autocomplete_cache_stattrak")
        cache = sds.MarketAutocompleteCache(temp_dir / "cache.json")

        stattrak_response = Mock()
        stattrak_response.raise_for_status = Mock()
        stattrak_response.json.return_value = {
            "results": [
                {
                    "hash_name": "StatTrak\u2122 AK-47 | Redline (Field-Tested)",
                    "asset_description": {
                        "market_hash_name": "StatTrak\u2122 AK-47 | Redline (Field-Tested)",
                        "market_bucket_group_name": "AK-47 | Redline",
                    },
                },
            ]
        }
        sticker_response = Mock()
        sticker_response.raise_for_status = Mock()
        sticker_response.json.return_value = {
            "results": [
                {
                    "hash_name": "Sticker | Crown (Foil)",
                    "asset_description": {
                        "market_hash_name": "Sticker | Crown (Foil)",
                    },
                },
            ]
        }

        fake_session = Mock()
        fake_session.get.side_effect = [stattrak_response, stattrak_response, stattrak_response, sticker_response]
        mocked_create_session.return_value = fake_session

        suggestions = cache.fetch_and_cache_suggestions("StatTrack AK-47 | Redline")

        self.assertEqual(len(suggestions), 1)
        self.assertEqual(suggestions[0].base_name, "StatTrak\u2122 AK-47 | Redline")
        self.assertEqual(suggestions[0].wears, ["Field-Tested"])

        sticker_suggestions = cache.fetch_and_cache_suggestions("Sticker | Crown")
        self.assertEqual(len(sticker_suggestions), 1)
        self.assertEqual(sticker_suggestions[0].base_name, "Sticker | Crown (Foil)")
        self.assertEqual(sticker_suggestions[0].wears, [])


class TestDesktopQueryExecution(unittest.TestCase):
    @patch("smte_desktop_support.sme.build_show_dataframe")
    @patch("smte_desktop_support.sme.dataframe_matches_inline_query")
    @patch("smte_desktop_support.sme.sync_market_dataframe")
    @patch("smte_desktop_support.sme.fetch_market_dataframe")
    def test_execute_desktop_query_uses_core_pipeline(
        self,
        mocked_fetch_market_dataframe,
        mocked_sync_market_dataframe,
        mocked_dataframe_matches_inline_query,
        mocked_build_show_dataframe,
    ):
        query = sds.DesktopQuery(
            base_name="AK-47 | Safari Mesh",
            wear="Minimal Wear",
            max_float=0.11,
            sort_by=["price"],
            limit=50,
        )
        settings = sds.DesktopSettings()

        scraped_dataframe = pd.DataFrame([{"listing_id": "1", "price": 0.99, "float": 0.05}])
        matched_dataframe = pd.DataFrame([{"listing_id": "1", "price": 0.99, "float": 0.05}])
        display_dataframe = pd.DataFrame([{"listing_id": "1", "price": "0.99", "float": "0.050000"}])
        fetch_result = sme.FetchResult(
            market_hash_name="AK-47 | Safari Mesh (Minimal Wear)",
            output_path=Path("exports/ak_47_safari_mesh_minimal_wear.xlsx"),
            dataframe=scraped_dataframe,
            change_summary=None,
        )

        mocked_fetch_market_dataframe.return_value = scraped_dataframe
        mocked_sync_market_dataframe.return_value = fetch_result
        mocked_dataframe_matches_inline_query.return_value = matched_dataframe
        mocked_build_show_dataframe.return_value = display_dataframe

        result = sds.execute_desktop_query(query, settings)

        self.assertEqual(result.query.base_name, "AK-47 | Safari Mesh")
        self.assertEqual(result.fetch_result.output_path.name, "ak_47_safari_mesh_minimal_wear.xlsx")
        self.assertTrue(result.matched_dataframe.equals(matched_dataframe))
        self.assertTrue(result.display_dataframe.equals(display_dataframe))

    @patch("smte_desktop_support.sme.build_show_dataframe")
    @patch("smte_desktop_support.sme.dataframe_matches_inline_query")
    @patch("smte_desktop_support.sme.sync_market_dataframe")
    @patch("smte_desktop_support.sme.fetch_market_dataframe")
    def test_execute_desktop_query_can_store_cases_in_one_shared_workbook(
        self,
        mocked_fetch_market_dataframe,
        mocked_sync_market_dataframe,
        mocked_dataframe_matches_inline_query,
        mocked_build_show_dataframe,
    ):
        query = sds.DesktopQuery(
            base_name="Gallery Case",
            wear=None,
            sort_by=["price"],
            limit=50,
        )
        settings = sds.DesktopSettings(combine_case_exports=True)

        combined_history_dataframe = pd.DataFrame(
            [
                {
                    "market_hash_name": "Gallery Case",
                    "price": 1.62,
                    "snapshot_timestamp": "2026-04-30T10:00:00-07:00",
                },
                {
                    "market_hash_name": "Kilowatt Case",
                    "price": 0.37,
                    "snapshot_timestamp": "2026-04-30T10:00:05-07:00",
                },
            ]
        )
        matched_dataframe = combined_history_dataframe.iloc[[0]].copy()
        display_dataframe = pd.DataFrame([{"#": 1, "price": "1.62"}])
        fetch_result = sme.FetchResult(
            market_hash_name="Gallery Case",
            output_path=Path("exports/cases/all_cases.xlsx"),
            dataframe=combined_history_dataframe,
            change_summary=None,
        )

        mocked_fetch_market_dataframe.return_value = matched_dataframe
        mocked_sync_market_dataframe.return_value = fetch_result
        mocked_dataframe_matches_inline_query.return_value = matched_dataframe
        mocked_build_show_dataframe.return_value = display_dataframe

        result = sds.execute_desktop_query(query, settings)

        mocked_sync_market_dataframe.assert_called_once()
        self.assertEqual(
            Path(mocked_sync_market_dataframe.call_args.kwargs["output_name"]).as_posix(),
            "cases/all_cases.xlsx",
        )
        self.assertEqual(result.fetch_result.output_path.name, "all_cases.xlsx")
        self.assertTrue(result.matched_dataframe.equals(matched_dataframe))

    @patch("smte_desktop_support.sme.build_show_dataframe")
    @patch("smte_desktop_support.sme.dataframe_matches_inline_query")
    @patch("smte_desktop_support.sme.update_latest_no_wear_snapshot_price")
    def test_apply_manual_price_override_rebuilds_desktop_result(
        self,
        mocked_update_latest_no_wear_snapshot_price,
        mocked_dataframe_matches_inline_query,
        mocked_build_show_dataframe,
    ):
        query = sds.DesktopQuery(
            base_name="Gallery Case",
            wear=None,
            sort_by=["price"],
            limit=50,
        )
        settings = sds.DesktopSettings()
        output_path = Path("exports/cases/gallery_case.xlsx")
        updated_dataframe = pd.DataFrame([{"listing_id": "1", "price": 1.68}])
        matched_dataframe = pd.DataFrame([{"listing_id": "1", "price": 1.68}])
        display_dataframe = pd.DataFrame([{"#": 1, "price": "1.68"}])

        mocked_update_latest_no_wear_snapshot_price.return_value = updated_dataframe
        mocked_dataframe_matches_inline_query.return_value = matched_dataframe
        mocked_build_show_dataframe.return_value = display_dataframe

        result = sds.apply_manual_price_override(
            query,
            settings,
            1.68,
            output_path=output_path,
        )

        mocked_update_latest_no_wear_snapshot_price.assert_called_once()
        self.assertEqual(result.fetch_result.output_path, output_path)
        self.assertTrue(result.fetch_result.dataframe.equals(updated_dataframe))
        self.assertIn("Manually updated the latest saved price", result.fetch_result.summary_override)

    def test_filter_result_dataframe_to_query_keeps_only_matching_market_rows(self):
        dataframe = pd.DataFrame(
            [
                {"market_hash_name": "Gallery Case", "price": 1.62},
                {"market_hash_name": "Kilowatt Case", "price": 0.37},
            ]
        )

        filtered = sds.filter_result_dataframe_to_query(
            dataframe,
            sds.DesktopQuery(base_name="Gallery Case", wear=None),
        )

        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered.iloc[0]["market_hash_name"], "Gallery Case")


class TestDesktopAppModule(unittest.TestCase):
    class FakeText:
        def __init__(self, value: str = ""):
            self.value = value

        def get(self, _start: str, _end: str) -> str:
            return self.value

        def delete(self, _start: str, _end: str) -> None:
            self.value = ""

        def insert(self, _start: str, new_value: str) -> None:
            self.value = new_value

    def test_desktop_entry_point_is_exposed(self):
        self.assertTrue(callable(smte_desktop.main))

    def test_desktop_icon_assets_exist(self):
        png_path = smte_desktop.get_resource_path("assets", "smte_desktop_icon.png")
        ico_path = smte_desktop.get_resource_path("assets", "smte_desktop_icon.ico")

        self.assertTrue(png_path.exists())
        self.assertTrue(ico_path.exists())

    def test_clear_results_workspace_keeps_queue_untouched(self):
        app = smte_desktop.SMTEDesktopApp.__new__(smte_desktop.SMTEDesktopApp)
        query_items = [object(), object()]
        app.query_items = query_items
        frame_one = Mock()
        frame_two = Mock()
        app.result_tabs = [
            {"frame": frame_one},
            {"frame": frame_two},
        ]
        app.results_tab_bar = Mock()
        app.results_placeholder = Mock()
        app.results_placeholder.winfo_ismapped.return_value = False
        app.results_summary_var = Mock()
        app.status_var = Mock()
        app._append_log = Mock()
        app._render_results_tab_bar = Mock()

        app._clear_results_workspace()

        self.assertIs(app.query_items, query_items)
        frame_one.destroy.assert_called_once()
        frame_two.destroy.assert_called_once()
        app._render_results_tab_bar.assert_called_once()
        app.results_placeholder.grid.assert_called_once()
        app.results_summary_var.set.assert_called_once_with("Run a search to open result tabs here.")
        app.status_var.set.assert_called_once_with("Results cleared.")
        app._append_log.assert_called_once_with("Cleared all open result tabs.")

    def test_matching_suggestion_for_item_name_finds_no_wear_and_stattrak_entries(self):
        app = smte_desktop.SMTEDesktopApp.__new__(smte_desktop.SMTEDesktopApp)
        app.current_suggestions = [
            sds.MarketSuggestion(
                base_name="Sticker | Crown (Foil)",
                example_hash_name="Sticker | Crown (Foil)",
                wears=[],
            ),
            sds.MarketSuggestion(
                base_name="StatTrak\u2122 AK-47 | Redline",
                example_hash_name="StatTrak\u2122 AK-47 | Redline (Field-Tested)",
                wears=["Field-Tested"],
            ),
        ]

        sticker_match = app._matching_suggestion_for_item_name("Sticker | Crown (Foil)")
        stattrak_match = app._matching_suggestion_for_item_name("StatTrack AK-47 | Redline")

        self.assertIsNotNone(sticker_match)
        self.assertEqual(sticker_match.base_name, "Sticker | Crown (Foil)")
        self.assertIsNotNone(stattrak_match)
        self.assertEqual(stattrak_match.base_name, "StatTrak\u2122 AK-47 | Redline")

    @patch("smte_desktop.create_query_from_form")
    def test_build_queries_from_editor_infers_no_wear_from_matching_suggestion(self, mocked_create_query):
        class FakeVar:
            def __init__(self, value):
                self.value = value

            def get(self):
                return self.value

            def set(self, new_value):
                self.value = new_value

        app = smte_desktop.SMTEDesktopApp.__new__(smte_desktop.SMTEDesktopApp)
        app.current_suggestions = [
            sds.MarketSuggestion(
                base_name="Sticker | Crown (Foil)",
                example_hash_name="Sticker | Crown (Foil)",
                wears=[],
            )
        ]
        app.item_entry = self.FakeText("Sticker | Crown (Foil)")
        app.item_name_var = FakeVar("Sticker | Crown (Foil)")
        app.no_wear_item_var = FakeVar(False)
        app.max_float_var = FakeVar("")
        app.max_price_var = FakeVar("12.50")
        app.paint_seed_var = FakeVar("")
        app.has_stickers_var = FakeVar(False)
        app.no_stickers_var = FakeVar(False)
        app.min_sticker_count_var = FakeVar("")
        app.max_sticker_count_var = FakeVar("")
        app.sort_by_var = FakeVar("price")
        app.descending_var = FakeVar(False)
        app.limit_var = FakeVar("100")
        app._refresh_no_wear_mode = Mock()
        app._selected_wears = Mock(return_value=[])
        mocked_create_query.return_value = object()

        result = app._build_queries_from_editor()

        self.assertTrue(app.no_wear_item_var.get())
        app._refresh_no_wear_mode.assert_called()
        mocked_create_query.assert_called_once()
        self.assertTrue(mocked_create_query.call_args.kwargs["item_has_no_wear"])
        self.assertIsNone(mocked_create_query.call_args.kwargs["wear_name"])
        self.assertEqual(len(result), 1)

    @patch("smte_desktop.create_query_from_form")
    def test_build_queries_from_editor_supports_bulk_no_wear_items(self, mocked_create_query):
        class FakeVar:
            def __init__(self, value):
                self.value = value

            def get(self):
                return self.value

            def set(self, new_value):
                self.value = new_value

        app = smte_desktop.SMTEDesktopApp.__new__(smte_desktop.SMTEDesktopApp)
        app.current_suggestions = []
        app.item_entry = self.FakeText("Gallery Case\nKilowatt Case\nGallery Case")
        app.item_name_var = FakeVar("Gallery Case\nKilowatt Case\nGallery Case")
        app.no_wear_item_var = FakeVar(True)
        app.max_float_var = FakeVar("")
        app.max_price_var = FakeVar("")
        app.paint_seed_var = FakeVar("")
        app.has_stickers_var = FakeVar(False)
        app.no_stickers_var = FakeVar(False)
        app.min_sticker_count_var = FakeVar("")
        app.max_sticker_count_var = FakeVar("")
        app.sort_by_var = FakeVar("price")
        app.descending_var = FakeVar(False)
        app.limit_var = FakeVar("100")
        app._refresh_no_wear_mode = Mock()
        app._selected_wears = Mock(return_value=[])
        mocked_create_query.side_effect = [object(), object()]

        result = app._build_queries_from_editor()

        self.assertEqual(len(result), 2)
        self.assertEqual(mocked_create_query.call_count, 2)
        self.assertEqual(mocked_create_query.call_args_list[0].kwargs["base_name"], "Gallery Case")
        self.assertEqual(mocked_create_query.call_args_list[1].kwargs["base_name"], "Kilowatt Case")

    @patch("smte_desktop.create_query_from_form")
    def test_build_queries_from_editor_supports_bulk_skin_market_names(self, mocked_create_query):
        class FakeVar:
            def __init__(self, value):
                self.value = value

            def get(self):
                return self.value

            def set(self, new_value):
                self.value = new_value

        app = smte_desktop.SMTEDesktopApp.__new__(smte_desktop.SMTEDesktopApp)
        app.current_suggestions = []
        app.autocomplete_cache = Mock()
        app.autocomplete_cache.fetch_and_cache_suggestions.side_effect = [
            [
                sds.MarketSuggestion(
                    base_name="AWP | Chromatic Aberration",
                    example_hash_name="AWP | Chromatic Aberration (Factory New)",
                    wears=["Factory New", "Minimal Wear", "Field-Tested"],
                )
            ],
            [
                sds.MarketSuggestion(
                    base_name="AK-47 | Ice Coaled",
                    example_hash_name="AK-47 | Ice Coaled (Factory New)",
                    wears=["Factory New", "Minimal Wear", "Field-Tested"],
                )
            ],
        ]
        app.item_entry = self.FakeText(
            "AWP | Chromatic Aberration (Factory New)\n"
            "AWP | Chromatic Aberration (Minimal Wear)\n"
            "AK-47 | Ice Coaled (Field-Tested)"
        )
        app.item_name_var = FakeVar(app.item_entry.get("1.0", "end-1c"))
        app.no_wear_item_var = FakeVar(False)
        app.max_float_var = FakeVar("0.10")
        app.max_price_var = FakeVar("2.00")
        app.paint_seed_var = FakeVar("123")
        app.has_stickers_var = FakeVar(True)
        app.no_stickers_var = FakeVar(False)
        app.min_sticker_count_var = FakeVar("1")
        app.max_sticker_count_var = FakeVar("4")
        app.sort_by_var = FakeVar("price")
        app.descending_var = FakeVar(False)
        app.limit_var = FakeVar("100")
        app._refresh_no_wear_mode = Mock()
        app._selected_wears = Mock(return_value=[])
        mocked_create_query.side_effect = [object(), object(), object()]

        result = app._build_queries_from_editor()

        self.assertEqual(len(result), 3)
        self.assertEqual(app.autocomplete_cache.fetch_and_cache_suggestions.call_count, 2)
        first_call = mocked_create_query.call_args_list[0].kwargs
        self.assertEqual(first_call["base_name"], "AWP | Chromatic Aberration")
        self.assertEqual(first_call["wear_name"], "Factory New")
        self.assertEqual(first_call["max_float_text"], "")
        self.assertFalse(first_call["has_stickers"])

    def test_build_queries_from_editor_rejects_invalid_bulk_skin_market_names(self):
        class FakeVar:
            def __init__(self, value):
                self.value = value

            def get(self):
                return self.value

            def set(self, new_value):
                self.value = new_value

        app = smte_desktop.SMTEDesktopApp.__new__(smte_desktop.SMTEDesktopApp)
        app.current_suggestions = []
        app.autocomplete_cache = Mock()
        app.autocomplete_cache.fetch_and_cache_suggestions.side_effect = [
            [
                sds.MarketSuggestion(
                    base_name="AWP | Chromatic Aberration",
                    example_hash_name="AWP | Chromatic Aberration (Factory New)",
                    wears=["Factory New", "Minimal Wear"],
                )
            ],
            [],
            [],
            [],
        ]
        app.item_entry = self.FakeText(
            "AWP | Chromatic Aberration (Battle-Scarred)\n"
            "Typo Skin (Factory New)"
        )
        app.item_name_var = FakeVar(app.item_entry.get("1.0", "end-1c"))
        app.no_wear_item_var = FakeVar(False)
        app.max_float_var = FakeVar("")
        app.max_price_var = FakeVar("")
        app.paint_seed_var = FakeVar("")
        app.has_stickers_var = FakeVar(False)
        app.no_stickers_var = FakeVar(False)
        app.min_sticker_count_var = FakeVar("")
        app.max_sticker_count_var = FakeVar("")
        app.sort_by_var = FakeVar("price")
        app.descending_var = FakeVar(False)
        app.limit_var = FakeVar("100")
        app._refresh_no_wear_mode = Mock()
        app._selected_wears = Mock(return_value=[])

        with self.assertRaisesRegex(ValueError, "Bulk skin add could not validate"):
            app._build_queries_from_editor()

    def test_build_queries_from_editor_requires_exact_autocomplete_match_for_skins(self):
        class FakeVar:
            def __init__(self, value):
                self.value = value

            def get(self):
                return self.value

            def set(self, new_value):
                self.value = new_value

        app = smte_desktop.SMTEDesktopApp.__new__(smte_desktop.SMTEDesktopApp)
        app.current_suggestions = []
        app.item_entry = self.FakeText("AK-47 | Safari Mesh")
        app.item_name_var = FakeVar("AK-47 | Safari Mesh")
        app.no_wear_item_var = FakeVar(False)
        app.max_float_var = FakeVar("")
        app.max_price_var = FakeVar("")
        app.paint_seed_var = FakeVar("")
        app.has_stickers_var = FakeVar(False)
        app.no_stickers_var = FakeVar(False)
        app.min_sticker_count_var = FakeVar("")
        app.max_sticker_count_var = FakeVar("")
        app.sort_by_var = FakeVar("price")
        app.descending_var = FakeVar(False)
        app.limit_var = FakeVar("100")
        app._refresh_no_wear_mode = Mock()
        app._selected_wears = Mock(return_value=["Minimal Wear"])

        with self.assertRaisesRegex(ValueError, "exact autocomplete suggestion"):
            app._build_queries_from_editor()

    @patch("smte_desktop.messagebox.showerror")
    @patch("smte_desktop.save_desktop_settings")
    def test_start_run_blocks_invalid_queries_before_fetching(self, mocked_save_settings, mocked_showerror):
        class FakeVar:
            def __init__(self, value):
                self.value = value

            def get(self):
                return self.value

            def set(self, new_value):
                self.value = new_value

        app = smte_desktop.SMTEDesktopApp.__new__(smte_desktop.SMTEDesktopApp)
        query = sds.DesktopQuery(base_name="Typo Case", wear=None, sort_by=["price"], limit=100)
        app.worker_thread = None
        app.query_items = [query]
        app.query_tree_left = Mock()
        app.query_tree_right = Mock()
        app.left_query_row_mappings = {}
        app.right_query_row_mappings = {}
        app.settings = sds.DesktopSettings()
        app.settings_continue_var = FakeVar(True)
        app.root = Mock()
        app.status_var = FakeVar("")
        app._append_log = Mock()
        app._collect_runtime_settings = Mock(return_value=app.settings)
        app._persist_query_queue = Mock()
        app._validate_queries = Mock(return_value=[sds.QueryValidationResult(query=query, is_valid=False, status_text="Not found")])
        app._apply_validation_results = Mock()

        app._start_run(selected_only=False)

        app._validate_queries.assert_called_once()
        app._apply_validation_results.assert_called_once()
        mocked_showerror.assert_called_once()

    @patch("smte_desktop.threading.Thread")
    @patch("smte_desktop.save_desktop_settings")
    def test_start_run_skips_explicit_validation_for_skin_queries(
        self,
        mocked_save_settings,
        mocked_thread,
    ):
        class FakeVar:
            def __init__(self, value):
                self.value = value

            def get(self):
                return self.value

            def set(self, new_value):
                self.value = new_value

        app = smte_desktop.SMTEDesktopApp.__new__(smte_desktop.SMTEDesktopApp)
        query = sds.DesktopQuery(
            base_name="AK-47 | Safari Mesh",
            wear="Minimal Wear",
            sort_by=["price"],
            limit=100,
        )
        fake_thread = Mock()
        fake_thread.start = Mock()
        mocked_thread.return_value = fake_thread

        app.worker_thread = None
        app.query_items = [query]
        app.query_tree_left = Mock()
        app.query_tree_right = Mock()
        app.left_query_row_mappings = {}
        app.right_query_row_mappings = {}
        app.settings = sds.DesktopSettings()
        app.settings_continue_var = FakeVar(True)
        app.root = Mock()
        app.status_var = FakeVar("")
        app._append_log = Mock()
        app._collect_runtime_settings = Mock(return_value=app.settings)
        app._persist_query_queue = Mock()
        app._validate_queries = Mock()
        app._apply_validation_results = Mock()
        app.query_validation_statuses = {}

        app._start_run(selected_only=False)

        app._validate_queries.assert_not_called()
        app._apply_validation_results.assert_not_called()
        mocked_thread.assert_called_once()
        fake_thread.start.assert_called_once()

    def test_selected_query_indices_from_tree_reads_left_and_right_individual_selections(self):
        app = smte_desktop.SMTEDesktopApp.__new__(smte_desktop.SMTEDesktopApp)
        app.left_query_row_mappings = {
            "row-0": 0,
            "row-1": 2,
        }
        app.right_query_row_mappings = {
            "row-0": 1,
        }
        app.query_tree_left = Mock()
        app.query_tree_right = Mock()
        app.query_tree_left.selection.return_value = ["row-0", "row-1"]
        app.query_tree_right.selection.return_value = ["row-0"]

        result = app._selected_query_indices_from_tree()

        self.assertEqual(result, [0, 1, 2])

    def test_result_tab_grid_position_wraps_after_twenty_tabs(self):
        self.assertEqual(smte_desktop.SMTEDesktopApp._result_tab_grid_position(0), (0, 0))
        self.assertEqual(smte_desktop.SMTEDesktopApp._result_tab_grid_position(19), (0, 19))
        self.assertEqual(smte_desktop.SMTEDesktopApp._result_tab_grid_position(20), (1, 0))
        self.assertEqual(smte_desktop.SMTEDesktopApp._result_tab_grid_position(24), (1, 4))

    def test_format_result_tab_title_preserves_opening_letters_when_truncated(self):
        formatted = smte_desktop.SMTEDesktopApp._format_result_tab_title("Dreams & Nightmares Case")

        self.assertTrue(formatted.startswith("Dre"))
        self.assertTrue(len(formatted) <= smte_desktop.RESULT_TAB_MAX_LABEL_CHARS)


if __name__ == "__main__":
    unittest.main()
