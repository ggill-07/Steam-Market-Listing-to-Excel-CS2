# Steam Market Listing to Excel (CS2)

A command-line tool for scraping CS2 Steam Community Market listings, saving them to Excel or CSV, and then exploring the saved data from the terminal.

The project reads the metadata it can directly from Steam's own market payload instead of depending on CSFloat at runtime.

## What the tool can do

- `fetch` Steam Community Market listings for a CS2 item and save them to a file
- `sort` an existing export file by one or more columns
- `filter` an existing export file and write only matching rows
- `show` matching rows directly in the terminal
- `stats` print summary information for an existing export file

The older direct fetch style still works too:

```bash
python src/steam_market_to_excel.py "AK-47 | Redline (Field-Tested)"
```

## Exported columns

- `listing_id`
- `asset_id`
- `page`
- `price`
- `currency`
- `float`
- `wear`
- `paint_seed`
- `has_stickers`
- `sticker_count`
- `inspect_link`

## Current project files

- `src/steam_market_to_excel.py` - the real CLI tool
- `src/steam_market_to_excel_explained.py` - beginner-friendly explained copy of the main scraper/export file
- `tests/test_steam_market_to_excel.py` - automated tests for the real script

## Requirements

- Python 3.10+
- `requests`
- `pandas`
- `openpyxl`

Install dependencies:

```bash
python -m pip install requests pandas openpyxl
```

## How it works

- Steam listing pages are requested directly from the market render endpoint
- the scraper requests up to `100` listings per Steam page
- float, paint seed, sticker presence, sticker count, and inspect-link data are read from Steam asset data when Steam includes them
- temporary Steam failures like `429`, `500`, `502`, `503`, and `504` are retried automatically
- plain output filenames are saved into the `exports/` folder by default
- file-based commands can use `latest` as a shortcut for the newest export in `exports/`

## Basic usage

Fetch and save listings:

```bash
python src/steam_market_to_excel.py fetch "AK-47 | Redline (Field-Tested)" -o redline.xlsx
```

If you use PowerShell often, you can create a short helper function so you can run the tool as `smte` instead of typing the full Python command each time:

```powershell
function smte { python "D:\RUN\GITHUB\REPOS\STEAM_MARKET_TOOL\Steam-Market-Listing-to-Excel-CS2\src\steam_market_to_excel.py" @args }
```

After that, the same fetch command becomes:

```powershell
smte fetch "AK-47 | Redline (Field-Tested)" -o redline.xlsx
```

If you use a plain filename with `-o`, it is saved to:

```bash
exports/redline.xlsx
```

Use the old direct style if you prefer:

```bash
python src/steam_market_to_excel.py "AK-47 | Redline (Field-Tested)" -o redline.xlsx
```

You can also use the PowerShell shortcut with the newer file-based commands:

```powershell
smte show latest --max-float 0.10 --sort-by float --limit 10
smte stats latest
```

## CLI commands

### `fetch`

Scrape Steam and save a new export file.

```bash
python src/steam_market_to_excel.py fetch "MP5-SD | Neon Squeezer (Field-Tested)" -o mp5_neon_squeezer_ft.xlsx
```

Useful options:

- `--currency` - Steam currency ID, default `1` for USD
- `--country` - Steam country code, default `US`
- `--language` - Steam language, default `english`
- `--steam-page-delay` - seconds to wait between Steam page requests, default `1.0`
- `--steam-max-retries` - retry count for temporary Steam errors, default `5`
- `-o/--output` - plain filenames go into `exports/`; custom paths are respected

### `show`

Load an existing export file, optionally filter/sort it, and print matching rows in the terminal.

```bash
python src/steam_market_to_excel.py show latest --max-float 0.10 --sort-by float --limit 10
```

Examples:

```bash
python src/steam_market_to_excel.py show latest --has-stickers --sort-by price --descending
python src/steam_market_to_excel.py show exports/ak_47_safari_mesh_mw.xlsx --wear "Minimal Wear" --limit 20
```

Useful options:

- `--min-float` / `--max-float`
- `--min-price` / `--max-price`
- `--wear`
- `--paint-seed`
- `--has-stickers` / `--no-stickers`
- `--min-sticker-count` / `--max-sticker-count`
- `--sort-by`
- `--descending`
- `--limit`
- `--columns`

### `sort`

Sort an existing export file and write a new file.

```bash
python src/steam_market_to_excel.py sort latest --by float price
```

If `-o/--output` is omitted, the tool derives a name such as:

```bash
exports/redline_sorted.xlsx
```

### `filter`

Filter an existing export file and write a new file.

```bash
python src/steam_market_to_excel.py filter latest --max-float 0.10 --has-stickers
```

If `-o/--output` is omitted, the tool derives a name such as:

```bash
exports/redline_filtered.xlsx
```

### `stats`

Print a quick summary for an existing export file.

```bash
python src/steam_market_to_excel.py stats latest
```

## The `latest` shortcut

For file-based commands, you can use:

```bash
latest
```

instead of typing a full file path. The tool will pick the newest `.xlsx`, `.xls`, or `.csv` file inside `exports/`.

This works with:

- `show`
- `sort`
- `filter`
- `stats`

## Running tests

Run the full test suite with:

```bash
python -B -m unittest discover -s tests -v
```

The current test suite covers:

- Steam parsing helpers
- retry behavior
- DataFrame/export helpers
- CLI argument parsing
- command dispatch
- file-based CLI workflows including `show`, `sort`, `filter`, `stats`, and `latest`

## Notes

- Steam can still rate-limit or temporarily fail on large crawls
- this is best treated as a personal, best-effort scraper rather than a guaranteed long-running data pipeline
- some metadata depends on what Steam includes in the asset payload for a given listing
- the main file to run is `src/steam_market_to_excel.py`
