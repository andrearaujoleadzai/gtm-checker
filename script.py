import requests
import csv

SHEET_URL = "https://docs.google.com/spreadsheets/d/1dktdNbgWmTPl-yGbVsg3x2sta1Zb4ZEDyGJuKC2IXhI/export?format=csv&gid=1949940405"

headers = {
    "User-Agent": "Mozilla/5.0"
}

response = requests.get(SHEET_URL)
response.raise_for_status()

lines = response.text.splitlines()
reader = csv.reader(lines)

# se tiver header, ignora primeira linha
urls = []
for i, row in enumerate(reader):
    if i == 0:
        continue  # remove se não tiver header
    
    if row and row[0].startswith("http"):
        urls.append(row[0].strip())

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
