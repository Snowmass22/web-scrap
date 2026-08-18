import os
import sys
import argparse
import pandas as pd
import re
import urllib.parse
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(description="Filter raw sitemap URLs by location.")
    parser.add_argument(
        "-l", "--location",
        type=str,
        default="pune",
        help="Target location keyword to filter URLs by (e.g., pune, mumbai, delhi, margao, bangalore). Default: pune"
    )
    parser.add_argument(
        "-i", "--input",
        type=str,
        default=None,
        help="Path to raw profile URLs CSV. Default: output/profile_urls_raw.csv"
    )
    parser.add_argument(
        "-o", "--output",
        type=str,
        default=None,
        help="Path for output filtered CSV. Default: output/profile_urls_<location>.csv"
    )

    args = parser.parse_args()
    location_keyword = args.location.strip().lower()

    base_dir = Path(__file__).parent.parent
    input_file = Path(args.input) if args.input else base_dir / "output" / "profile_urls_raw.csv"
    output_file = Path(args.output) if args.output else base_dir / "output" / f"profile_urls_{location_keyword}.csv"

    if not input_file.exists():
        print(f"Error: Input file {input_file} not found.")
        print("Please wait for the sitemap extraction script to generate it before running this.")
        sys.exit(1)

    print(f"Reading from {input_file}...")
    df = pd.read_csv(input_file)
    
    if 'url' not in df.columns:
        print("Error: 'url' column not found in the CSV.")
        sys.exit(1)
        
    initial_count = len(df)
    print(f"Loaded {initial_count:,} URLs. Target location keyword: '{location_keyword}'")

    # 1. Disallow patterns from robots.txt
    disallow_patterns = [
        r'/appointment', r'/search', r'/malaysia', r'/kuala-lumpur', 
        r'/id-id/', r'/pt-br/', r'/en-id/', r'/tests/test-city/', 
        r'/tawang/', r'/marketplace-api/', r'/client-api/', 
        r'/health/search', r'/health/api', r'/share/', r'/wave/', 
        r'/cerebro/', r'/\?gid=', r'\.php' 
    ]

    # Combine into a single regex for efficiency
    disallow_regex = re.compile('|'.join(disallow_patterns), re.IGNORECASE)

    def is_valid(url):
        if not isinstance(url, str):
            return False
        
        # Parse the URL to get the path
        parsed = urllib.parse.urlparse(url)
        path_and_query = parsed.path + ('?' + parsed.query if parsed.query else '')
        
        # 1. Filter out disallowed patterns
        if disallow_regex.search(path_and_query):
            return False
            
        # 2. Must contain location keyword as an exact path segment
        #    e.g. /panaji/ matches, but /navi-mumbai/ won't match 'mumbai'
        path = parsed.path.lower()
        if not re.search(r'(?:^|/)' + re.escape(location_keyword) + r'(?:/|$)', path):
            return False
            
        return True

    print("Filtering URLs...")
    mask = df['url'].apply(is_valid)
    df_filtered = df[mask]
    
    final_count = len(df_filtered)
    print(f"Filtering complete. {final_count:,} out of {initial_count:,} URLs matched '{location_keyword}'.")

    if final_count > 0:
        os.makedirs(output_file.parent, exist_ok=True)
        df_filtered.to_csv(output_file, index=False)
        print(f"\nSUCCESS: Saved {final_count:,} {location_keyword.capitalize()} URLs to {output_file}")
    else:
        print(f"\nNo URLs matched the filter '{location_keyword}'. No output file was generated.")

if __name__ == '__main__':
    main()

