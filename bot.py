"""
✈️ SearchElfla Bot - Scraping TurismoCity
Destinos fijos + comodín rotativo. 1 vez por día.
"""

import asyncio
import json
import os
import re
import logging
from datetime import datetime, timedelta
from playwright.async_api import async_playwright
from telegram import Bot
from telegram.constants import ParseMode

TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "8767742566:AAFYfn-rQJNweL--WWwbQEy1DsuI2jB4FB8")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "-5243665537")

DURACIONES  = [7, 14]
FECHAS_IDA  = ["2026-07-10", "2026-12-05"]

DESTINOS_FIJOS = [
    {"ciudad": "Rio de Janeiro", "codigo": "GIG", "emoji": "🇧🇷", "precio_max": 600},
    {"ciudad": "Nueva York",     "codigo": "JFK", "emoji": "🗽", "precio_max": 600},
    {"ciudad": "Newark",         "codigo": "EWR", "emoji": "🗽", "precio_max": 600},
    {"ciudad": "Tokio",          "codigo": "NRT", "emoji": "🗾", "precio_max": 1200},
    {"ciudad": "Madrid",         "codigo": "MAD", "emoji": "🥘", "precio_max": 800},
]

COMODINES = [
    {"ciudad": "Marruecos",     "codigo": "CMN", "emoji": "🇲🇦", "precio_max": 900},   # Lunes
    {"ciudad": "París",         "codigo": "CDG", "emoji": "🗼",  "precio_max": 800},   # Martes
    {"ciudad": "Porto",         "codigo": "OPO", "emoji": "🇵🇹", "precio_max": 800},   # Miércoles
    {"ciudad": "Los Angeles",   "codigo": "LAX", "emoji": "🎬",  "precio_max": 700},   # Jueves
    {"ciudad": "Corea del Sur", "codigo": "ICN", "emoji": "🇰🇷", "precio_max": 1200},  # Viernes
    {"ciudad": "China",         "codigo": "PEK", "emoji": "🇨🇳", "precio_max": 1200},  # Sábado
    {"ciudad": "Marruecos",     "codigo": "CMN", "emoji": "🇲🇦", "precio_max": 900},   # Domingo
]

ORIGENES = ["EZE", "AEP"]

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
log = logging.getLogger(__name__)
CACHE_FILE = "alertas_enviadas.json"


def cargar_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE) as f:
            return set(json.load(f))
    return set()


def guardar_cache(cache):
    with open(CACHE_FILE, "w") as f:
        json.dump(list(cache), f)


async def buscar_vuelo(page, origen, destino, precio_max):
    mejor = None
    mejor_absoluto = None

    for fecha_ida in FECHAS_IDA:
        for dias in DURACIONES:
            fecha_vuelta = (
                datetime.strptime(fecha_ida, "%Y-%m-%d") + timedelta(days=dias)
            ).strftime("%Y-%m-%d")

            # URL directa de TurismoCity: /vuelos/ORIGEN/DESTINO/IDA/VUELTA/adultos/ninos/bebes
            url = (
                f"https://www.turismocity.com.ar/vuelos/"
                f"{origen}/{destino}/{fecha_ida}/{fecha_vuelta}/1/0/0"
            )

            try:
                await page.goto(url, timeout=60000, wait_until="networkidle")
                await page.wait_for_timeout(8000)

                content = await page.content()
                precios = []

                # TurismoCity muestra precios en USD con formato "USD 1.234" o "U$S 1.234"
                for pattern in [
                    r'USD\s*(\d[\d\.]+)',
                    r'U\$S\s*(\d[\d\.]+)',
                    r'\$\s*(\d[\d\.]+)',
                    r'"price"\s*:\s*(\d+)',
                    r'"amount"\s*:\s*(\d+)',
                    r'data-price="(\d+)"',
                    r'class="[^"]*price[^"]*"[^>]*>\s*[\$USD]*\s*([\d\.]+)',
                ]:
                    for m in re.findall(pattern, content):
                        try:
                            # TurismoCity usa punto como separador de miles
                            p = float(m.replace(".", "").replace(",", "."))
                            if 200 < p < 8000:
                                precios.append(p)
                        except Exception:
                            pass

                if precios:
                    precio = min(precios)
                    link = url
                    vuelo = {
                        "origen": origen, "destino": destino,
                        "fecha_ida": fecha_ida, "fecha_vuelta": fecha_vuelta,
                        "dias": dias, "precio": precio, "link": link,
                    }
                    if precio <= precio_max:
                        if mejor is None or precio < mejor["precio"]:
                            mejor = vuelo
                    if mejor_absoluto is None or precio < mejor_absoluto["precio"]:
                        mejor_absoluto = vuelo
                    log.info(f"    → USD {precio:.0f}")
                else:
                    log.info(f"    → Sin precio")

            except Exception as e:
                log.warning(f"    Error: {e}")

    return mejor, mejor_absoluto


