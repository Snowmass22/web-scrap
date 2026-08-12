import os
import pandas as pd
from playwright.sync_api import sync_playwright

def main():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    # We will try the filtered file first, then raw, then fallback.
    pune_file = os.path.join(base_dir, 'output', 'profile_urls_pune.csv')
    raw_file = os.path.join(base_dir, 'output', 'profile_urls_raw.csv')
    
    url = None
    
    if os.path.exists(pune_file):
        df = pd.read_csv(pune_file)
        if not df.empty and 'url' in df.columns:
            url = df['url'].iloc[0]
            print(f"Found URL in filtered list: {url}")
            
    if not url and os.path.exists(raw_file):
        df = pd.read_csv(raw_file)
        if not df.empty and 'url' in df.columns:
            # Let's try to find a 'pune' doctor in the raw file just in case
            pune_urls = df[df['url'].str.contains('pune', case=False, na=False)]
            if not pune_urls.empty:
                url = pune_urls['url'].iloc[0]
                print(f"Found 'pune' URL in raw list: {url}")
            else:
                url = df['url'].iloc[0]
                print(f"Using first URL from raw list: {url}")
                
    if not url:
        # Fallback URL if extraction is still running and files are empty
        url = "https://www.practo.com/delhi/doctor/dr-sumit-anand-orthopedist"
        print(f"Extraction not finished yet. Using a fallback sample URL: {url}")

    print(f"\nLaunching Playwright in headed mode...")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        
        print(f"Navigating to: {url}")
        page.goto(url, wait_until='domcontentloaded', timeout=60000)
        
        print("Waiting 5 seconds for dynamic content to render...")
        page.wait_for_timeout(5000)
        
        # Fetch the rendered HTML
        html_content = page.content()
        
        # Save to output/sample_profile.html
        output_html = os.path.join(base_dir, 'output', 'sample_profile.html')
        os.makedirs(os.path.dirname(output_html), exist_ok=True)
        
        with open(output_html, 'w', encoding='utf-8') as f:
            f.write(html_content)
            
        print(f"\nSUCCESS: Saved fully rendered HTML to {output_html}")
        
        # Close the browser
        browser.close()

if __name__ == '__main__':
    main()
