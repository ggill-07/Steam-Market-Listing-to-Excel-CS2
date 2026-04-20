# Steam Market Listing Tool (CS2)

A CLI and desktop search tool for scraping CS2 Steam Community Market listings, saving them to Excel or CSV, and then exploring the data either from the terminal or from a desktop app.

This is a personal project built to make that workflow faster and less painful.

The tool grew out of a simple problem: manually digging through thousands of Steam Market listings to find the few items that actually matched the float, price, sticker, and wear conditions you cared about.

The project reads the metadata it can directly from Steam's own market payload instead of depending on CSFloat at runtime.

The project is released under the `MIT` license, so other people can use, modify, and share it with attribution.

## What the tool can do

- launch a desktop app for building and running search batches with a cleaner, more user-friendly UI
- `fetch` Steam Community Market listings for a CS2 item and save them to a file
- `fetch` now reuses a stable per-item file name by default and syncs that file in place
- `fetch` can now filter, sort, and optionally show matching rows in the same command
- `fetch-many` can fetch multiple items in parallel
- `sort` an existing export file by one or more columns
- `filter` an existing export file and write only matching rows
- `show` matching rows directly in the terminal
- `stats` print summary information for an existing export file
- `use` choose which export file the `latest` shortcut should point to

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
- `src/smte_desktop.py` - the desktop app entry point
- `src/smte_desktop_support.py` - the desktop app's reusable non-UI logic
- `pyproject.toml` - packaging config that makes the tool installable as a real CLI command
- `tests/test_steam_market_to_excel.py` - automated tests for the CLI tool
- `tests/test_smte_desktop_support.py` - automated tests for the desktop app support layer

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

The desktop app is also installable:

```bash
smte-desktop
```

Those installed commands are created from the project entry points in `pyproject.toml`.

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
- the tool accepts user-friendly `StatTrack` or `StatTrak` prefixes and normalizes them to Steam's real `StatTrak™` market name format
- temporary Steam failures like `429`, `500`, `502`, `503`, and `504` are retried automatically
- plain output filenames are saved into the `exports/` folder by default
- if `fetch` is run without `-o`, it derives a stable filename from the item name, such as `ak_47_redline_field_tested.xlsx`
- fetching the same item again updates that same file in place and reports how many listings were added, removed, or stayed the same
- `fetch` can immediately filter, sort, and show the current results without making you run separate commands afterward
- `fetch-many` can process several market names in parallel and sync one file per item
- file-based commands can use `latest` as a shortcut for the export file you most recently chose with `use`
- if you have not chosen one with `use`, `latest` falls back to the newest export in `exports/`
- the desktop app uses the same scraping/filtering engine as the CLI instead of duplicating the logic
- desktop autocomplete suggestions are cached locally in `app_data/` so repeated searches do not have to start from scratch every launch

## Desktop app

The project now includes a desktop UI aimed at the workflow where you want to:

- type an item name and get autocomplete suggestions
- choose one or more wear checkboxes
- fill in filters like max float, max price, paint seed, and stickers
- queue several searches
- run them as a batch
- view each result set in its own tab with a structured results table

Run the desktop app from an install:

```bash
smte-desktop
```

Or directly from the repo:

```bash
python src/smte_desktop.py
```

Desktop app notes:

- autocomplete suggestions are fetched from Steam's market search endpoint and then cached locally in `app_data/market_name_autocomplete_cache.json`
- desktop settings are stored locally in `app_data/desktop_app_settings.json`
- queued searches are restored automatically from `app_data/desktop_query_queue.json` when you relaunch the desktop app
- the `Save App State` button saves both the current desktop settings and the queued searches immediately
- `app_data/` is ignored by Git so the cache and settings stay local to each machine
- the desktop app runs searches sequentially by default, which is slower than aggressive batching but safer against Steam rate limits

## Basic usage

Recommended installed usage:

```bash
smte fetch "AK-47 | Redline (Field-Tested)" -o redline.xlsx
```

If you omit `-o`, the tool now derives a stable per-item filename automatically:

```bash
smte fetch "AK-47 | Redline (Field-Tested)"
```

That will save to something like:

```bash
exports/ak_47_redline_field_tested.xlsx
```

Direct Python usage still works too:

```bash
python src/steam_market_to_excel.py fetch "AK-47 | Redline (Field-Tested)" -o redline.xlsx
```

You can also fetch, filter, sort, and show in one line:

```bash
smte fetch "AK-47 | Safari Mesh (Minimal Wear)" --max-float 0.10 --max-price 5.00 --sort-by float price --show --limit 10
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
smte use exports/redline_filtered.xlsx
```

For the desktop flow instead of the terminal flow:

```powershell
smte-desktop
```

## Installable CLI command

The project can now be installed as a proper command-line tool.

Recommended setup:

```bash
python -m pip install -e .
smte --help
smte-desktop
```

If you prefer a normal non-editable install:

```bash
python -m pip install .
smte --help
smte-desktop
```

## CLI commands

### `fetch`

Scrape Steam and save a new export file.

```bash
smte fetch "MP5-SD | Neon Squeezer (Field-Tested)" -o mp5_neon_squeezer_ft.xlsx
```

