"""
neon_upload.py
--------------
Uploads cleaned Practo doctor data to a Neon (PostgreSQL) database.

A separate table is created per city automatically if it doesn't exist:
  practo_doctors_<city> (
    id                  SERIAL PRIMARY KEY,
    full_name           TEXT,
    first_name          TEXT,
    last_name           TEXT,
    specialization      TEXT,
    specialization_alias TEXT,
    qualification       TEXT,
    experience          TEXT,
    address_of_clinic   TEXT,
    location            TEXT,
    registration_details TEXT,
    practo_profile_url  TEXT UNIQUE,
    uploaded_at         TIMESTAMPTZ DEFAULT NOW()
  )

Usage:
  python scripts/neon_upload.py --location mumbai
  python scripts/neon_upload.py --location delhi --input path/to/custom.csv
"""

import sys
import io
import os
import argparse
import logging
from pathlib import Path

# Fix Unicode output on Windows consoles (cp1252 → utf-8)
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv

# ── Load .env ──────────────────────────────────────────────────────────────
load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

# ── Paths ──────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent
LOG_DIR  = BASE_DIR / "logs"

# ── Logging ────────────────────────────────────────────────────────────────
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / "neon_upload.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("neon_upload")


def _table_name(loc: str) -> str:
    """Return the per-city table name, e.g. 'practo_doctors_hyderabad'."""
    # Sanitize: lowercase, replace hyphens/spaces with underscores
    safe = loc.strip().lower().replace("-", "_").replace(" ", "_")
    return f"practo_doctors_{safe}"


def _make_create_sql(table: str) -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {table} (
    id                   SERIAL PRIMARY KEY,
    full_name            TEXT,
    first_name           TEXT,
    last_name            TEXT,
    specialization       TEXT,
    specialization_alias TEXT,
    qualification        TEXT,
    experience           TEXT,
    address_of_clinic    TEXT,
    location             TEXT,
    registration_details TEXT,
    practo_profile_url   TEXT UNIQUE,
    uploaded_at          TIMESTAMPTZ DEFAULT NOW()
);
"""


def _make_insert_sql(table: str) -> str:
    return f"""
INSERT INTO {table}
    (full_name, first_name, last_name, specialization, specialization_alias,
     qualification, experience, address_of_clinic, location,
     registration_details, practo_profile_url)
VALUES %s
ON CONFLICT (practo_profile_url) DO UPDATE SET
    full_name            = EXCLUDED.full_name,
    first_name           = EXCLUDED.first_name,
    last_name            = EXCLUDED.last_name,
    specialization       = EXCLUDED.specialization,
    specialization_alias = EXCLUDED.specialization_alias,
    qualification        = EXCLUDED.qualification,
    experience           = EXCLUDED.experience,
    address_of_clinic    = EXCLUDED.address_of_clinic,
    location             = EXCLUDED.location,
    registration_details = EXCLUDED.registration_details,
    uploaded_at          = NOW();
"""


def _connect() -> psycopg2.extensions.connection:
    """Connect to Neon DB using DATABASE_URL from .env"""
    db_url = os.getenv("NEON_DATABASE_URL")
    if not db_url or "your_user" in db_url:
        log.error(
            "NEON_DATABASE_URL is not set or still has placeholder values.\n"
            "  -> Open the .env file in your project root and paste your Neon connection string."
        )
        sys.exit(1)

    log.info("Connecting to Neon DB...")
    conn = psycopg2.connect(db_url)
    conn.autocommit = False
    log.info("  Connected successfully.")
    return conn


def _upload(df: pd.DataFrame, loc: str, conn: psycopg2.extensions.connection) -> int:
    """
    Upsert all rows from df into the city-specific table.
    Returns the number of rows inserted/updated.
    """
    table = _table_name(loc)
    log.info(f"  Target table: {table}")

    # Replace empty strings with None so DB stores NULL
    df = df.replace("", None)

    rows = [
        (
            row.get("full_name"),
            row.get("first_name"),
            row.get("last_name"),
            row.get("specialization"),
            row.get("specialization_alias"),
            row.get("qualification"),
            row.get("experience"),
            row.get("address_of_clinic"),
            row.get("location"),
            row.get("registration_details"),
            row.get("practo_profile_url"),
        )
        for _, row in df.iterrows()
    ]

    create_sql = _make_create_sql(table)
    insert_sql = _make_insert_sql(table)

    with conn.cursor() as cur:
        # Ensure city table exists
        cur.execute(create_sql)

        # Batch upsert in chunks of 1000 rows
        BATCH = 1000
        total = 0
        for i in range(0, len(rows), BATCH):
            batch = rows[i : i + BATCH]
            execute_values(cur, insert_sql, batch)
            total += len(batch)
            log.info(f"  Uploaded {min(i + BATCH, len(rows)):,} / {len(rows):,} rows...")

    conn.commit()
    return total


def main() -> None:
    parser = argparse.ArgumentParser(description="Upload cleaned Practo data to Neon DB (per-city table).")
    parser.add_argument(
        "-l", "--location",
        type=str,
        default="pune",
        help="City name — also determines the table name (e.g. pune -> practo_doctors_pune). Default: pune"
    )
    parser.add_argument(
        "-i", "--input",
        type=str,
        default=None,
        help="Path to the final cleaned CSV to upload. Default: output/practo_doctors_final_<location>.csv"
    )

    args = parser.parse_args()
    loc = args.location.strip().lower()
    table = _table_name(loc)

    if args.input:
        input_csv = Path(args.input)
    else:
        fname = "practo_doctors_final.csv" if loc == "pune" else f"practo_doctors_final_{loc}.csv"
        input_csv = BASE_DIR / "output" / fname

    if not input_csv.exists():
        log.error(
            f"Input file not found: {input_csv}\n"
            f"  -> Run 'python scripts/clean_and_export.py --location {loc}' first."
        )
        sys.exit(1)

    log.info(f"Loading: {input_csv}")
    df = pd.read_csv(input_csv, dtype=str).fillna("")
    log.info(f"  Rows to upload: {len(df):,}")

    conn = _connect()
    try:
        uploaded = _upload(df, loc, conn)
        log.info("=" * 60)
        log.info("NEON UPLOAD COMPLETE")
        log.info(f"  Location  : {loc}")
        log.info(f"  Table     : {table}")
        log.info(f"  Rows upserted : {uploaded:,}")
        log.info("=" * 60)
    except Exception as e:
        conn.rollback()
        log.error(f"Upload failed: {e}")
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
