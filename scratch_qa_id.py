import re
html = open('output/sample_profile.html', encoding='utf-8').read()
print(set(re.findall(r'data-qa-id="([^"]+)"', html)))