If you omit `-o`, `fetch` derives a filename from the market name and reuses that same file on later fetches of the same item.

When that file already exists, `fetch` syncs it in place and prints a summary like:

```text
Synced 6846 current listings to exports/ak_47_safari_mesh_minimal_wear.xlsx (added 120, removed 98, unchanged 6628)
```

You can also use `fetch` as a one-line fetch/filter/sort/show workflow:

```bash
smte fetch "AK-47 | Safari Mesh (Minimal Wear)" --max-float 0.10 --max-price 5.00 --sort-by float price --show --limit 10
```

Useful options:

- `--currency` - Steam currency ID, default `1` for USD
- `--country` - Steam country code, default `US`
- `--language` - Steam language, default `english`
- `--steam-page-delay` - seconds to wait between Steam page requests, default `0.0`
- `--steam-max-retries` - retry count for temporary Steam errors, default `5`
- `-o/--output` - plain filenames go into `exports/`; custom paths are respected
- `--min-float` / `--max-float`
- `--min-price` / `--max-price`
- `--wear`
- `--paint-seed`
- `--has-stickers` / `--no-stickers`
- `--min-sticker-count` / `--max-sticker-count`
- `--sort-by`
- `--descending`
- `--show`
- `--limit`
- `--columns`

### `fetch-many`

Fetch multiple market items in parallel and sync one file per item.

```bash
smte fetch-many "AK-47 | Safari Mesh (Minimal Wear)" "MP7 | Astrolabe (Minimal Wear)" --workers 3
```

You can also load the item names from a text file with one item per line:

```bash
smte fetch-many --items-file items.txt --workers 3
```

Like `fetch`, this command can also filter, sort, and show matching rows inline:

```bash
smte fetch-many --items-file items.txt --max-float 0.10 --sort-by float --show --limit 5
```

Useful options:

- `--items-file` - text file with one exact Steam market name per line
- `--workers` - how many items to fetch in parallel, default `3`
- `--steam-page-delay` - delay inside each worker, default `0.0`
- all the same inline filter/sort/show options supported by `fetch`

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

### `use`

Pick which file `latest` should mean from now on.

```bash
smte use exports/redline_filtered.xlsx
```

After that, commands like these will use the file you picked:

```bash
smte show latest --max-float 0.10
smte stats latest
```

## The `latest` shortcut

For file-based commands, you can use:

```bash
latest
```

instead of typing a full file path.

By default, the tool picks the newest `.xlsx`, `.xls`, or `.csv` file inside `exports/`.

If you want to choose it yourself, run:

```bash
smte use exports/redline_filtered.xlsx
```

After that, `latest` will point to the file you selected until you pick another one or create a newer file with `fetch`, `sort`, or `filter`.

This works with:

- `show`
- `sort`
- `filter`
- `stats`

## Speed notes

This branch now defaults to a much faster fetch configuration than before:

- `fetch` uses a default Steam page delay of `0.0`
- `fetch-many` uses `3` workers by default

In live probes during development on this branch:

- `20` straight market page requests at `0.0` delay completed successfully in one session
- `3` items fetched in parallel with `3` workers also completed successfully in a small parallel probe

That does not guarantee Steam will always allow the same speed forever, so if you start seeing more `429` or `502` responses, the first things to try are:

- increase `--steam-page-delay` to `0.10` or `0.25`
- reduce `--workers` to `2` or `1`

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
- file-based CLI workflows including `fetch`, `fetch-many`, `show`, `sort`, `filter`, `stats`, `use`, and `latest`
- stable per-item fetch output naming and in-place sync summaries
- inline fetch filtering, sorting, and terminal display
- packaging metadata for the installable `smte` command
- Windows `.exe` build script wiring for both the CLI and the desktop app

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

## Windows desktop app build

If you want the desktop UI to feel like a normal Windows app you can click from a shortcut, build the desktop executable instead of the CLI executable:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_windows_desktop_exe.ps1
```

That builds:

```text
dist\smte-desktop.exe
```

The desktop build is:

- windowed, so it opens like a normal app instead of showing a console window
- bundled with the custom SMTE icon
- bundled with the icon assets the app uses at runtime

You can test the desktop executable by launching it directly:

```powershell
.\dist\smte-desktop.exe
```

You can also choose a custom executable name:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_windows_desktop_exe.ps1 -Name SMTE-Desktop-App
```

That would build:

```text
dist\SMTE-Desktop-App.exe
```

### Create a real desktop shortcut

Once the desktop executable exists, the easiest Windows workflow is:

1. Open the `dist\` folder.
2. Right-click `smte-desktop.exe`.
3. Choose `Send to > Desktop (create shortcut)`.
4. Rename the shortcut to something friendly like `SMTE Desktop`.

After that, you can launch the app the same way you launch other desktop programs: just double-click the shortcut.

## Notes

- Steam can still rate-limit or temporarily fail on large crawls
- this is best treated as a personal, best-effort scraper rather than a guaranteed long-running data pipeline
- some metadata depends on what Steam includes in the asset payload for a given listing
- after installation, the main command to run is `smte`
- the direct source entry point is still `src/steam_market_to_excel.py`
