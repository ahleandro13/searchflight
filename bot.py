"""
✈️ SearchElfla Bot - Intercepta requests internas de Google Flights
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


def extraer_precios_de_response(body_text):
    """Extrae precios USD de las respuestas internas de Google Flights."""
    precios = []
    try:
        # Buscar patrones de precio con contexto USD o $ cercano
        # Formato típico en respuestas internas: ,"USD","450", o similar
        matches = re.findall(r'["\[]USD["\]],?\s*["\[]?(\d{3,5})["\]]?', body_text)
        for m in matches:
            p = int(m)
            if 200 < p < 8000:
                precios.append(p)

        # Formato: "price":{"amount":"550"
        matches2 = re.findall(r'"(?:amount|price|totalPrice|total)"\s*:\s*"?(\d{3,5})"?', body_text)
        for m in matches2:
            p = int(m)
            if 200 < p < 8000:
                precios.append(p)

        # Formato con decimales tipo 550.00
        matches3 = re.findall(r'\b([3-9]\d{2}|[1-7]\d{3})\.\d{2}\b', body_text)
        for m in matches3:
            p = int(m)
            if 200 < p < 8000:
                precios.append(p)
    except Exception:
        pass
    return precios


async def buscar_vuelo(context, origen, destino, precio_max):
    mejor = None
    mejor_absoluto = None

    for fecha_ida in FECHAS_IDA:
        for dias in DURACIONES:
            fecha_vuelta = (
                datetime.strptime(fecha_ida, "%Y-%m-%d") + timedelta(days=dias)
            ).strftime("%Y-%m-%d")

            precios_capturados = []

            page = await context.new_page()

            async def capturar_response(response):
                url = response.url
                # Interceptar requests que Google Flights hace internamente
                if any(k in url for k in ["flights/", "travel/flights", "batchexecute", "BestFlights", "GetShoppingResults"]):
                    try:
                        body = await response.text()
                        ps = extraer_precios_de_response(body)
                        precios_capturados.extend(ps)
                    except Exception:
                        pass

            page.on("response", capturar_response)

            try:
                # URL directa con parámetros de fecha
                fi = fecha_ida.replace("-", "")
                fv = fecha_vuelta.replace("-", "")
                url = (
                    f"https://www.google.com/travel/flights?"
                    f"tfs=CBwQAhoeEgoyMDI2LTA3LTEwagcIARID{origen}cgcIARID{destino}"
                    f"&curr=USD&hl=es-419"
                )
                # URL más simple que sí funciona
                url = (
                    f"https://www.google.com/travel/flights/search?"
                    f"tfs=CBwQAho"
                    f"&hl=es-419&curr=USD"
                    f"&tfu=EgIIAQ"
                )
                # Usar URL con query string legible
                url = (
                    f"https://www.google.com/travel/flights?"
                    f"q=flights+from+{origen}+to+{destino}"
                    f"+on+{fecha_ida}+returning+{fecha_vuelta}"
                    f"&curr=USD&hl=es"
                )

                await page.goto(url, timeout=50000, wait_until="networkidle")
                await page.wait_for_timeout(6000)

                # Si no capturamos nada por network, intentar desde el DOM
                if not precios_capturados:
                    content = await page.content()
                    # Buscar precios con $ seguido de 3-4 dígitos, con contexto
                    for pattern in [
                        r'aria-label="[^"]*\$\s*(\d[\d,]+)',
                        r'>\$\s*([3-9]\d{2}|[1-7]\d{3})<',
                        r'"totalPrice"\s*:\s*"(\d{3,5})"',
                        r'data-price="([3-9]\d{2}|[1-7]\d{3})"',
                    ]:
                        for m in re.findall(pattern, content):
                            try:
                                p = int(m.replace(",", ""))
                                if 200 < p < 8000:
                                    precios_capturados.append(p)
                            except Exception:
                                pass

                if precios_capturados:
                    precio = min(precios_capturados)
                    link = (
                        f"https://www.google.com/travel/flights?"
                        f"q=flights+from+{origen}+to+{destino}"
                        f"+on+{fecha_ida}+returning+{fecha_vuelta}&curr=USD"
                    )
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
                    log.info(f"    → USD {precio}")
                else:
                    log.warning(f"    → Sin precio encontrado")

            except Exception as e:
                log.warning(f"    Error: {e}")
            finally:
                await page.close()

    return mejor, mejor_absoluto


def formatear_vuelo(vuelo, emoji, ciudad, origen_label=None, es_mejor_disponible=False):
    origen = origen_label or vuelo["origen"]
    prefijo = "⚠️ *Mejor precio disponible*\n" if es_mejor_disponible else ""
    return (
        f"{prefijo}{emoji} *{origen} → {ciudad}*\n"
        f"  📅 {vuelo['fecha_ida']} → {vuelo['fecha_vuelta']} _{vuelo['dias']} días_\n"
        f"  💰 *USD {vuelo['precio']:.0f}* ida y vuelta\n"
        f"  🔗 [Ver vuelo]({vuelo['link']})"
    )


async def enviar_alertas():
    log.info("🔍 Iniciando búsqueda con Google Flights...")
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
                "--lang=es-AR",
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
            extra_http_headers={"Accept-Language": "es-AR,es;q=0.9"},
        )
        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

        for dest in todos_destinos:
            for origen in ORIGENES:
                log.info(f"  {origen} → {dest['ciudad']}")
                vuelo, vuelo_abs = await buscar_vuelo(context, origen, dest["codigo"], dest["precio_max"])

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
