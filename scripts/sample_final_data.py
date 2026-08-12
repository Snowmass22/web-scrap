"""
sample_final_data.py
--------------------
Randomly samples 15 rows from output/practo_doctors_final.csv 
and prints them in a highly readable format for manual cross-checking.
"""

import sys
from pathlib import Path
import pandas as pd

# ── Paths ──────────────────────────────────────────────────────────────────
BASE_DIR  = Path(__file__).parent.parent
FINAL_CSV = BASE_DIR / "output" / "practo_doctors_final.csv"

def main():
    if not FINAL_CSV.exists():
        print(f"\n[ERROR] Final CSV not found at: {FINAL_CSV}")
        print("You must run clean_and_export.py first (and ideally bulk_scraper.py).\n")
        sys.exit(1)

    # Read data, replacing NaN with empty string just in case
    df = pd.read_csv(FINAL_CSV, dtype=str).fillna("")
    total_rows = len(df)

    if total_rows == 0:
        print("\n[WARNING] The dataset is empty.\n")
        sys.exit(0)

    # Sample up to 15 rows
    sample_size = min(15, total_rows)
    sample_df = df.sample(n=sample_size, random_state=None)

    print("=" * 80)
    print(f"  RANDOM SAMPLE FOR MANUAL QA ({sample_size} of {total_rows:,} rows)")
    print("=" * 80)

    # Print each row in a vertical, readable format
    for i, (_, row) in enumerate(sample_df.iterrows(), start=1):
        print(f"\n--- [ Sample {i}/{sample_size} ] ---")
        
        # Enforce exact column order visually
        columns_to_show = [
            "full_name", 
            "specialization", 
            "qualification", 
            "experience", 
            "location", 
            "registration_details", 
            "practo_profile_url"
        ]
        
        for col in columns_to_show:
            val = row.get(col, "")
            # Highlight missing fields with [MISSING] for easier spotting
            display_val = val if val else "[MISSING]"
            print(f"  {col:>20} : {display_val}")

    print("\n" + "=" * 80)
    print("  END OF SAMPLE")
    print("=" * 80 + "\n")

if __name__ == "__main__":
    main()
