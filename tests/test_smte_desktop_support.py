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

    def test_create_query_from_form_parses_values(self):
        result = sds.create_query_from_form(
            base_name="AK-47 | Safari Mesh",
            wear_name="Minimal Wear",
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

    def test_create_query_from_form_rejects_conflicting_sticker_modes(self):
        with self.assertRaisesRegex(ValueError, "either has stickers or no stickers"):
            sds.create_query_from_form(
                base_name="AK-47 | Safari Mesh",
                wear_name="Minimal Wear",
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

    def test_save_and_load_desktop_settings_round_trip(self):
        temp_dir = make_workspace_temp_dir("desktop_settings")
        settings_path = temp_dir / "desktop_app_settings.json"
        original = sds.DesktopSettings(
            steam_page_delay=1.0,
            steam_max_retries=7,
            pause_between_queries=4.5,
            continue_on_error=False,
        )

        sds.save_desktop_settings(original, settings_path=settings_path)
        loaded = sds.load_desktop_settings(settings_path=settings_path)

        self.assertEqual(loaded.steam_page_delay, 1.0)
        self.assertEqual(loaded.steam_max_retries, 7)
        self.assertEqual(loaded.pause_between_queries, 4.5)
        self.assertFalse(loaded.continue_on_error)

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


class TestDesktopAppModule(unittest.TestCase):
    def test_desktop_entry_point_is_exposed(self):
        self.assertTrue(callable(smte_desktop.main))

    def test_desktop_icon_assets_exist(self):
        png_path = smte_desktop.get_resource_path("assets", "smte_desktop_icon.png")
        ico_path = smte_desktop.get_resource_path("assets", "smte_desktop_icon.ico")

        self.assertTrue(png_path.exists())
        self.assertTrue(ico_path.exists())


if __name__ == "__main__":
    unittest.main()
