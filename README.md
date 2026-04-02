# Steam Market Listing to Excel (CS2)

A small CLI tool that crawls Steam Community Market listings for a CS2 item and exports listing data to an Excel file.

## What it exports
- Float value
- Wear tier (derived from float)
- Paint seed
- Page number (10 listings per page)
- Price
- Sticker presence (+ sticker count)
- Listing ID / asset ID / inspect link

## Project structure
- `src/steam_market_to_excel.py` - main scraper/export script
- `tests/` - placeholder directory for future tests

## Requirements
- Python 3.10+
- `requests`
- `pandas`
- `openpyxl`

Install dependencies:

```bash
python -m pip install requests pandas openpyxl
```

## Usage

```bash
python src/steam_market_to_excel.py "AK-47 | Redline (Field-Tested)" -o redline_listings.xlsx
```

Optional flags:
- `--currency` (default: `1` for USD)
- `--country` (default: `US`)
- `--language` (default: `english`)

## Notes
- Steam may rate-limit requests if run too aggressively.
- Float/paint-seed/sticker metadata depends on inspect link availability and float API responsiveness.
