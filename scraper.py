"""
Dropi Scraper v5 - Intercepta el token de la sesión real del browser
"""

import asyncio
import json
import csv
import os
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from playwright.async_api import async_playwright

load_dotenv()

CATEGORIAS = [
    "Mascotas",
    # "Electrónica",
    # "Hogar",
]

PAGE_SIZE  = 60
OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)
API_URL    = "https://api.dropi.ar/api/products/v4/index"
BASE_URL   = "https://app.dropi.ar"


async def esperar_login_y_capturar_token(page) -> str:
    """Abre el browser, espera login manual e intercepta el token."""
    token_capturado = {"value": None}

    async def interceptar(response):
        if token_capturado["value"]:
            return
        try:
            ct = response.headers.get("content-type", "")
            if "json" not in ct:
                return
            # Buscar en cualquier respuesta de la API de dropi
            if "dropi.ar" not in response.url:
                return
            auth = response.request.headers.get("x-authorization", "")
            if auth.startswith("Bearer "):
                token_capturado["value"] = auth.replace("Bearer ", "").strip()
                print(f"   🔑 Token capturado de la sesión")
        except Exception:
            pass

    page.on("response", interceptar)

    email = os.getenv("EMAIL", "")
    password = os.getenv("PASSWORD", "")

    print("🌐 Abriendo Dropi en el browser...")
    await page.goto(f"{BASE_URL}/auth/login", wait_until="domcontentloaded")
    await page.wait_for_timeout(2000)

    if email and password:
        try:
            email_input = page.locator("input[type='email'], input[name='email'], input[name='username']").first
            pass_input  = page.locator("input[type='password']").first
            if await email_input.is_visible(timeout=3000):
                await email_input.fill(email)
                await pass_input.fill(password)
                submit = page.locator("button[type='submit'], button:has-text('Ingresar'), button:has-text('Iniciar')").first
                if await submit.is_visible(timeout=2000):
                    await submit.click()
                print("   ✅ Credenciales autocompletadas — si hay 2FA, completalo en el browser\n")
        except Exception:
            print("   ⚠️  No se pudieron autocompletar las credenciales, login manual requerido\n")
    else:
        print("   → Completá email y contraseña en el browser\n")

    print("   → Si hay 2FA, completalo. Cuando estés en el dashboard, el script continúa\n")
    await page.wait_for_url("**/dashboard/**", timeout=120000)
    await page.wait_for_timeout(3000)

    # Si no capturamos el token aún, navegar para disparar requests
    if not token_capturado["value"]:
        await page.goto(
            f"{BASE_URL}/dashboard/search?search_type=simple&category=Mascotas",
            wait_until="networkidle"
        )
        await page.wait_for_timeout(3000)

    page.remove_listener("response", interceptar)

    if not token_capturado["value"]:
        raise Exception("No se pudo capturar el token. Intentá navegar a alguna categoría manualmente.")

    print("✅ Login exitoso y token capturado\n")
    return token_capturado["value"]


async def fetch_page(page, token: str, categoria: str, start: int) -> dict:
    """Llama a la API usando el token capturado."""
    payload = {
        "pageSize": PAGE_SIZE,
        "startData": start,
        "privated_product": False,
        "category": [categoria],
        "userVerified": False,
        "favorite": False,
        "with_collection": True,
        "get_stock": False,
        "no_count": True,
        "search_type": "simple",
        "country": "ARGENTINA",
    }

    result = await page.evaluate("""
        async ([url, token, payload]) => {
            const resp = await fetch(url, {
                method: "POST",
                headers: {
                    "Accept": "application/json, text/plain, */*",
                    "Content-Type": "application/json",
                    "X-Authorization": "Bearer " + token,
                    "x-captcha-token": "",
                    "Origin": "https://app.dropi.ar",
                    "Referer": "https://app.dropi.ar/",
                },
                body: JSON.stringify(payload),
            });
            const data = await resp.json();
            return { status: resp.status, data };
        }
    """, [API_URL, token, payload])

    if result["status"] != 200:
        raise Exception(f"HTTP {result['status']}: {json.dumps(result['data'])}")

    return result["data"]


