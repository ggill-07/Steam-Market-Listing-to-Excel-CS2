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

    def test_resolve_output_path_keeps_custom_folder_paths(self):
        result = sme.resolve_output_path("custom_folder/result.xlsx")
        self.assertEqual(result, Path("custom_folder") / "result.xlsx")

    def test_resolve_input_path_supports_latest_keyword(self):
        temp_dir = make_workspace_temp_dir("resolve_latest")
        older_file = temp_dir / "older.xlsx"
        newer_file = temp_dir / "newer.xlsx"
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
        older_file = temp_dir / "older.xlsx"
        pinned_file = temp_dir / "pinned.xlsx"
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
        self.assertEqual(args.output, "steam_listings.xlsx")

    def test_parse_args_supports_fetch_subcommand(self):
        args = sme.parse_args(
            ["fetch", "AK-47 | Redline (Field-Tested)", "-o", "custom.xlsx"]
        )

        self.assertEqual(args.command, "fetch")
        self.assertEqual(args.market_hash_name, "AK-47 | Redline (Field-Tested)")
        self.assertEqual(args.output, "custom.xlsx")

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
            ["steam_market_to_excel"],
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
            ["page", "float", "price", "stickers", "wear", "paint_seed", "listing_id"],
        )
        self.assertEqual(display_dataframe.iloc[0]["float"], "0.123457")
        self.assertEqual(display_dataframe.iloc[0]["price"], "2.00")
        self.assertEqual(display_dataframe.iloc[0]["stickers"], "yes")

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
