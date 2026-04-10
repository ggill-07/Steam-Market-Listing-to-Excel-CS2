"""Beginner-friendly tests for steam_market_to_excel.py.

This file uses Python's built-in unittest library.

Big picture:
- A test calls one small part of your code.
- It checks that the result matches what you expected.
- Some tests use fake objects so we do not call the real Steam site or float API.

You can run these tests with:
    python -B -m unittest discover -s tests -v
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


# Make sure Python can import the file from the src/ folder.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import steam_market_to_excel as sme


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

    @patch("steam_market_to_excel.run_fetch")
    def test_main_uses_legacy_style_as_fetch_command(self, mocked_run_fetch):
        sme.main(["AK-47 | Redline (Field-Tested)"])

        mocked_run_fetch.assert_called_once()
        args = mocked_run_fetch.call_args.args[0]
        self.assertEqual(args.command, "fetch")
        self.assertEqual(args.market_hash_name, "AK-47 | Redline (Field-Tested)")

    @patch("steam_market_to_excel.run_fetch")
    def test_main_uses_fetch_subcommand(self, mocked_run_fetch):
        sme.main(["fetch", "AK-47 | Redline (Field-Tested)"])

        mocked_run_fetch.assert_called_once()
        args = mocked_run_fetch.call_args.args[0]
        self.assertEqual(args.command, "fetch")
        self.assertEqual(args.market_hash_name, "AK-47 | Redline (Field-Tested)")


if __name__ == "__main__":
    unittest.main()
