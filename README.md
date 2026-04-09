# Steam Market Listing to Excel (CS2)

A command-line tool that exports CS2 Steam Community Market listings to Excel.

The project now pulls the useful metadata it can directly from Steam's own market payload instead of depending on CSFloat at runtime.

## What it exports

- Listing ID
- Asset ID
- Page number
- Price
- Currency
- Float value
- Wear tier (calculated from float)
- Paint seed
- Sticker presence
- Sticker count
- Inspect link

## Current project files

- `src/steam_market_to_excel.py` - the real script you run
- `src/steam_market_to_excel_explained.py` - a beginner-friendly learning copy with heavy comments
- `tests/test_steam_market_to_excel.py` - automated tests for the main script

## Requirements

- Python 3.10+
- `requests`
- `pandas`
- `openpyxl`

Install dependencies:

```bash
python -m pip install requests pandas openpyxl
```

## How it works now

- The script requests Steam market listing pages directly.
- It fetches up to `100` listings per Steam page request.
- It reads float / paint seed / sticker-related information from Steam's asset payload when Steam includes it.
- It retries temporary Steam errors like `429`, `500`, `502`, `503`, and `504`.
- By default, plain output filenames are saved inside the `exports/` folder.
- It writes the final results to an `.xlsx` file.

## Usage

Basic example:

```bash
python src/steam_market_to_excel.py "AK-47 | Redline (Field-Tested)" -o redline_listings.xlsx
```

Example used during testing:

```bash
python src/steam_market_to_excel.py "MP5-SD | Neon Squeezer (Field-Tested)" -o mp5_neon_squeezer_ft.xlsx --steam-page-delay 2.0 --steam-max-retries 8
```

With the current behavior, that example saves to:

```bash
exports/mp5_neon_squeezer_ft.xlsx
```

## Command line options

- `--currency` - Steam currency ID, default `1` for USD
- `--country` - Steam country code, default `US`
- `--language` - Steam language, default `english`
- `--steam-page-delay` - seconds to wait between Steam page requests, default `1.0`
- `--steam-max-retries` - retry count for temporary Steam errors, default `5`
- `-o/--output` - plain filenames go into `exports/`; custom paths are respected

## Running tests

Run the full test suite with:

```bash
python -B -m unittest discover -s tests -v
```

At the moment, the automated test file covers the main logic with mocked Steam responses and export behavior.

## Important notes

- Steam can still rate-limit or temporarily fail on large crawls.
- This tool is best treated as a personal, best-effort scraper rather than a guaranteed long-running data pipeline.
- Some metadata depends on what Steam includes in the asset payload for a given listing.
- The explained file is meant for learning and debugging, but the main file is the one you should normally run.
