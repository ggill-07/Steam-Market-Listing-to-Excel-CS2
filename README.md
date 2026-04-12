# Steam Market Listing to CLI Tool (CS2)

A command-line tool for scraping CS2 Steam Community Market listings, saving them to Excel or CSV, and then exploring the saved data from the terminal.

The tool grew out of a simple problem: manually digging through thousands of Steam Market listings to find the few items that actually matched the float, price, sticker, and wear conditions you cared about.

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
- `pyproject.toml` - packaging config that makes the tool installable as a real CLI command
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

Or install the project itself as a CLI command:

```bash
python -m pip install .
```

For active development, an editable install is more convenient:

```bash
python -m pip install -e .
```

After either install, you can run the tool as:

```bash
smte --help
```

That installed command is created from the project entry point in `pyproject.toml`.

On Windows, a `--user` install usually places `smte.exe` here:

```text
C:\Users\<your-user>\AppData\Roaming\Python\Python313\Scripts
```

If `smte` is not recognized in PowerShell, add that Scripts folder to your `PATH`, or use the full path to `smte.exe`.

If your Python environment is very minimal and `pip install .` complains about missing build tools, install `setuptools` first:

```bash
python -m pip install setuptools
```

## How it works

- Steam listing pages are requested directly from the market render endpoint
- the scraper requests up to `100` listings per Steam page
- float, paint seed, sticker presence, sticker count, and inspect-link data are read from Steam asset data when Steam includes them
- temporary Steam failures like `429`, `500`, `502`, `503`, and `504` are retried automatically
- plain output filenames are saved into the `exports/` folder by default
- file-based commands can use `latest` as a shortcut for the newest export in `exports/`

## Basic usage

Recommended installed usage:

```bash
smte fetch "AK-47 | Redline (Field-Tested)" -o redline.xlsx
```

Direct Python usage still works too:

```bash
python src/steam_market_to_excel.py fetch "AK-47 | Redline (Field-Tested)" -o redline.xlsx
```

If you have not installed the project yet and you use PowerShell often, you can create a short helper function so you can still run the tool as `smte` instead of typing the full Python command each time:

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

## Installable CLI command

The project can now be installed as a proper command-line tool.

Recommended setup:

```bash
python -m pip install -e .
smte --help
```

If you prefer a normal non-editable install:

```bash
python -m pip install .
smte --help
```

## CLI commands

### `fetch`

Scrape Steam and save a new export file.

```bash
smte fetch "MP5-SD | Neon Squeezer (Field-Tested)" -o mp5_neon_squeezer_ft.xlsx
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
smte show latest --max-float 0.10 --sort-by float --limit 10
```

Examples:

```bash
smte show latest --has-stickers --sort-by price --descending
smte show exports/ak_47_safari_mesh_mw.xlsx --wear "Minimal Wear" --limit 20
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
smte sort latest --by float price
```

If `-o/--output` is omitted, the tool derives a name such as:

```bash
exports/redline_sorted.xlsx
```

### `filter`

Filter an existing export file and write a new file.

```bash
smte filter latest --max-float 0.10 --has-stickers
```

If `-o/--output` is omitted, the tool derives a name such as:

```bash
exports/redline_filtered.xlsx
```

### `stats`

Print a quick summary for an existing export file.

```bash
smte stats latest
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
- packaging metadata for the installable `smte` command
- Windows `.exe` build script wiring

## Windows `.exe` build

If you want a standalone Windows executable, install `PyInstaller` and run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_windows_exe.ps1
```

That builds:

```text
dist\smte.exe
```

After building, you can test the executable directly with:

```powershell
.\dist\smte.exe --help
```

You can also choose a custom executable name:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_windows_exe.ps1 -Name steam-market-tool
```

That would build:

```text
dist\steam-market-tool.exe
```

And you would run it like:

```powershell
.\dist\steam-market-tool.exe --help
```

If you rebuild often, make sure an older copy of `dist\smte.exe` is not currently open before rebuilding. The build script now retries removal of the previous output first, and if the file is still locked it will tell you to close it or choose a different `-Name`.

## Notes

- Steam can still rate-limit or temporarily fail on large crawls
- this is best treated as a personal, best-effort scraper rather than a guaranteed long-running data pipeline
- some metadata depends on what Steam includes in the asset payload for a given listing
- after installation, the main command to run is `smte`
- the direct source entry point is still `src/steam_market_to_excel.py`