def parse_products(data: dict, categoria: str) -> list[dict]:
    raw_list = (
        data.get("objects") or data.get("products") or data.get("data") or
        data.get("items") or data.get("results") or []
    )
    if isinstance(raw_list, dict):
        raw_list = raw_list.get("data") or raw_list.get("items") or []

    products = []
    for p in raw_list:
        if not isinstance(p, dict):
            continue
        pid  = p.get("id") or p.get("product_id") or ""
        slug = p.get("slug") or p.get("url_key") or ""
        img  = p.get("image") or p.get("main_image") or p.get("thumbnail") or ""
        if isinstance(img, list): img = img[0] if img else ""
        if isinstance(img, dict): img = img.get("url") or img.get("src") or ""

        products.append({
            "id":                  pid,
            "nombre":              p.get("name") or p.get("title") or "",
            "precio_dropshipping": p.get("dropshipping_price") or p.get("drop_price") or p.get("price") or 0,
            "precio_sugerido":     p.get("suggested_price") or p.get("sale_price") or 0,
            "stock":               p.get("stock") or p.get("quantity") or p.get("available_quantity") or "N/A",
            "categoria":           categoria,
            "sku":                 p.get("sku") or "",
            "marca":               p.get("brand") or p.get("marca") or "",
            "imagen":              str(img),
            "url":                 f"{BASE_URL}/dashboard/product-details/{pid}/{slug}" if pid else "",
            "fecha_scraping":      datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
    return products


async def scrape_categoria(page, token: str, categoria: str) -> list[dict]:
    print(f"📦 Scrapeando: {categoria}")

    await page.goto(
        f"{BASE_URL}/dashboard/search?search_type=simple&category={categoria}",
        wait_until="networkidle"
    )
    await page.wait_for_timeout(2000)

    all_products, start, page_num = [], 0, 1

    while True:
        print(f"   📄 Página {page_num} (offset {start})...", end=" ", flush=True)
        try:
            data = await fetch_page(page, token, categoria, start)
        except Exception as e:
            print(f"\n   ❌ {e}")
            break

        products = parse_products(data, categoria)
        print(f"{len(products)} productos")

        if not products:
            print(f"   ℹ️  Respuesta: {json.dumps(data, ensure_ascii=False)[:400]}")
            break

        all_products.extend(products)
        if len(products) < PAGE_SIZE:
            break

        start    += PAGE_SIZE
        page_num += 1
        await asyncio.sleep(0.5)

    print(f"   ✅ Total: {len(all_products)} en '{categoria}'\n")
    return all_products


def export(products, ts):
    fields = ["id", "nombre", "precio_dropshipping", "precio_sugerido",
              "stock", "categoria", "sku", "marca", "url", "fecha_scraping"]

    csv_path = OUTPUT_DIR / f"dropi_{ts}.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(products)

    json_path = OUTPUT_DIR / f"dropi_{ts}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(products, f, ensure_ascii=False, indent=2)

    print(f"📄 CSV  → {csv_path}")
    print(f"📄 JSON → {json_path}")


async def main():
    print("=" * 50)
    print("  DROPI SCRAPER v5")
    print("=" * 50)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=False,
            args=["--no-sandbox", "--start-maximized"]
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
        )
        page = await context.new_page()

        token = await esperar_login_y_capturar_token(page)

        all_products = []
        for cat in CATEGORIAS:
            productos = await scrape_categoria(page, token, cat)
            all_products.extend(productos)

        await browser.close()

    if not all_products:
        print("⚠️  No se encontraron productos.")
        return

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    export(all_products, ts)

    print(f"\n✅ {len(all_products)} productos totales.")
    print("\n--- Muestra ---")
    for p in all_products[:3]:
        print(f"  [{p['id']}] {p['nombre']} | Drop: ${p['precio_dropshipping']} | Stock: {p['stock']}")


if __name__ == "__main__":
    asyncio.run(main())