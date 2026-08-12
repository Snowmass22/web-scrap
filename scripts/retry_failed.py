"""
retry_failed.py
---------------
Retries scraping URLs from output/failed_urls.csv.

Behaviour:
  - Reads failed_urls.csv and attempts to re-scrape each URL
  - Successful results are merged (appended) into practo_doctors_checkpoint.csv
  - URLs that succeed are removed from failed_urls.csv
  - URLs that still fail stay in failed_urls.csv with an incremented retry_count
  - Uses a longer delay (4-7s) than the main scraper since these already failed once
  - Safe to run multiple times — idempotent
"""

import sys
import random
import time
import logging
from datetime import datetime
from pathlib import Path

import pandas as pd

# ── Import the single-profile scraper ─────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))
from scrape_doctor_profile import scrape_doctor_profile

# ── Paths ──────────────────────────────────────────────────────────────────
BASE_DIR       = Path(__file__).parent.parent
FAILED_CSV     = BASE_DIR / "output" / "failed_urls.csv"
CHECKPOINT_CSV = BASE_DIR / "output" / "practo_doctors_checkpoint.csv"
LOG_DIR        = BASE_DIR / "logs"

# ── Retry config ───────────────────────────────────────────────────────────
RETRY_DELAY_MIN = 4.0   # longer delay — these already failed once
RETRY_DELAY_MAX = 7.0
MAX_RETRIES     = 3     # skip URL permanently after this many total attempts

# ── Logging ────────────────────────────────────────────────────────────────
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / "retry_scraper.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("retry_failed")


# ── Helpers ────────────────────────────────────────────────────────────────

def _is_failed_result(result: dict) -> bool:
    """Return True if the scrape returned no useful data."""
    return all(v is None for k, v in result.items() if k != "practo_profile_url")


def _merge_into_checkpoint(records: list[dict]) -> None:
    """Append successfully scraped records to the checkpoint CSV."""
    if not records:
        return
    df_new = pd.DataFrame(records)
    if CHECKPOINT_CSV.exists():
        df_new.to_csv(CHECKPOINT_CSV, mode="a", index=False, header=False)
    else:
        df_new.to_csv(CHECKPOINT_CSV, mode="w", index=False, header=True)
    log.info(f"  ✓ Merged {len(records)} new record(s) into {CHECKPOINT_CSV.name}")


def _already_in_checkpoint(url: str) -> bool:
    """Check whether a URL is already successfully scraped in the checkpoint."""
    if not CHECKPOINT_CSV.exists():
        return False
    try:
        df = pd.read_csv(CHECKPOINT_CSV, usecols=["practo_profile_url"])
        return url in df["practo_profile_url"].values
    except Exception:
        return False


# ── Main ───────────────────────────────────────────────────────────────────

def main() -> None:
    if not FAILED_CSV.exists():
        log.info(f"No failed_urls.csv found at {FAILED_CSV}. Nothing to retry.")
        return

    # Load failed URLs
    df_failed = pd.read_csv(FAILED_CSV)

    # Ensure required columns exist
    if "url" not in df_failed.columns:
        log.error("failed_urls.csv has no 'url' column. Aborting.")
        return
    if "retry_count" not in df_failed.columns:
        df_failed["retry_count"] = 0
    if "reason" not in df_failed.columns:
        df_failed["reason"] = ""
    if "timestamp" not in df_failed.columns:
        df_failed["timestamp"] = ""

    # Filter: skip rows that already hit MAX_RETRIES or are already in checkpoint
    eligible = df_failed[df_failed["retry_count"] < MAX_RETRIES].copy()
    exhausted = df_failed[df_failed["retry_count"] >= MAX_RETRIES].copy()

    log.info(f"Failed URLs loaded       : {len(df_failed):,}")
    log.info(f"Eligible for retry       : {len(eligible):,}")
    log.info(f"Permanently exhausted    : {len(exhausted):,} (retry_count >= {MAX_RETRIES})")

    if eligible.empty:
        log.info("No eligible URLs to retry. Exiting.")
        return

    successful_records = []
    still_failing_rows = []

    for idx, row in enumerate(eligible.itertuples(index=False), start=1):
        url = row.url
        retry_count = int(row.retry_count)

        # If it already made it into the checkpoint from a previous run, skip
        if _already_in_checkpoint(url):
            log.info(f"[{idx}/{len(eligible)}] Already in checkpoint, skipping: {url}")
            continue

        log.info(f"[{idx}/{len(eligible)}] Retry #{retry_count + 1} → {url}")

        try:
            result = scrape_doctor_profile(url)
        except Exception as exc:
            log.error(f"  Unhandled exception: {exc}")
            still_failing_rows.append({
                "url":         url,
                "reason":      f"exception: {exc}",
                "retry_count": retry_count + 1,
                "timestamp":   datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            })
            continue

        if _is_failed_result(result):
            log.warning(f"  → Still failing (all fields None)")
            still_failing_rows.append({
                "url":         url,
                "reason":      "all fields None after retry",
                "retry_count": retry_count + 1,
                "timestamp":   datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            })
        else:
            log.info(f"  → SUCCESS: {result.get('full_name')} | {result.get('specialization')}")
            successful_records.append(result)

        # Polite delay between retries
        if idx < len(eligible):
            delay = random.uniform(RETRY_DELAY_MIN, RETRY_DELAY_MAX)
            log.info(f"  Waiting {delay:.1f}s before next retry...")
            time.sleep(delay)

    # ── Merge successes into checkpoint ────────────────────────────────────
    _merge_into_checkpoint(successful_records)

    # ── Rebuild failed_urls.csv ────────────────────────────────────────────
    # Keep: still-failing rows + permanently exhausted rows
    remaining_df = pd.DataFrame(
        still_failing_rows + exhausted.to_dict("records")
    )

    if remaining_df.empty:
        # All failures resolved — remove the file
        FAILED_CSV.unlink(missing_ok=True)
        log.info("All failed URLs resolved! failed_urls.csv removed.")
    else:
        remaining_df.to_csv(FAILED_CSV, index=False)
        log.info(f"Updated failed_urls.csv → {len(remaining_df):,} URLs remain "
                 f"({len(still_failing_rows)} still failing, "
                 f"{len(exhausted)} permanently exhausted)")

    # ── Final summary ──────────────────────────────────────────────────────
    log.info("=" * 60)
    log.info("RETRY RUN COMPLETE")
    log.info(f"  URLs retried this run    : {len(eligible):,}")
    log.info(f"  Newly recovered          : {len(successful_records):,}")
    log.info(f"  Still failing            : {len(still_failing_rows):,}")
    log.info(f"  Permanently exhausted    : {len(exhausted):,}")
    log.info(f"  Checkpoint file          : {CHECKPOINT_CSV}")
    log.info(f"  Remaining failures file  : {FAILED_CSV}")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
