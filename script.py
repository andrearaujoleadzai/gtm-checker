import requests
import csv

SHEET_URL = "https://docs.google.com/spreadsheets/d/1dktdNbgWmTPl-yGbVsg3x2sta1Zb4ZEDyGJuKC2IXhI/export?format=csv&gid=1949940405"

headers = {
    "User-Agent": "Mozilla/5.0"
}

response = requests.get(SHEET_URL)
response.raise_for_status()

lines = response.text.splitlines()
reader = csv.DictReader(lines)

urls = []

for row in reader:
    website = row.get("website")
    
    if website:
        website = website.strip().lower()
        
        # adicionar https se não existir
        if not website.startswith("http"):
            website = "https://" + website
        
        urls.append(website)

missing_gtm = set()

for url in urls:
    try:
        r = requests.get(url, headers=headers, timeout=10)
        html = r.text
        
        if "googletagmanager.com" not in html:
            missing_gtm.add(url)
    
    except Exception as e:
        print(f"Erro em {url}: {e}")

print(f"Checked: {len(urls)} sites")
print(f"Missing GTM: {len(missing_gtm)}")

for site in missing_gtm:
    print(site)
