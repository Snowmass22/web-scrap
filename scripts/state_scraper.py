"""
state_scraper.py
----------------
Scrapes Practo doctor profiles for an entire STATE by combining
multiple city-level scrapes into a single merged output file.

How it works:
  1. For each city in the state's city list → filter URLs from raw sitemap
  2. Scrape each city's profiles (with resume support per city)
  3. Merge all city checkpoint CSVs into one state-level file
  4. Run clean_and_export pipeline on the merged file
  5. Optionally upload to Neon DB

Built-in state → cities mapping (extend STATE_CITIES as needed):
  goa       → panaji, margao, mapusa, vasco, ponda, calangute
  maharashtra → pune, mumbai, nagpur, nashik, aurangabad, solapur
  karnataka → bangalore, mysore, hubli, mangalore, belgaum
  rajasthan → jaipur, jodhpur, udaipur, ajmer, kota
  kerala    → kochi, thiruvananthapuram, kozhikode, thrissur

Usage:
  python scripts/state_scraper.py --state goa
  python scripts/state_scraper.py --state goa --cities panaji,margao,mapusa
  python scripts/state_scraper.py --state goa --skip-scrape   # only merge
"""

import sys
import os
import argparse
import logging
import subprocess
import time
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

# ── Load .env ──────────────────────────────────────────────────────────────
load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

# ── Paths ──────────────────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).parent.parent
OUTPUT_DIR = BASE_DIR / "output"
LOG_DIR    = BASE_DIR / "logs"
SCRIPTS    = Path(__file__).parent

# ── Logging ────────────────────────────────────────────────────────────────
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / "state_scraper.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("state_scraper")

# ── Final columns (must match clean_and_export schema) ────────────────────
FINAL_COLUMNS = [
    "full_name",
    "first_name",
    "last_name",
    "specialization",
    "specialization_alias",
    "qualification",
    "experience",
    "address_of_clinic",
    "location",
    "registration_details",
    "practo_profile_url",
]

# ── Built-in State → Cities mapping ───────────────────────────────────────
STATE_CITIES: dict[str, list[str]] = {
    "goa": [
        "north-goa",
        "south-goa",
    ],
    "maharashtra": [
        "pune", "mumbai", "nagpur", "nashik", "aurangabad",
        "solapur", "kolhapur", "thane", "navi-mumbai",
    ],
    "karnataka": [
        "bangalore", "mysore", "hubli", "mangalore",
        "belgaum", "gulbarga", "davangere",
    ],
    "rajasthan": [
        "jaipur", "jodhpur", "udaipur", "ajmer", "kota",
        "bikaner", "alwar",
    ],
    "kerala": [
        "kochi", "thiruvananthapuram", "kozhikode",
        "thrissur", "malappuram", "kannur",
    ],
    "gujarat": [
        "ahmedabad", "surat", "vadodara", "rajkot",
        "gandhinagar", "bhavnagar",
    ],
    "tamil-nadu": [
        "chennai", "coimbatore", "madurai", "tiruchirappalli",
        "salem", "tirunelveli",
    ],
    "west-bengal": [
        "kolkata", "howrah", "durgapur", "asansol",
        "siliguri",
    ],
    "telangana": [
        "hyderabad", "warangal", "nizamabad", "karimnagar",
    ],
    "andhra-pradesh": [
        "visakhapatnam", "vijayawada", "guntur", "tirupati",
        "nellore",
    ],
}


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _run(cmd: list[str], label: str) -> bool:
    """Run a subprocess command, stream output, return True on success."""
    log.info(f"\n{'─'*60}")
    log.info(f"  ▶  {label}")
    log.info(f"{'─'*60}")
    result = subprocess.run(cmd, cwd=str(BASE_DIR))
    if result.returncode != 0:
        log.error(f"  ✗ FAILED: {label} (exit code {result.returncode})")
        return False
    log.info(f"  ✓ DONE: {label}")
    return True


def _filter_city(city: str) -> bool:
    """Run filter_pune_urls.py for a single city. Returns True on success."""
    csv_path = OUTPUT_DIR / f"profile_urls_{city}.csv"
    if csv_path.exists():
        count = sum(1 for _ in open(csv_path)) - 1  # subtract header
        log.info(f"  Skipping filter for '{city}' — file already exists ({count:,} URLs).")
        return True
    return _run(
        [sys.executable, str(SCRIPTS / "filter_pune_urls.py"), "--location", city],
        f"Filtering URLs for city: {city}"
    )


def _scrape_city(city: str) -> bool:
    """Run bulk_scraper.py for a single city. Returns True on success."""
    url_csv = OUTPUT_DIR / f"profile_urls_{city}.csv"
    if not url_csv.exists():
        log.warning(f"  No URL file for '{city}', skipping scrape.")
        return False

    # Count URLs in file
    try:
        url_count = sum(1 for _ in open(url_csv)) - 1
        if url_count == 0:
            log.warning(f"  No URLs found for '{city}', skipping scrape.")
            return True
        log.info(f"  '{city}' has {url_count:,} URLs to scrape.")
    except Exception:
        pass

    return _run(
        [sys.executable, str(SCRIPTS / "bulk_scraper.py"), "--location", city],
        f"Scraping profiles for city: {city}"
    )


