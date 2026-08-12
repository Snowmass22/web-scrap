"""
bulk_scraper.py
---------------
Bulk scraper for Practo Pune doctor profiles.

Features:
  - Reads URLs from output/profile_urls_pune.csv
  - Resumes automatically: skips URLs already present in the checkpoint file
  - Saves progress to output/practo_doctors_checkpoint.csv every CHECKPOINT_EVERY profiles
  - Logs failed/blocked URLs to output/failed_urls.csv for retry
  - Respects the same random 2-4s polite delay as the single-profile scraper
  - Prints a live progress summary to the console
"""

import os
import sys
import random
import time
import logging
import concurrent.futures
from datetime import datetime
from pathlib import Path

import pandas as pd

# Ensure the scripts/ directory is importable regardless of CWD
sys.path.insert(0, str(Path(__file__).parent))
from scrape_doctor_profile import scrape_doctor_profile, DELAY_MIN, DELAY_MAX

# ── Paths ──────────────────────────────────────────────────────────────────
BASE_DIR        = Path(__file__).parent.parent
INPUT_CSV       = BASE_DIR / "output" / "profile_urls_pune.csv"
CHECKPOINT_CSV  = BASE_DIR / "output" / "practo_doctors_checkpoint.csv"
FAILED_CSV      = BASE_DIR / "output" / "failed_urls.csv"
LOG_DIR         = BASE_DIR / "logs"

# ── Config ─────────────────────────────────────────────────────────────────
MAX_WORKERS      = 3      # Number of concurrent browser windows
CHECKPOINT_EVERY = 100    # flush to CSV every N successful profiles

# ── Logging ────────────────────────────────────────────────────────────────
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / "bulk_scraper.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("bulk_scraper")


# ── Helpers ────────────────────────────────────────────────────────────────

def _load_already_scraped() -> set[str]:
    """Return the set of practo_profile_urls already present in the checkpoint file."""
    if CHECKPOINT_CSV.exists():
        try:
            df = pd.read_csv(CHECKPOINT_CSV, usecols=["practo_profile_url"])
            urls = set(df["practo_profile_url"].dropna().tolist())
            log.info(f"Resuming — {len(urls)} URLs already in checkpoint, skipping them.")
            return urls
        except Exception as e:
            log.warning(f"Could not read checkpoint file ({e}), starting fresh.")
    return set()


def _load_already_failed() -> set[str]:
    """Return the set of URLs already recorded in failed_urls.csv."""
    if FAILED_CSV.exists():
        try:
            df = pd.read_csv(FAILED_CSV, usecols=["url"])
            return set(df["url"].dropna().tolist())
        except Exception:
            pass
    return set()


def _save_checkpoint(records: list[dict]) -> None:
    """Append records to the checkpoint CSV, creating it with a header if needed."""
    df_new = pd.DataFrame(records)
    if CHECKPOINT_CSV.exists():
        df_new.to_csv(CHECKPOINT_CSV, mode="a", index=False, header=False)
    else:
        df_new.to_csv(CHECKPOINT_CSV, mode="w", index=False, header=True)
    log.info(f"  ✓ Checkpoint saved — {len(records)} new rows written to {CHECKPOINT_CSV.name}")


def _record_failure(url: str, reason: str) -> None:
    """Append one row to failed_urls.csv."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    row = pd.DataFrame([{"url": url, "reason": reason, "timestamp": ts}])
    if FAILED_CSV.exists():
        row.to_csv(FAILED_CSV, mode="a", index=False, header=False)
    else:
        row.to_csv(FAILED_CSV, mode="w", index=False, header=True)


def _is_failed_result(result: dict) -> bool:
    """Return True if the scrape returned no useful data (all None except practo_profile_url)."""
    return all(v is None for k, v in result.items() if k != "practo_profile_url")


# ── Main loop ──────────────────────────────────────────────────────────────

def main() -> None:
    # 1. Load input URLs
    if not INPUT_CSV.exists():
        log.error(f"Input file not found: {INPUT_CSV}")
        sys.exit(1)

    all_urls = pd.read_csv(INPUT_CSV)["url"].dropna().tolist()
    log.info(f"Total URLs in input: {len(all_urls):,}")

    # 2. Determine resume state
    done_urls   = _load_already_scraped()
    failed_urls = _load_already_failed()
    skip_urls   = done_urls | failed_urls

    todo = [u for u in all_urls if u not in skip_urls]
    log.info(f"URLs to process this run: {len(todo):,}  "
             f"(skipping {len(skip_urls):,} already done/failed)")

    if not todo:
        log.info("Nothing left to scrape. Exiting.")
        return

    # 3. Scrape loop
    buffer        = []   # holds unsaved results since last checkpoint
    success_total = len(done_urls)
    fail_total    = len(failed_urls)
    run_success   = 0
    run_fail      = 0
    start_time    = time.time()

    def _worker(target_url: str):
        # Stagger initial startup slightly
        time.sleep(random.uniform(0.1, 1.5))
        try:
            res = scrape_doctor_profile(target_url)
            # Sleep after scrape to maintain polite delay between requests on this thread
            time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))
            return target_url, res, None
        except Exception as e:
            return target_url, None, e

    log.info(f"Starting ThreadPoolExecutor with {MAX_WORKERS} concurrent workers...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # Submit all tasks (memory overhead for 70k futures is negligible)
        future_to_url = {executor.submit(_worker, u): u for u in todo}

        for idx, future in enumerate(concurrent.futures.as_completed(future_to_url), start=1):
            url = future_to_url[future]
            try:
                url, result, exc = future.result()
            except Exception as e:
                exc = e
                result = None

            if exc:
                log.error(f"  Unhandled exception for {url}: {exc}")
                _record_failure(url, f"exception: {exc}")
                run_fail += 1
                fail_total += 1
                continue

            if _is_failed_result(result):
                reason = "all fields None (blocked/404/empty)"
                log.warning(f"  → FAILED — {reason}")
                _record_failure(url, reason)
                run_fail += 1
                fail_total += 1
            else:
                buffer.append(result)
                run_success += 1
                success_total += 1

            # 4. Checkpoint every N successful profiles
            if len(buffer) >= CHECKPOINT_EVERY:
                _save_checkpoint(buffer)
                buffer = []

            # 5. Live progress summary
            elapsed = time.time() - start_time
            rate = idx / elapsed if elapsed > 0 else 0
            remaining = (len(todo) - idx) / rate if rate > 0 else 0
            log.info(
                f"  Progress: {idx}/{len(todo)} | "
                f"✓ {run_success} scraped | ✗ {run_fail} failed | "
                f"{rate:.2f} req/s | ETA ~{remaining/60:.0f}m"
            )

    # 7. Final flush for any remaining buffered results
    if buffer:
        _save_checkpoint(buffer)

    # 8. Final summary
    elapsed = time.time() - start_time
    log.info("=" * 65)
    log.info("SCRAPE COMPLETE")
    log.info(f"  Total URLs processed this run : {idx:,}")
    log.info(f"  Successfully scraped          : {run_success:,}")
    log.info(f"  Failed / blocked              : {run_fail:,}")
    log.info(f"  Total in checkpoint file      : {success_total:,}")
    log.info(f"  Total in failed_urls file     : {fail_total:,}")
    log.info(f"  Time elapsed                  : {elapsed/60:.1f} minutes")
    log.info(f"  Output                        : {CHECKPOINT_CSV}")
    log.info(f"  Failed URLs                   : {FAILED_CSV}")
    log.info("=" * 65)


if __name__ == "__main__":
    main()
