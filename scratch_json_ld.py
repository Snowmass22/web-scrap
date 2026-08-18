import json
from bs4 import BeautifulSoup

soup = BeautifulSoup(open('output/sample_profile.html', encoding='utf-8'), 'lxml')
for tag in soup.find_all("script", type="application/ld+json"):
    if tag.string:
        try:
            print(json.dumps(json.loads(tag.string), indent=2))
        except Exception:
            pass
