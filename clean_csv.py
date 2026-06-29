import csv
import re
import unicodedata
from pathlib import Path
from datetime import datetime

OUTPUT_DIR = Path("output")

csv_files = sorted(OUTPUT_DIR.glob("dropi_[0-9]*.csv"))
csv_files = [f for f in csv_files if "_clean" not in f.name]
if not csv_files:
    print("No se encontraron archivos CSV originales en output/")
    exit(1)

latest = csv_files[-1]
print(f"Leyendo: {latest}")

with open(latest, newline="", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    rows = list(reader)

def clean_text(text: str) -> str:
    text = text.strip()
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"\s+", " ", text)
    text = text.title()
    return text

for r in rows:
    r["nombre"] = clean_text(r.get("nombre", ""))

rows.sort(key=lambda r: r.get("nombre", "").strip().lower())

KEEP = ["nombre", "precio_sugerido", "sku", "categoria", "url", "fecha_scraping"]

ts = datetime.now().strftime("%Y%m%d_%H%M%S")
clean_path = OUTPUT_DIR / f"dropi_{ts}_clean.csv"
with open(clean_path, "w", newline="", encoding="utf-8-sig") as f:
    writer = csv.DictWriter(f, fieldnames=KEEP, extrasaction="ignore", delimiter=";")
    writer.writeheader()
    writer.writerows(rows)

print(f"CSV limpio  → {clean_path}")
print(f"Total: {len(rows)} productos")

for r in rows[:5]:
    print(f"  {r['nombre']} | ${r['precio_sugerido']} | SKU: {r.get('sku', '')}")
