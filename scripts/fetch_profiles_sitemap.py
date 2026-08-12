import os
import requests
from bs4 import BeautifulSoup
import pandas as pd

def fetch_sitemap(url, visited=None):
    """
    Recursively fetches sitemaps and extracts URLs.
    """
    if visited is None:
        visited = set()
    
    if url in visited:
        return []
    
    visited.add(url)
    print(f"Fetching: {url}")
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36'
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        
        content = response.content
        if url.endswith('.gz'):
            import gzip
            from io import BytesIO
            content = gzip.GzipFile(fileobj=BytesIO(content)).read()
            
    except Exception as e:
        print(f"Failed to fetch {url}: {e}")
        return []

    soup = BeautifulSoup(content, 'lxml-xml')
    
    urls = []
    
    # Check if it's a sitemap index (contains <sitemap> tags)
    sitemaps = soup.find_all('sitemap')
    if sitemaps:
        print(f"Found sitemap index at {url}, fetching {len(sitemaps)} sub-sitemaps...")
        for sitemap in sitemaps:
            loc = sitemap.find('loc')
            if loc and loc.text:
                urls.extend(fetch_sitemap(loc.text.strip(), visited))
    else:
        # It's a regular sitemap, find all <loc> inside <url> tags
        url_tags = soup.find_all('url')
        for url_tag in url_tags:
            loc = url_tag.find('loc')
            if loc and loc.text:
                urls.append(loc.text.strip())
                
    return urls

def main():
    sitemap_url = 'https://www.practo.com/profiles-sitemap.xml'
    print(f"Starting sitemap traversal from: {sitemap_url}")
    
    all_urls = fetch_sitemap(sitemap_url)
    
    print(f"Extraction complete. Found {len(all_urls)} URLs in total.")
    
    # Ensure the output directory exists
    output_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'output')
    os.makedirs(output_dir, exist_ok=True)
    
    # Save the list to output/profile_urls_raw.csv
    output_file = os.path.join(output_dir, 'profile_urls_raw.csv')
    df = pd.DataFrame({'url': all_urls})
    df.to_csv(output_file, index=False)
    
    print(f"Saved URLs to {output_file}")

if __name__ == '__main__':
    main()
