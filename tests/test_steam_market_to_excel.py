"""Beginner-friendly tests for steam_market_to_excel.py.

This file uses Python's built-in unittest library.

Big picture:
- A test calls one small part of your code.
- It checks that the result matches what you expected.
- Some tests use fake objects so we do not call the real Steam site or float API.

You can run these tests with:
    python -B -m unittest discover -s tests -v
"""

import argparse
import io
import shutil
import sys
import tomllib
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd
import requests


# Make sure Python can import the file from the src/ folder.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import steam_market_to_excel as sme


def make_workspace_temp_dir(name: str) -> Path:
    temp_dir = PROJECT_ROOT / "tests" / "_tmp_runtime" / name
    if temp_dir.exists():
        shutil.rmtree(temp_dir, ignore_errors=True)
    temp_dir.mkdir(parents=True, exist_ok=True)
    return temp_dir


class TestBasicHelpers(unittest.TestCase):
    """Tests for small helper functions.

    These are the easiest tests to understand because they do not need fake
    network calls. They simply give a function an input and check the output.
    """

    def test_get_wear_from_float_returns_expected_labels(self):
        self.assertIsNone(sme.get_wear_from_float(None))
        self.assertEqual(sme.get_wear_from_float(0.01), "Factory New")
        self.assertEqual(sme.get_wear_from_float(0.10), "Minimal Wear")
        self.assertEqual(sme.get_wear_from_float(0.20), "Field-Tested")
        self.assertEqual(sme.get_wear_from_float(0.40), "Well-Worn")
        self.assertEqual(sme.get_wear_from_float(0.90), "Battle-Scarred")

    def test_normalize_inspect_link_replaces_placeholders(self):
        raw_link = "steam://rungame/730/%listingid%/%assetid%"
        result = sme.normalize_inspect_link(raw_link, "123", "456")
        self.assertEqual(result, "steam://rungame/730/123/456")

    def test_normalize_inspect_link_replaces_propid_placeholders(self):
        raw_link = "steam://run/730//+csgo_econ_action_preview%20%propid:6%"
        asset_payload = {
            "asset_properties": [
                {"propertyid": 6, "string_value": "TOKEN123"}
            ]
        }

        result = sme.normalize_inspect_link(
            raw_link,
            "123",
            "456",
            asset_payload=asset_payload,
        )

        self.assertEqual(result, "steam://run/730//+csgo_econ_action_preview%20TOKEN123")

    def test_extract_inspect_link_uses_market_actions_when_present(self):
        asset_payload = {
            "market_actions": [
                {"link": "steam://rungame/730/%listingid%/%assetid%"}
            ]
        }

        result = sme.extract_inspect_link(
            asset_payload,
            listing_id="111",
            asset_id="222",
        )

        self.assertEqual(result, "steam://rungame/730/111/222")

    def test_extract_inspect_link_supports_propid_based_format(self):
        asset_payload = {
            "market_actions": [
                {"link": "steam://run/730//+csgo_econ_action_preview%20%propid:6%"}
            ],
            "asset_properties": [
                {"propertyid": 6, "string_value": "TOKEN123"}
            ],
        }

        result = sme.extract_inspect_link(
            asset_payload,
            listing_id="111",
            asset_id="222",
        )

        self.assertEqual(result, "steam://run/730//+csgo_econ_action_preview%20TOKEN123")

    def test_extract_inspect_link_returns_none_when_no_valid_link_exists(self):
        asset_payload = {
            "actions": [{"link": "https://example.com/not-an-inspect-link"}]
        }

        result = sme.extract_inspect_link(
            asset_payload,
            listing_id="111",
            asset_id="222",
        )

        self.assertIsNone(result)

    def test_resolve_output_path_uses_exports_folder_for_plain_filename(self):
        result = sme.resolve_output_path("result.xlsx")
        self.assertEqual(result, sme.DEFAULT_OUTPUT_DIR / "result.xlsx")

    def test_get_runtime_project_dir_uses_project_root_for_dist_builds(self):
        temp_dir = make_workspace_temp_dir("runtime_project_dir")
        dist_dir = temp_dir / "dist"
        dist_dir.mkdir(parents=True, exist_ok=True)
        (temp_dir / "src").mkdir(parents=True, exist_ok=True)
        fake_executable = dist_dir / "smte-desktop.exe"
        fake_executable.write_text("placeholder", encoding="utf-8")

        with patch.object(sme.sys, "executable", str(fake_executable)):
            with patch.object(sme.sys, "frozen", True, create=True):
                result = sme.get_runtime_project_dir()

        self.assertEqual(result, temp_dir)

    def test_default_fetch_output_name_uses_market_name_slug(self):
        result = sme.default_fetch_output_name("AK-47 | Safari Mesh (Minimal Wear)")
        self.assertEqual(Path(result), Path("skins") / "ak_47_safari_mesh_minimal_wear.xlsx")

    def test_normalize_market_hash_name_input_supports_stattrak_aliases(self):
        self.assertEqual(
            sme.normalize_market_hash_name_input("StatTrack AK-47 | Redline (Field-Tested)"),
            "StatTrak\u2122 AK-47 | Redline (Field-Tested)",
        )
        self.assertEqual(
            sme.normalize_market_hash_name_input("StatTrak AK-47 | Redline (Field-Tested)"),
            "StatTrak\u2122 AK-47 | Redline (Field-Tested)",
        )

    def test_default_fetch_output_name_normalizes_stattrak_alias(self):
        result = sme.default_fetch_output_name("StatTrack AK-47 | Redline (Field-Tested)")
        self.assertEqual(Path(result), Path("skins") / "stattrak_ak_47_redline_field_tested.xlsx")

    def test_default_fetch_output_name_routes_cases_and_stickers_to_subfolders(self):
        case_result = sme.default_fetch_output_name("Gallery Case")
        sticker_result = sme.default_fetch_output_name("Sticker | Crown (Foil)")

        self.assertEqual(Path(case_result), Path("cases") / "gallery_case.xlsx")
        self.assertEqual(Path(sticker_result), Path("stickers") / "sticker_crown_foil.xlsx")

    def test_extract_wear_name_from_market_hash_name_reads_known_wear(self):
        self.assertEqual(
            sme.extract_wear_name_from_market_hash_name("AK-47 | Safari Mesh (Minimal Wear)"),
            "Minimal Wear",
        )
        self.assertIsNone(
            sme.extract_wear_name_from_market_hash_name("Sticker | Crown (Foil)")
        )

    def test_market_item_supports_wear_matches_skin_vs_case_style_items(self):
        self.assertTrue(sme.market_item_supports_wear("AK-47 | Safari Mesh (Minimal Wear)"))
        self.assertFalse(sme.market_item_supports_wear("Gallery Case"))

    def test_parse_price_text_reads_currency_strings(self):
        self.assertEqual(sme.parse_price_text("$1.23"), 1.23)
        self.assertEqual(sme.parse_price_text("CDN$ 12.45"), 12.45)
        self.assertIsNone(sme.parse_price_text("not a price"))

    def test_extract_listing_total_price_ignores_zero_and_uses_market_fallback(self):
        self.assertEqual(
            sme.extract_listing_total_price({"price": 110, "fee": 5}),
            1.15,
        )
        self.assertEqual(
            sme.extract_listing_total_price({"price": 0, "fee": 0}, market_level_fallback_price=2.45),
            2.45,
        )
        self.assertIsNone(
            sme.extract_listing_total_price({"price": 0, "fee": 0}, market_level_fallback_price=None)
        )

    def test_resolve_output_path_keeps_custom_folder_paths(self):
        result = sme.resolve_output_path("custom_folder/result.xlsx")
        self.assertEqual(result, Path("custom_folder") / "result.xlsx")

    def test_should_refresh_steam_session_every_ten_pages(self):
        self.assertFalse(sme.should_refresh_steam_session(0))
        self.assertFalse(sme.should_refresh_steam_session(9))
        self.assertTrue(sme.should_refresh_steam_session(10))
        self.assertTrue(sme.should_refresh_steam_session(20))

    def test_resolve_input_path_supports_latest_keyword(self):
        temp_dir = make_workspace_temp_dir("resolve_latest")
        older_file = temp_dir / "skins" / "older.xlsx"
        newer_file = temp_dir / "cases" / "newer.xlsx"
        older_file.parent.mkdir(parents=True, exist_ok=True)
        newer_file.parent.mkdir(parents=True, exist_ok=True)
        older_file.write_text("older", encoding="utf-8")
        newer_file.write_text("newer", encoding="utf-8")
        older_timestamp = 1_700_000_000
        newer_timestamp = older_timestamp + 10
        older_file.touch()
        newer_file.touch()
        import os
        os.utime(older_file, (older_timestamp, older_timestamp))
        os.utime(newer_file, (newer_timestamp, newer_timestamp))

        with patch.object(sme, "DEFAULT_OUTPUT_DIR", temp_dir):
            result = sme.resolve_input_path("latest")

        self.assertEqual(result, newer_file)

    def test_resolve_input_path_prefers_pinned_latest_file(self):
        temp_dir = make_workspace_temp_dir("resolve_pinned_latest")
        older_file = temp_dir / "skins" / "older.xlsx"
        pinned_file = temp_dir / "cases" / "pinned.xlsx"
        older_file.parent.mkdir(parents=True, exist_ok=True)
        pinned_file.parent.mkdir(parents=True, exist_ok=True)
        older_file.write_text("older", encoding="utf-8")
        pinned_file.write_text("pinned", encoding="utf-8")
        sme_pointer_path = temp_dir / sme.LATEST_POINTER_FILENAME
        sme_pointer_path.write_text(str(pinned_file.resolve()), encoding="utf-8")

        with patch.object(sme, "DEFAULT_OUTPUT_DIR", temp_dir):
            result = sme.resolve_input_path("latest")

        self.assertEqual(result, pinned_file)

    def test_parse_args_supports_legacy_fetch_style(self):
        args = sme.parse_args(["AK-47 | Redline (Field-Tested)"])

        self.assertEqual(args.command, "fetch")
        self.assertEqual(args.market_hash_name, "AK-47 | Redline (Field-Tested)")
        self.assertIsNone(args.output)

    def test_parse_args_supports_fetch_subcommand(self):
        args = sme.parse_args(
            ["fetch", "AK-47 | Redline (Field-Tested)", "-o", "custom.xlsx", "--max-float", "0.10", "--sort-by", "float", "--show"]
        )

        self.assertEqual(args.command, "fetch")
        self.assertEqual(args.market_hash_name, "AK-47 | Redline (Field-Tested)")
        self.assertEqual(args.output, "custom.xlsx")
        self.assertEqual(args.max_float, 0.10)
        self.assertEqual(args.sort_by, ["float"])
        self.assertTrue(args.show)

    def test_parse_args_supports_fetch_many_subcommand(self):
        args = sme.parse_args(
            [
                "fetch-many",
                "AK-47 | Redline (Field-Tested)",
                "M4A1-S | Basilisk (Field-Tested)",
                "--workers",
                "2",
            ]
        )

        self.assertEqual(args.command, "fetch-many")
        self.assertEqual(
            args.market_hash_names,
            ["AK-47 | Redline (Field-Tested)", "M4A1-S | Basilisk (Field-Tested)"],
        )
        self.assertEqual(args.workers, 2)

    def test_describe_listing_changes_counts_added_removed_and_unchanged(self):
        previous_dataframe = pd.DataFrame([{"listing_id": "1"}, {"listing_id": "2"}])
        current_dataframe = pd.DataFrame([{"listing_id": "2"}, {"listing_id": "3"}])

        result = sme.describe_listing_changes(previous_dataframe, current_dataframe)

        self.assertEqual(result, {"added": 1, "removed": 1, "unchanged": 1})

    def test_append_price_snapshot_history_adds_timestamp_columns(self):
        current_dataframe = pd.DataFrame(
            [{"listing_id": "listing-1", "price": 2.45, "wear": None}]
        )

        history_dataframe = sme.append_price_snapshot_history(
            previous_dataframe=None,
            current_dataframe=current_dataframe,
            market_hash_name="Gallery Case",
        )

        self.assertEqual(len(history_dataframe), 1)
        self.assertEqual(history_dataframe.iloc[0]["market_hash_name"], "Gallery Case")
        self.assertIn("snapshot_date", history_dataframe.columns)
        self.assertIn("snapshot_timestamp", history_dataframe.columns)
        self.assertTrue(pd.isna(history_dataframe.iloc[0]["wear"]))

    def test_attach_fetch_timestamp_columns_adds_timestamp_metadata(self):
        dataframe = pd.DataFrame([{"listing_id": "listing-1", "price": 1.25}])

        timestamped_dataframe = sme.attach_fetch_timestamp_columns(dataframe)

        self.assertIn("snapshot_date", timestamped_dataframe.columns)
        self.assertIn("snapshot_timestamp", timestamped_dataframe.columns)

    def test_extract_lowest_histogram_price_reads_lowest_sell_order(self):
        self.assertEqual(
            sme.extract_lowest_histogram_price({"lowest_sell_order": 222}),
            2.22,
        )
        self.assertEqual(
            sme.extract_lowest_histogram_price({"sell_order_graph": [[2.67, 65, "x"]]}),
            2.67,
        )

    def test_extract_item_nameid_from_listing_html_reads_market_load_order_spread(self):
        listing_html = "<script>Market_LoadOrderSpread( 176288467 );</script>"
        self.assertEqual(
            sme.extract_item_nameid_from_listing_html(listing_html),
            "176288467",
        )

    def test_create_requests_session_disables_environment_proxies(self):
        session = sme.create_requests_session()
        self.assertFalse(session.trust_env)
        sme.close_requests_session(session)

    def test_update_latest_no_wear_snapshot_price_updates_latest_row_and_tags_override(self):
        temp_dir = make_workspace_temp_dir("manual_case_price_update")
        output_path = temp_dir / "cases" / "all_cases.xlsx"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        starting_dataframe = pd.DataFrame(
            [
                {"listing_id": "old-row", "price": 1.25, "market_hash_name": "Gallery Case"},
                {"listing_id": "other-case-latest", "price": 2.75, "market_hash_name": "Kilowatt Case"},
                {"listing_id": "latest-row", "price": 1.50, "market_hash_name": "Gallery Case"},
            ]
        )
        starting_dataframe.to_excel(output_path, index=False)

        updated_dataframe = sme.update_latest_no_wear_snapshot_price(
            output_path=output_path,
            market_hash_name="Gallery Case",
            new_price=1.68,
        )

        gallery_rows = updated_dataframe[updated_dataframe["market_hash_name"] == "Gallery Case"]
        kilowatt_rows = updated_dataframe[updated_dataframe["market_hash_name"] == "Kilowatt Case"]
        self.assertEqual(gallery_rows.iloc[-1]["price"], 1.68)
        self.assertEqual(gallery_rows.iloc[-1]["price_source"], "manual_override")
        self.assertTrue(gallery_rows.iloc[-1]["manual_price_override"])
        self.assertEqual(kilowatt_rows.iloc[-1]["price"], 2.75)
        self.assertIn("manual_price_override_at", updated_dataframe.columns)

    def test_append_price_snapshot_history_organizes_columns_for_readability(self):
        history_dataframe = sme.append_price_snapshot_history(
            previous_dataframe=pd.DataFrame(
                [
                    {
                        "listing_id": "",
                        "price": 1.25,
                        "market_hash_name": "Kilowatt Case",
                        "snapshot_timestamp": "2026-04-29T09:00:00-07:00",
                    }
                ]
            ),
            current_dataframe=pd.DataFrame([{"listing_id": "", "price": 1.68, "currency": "1"}]),
            market_hash_name="Gallery Case",
        )

        self.assertEqual(
            list(history_dataframe.columns[:5]),
            ["market_hash_name", "snapshot_date", "snapshot_timestamp", "price", "currency"],
        )
        self.assertEqual(history_dataframe.iloc[0]["market_hash_name"], "Gallery Case")

    def test_parse_args_supports_sort_subcommand(self):
        args = sme.parse_args(["sort", "exports/sample.xlsx", "--by", "float", "price"])

        self.assertEqual(args.command, "sort")
        self.assertEqual(args.input_path, "exports/sample.xlsx")
        self.assertEqual(args.by, ["float", "price"])

    def test_parse_args_supports_filter_subcommand(self):
        args = sme.parse_args(["filter", "exports/sample.xlsx", "--max-float", "0.15"])

        self.assertEqual(args.command, "filter")
        self.assertEqual(args.input_path, "exports/sample.xlsx")
        self.assertEqual(args.max_float, 0.15)

    def test_parse_args_supports_stats_subcommand(self):
        args = sme.parse_args(["stats", "exports/sample.xlsx"])

        self.assertEqual(args.command, "stats")
        self.assertEqual(args.input_path, "exports/sample.xlsx")

    def test_parse_args_supports_use_subcommand(self):
        args = sme.parse_args(["use", "exports/sample.xlsx"])

        self.assertEqual(args.command, "use")
        self.assertEqual(args.input_path, "exports/sample.xlsx")

    def test_parse_args_supports_show_subcommand(self):
        args = sme.parse_args(["show", "exports/sample.xlsx", "--max-float", "0.10", "--sort-by", "float"])

        self.assertEqual(args.command, "show")
        self.assertEqual(args.input_path, "exports/sample.xlsx")
        self.assertEqual(args.max_float, 0.10)
        self.assertEqual(args.sort_by, ["float"])

    def test_parse_args_supports_latest_as_input_path(self):
        args = sme.parse_args(["show", "latest", "--max-float", "0.10"])

        self.assertEqual(args.command, "show")
        self.assertEqual(args.input_path, "latest")

    def test_pyproject_declares_installable_smte_command(self):
        pyproject_path = PROJECT_ROOT / "pyproject.toml"
        with pyproject_path.open("rb") as handle:
            pyproject_data = tomllib.load(handle)

        self.assertEqual(
            pyproject_data["project"]["scripts"]["smte"],
            "steam_market_to_excel:main",
        )
        self.assertEqual(
            pyproject_data["tool"]["setuptools"]["py-modules"],
            ["steam_market_to_excel", "smte_desktop", "smte_desktop_support"],
        )
        self.assertEqual(
            pyproject_data["project"]["scripts"]["smte-desktop"],
            "smte_desktop:main",
        )

    def test_license_file_exists_and_mentions_mit(self):
        license_path = PROJECT_ROOT / "LICENSE"
        license_text = license_path.read_text(encoding="utf-8")

        self.assertIn("MIT License", license_text)
        self.assertIn("Permission is hereby granted, free of charge", license_text)

    def test_windows_exe_build_script_exists_and_targets_main_script(self):
        build_script_path = PROJECT_ROOT / "scripts" / "build_windows_exe.ps1"
        script_text = build_script_path.read_text(encoding="utf-8")

        self.assertIn("python -m PyInstaller", script_text)
        self.assertIn("--onefile", script_text)
        self.assertIn("--specpath $buildDir", script_text)
        self.assertIn("Remove-Item -LiteralPath $exePath -Force", script_text)
        self.assertIn("if ($LASTEXITCODE -ne 0)", script_text)
        self.assertIn("for ($attempt = 1; $attempt -le 10; $attempt++)", script_text)
        self.assertIn("Start-Sleep -Milliseconds (200 * $attempt)", script_text)
        self.assertIn("src\\steam_market_to_excel.py", script_text)
        self.assertIn('$distDir = Join-Path $repoRoot "dist"', script_text)

    def test_windows_desktop_exe_build_script_exists_and_targets_desktop_app(self):
        build_script_path = PROJECT_ROOT / "scripts" / "build_windows_desktop_exe.ps1"
        script_text = build_script_path.read_text(encoding="utf-8")

        self.assertIn("python -m PyInstaller", script_text)
        self.assertIn("--onefile", script_text)
        self.assertIn("--windowed", script_text)
        self.assertIn("--icon $iconIco", script_text)
        self.assertIn('--add-data "${iconIco};assets"', script_text)
        self.assertIn('--add-data "${iconPng};assets"', script_text)
        self.assertIn("src\\smte_desktop.py", script_text)
        self.assertIn('assets\\smte_desktop_icon.ico', script_text)
        self.assertIn('assets\\smte_desktop_icon.png', script_text)