def formatear_vuelo(vuelo, emoji, ciudad, es_mejor_disponible=False):
    prefijo = "⚠️ *Mejor precio disponible*\n" if es_mejor_disponible else ""
    return (
        f"{prefijo}{emoji} *{vuelo['origen']} → {ciudad}*\n"
        f"  📅 {vuelo['fecha_ida']} → {vuelo['fecha_vuelta']} _{vuelo['dias']} días_\n"
        f"  💰 *USD {vuelo['precio']:.0f}* ida y vuelta\n"
        f"  🔗 [Ver vuelo]({vuelo['link']})"
    )


async def enviar_alertas():
    log.info("🔍 Iniciando búsqueda en TurismoCity...")
    bot = Bot(token=TELEGRAM_TOKEN)
    cache = cargar_cache()
    hubo_algo = False

    dia_semana = datetime.now().weekday()
    comodin = COMODINES[dia_semana]
    log.info(f"🎲 Comodín de hoy: {comodin['ciudad']}")

    todos_destinos = DESTINOS_FIJOS + [comodin]
    resultados = []
    mejores_absolutos = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox", "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ]
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            locale="es-AR",
            timezone_id="America/Argentina/Buenos_Aires",
            viewport={"width": 1280, "height": 800},
        )
        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        page = await context.new_page()

        for dest in todos_destinos:
            for origen in ORIGENES:
                log.info(f"  {origen} → {dest['ciudad']}")
                vuelo, vuelo_abs = await buscar_vuelo(page, origen, dest["codigo"], dest["precio_max"])

                if vuelo:
                    clave = f"{origen}-{dest['codigo']}-{vuelo['fecha_ida']}-{vuelo['precio']}"
                    if clave not in cache:
                        resultados.append({**vuelo, "ciudad": dest["ciudad"], "emoji": dest["emoji"], "clave": clave})
                elif vuelo_abs:
                    clave = f"{origen}-{dest['codigo']}-{vuelo_abs['fecha_ida']}-{vuelo_abs['precio']}"
                    if clave not in cache:
                        mejores_absolutos.append({**vuelo_abs, "ciudad": dest["ciudad"], "emoji": dest["emoji"], "clave": clave})

        await browser.close()

    resultados.sort(key=lambda x: x["precio"])

    if resultados:
        hubo_algo = True
        header = (
            f"✈️ *SearchElfla — Promos del día*\n"
            f"📆 _{datetime.now().strftime('%d/%m/%Y')}_\n"
            f"🎲 Comodín: *{comodin['ciudad']}* {comodin['emoji']}"
        )
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=header, parse_mode=ParseMode.MARKDOWN)
        for v in resultados[:6]:
            msg = formatear_vuelo(v, v["emoji"], v["ciudad"])
            await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=msg, parse_mode=ParseMode.MARKDOWN)
            cache.add(v["clave"])
            await asyncio.sleep(0.5)
    elif mejores_absolutos:
        hubo_algo = True
        mejores_absolutos.sort(key=lambda x: x["precio"])
        header = f"✈️ *SearchElfla — Mejor disponible hoy*\n📆 _{datetime.now().strftime('%d/%m/%Y')}_"
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=header, parse_mode=ParseMode.MARKDOWN)
        for v in mejores_absolutos[:3]:
            msg = formatear_vuelo(v, v["emoji"], v["ciudad"], es_mejor_disponible=True)
            await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=msg, parse_mode=ParseMode.MARKDOWN)
            cache.add(v["clave"])
            await asyncio.sleep(0.5)

    if hubo_algo:
        guardar_cache(cache)
        log.info("✅ Alertas enviadas.")
    else:
        log.info("😴 No hay promos nuevas.")


if __name__ == "__main__":
    asyncio.run(enviar_alertas())
