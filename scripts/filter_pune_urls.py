import os
import pandas as pd
import re
import urllib.parse

def main():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    input_file = os.path.join(base_dir, 'output', 'profile_urls_raw.csv')
    output_file = os.path.join(base_dir, 'output', 'profile_urls_pune.csv')

    if not os.path.exists(input_file):
        print(f"Error: Input file {input_file} not found.")
        print("Please wait for the sitemap extraction script to generate it before running this.")
        return

    print(f"Reading from {input_file}...")
    df = pd.read_csv(input_file)
    
    if 'url' not in df.columns:
        print("Error: 'url' column not found in the CSV.")
        return
        
    initial_count = len(df)
    print(f"Loaded {initial_count} URLs.")

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
            
        # 2. Must contain "pune" in the URL path (case-insensitive)
        if 'pune' not in parsed.path.lower():
            return False
            
        return True

    print("Filtering URLs...")
    # Apply filtering
    mask = df['url'].apply(is_valid)
    df_filtered = df[mask]
    
    final_count = len(df_filtered)
    print(f"Filtering complete. {final_count} out of {initial_count} URLs matched the criteria.")

    if final_count > 0:
        # Ensure output directory exists
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        
        df_filtered.to_csv(output_file, index=False)
        print(f"\nSUCCESS: Saved {final_count} Pune URLs to {output_file}")
    else:
        print("\nNo URLs matched the filtering criteria. No output file was generated.")

if __name__ == '__main__':
    main()