class TestFakeApiResponses(unittest.TestCase):
    """Tests that use fake responses instead of real HTTP requests."""

    @patch("steam_market_to_excel.time.sleep")
    def test_steam_render_page_retries_when_steam_rate_limits(self, mocked_sleep):
        # First fake reply: Steam says "too many requests".
        rate_limited_response = Mock(status_code=429, headers={"Retry-After": "1"})

        # Second fake reply: Steam allows the request.
        success_response = Mock(status_code=200, headers={})
        success_response.raise_for_status = Mock()
        success_response.json.return_value = {
            "success": True,
            "total_count": 0,
            "listinginfo": {},
        }

        fake_session = Mock()

        # side_effect means: first call returns the 429 response,
        # second call returns the success response.
        fake_session.get.side_effect = [rate_limited_response, success_response]

        payload = sme.steam_render_page(
            session=fake_session,
            market_hash_name="AK-47 | Redline (Field-Tested)",
            start=0,
            currency=1,
            country="US",
            language="english",
            max_retries=2,
        )

        self.assertEqual(payload["total_count"], 0)
        self.assertEqual(fake_session.get.call_count, 2)
        mocked_sleep.assert_called_once_with(5)

    @patch("steam_market_to_excel.time.sleep")
    def test_steam_render_page_retries_when_steam_returns_502(self, mocked_sleep):
        bad_gateway_response = Mock(status_code=502, headers={})
        success_response = Mock(status_code=200, headers={})
        success_response.raise_for_status = Mock()
        success_response.json.return_value = {
            "success": True,
            "total_count": 0,
            "listinginfo": {},
        }

        fake_session = Mock()
        fake_session.get.side_effect = [bad_gateway_response, success_response]

        payload = sme.steam_render_page(
            session=fake_session,
            market_hash_name="AK-47 | Redline (Field-Tested)",
            start=0,
            currency=1,
            country="US",
            language="english",
            max_retries=2,
        )

        self.assertEqual(payload["total_count"], 0)
        self.assertEqual(fake_session.get.call_count, 2)
        mocked_sleep.assert_called_once_with(5)

    def test_steam_render_page_accepts_unsuccessful_empty_later_page(self):
        empty_later_page_response = Mock(status_code=200, headers={})
        empty_later_page_response.raise_for_status = Mock()
        empty_later_page_response.json.return_value = {
            "success": False,
            "start": 9000,
            "pagesize": 100,
            "total_count": 0,
            "listinginfo": {},
            "results_html": "<div class=\"market_listing_table_header\"></div>",
        }

        fake_session = Mock()
        fake_session.get.return_value = empty_later_page_response

        payload = sme.steam_render_page(
            session=fake_session,
            market_hash_name="MP5-SD | Neon Squeezer (Field-Tested)",
            start=9000,
            currency=1,
            country="US",
            language="english",
            max_retries=2,
        )

        self.assertFalse(payload["success"])
        self.assertEqual(payload["start"], 9000)

    def test_steam_render_page_still_errors_on_unsuccessful_first_page(self):
        unsuccessful_first_page_response = Mock(status_code=200, headers={})
        unsuccessful_first_page_response.raise_for_status = Mock()
        unsuccessful_first_page_response.json.return_value = {
            "success": False,
            "start": 0,
            "pagesize": 100,
            "total_count": 0,
            "listinginfo": {},
        }

        fake_session = Mock()
        fake_session.get.return_value = unsuccessful_first_page_response

        with self.assertRaisesRegex(RuntimeError, "unsuccessful response for start=0"):
            sme.steam_render_page(
                session=fake_session,
                market_hash_name="MP5-SD | Neon Squeezer (Field-Tested)",
                start=0,
                currency=1,
                country="US",
                language="english",
                max_retries=2,
            )

    @patch("steam_market_to_excel.time.sleep")
    @patch("steam_market_to_excel.create_requests_session")
    def test_recover_steam_render_page_refreshes_session_and_returns_payload(
        self,
        mocked_create_requests_session,
        mocked_sleep,
    ):
        original_session = Mock()
        refreshed_session = Mock()
        mocked_create_requests_session.return_value = refreshed_session
        expected_payload = {"success": True, "total_count": 100, "listinginfo": {"1": {}}}

        with patch(
            "steam_market_to_excel.steam_render_page",
            return_value=expected_payload,
        ) as mocked_steam_render_page:
            payload, returned_session, adjusted_delay = sme.recover_steam_render_page(
                session=original_session,
                market_hash_name="MP5-SD | Neon Squeezer (Field-Tested)",
                start=6800,
                currency=1,
                country="US",
                language="english",
                max_retries=5,
                steam_page_delay=0.0,
            )

        self.assertEqual(payload, expected_payload)
        self.assertIs(returned_session, refreshed_session)
        self.assertEqual(adjusted_delay, sme.STEAM_RECOVERY_PAGE_DELAY_FLOOR)
        mocked_sleep.assert_called_once_with(sme.STEAM_RECOVERY_WAIT_STEPS[0])
        mocked_steam_render_page.assert_called_once()

    @patch("steam_market_to_excel.time.sleep")
    @patch("steam_market_to_excel.create_requests_session")
    def test_recover_steam_render_page_raises_after_all_recovery_rounds(
        self,
        mocked_create_requests_session,
        mocked_sleep,
    ):
        refreshed_session = Mock()
        refreshed_session.close = Mock()
        mocked_create_requests_session.return_value = refreshed_session
        http_error = requests.HTTPError("still rate limited", response=Mock(status_code=429))

        with patch(
            "steam_market_to_excel.steam_render_page",
            side_effect=http_error,
        ):
            with self.assertRaisesRegex(requests.HTTPError, "extended recovery"):
                sme.recover_steam_render_page(
                    session=Mock(),
                    market_hash_name="MP5-SD | Neon Squeezer (Field-Tested)",
                    start=6800,
                    currency=1,
                    country="US",
                    language="english",
                    max_retries=5,
                    steam_page_delay=0.0,
                )

        self.assertEqual(mocked_sleep.call_count, len(sme.STEAM_RECOVERY_WAIT_STEPS))

    @patch("steam_market_to_excel.time.sleep")
    @patch("steam_market_to_excel.recover_steam_render_page")
    def test_iter_listings_recovers_after_temporary_http_error(
        self,
        mocked_recover_steam_render_page,
        mocked_sleep,
    ):
        fake_payload = {
            "total_count": 1,
            "listinginfo": {
                "12345": {
                    "asset": {"id": "67890"},
                    "converted_price": 123,
                    "converted_fee": 22,
                    "currencyid": 1,
                }
            },
            "assets": {
                "730": {
                    "2": {
                        "67890": {
                            "market_actions": [{"link": "steam://rungame/730/%listingid%/%assetid%"}],
                            "asset_properties": [
                                {"propertyid": 2, "float_value": 0.091},
                                {"propertyid": 1, "int_value": 777},
                            ],
                            "descriptions": [{"value": "Sticker: Test"}],
                        }
                    }
                }
            },
        }
        fake_session = Mock()
        temporary_error = requests.HTTPError("rate limited", response=Mock(status_code=429))

        with patch(
            "steam_market_to_excel.steam_render_page",
            side_effect=[temporary_error],
        ):
            mocked_recover_steam_render_page.return_value = (
                fake_payload,
                fake_session,
                1.0,
            )
            rows = list(
                sme.iter_listings(
                    session=fake_session,
                    market_hash_name="AK-47 | Safari Mesh (Minimal Wear)",
                    currency=1,
                    country="US",
                    language="english",
                    steam_page_delay=0.0,
                    steam_max_retries=5,
                )
            )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].listing_id, "12345")
        self.assertEqual(rows[0].wear, "Minimal Wear")
        mocked_recover_steam_render_page.assert_called_once()
        mocked_sleep.assert_called_once_with(1.0)

    def test_extract_steam_metadata_reads_asset_properties(self):
        asset_payload = {
            "asset_properties": [
                {"propertyid": 1, "int_value": "321"},
                {"propertyid": 2, "float_value": "0.1234"},
                {"propertyid": 6, "string_value": "TOKEN123"},
            ]
        }

        result = sme.extract_steam_metadata(asset_payload)

        self.assertEqual(result["float_value"], 0.1234)
        self.assertEqual(result["paint_seed"], 321)
        self.assertIsNone(result["has_stickers"])
        self.assertIsNone(result["sticker_count"])

    def test_extract_steam_metadata_counts_stickers_from_descriptions(self):
        asset_payload = {
            "descriptions": [
                {"value": "Sticker: Crown (Foil)"},
                {"value": "Sticker: Team Dignitas"},
            ]
        }

        result = sme.extract_steam_metadata(asset_payload)

        self.assertTrue(result["has_stickers"])
        self.assertEqual(result["sticker_count"], 2)