def _merge_cities(state: str, cities: list[str]) -> Path | None:
    """
    Merge all city checkpoint CSVs into one state-level checkpoint CSV.
    Returns the path to the merged file, or None if no data found.
    """
    log.info(f"\n{'─'*60}")
    log.info(f"  ▶  Merging {len(cities)} cities into state file: {state}")
    log.info(f"{'─'*60}")

    dfs = []
    missing = []
    for city in cities:
        fname = f"practo_doctors_checkpoint_{city}.csv"
        path  = OUTPUT_DIR / fname
        if path.exists():
            try:
                df = pd.read_csv(path, dtype=str)
                df["city_tag"] = city
                dfs.append(df)
                log.info(f"    ✓ {city}: {len(df):,} rows from {fname}")
            except Exception as e:
                log.warning(f"    ✗ {city}: Could not read {fname} — {e}")
        else:
            missing.append(city)
            log.warning(f"    – {city}: checkpoint not found ({fname}), skipping.")

    if missing:
        log.warning(f"  Cities with no data: {missing}")

    if not dfs:
        log.error("  No city data found. Nothing to merge.")
        return None

    merged = pd.concat(dfs, ignore_index=True)

    # Deduplicate on practo_profile_url across cities
    before = len(merged)
    merged.drop_duplicates(subset=["practo_profile_url"], keep="first", inplace=True)
    log.info(f"  Total rows after merge  : {before:,}")
    log.info(f"  Duplicates removed      : {before - len(merged):,}")
    log.info(f"  Final unique rows       : {len(merged):,}")

    out_path = OUTPUT_DIR / f"practo_doctors_checkpoint_{state}.csv"
    merged.to_csv(out_path, index=False)
    log.info(f"  ✓ Merged checkpoint saved → {out_path}")
    return out_path


def _export_and_upload(state: str) -> None:
    """Run clean_and_export.py for the merged state checkpoint."""
    _run(
        [sys.executable, str(SCRIPTS / "clean_and_export.py"), "--location", state],
        f"Cleaning & exporting final dataset for state: {state}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scrape Practo doctor profiles for an entire state."
    )
    parser.add_argument(
        "-s", "--state",
        type=str,
        required=False,
        default=None,
        help="State name (e.g. goa, maharashtra, karnataka)"
    )
    parser.add_argument(
        "-c", "--cities",
        type=str,
        default=None,
        help=(
            "Comma-separated list of city keywords to scrape. "
            "If omitted, uses the built-in list for the state."
        )
    )
    parser.add_argument(
        "--skip-scrape",
        action="store_true",
        default=False,
        help=(
            "Skip URL filtering and scraping — only merge existing "
            "city checkpoint files into the state file."
        )
    )
    parser.add_argument(
        "--list-states",
        action="store_true",
        default=False,
        help="Print all built-in state → city mappings and exit."
    )

    args = parser.parse_args()

    if args.list_states:
        print("\nBuilt-in state -> city mappings:")
        for s, c in STATE_CITIES.items():
            print(f"  {s:20s} -> {', '.join(c)}")
        print()
        sys.exit(0)


    if not args.state:
        parser.error("--state is required unless --list-states is used.")

    state = args.state.strip().lower().replace(" ", "-")

    # Resolve city list
    if args.cities:
        cities = [c.strip().lower() for c in args.cities.split(",") if c.strip()]
    elif state in STATE_CITIES:
        cities = STATE_CITIES[state]
        log.info(f"Using built-in city list for '{state}': {cities}")
    else:
        log.error(
            f"State '{state}' not found in built-in mapping and no --cities provided.\n"
            f"  Available states: {list(STATE_CITIES.keys())}\n"
            f"  Or use: --cities panaji,margao,mapusa"
        )
        sys.exit(1)

    log.info(f"\n{'='*60}")
    log.info(f"  STATE SCRAPE: {state.upper()}")
    log.info(f"  Cities ({len(cities)}): {', '.join(cities)}")
    log.info(f"{'='*60}\n")

    if not args.skip_scrape:
        # ── Step 1: Filter URLs per city ─────────────────────────────────
        log.info("STEP 1/3 — Filtering URLs for each city...")
        for city in cities:
            _filter_city(city)

        # ── Step 2: Scrape each city ──────────────────────────────────────
        log.info("\nSTEP 2/3 — Scraping profiles for each city...")
        for city in cities:
            _scrape_city(city)
    else:
        log.info("  --skip-scrape flag set. Skipping URL filtering and scraping.")

    # ── Step 3: Merge all cities into one state file ──────────────────────
    log.info("\nSTEP 3/3 — Merging city data into state-level file...")
    merged_path = _merge_cities(state, cities)

    if not merged_path:
        log.error("Merge produced no output. Exiting.")
        sys.exit(1)

    # ── Step 4: Clean, export, and optionally upload to Neon DB ──────────
    _export_and_upload(state)

    log.info(f"\n{'='*60}")
    log.info(f"  STATE SCRAPE COMPLETE: {state.upper()}")
    log.info(f"  Cities scraped  : {', '.join(cities)}")
    log.info(f"  Final CSV/XLSX  : output/practo_doctors_final_{state}.*")
    log.info(f"{'='*60}\n")


if __name__ == "__main__":
    main()
