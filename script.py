import requests
import csv

SHEET_URL = "https://docs.google.com/spreadsheets/d/1dktdNbgWmTPl-yGbVsg3x2sta1Zb4ZEDyGJuKC2IXhI/export?format=csv"

response = requests.get(SHEET_URL)
lines = response.text.splitlines()
urls = [row[0] for row in csv.reader(lines)]

missing_gtm = set()

headers = {
    "User-Agent": "Mozilla/5.0"
}

for url in urls:
    try:
        r = requests.get(url, headers=headers, timeout=10)
        html = r.text
        
        if "googletagmanager.com" not in html:
            missing_gtm.add(url)
    
    except:
        continue

print("Sites sem GTM:")
for site in missing_gtm:
    print(site)