class TestListingAndExportFlow(unittest.TestCase):
    """Tests a larger chunk of the program with fake helper functions."""

    @patch("steam_market_to_excel.time.sleep")
    def test_iter_listings_builds_a_listing_row_from_fake_data(self, mocked_sleep):
        fake_steam_payload = {
            "success": True,
            "total_count": 1,
            "listinginfo": {
                "listing-1": {
                    "asset": {"id": "asset-1"},
                    "price": 125,
                    "fee": 25,
                    "currencyid": 1,
                }
            },
            "assets": {
                str(sme.STEAM_APP_ID): {
                    str(sme.STEAM_CONTEXT_ID): {
                        "asset-1": {
                            "market_actions": [
                                {"link": "steam://run/730//+csgo_econ_action_preview%20%propid:6%"}
                            ],
                            "asset_properties": [
                                {"propertyid": 1, "int_value": "7"},
                                {"propertyid": 2, "float_value": "0.12"},
                                {"propertyid": 6, "string_value": "TOKEN123"},
                            ],
                        }
                    }
                }
            },
        }

        # Here we replace the helper functions completely.
        # That means iter_listings() runs, but it receives predictable fake data.
        with patch("steam_market_to_excel.steam_render_page", return_value=fake_steam_payload):
            rows = list(
                sme.iter_listings(
                    session=Mock(),
                    market_hash_name="AK-47 | Redline (Field-Tested)",
                    currency=1,
                    country="US",
                    language="english",
                    steam_page_delay=0,
                    steam_max_retries=1,
                )
            )

        self.assertEqual(len(rows), 1)

        row = rows[0]
        self.assertEqual(row.listing_id, "listing-1")
        self.assertEqual(row.asset_id, "asset-1")
        self.assertEqual(row.page, 1)
        self.assertEqual(row.price, 1.5)
        self.assertEqual(row.currency, "1")
        self.assertEqual(row.float_value, 0.12)
        self.assertEqual(row.wear, "Minimal Wear")
        self.assertEqual(row.paint_seed, 7)
        self.assertIsNone(row.has_stickers)
        self.assertIsNone(row.sticker_count)
        self.assertEqual(row.inspect_link, "steam://run/730//+csgo_econ_action_preview%20TOKEN123")

        # The function sleeps once after the page finishes.
        self.assertEqual(mocked_sleep.call_count, 1)

    @patch("steam_market_to_excel.time.sleep")
    def test_iter_listings_skips_zero_priced_listings(self, mocked_sleep):
        fake_steam_payload = {
            "success": True,
            "total_count": 2,
            "listinginfo": {
                "listing-zero": {
                    "asset": {"id": "asset-zero"},
                    "price": 0,
                    "fee": 0,
                    "currencyid": 1,
                },
                "listing-good": {
                    "asset": {"id": "asset-good"},
                    "price": 125,
                    "fee": 25,
                    "currencyid": 1,
                },
            },
            "assets": {
                str(sme.STEAM_APP_ID): {
                    str(sme.STEAM_CONTEXT_ID): {
                        "asset-zero": {},
                        "asset-good": {},
                    }
                }
            },
        }

        with patch("steam_market_to_excel.steam_render_page", return_value=fake_steam_payload):
            rows = list(
                sme.iter_listings(
                    session=Mock(),
                    market_hash_name="Gallery Case",
                    currency=1,
                    country="US",
                    language="english",
                    steam_page_delay=0,
                    steam_max_retries=1,
                )
            )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].listing_id, "listing-good")
        self.assertEqual(rows[0].price, 1.5)
        self.assertEqual(mocked_sleep.call_count, 1)

    def test_rows_to_dataframe_creates_expected_columns(self):
        rows = [
            sme.ListingRow(
                listing_id="listing-1",
                asset_id="asset-1",
                page=1,
                price=1.5,
                currency="1",
                float_value=0.12,
                wear="Minimal Wear",
                paint_seed=7,
                has_stickers=True,
                sticker_count=1,
                inspect_link="steam://inspect",
            )
        ]

        dataframe = sme.rows_to_dataframe(rows)

        self.assertEqual(
            list(dataframe.columns),
            [
                "listing_id",
                "asset_id",
                "page",
                "price",
                "currency",
                "float",
                "wear",
                "paint_seed",
                "has_stickers",
                "sticker_count",
                "inspect_link",
            ],
        )
        self.assertEqual(dataframe.iloc[0]["listing_id"], "listing-1")
        self.assertEqual(dataframe.iloc[0]["float"], 0.12)

    def test_build_lowest_listing_snapshot_dataframe_uses_cheapest_first_page_listing(self):
        fake_payload = {
            "success": True,
            "total_count": 5000,
            "listinginfo": {
                "listing-2": {
                    "price": 120,
                    "fee": 5,
                    "currencyid": 1,
                    "asset": {"id": "asset-2"},
                },
                "listing-1": {
                    "price": 110,
                    "fee": 5,
                    "currencyid": 1,
                    "asset": {"id": "asset-1"},
                },
            },
            "assets": {
                "730": {
                    "2": {
                        "asset-1": {},
                        "asset-2": {},
                    }
                }
            },
        }

        with patch("steam_market_to_excel.steam_render_page", return_value=fake_payload):
            with patch("steam_market_to_excel.fetch_commodity_lowest_price", return_value=(None, None)):
                dataframe = sme.build_lowest_listing_snapshot_dataframe(
                    session=Mock(),
                    market_hash_name="Gallery Case",
                    currency=1,
                    country="US",
                    language="english",
                    steam_max_retries=1,
                )

        self.assertEqual(len(dataframe), 1)
        self.assertEqual(dataframe.iloc[0]["listing_id"], "listing-1")
        self.assertEqual(dataframe.iloc[0]["page"], 1)
        self.assertEqual(dataframe.iloc[0]["price"], 1.15)
        self.assertTrue(pd.isna(dataframe.iloc[0]["float"]))
        self.assertTrue(pd.isna(dataframe.iloc[0]["wear"]))
        self.assertEqual(dataframe.iloc[0]["price_source"], "render_listing")
        self.assertIn("snapshot_timestamp", dataframe.columns)

    def test_build_lowest_listing_snapshot_dataframe_uses_market_fallback_when_listing_price_is_zero(self):
        fake_payload = {
            "success": True,
            "total_count": 50,
            "lowest_price": "$2.45",
            "listinginfo": {
                "listing-1": {
                    "price": 0,
                    "fee": 0,
                    "currencyid": 1,
                    "asset": {"id": "asset-1"},
                },
            },
            "assets": {
                "730": {
                    "2": {
                        "asset-1": {},
                    }
                }
            },
        }

        with patch("steam_market_to_excel.steam_render_page", return_value=fake_payload):
            with patch("steam_market_to_excel.fetch_commodity_lowest_price", return_value=(2.45, "priceoverview")):
                dataframe = sme.build_lowest_listing_snapshot_dataframe(
                    session=Mock(),
                    market_hash_name="Gallery Case",
                    currency=1,
                    country="US",
                    language="english",
                    steam_max_retries=1,
                )

        self.assertEqual(len(dataframe), 1)
        self.assertEqual(dataframe.iloc[0]["price"], 2.45)
        self.assertEqual(dataframe.iloc[0]["price_source"], "priceoverview")

    def test_build_lowest_listing_snapshot_dataframe_prefers_lower_market_level_price(self):
        fake_payload = {
            "success": True,
            "total_count": 50,
            "lowest_price": "$2.45",
            "listinginfo": {
                "listing-1": {
                    "price": 250,
                    "fee": 10,
                    "currencyid": 1,
                    "asset": {"id": "asset-1"},
                },
                "listing-2": {
                    "price": 255,
                    "fee": 10,
                    "currencyid": 1,
                    "asset": {"id": "asset-2"},
                },
            },
            "assets": {
                "730": {
                    "2": {
                        "asset-1": {},
                        "asset-2": {},
                    }
                }
            },
        }

        with patch("steam_market_to_excel.steam_render_page", return_value=fake_payload):
            with patch("steam_market_to_excel.fetch_commodity_lowest_price", return_value=(2.22, "itemordershistogram")):
                dataframe = sme.build_lowest_listing_snapshot_dataframe(
                    session=Mock(),
                    market_hash_name="Gallery Case",
                    currency=1,
                    country="US",
                    language="english",
                    steam_max_retries=1,
                )

        self.assertEqual(len(dataframe), 1)
        self.assertEqual(dataframe.iloc[0]["price"], 2.22)
        self.assertEqual(dataframe.iloc[0]["price_source"], "itemordershistogram")

    def test_build_lowest_listing_snapshot_dataframe_creates_row_when_render_has_no_listings(self):
        fake_payload = {
            "success": True,
            "total_count": 0,
            "listinginfo": {},
            "assets": {},
        }

        with patch("steam_market_to_excel.steam_render_page", return_value=fake_payload):
            with patch("steam_market_to_excel.fetch_commodity_lowest_price", return_value=(0.97, "itemordershistogram")):
                dataframe = sme.build_lowest_listing_snapshot_dataframe(
                    session=Mock(),
                    market_hash_name="Fracture Case",
                    currency=1,
                    country="US",
                    language="english",
                    steam_max_retries=1,
                )

        self.assertEqual(len(dataframe), 1)
        self.assertEqual(dataframe.iloc[0]["price"], 0.97)
        self.assertEqual(dataframe.iloc[0]["price_source"], "itemordershistogram")
        self.assertEqual(dataframe.iloc[0]["listing_id"], "")

    def test_save_table_and_load_table_support_csv(self):
        dataframe = sme.rows_to_dataframe(
            [
                sme.ListingRow(
                    listing_id="listing-1",
                    asset_id="asset-1",
                    page=1,
                    price=1.5,
                    currency="1",
                    float_value=0.12,
                    wear="Minimal Wear",
                    paint_seed=7,
                    has_stickers=True,
                    sticker_count=1,
                    inspect_link="steam://inspect",
                )
            ]
        )

        temp_dir = make_workspace_temp_dir("save_load_csv")
        output_path = temp_dir / "sample.csv"
        saved_path = sme.save_table(dataframe, str(output_path))
        loaded_dataframe = sme.load_table(str(saved_path))

        self.assertEqual(saved_path, output_path)
        self.assertEqual(len(loaded_dataframe), 1)
        self.assertEqual(loaded_dataframe.iloc[0]["listing_id"], "listing-1")

    def test_filter_dataframe_applies_requested_rules(self):
        dataframe = pd.DataFrame(
            [
                {"float": 0.05, "price": 2.0, "wear": "Factory New", "paint_seed": 10, "has_stickers": True, "sticker_count": 2},
                {"float": 0.20, "price": 1.0, "wear": "Field-Tested", "paint_seed": 11, "has_stickers": None, "sticker_count": None},
            ]
        )
        args = argparse.Namespace(
            min_float=0.04,
            max_float=0.10,
            min_price=1.5,
            max_price=2.5,
            wear="Factory New",
            paint_seed=10,
            has_stickers=True,
            no_stickers=False,
            min_sticker_count=1,
            max_sticker_count=3,
        )

        filtered_dataframe = sme.filter_dataframe(dataframe, args)

        self.assertEqual(len(filtered_dataframe), 1)
        self.assertEqual(filtered_dataframe.iloc[0]["paint_seed"], 10)

    def test_build_stats_lines_returns_summary_text(self):
        dataframe = pd.DataFrame(
            [
                {"price": 1.0, "float": 0.10, "wear": "Minimal Wear", "sticker_count": 1},
                {"price": 3.0, "float": 0.20, "wear": "Field-Tested", "sticker_count": 0},
            ]
        )

        lines = sme.build_stats_lines(dataframe, "exports/sample.xlsx")

        self.assertIn("Stats for exports/sample.xlsx", lines[0])
        self.assertIn("rows: 2", lines)
        self.assertIn("price_min: 1.00", lines)
        self.assertIn("price_max: 3.00", lines)

    def test_build_show_dataframe_formats_terminal_output_columns(self):
        dataframe = pd.DataFrame(
            [
                {
                    "page": 1,
                    "float": 0.1234567,
                    "price": 2,
                    "has_stickers": True,
                    "wear": "Minimal Wear",
                    "paint_seed": 7,
                    "listing_id": "listing-1",
                }
            ]
        )

        display_dataframe = sme.build_show_dataframe(dataframe)

        self.assertEqual(
            list(display_dataframe.columns),
            ["#", "page", "float", "price", "stickers", "wear", "paint_seed", "listing_id"],
        )
        self.assertEqual(display_dataframe.iloc[0]["#"], 1)
        self.assertEqual(display_dataframe.iloc[0]["float"], "0.123457")
        self.assertEqual(display_dataframe.iloc[0]["price"], "2.00")
        self.assertEqual(display_dataframe.iloc[0]["stickers"], "yes")

    def test_build_show_dataframe_leaves_missing_sticker_values_blank(self):
        dataframe = pd.DataFrame(
            [
                {
                    "page": 1,
                    "float": None,
                    "price": 2.45,
                    "has_stickers": None,
                    "wear": None,
                    "paint_seed": None,
                    "listing_id": "case-row",
                }
            ]
        )

        display_dataframe = sme.build_show_dataframe(dataframe)

        self.assertEqual(display_dataframe.iloc[0]["stickers"], "")

    def test_format_terminal_table_draws_a_readable_grid(self):
        source_dataframe = pd.DataFrame(
            [
                {"page": "1", "float": "0.123456", "price": "2.00", "wear": "Minimal Wear"},
                {"page": "2", "float": "0.200000", "price": "3.50", "wear": "Field-Tested"},
            ]
        )
        display_dataframe = sme.build_show_dataframe(
            source_dataframe,
            columns=["page", "float", "price", "wear"],
            limit=None,
        )

        table_text = sme.format_terminal_table(display_dataframe)

        self.assertIn("#", table_text)
        self.assertIn("page", table_text)
        self.assertIn("Minimal Wear", table_text)
        self.assertIn("-+-", table_text)

    @patch("steam_market_to_excel.iter_listings")
    @patch("steam_market_to_excel.requests.Session")
    def test_run_fetch_reuses_market_name_based_output_file(self, mocked_session_cls, mocked_iter_listings):
        mocked_session = Mock()
        mocked_session.headers = Mock()
        mocked_session.headers.update = Mock()
        mocked_session_cls.return_value = mocked_session
        mocked_iter_listings.return_value = [
            sme.ListingRow(
                listing_id="listing-1",
                asset_id="asset-1",
                page=1,
                price=1.5,
                currency="1",
                float_value=0.12,
                wear="Minimal Wear",
                paint_seed=7,
                has_stickers=True,
                sticker_count=1,
                inspect_link="steam://inspect",
            )
        ]

        temp_dir = make_workspace_temp_dir("run_fetch_default_name")
        args = argparse.Namespace(
            market_hash_name="AK-47 | Safari Mesh (Minimal Wear)",
            output=None,
            currency=1,
            country="US",
            language="english",
            steam_page_delay=0,
            steam_max_retries=1,
        )
        buffer = io.StringIO()

        with patch.object(sme, "DEFAULT_OUTPUT_DIR", temp_dir):
            with redirect_stdout(buffer):
                sme.run_fetch(args)

        output_text = buffer.getvalue()
        output_path = temp_dir / "skins" / "ak_47_safari_mesh_minimal_wear.xlsx"
        self.assertTrue(output_path.exists())
        self.assertIn(str(output_path), output_text)
        self.assertTrue(
            "Exported 1 listings to" in output_text
            or "Synced 1 current listings to" in output_text
        )

    @patch("steam_market_to_excel.build_lowest_listing_snapshot_dataframe")
    @patch("steam_market_to_excel.iter_listings")
    @patch("steam_market_to_excel.requests.Session")
    def test_fetch_market_dataframe_uses_lowest_listing_snapshot_for_no_wear_items(
        self,
        mocked_session_cls,
        mocked_iter_listings,
        mocked_build_lowest_listing_snapshot_dataframe,
    ):
        mocked_session = Mock()
        mocked_session.headers = Mock()
        mocked_session.headers.update = Mock()
        mocked_session_cls.return_value = mocked_session
        mocked_build_lowest_listing_snapshot_dataframe.return_value = pd.DataFrame(
            [{"listing_id": "listing-1", "price": 1.15, "wear": None}]
        )
        args = argparse.Namespace(
            currency=1,
            country="US",
            language="english",
            steam_page_delay=0.5,
            steam_max_retries=1,
        )

        dataframe = sme.fetch_market_dataframe(args, "Gallery Case")

        mocked_build_lowest_listing_snapshot_dataframe.assert_called_once()
        mocked_iter_listings.assert_not_called()
        self.assertEqual(len(dataframe), 1)
        self.assertEqual(dataframe.iloc[0]["price"], 1.15)

    @patch("steam_market_to_excel.iter_listings")
    @patch("steam_market_to_excel.requests.Session")
    def test_run_fetch_supports_inline_filter_sort_and_show(self, mocked_session_cls, mocked_iter_listings):
        mocked_session = Mock()
        mocked_session.headers = Mock()
        mocked_session.headers.update = Mock()
        mocked_session_cls.return_value = mocked_session
        mocked_iter_listings.return_value = [
            sme.ListingRow(
                listing_id="listing-2",
                asset_id="asset-2",
                page=1,
                price=2.5,
                currency="1",
                float_value=0.08,
                wear="Minimal Wear",
                paint_seed=9,
                has_stickers=True,
                sticker_count=1,
                inspect_link="steam://inspect2",
            ),
            sme.ListingRow(
                listing_id="listing-3",
                asset_id="asset-3",
                page=1,
                price=9.5,
                currency="1",
                float_value=0.20,
                wear="Field-Tested",
                paint_seed=10,
                has_stickers=None,
                sticker_count=None,
                inspect_link="steam://inspect3",
            ),
        ]

        temp_dir = make_workspace_temp_dir("run_fetch_inline")
        args = argparse.Namespace(
            market_hash_name="AK-47 | Safari Mesh (Minimal Wear)",
            output=None,
            currency=1,
            country="US",
            language="english",
            steam_page_delay=0,
            steam_max_retries=1,
            min_float=None,
            max_float=0.10,
            min_price=None,
            max_price=5.0,
            wear=None,
            paint_seed=None,
            has_stickers=False,
            no_stickers=False,
            min_sticker_count=None,
            max_sticker_count=None,
            sort_by=["float"],
            descending=False,
            show=True,
            limit=25,
            columns=None,
        )
        buffer = io.StringIO()

        with patch.object(sme, "DEFAULT_OUTPUT_DIR", temp_dir):
            with redirect_stdout(buffer):
                sme.run_fetch(args)

        output_text = buffer.getvalue()
        self.assertIn("Inline query matched 1 rows", output_text)
        self.assertIn("Showing 1 of 1 matching rows", output_text)
        self.assertIn("listing-2", output_text)
        self.assertNotIn("listing-3", output_text)

    @patch("steam_market_to_excel.iter_listings")
    @patch("steam_market_to_excel.requests.Session")
    def test_run_fetch_syncs_existing_file_in_place(self, mocked_session_cls, mocked_iter_listings):
        mocked_session = Mock()
        mocked_session.headers = Mock()
        mocked_session.headers.update = Mock()
        mocked_session_cls.return_value = mocked_session
        mocked_iter_listings.return_value = [
            sme.ListingRow(
                listing_id="listing-2",
                asset_id="asset-2",
                page=1,
                price=2.5,
                currency="1",
                float_value=0.08,
                wear="Minimal Wear",
                paint_seed=9,
                has_stickers=None,
                sticker_count=None,
                inspect_link="steam://inspect2",
            ),
            sme.ListingRow(
                listing_id="listing-3",
                asset_id="asset-3",
                page=1,
                price=3.5,
                currency="1",
                float_value=0.09,
                wear="Minimal Wear",
                paint_seed=10,
                has_stickers=True,
                sticker_count=2,
                inspect_link="steam://inspect3",
            ),
        ]

        temp_dir = make_workspace_temp_dir("run_fetch_sync")
        existing_output_path = temp_dir / "skins" / "ak_47_safari_mesh_minimal_wear.xlsx"
        existing_output_path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(
            [
                {"listing_id": "listing-1", "price": 1.0},
                {"listing_id": "listing-2", "price": 2.0},
            ]
        ).to_excel(existing_output_path, index=False)

        args = argparse.Namespace(
            market_hash_name="AK-47 | Safari Mesh (Minimal Wear)",
            output=None,
            currency=1,
            country="US",
            language="english",
            steam_page_delay=0,
            steam_max_retries=1,
        )
        buffer = io.StringIO()

        with patch.object(sme, "DEFAULT_OUTPUT_DIR", temp_dir):
            with redirect_stdout(buffer):
                sme.run_fetch(args)

            synced_dataframe = pd.read_excel(existing_output_path)

        output_text = buffer.getvalue()
        self.assertEqual(len(synced_dataframe), 2)
        self.assertEqual(set(synced_dataframe["listing_id"]), {"listing-2", "listing-3"})
        self.assertIn("Synced 2 current listings", output_text)
        self.assertIn("added 1, removed 1, unchanged 1", output_text)

    def test_sync_market_dataframe_appends_no_wear_price_history(self):
        temp_dir = make_workspace_temp_dir("sync_no_wear_history")
        output_path = temp_dir / "cases" / "gallery_case.xlsx"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        previous_dataframe = pd.DataFrame(
            [
                {
                    "listing_id": "old-listing",
                    "price": 2.10,
                    "market_hash_name": "Gallery Case",
                    "snapshot_date": "2026-04-28",
                    "snapshot_timestamp": "2026-04-28T12:00:00-07:00",
                }
            ]
        )
        previous_dataframe.to_excel(output_path, index=False)
        current_dataframe = pd.DataFrame(
            [{"listing_id": "new-listing", "price": 2.45, "wear": None}]
        )

        with patch.object(sme, "DEFAULT_OUTPUT_DIR", temp_dir):
            result = sme.sync_market_dataframe(
                dataframe=current_dataframe,
                market_hash_name="Gallery Case",
                output_name=None,
                update_latest=False,
            )

        saved_dataframe = pd.read_excel(output_path)
        self.assertEqual(len(saved_dataframe), 2)
        self.assertEqual(saved_dataframe.iloc[0]["listing_id"], "old-listing")
        self.assertEqual(saved_dataframe.iloc[1]["listing_id"], "new-listing")
        self.assertIn("snapshot_date", saved_dataframe.columns)
        self.assertIn("snapshot_timestamp", saved_dataframe.columns)
        self.assertIn("Appended 1 lowest-price snapshot row(s)", sme.build_fetch_result_summary(result))

    def test_sync_market_dataframe_keeps_no_wear_history_when_current_snapshot_is_empty(self):
        temp_dir = make_workspace_temp_dir("sync_no_wear_history_empty")
        output_path = temp_dir / "cases" / "gallery_case.xlsx"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        previous_dataframe = pd.DataFrame(
            [
                {
                    "listing_id": "old-listing",
                    "price": 2.10,
                    "market_hash_name": "Gallery Case",
                    "snapshot_date": "2026-04-28",
                    "snapshot_timestamp": "2026-04-28T12:00:00-07:00",
                }
            ]
        )
        previous_dataframe.to_excel(output_path, index=False)

        with patch.object(sme, "DEFAULT_OUTPUT_DIR", temp_dir):
            result = sme.sync_market_dataframe(
                dataframe=pd.DataFrame(columns=previous_dataframe.columns),
                market_hash_name="Gallery Case",
                output_name=None,
                update_latest=False,
            )

        saved_dataframe = pd.read_excel(output_path)
        self.assertEqual(len(saved_dataframe), 1)
        self.assertEqual(saved_dataframe.iloc[0]["listing_id"], "old-listing")
        self.assertIn("Steam did not return a current active listing price", sme.build_fetch_result_summary(result))
        self.assertIn("Kept 1 historical snapshot row(s)", sme.build_fetch_result_summary(result))

    @patch("steam_market_to_excel.fetch_market_dataframe")
    def test_run_fetch_many_processes_multiple_items(self, mocked_fetch_market_dataframe):
        mocked_fetch_market_dataframe.side_effect = [
            pd.DataFrame([{"listing_id": "listing-1", "price": 1.0}]),
            pd.DataFrame([{"listing_id": "listing-2", "price": 2.0}]),
        ]

        temp_dir = make_workspace_temp_dir("run_fetch_many")
        args = argparse.Namespace(
            market_hash_names=["AK-47 | Redline (Field-Tested)", "M4A1-S | Basilisk (Field-Tested)"],
            items_file=None,
            currency=1,
            country="US",
            language="english",
            steam_page_delay=0,
            steam_max_retries=1,
            workers=1,
            min_float=None,
            max_float=None,
            min_price=None,
            max_price=None,
            wear=None,
            paint_seed=None,
            has_stickers=False,
            no_stickers=False,
            min_sticker_count=None,
            max_sticker_count=None,
            sort_by=None,
            descending=False,
            show=False,
            limit=25,
            columns=None,
        )
        buffer = io.StringIO()

        with patch.object(sme, "DEFAULT_OUTPUT_DIR", temp_dir):
            with redirect_stdout(buffer):
                sme.run_fetch_many(args)

        output_text = buffer.getvalue()
        self.assertTrue((temp_dir / "skins" / "ak_47_redline_field_tested.xlsx").exists())
        self.assertTrue((temp_dir / "skins" / "m4a1_s_basilisk_field_tested.xlsx").exists())
        self.assertIn("Fetching 2 items with 1 worker(s)...", output_text)

    def test_run_sort_creates_sorted_output_file(self):
        dataframe = pd.DataFrame(
            [
                {"listing_id": "b", "float": 0.20, "price": 2.0},
                {"listing_id": "a", "float": 0.10, "price": 1.0},
            ]
        )

        temp_dir = make_workspace_temp_dir("run_sort")
        input_path = temp_dir / "sample.csv"
        dataframe.to_csv(input_path, index=False)
        args = argparse.Namespace(
            input_path=str(input_path),
            by=["float"],
            descending=False,
            output=None,
        )

        with patch.object(sme, "DEFAULT_OUTPUT_DIR", temp_dir):
            sme.run_sort(args)
            resolved_latest = sme.resolve_input_path("latest")
        output_path = input_path.with_name("sample_sorted.csv")
        sorted_dataframe = pd.read_csv(output_path)

        self.assertEqual(list(sorted_dataframe["listing_id"]), ["a", "b"])
        self.assertEqual(resolved_latest, output_path)

    def test_run_filter_creates_filtered_output_file(self):
        dataframe = pd.DataFrame(
            [
                {"listing_id": "keep", "float": 0.05, "price": 2.0, "wear": "Factory New", "paint_seed": 1, "has_stickers": True, "sticker_count": 1},
                {"listing_id": "drop", "float": 0.40, "price": 0.5, "wear": "Well-Worn", "paint_seed": 2, "has_stickers": None, "sticker_count": None},
            ]
        )

        temp_dir = make_workspace_temp_dir("run_filter")
        input_path = temp_dir / "sample.csv"
        dataframe.to_csv(input_path, index=False)
        args = argparse.Namespace(
            input_path=str(input_path),
            min_float=None,
            max_float=0.10,
            min_price=None,
            max_price=None,
            wear=None,
            paint_seed=None,
            has_stickers=False,
            no_stickers=False,
            min_sticker_count=None,
            max_sticker_count=None,
            output=None,
        )

        with patch.object(sme, "DEFAULT_OUTPUT_DIR", temp_dir):
            sme.run_filter(args)
            resolved_latest = sme.resolve_input_path("latest")
        output_path = input_path.with_name("sample_filtered.csv")
        filtered_dataframe = pd.read_csv(output_path)

        self.assertEqual(list(filtered_dataframe["listing_id"]), ["keep"])
        self.assertEqual(resolved_latest, output_path)

    def test_run_stats_prints_summary(self):
        dataframe = pd.DataFrame(
            [
                {"price": 1.0, "float": 0.10, "wear": "Minimal Wear", "sticker_count": 1},
                {"price": 3.0, "float": 0.20, "wear": "Field-Tested", "sticker_count": 0},
            ]
        )

        temp_dir = make_workspace_temp_dir("run_stats")
        input_path = temp_dir / "sample.csv"
        dataframe.to_csv(input_path, index=False)
        args = argparse.Namespace(input_path=str(input_path))
        buffer = io.StringIO()

        with redirect_stdout(buffer):
            sme.run_stats(args)

        output_text = buffer.getvalue()
        self.assertIn("Stats for", output_text)
        self.assertIn("rows: 2", output_text)

    def test_run_show_prints_matching_rows(self):
        dataframe = pd.DataFrame(
            [
                {"page": 1, "float": 0.05, "price": 2.0, "wear": "Factory New", "paint_seed": 1, "has_stickers": True, "sticker_count": 1, "listing_id": "keep"},
                {"page": 2, "float": 0.20, "price": 3.0, "wear": "Field-Tested", "paint_seed": 2, "has_stickers": None, "sticker_count": None, "listing_id": "drop"},
            ]
        )

        temp_dir = make_workspace_temp_dir("run_show")
        input_path = temp_dir / "sample.csv"
        dataframe.to_csv(input_path, index=False)
        args = argparse.Namespace(
            input_path=str(input_path),
            min_float=None,
            max_float=0.10,
            min_price=None,
            max_price=None,
            wear=None,
            paint_seed=None,
            has_stickers=False,
            no_stickers=False,
            min_sticker_count=None,
            max_sticker_count=None,
            sort_by=["float"],
            descending=False,
            limit=25,
            columns=None,
        )
        buffer = io.StringIO()

        with redirect_stdout(buffer):
            sme.run_show(args)

        output_text = buffer.getvalue()
        self.assertIn("Showing 1 of 1 matching rows", output_text)
        self.assertIn("keep", output_text)
        self.assertNotIn("drop", output_text)

    def test_run_use_sets_latest_pointer(self):
        temp_dir = make_workspace_temp_dir("run_use")
        input_path = temp_dir / "sample.csv"
        input_path.write_text("listing_id\nkeep\n", encoding="utf-8")
        args = argparse.Namespace(input_path=str(input_path))
        buffer = io.StringIO()

        with patch.object(sme, "DEFAULT_OUTPUT_DIR", temp_dir):
            with redirect_stdout(buffer):
                sme.run_use(args)

            resolved_latest = sme.resolve_input_path("latest")

        output_text = buffer.getvalue()
        self.assertEqual(resolved_latest, input_path)
        self.assertIn("latest now points to", output_text)

    @patch("steam_market_to_excel.run_fetch")
    def test_main_uses_legacy_style_as_fetch_command(self, mocked_run_fetch):
        sme.main(["AK-47 | Redline (Field-Tested)"])

        mocked_run_fetch.assert_called_once()
        args = mocked_run_fetch.call_args.args[0]
        self.assertEqual(args.command, "fetch")
        self.assertEqual(args.market_hash_name, "AK-47 | Redline (Field-Tested)")

    @patch("steam_market_to_excel.run_sort")
    def test_main_uses_sort_subcommand(self, mocked_run_sort):
        sme.main(["sort", "exports/sample.xlsx", "--by", "float"])

        mocked_run_sort.assert_called_once()
        args = mocked_run_sort.call_args.args[0]
        self.assertEqual(args.command, "sort")
        self.assertEqual(args.by, ["float"])

    @patch("steam_market_to_excel.run_filter")
    def test_main_uses_filter_subcommand(self, mocked_run_filter):
        sme.main(["filter", "exports/sample.xlsx", "--max-float", "0.15"])

        mocked_run_filter.assert_called_once()
        args = mocked_run_filter.call_args.args[0]
        self.assertEqual(args.command, "filter")
        self.assertEqual(args.max_float, 0.15)

    @patch("steam_market_to_excel.run_stats")
    def test_main_uses_stats_subcommand(self, mocked_run_stats):
        sme.main(["stats", "exports/sample.xlsx"])

        mocked_run_stats.assert_called_once()
        args = mocked_run_stats.call_args.args[0]
        self.assertEqual(args.command, "stats")

    @patch("steam_market_to_excel.run_use")
    def test_main_uses_use_subcommand(self, mocked_run_use):
        sme.main(["use", "exports/sample.xlsx"])

        mocked_run_use.assert_called_once()
        args = mocked_run_use.call_args.args[0]
        self.assertEqual(args.command, "use")

    @patch("steam_market_to_excel.run_fetch_many")
    def test_main_uses_fetch_many_subcommand(self, mocked_run_fetch_many):
        sme.main(["fetch-many", "AK-47 | Redline (Field-Tested)"])

        mocked_run_fetch_many.assert_called_once()
        args = mocked_run_fetch_many.call_args.args[0]
        self.assertEqual(args.command, "fetch-many")

    @patch("steam_market_to_excel.run_show")
    def test_main_uses_show_subcommand(self, mocked_run_show):
        sme.main(["show", "exports/sample.xlsx", "--max-float", "0.10"])

        mocked_run_show.assert_called_once()
        args = mocked_run_show.call_args.args[0]
        self.assertEqual(args.command, "show")
        self.assertEqual(args.max_float, 0.10)

    @patch("steam_market_to_excel.run_fetch")
    def test_main_uses_fetch_subcommand(self, mocked_run_fetch):
        sme.main(["fetch", "AK-47 | Redline (Field-Tested)"])

        mocked_run_fetch.assert_called_once()
        args = mocked_run_fetch.call_args.args[0]
        self.assertEqual(args.command, "fetch")
        self.assertEqual(args.market_hash_name, "AK-47 | Redline (Field-Tested)")


if __name__ == "__main__":
    unittest.main()
