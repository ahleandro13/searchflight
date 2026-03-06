import asyncio
import json
import os
import logging
from datetime import datetime
from amadeus import Client, ResponseError
from telegram import Bot
from telegram.constants import ParseMode

AMADEUS_API_KEY    = "eoCeI32NL91jlziH9NdkHlMKBlUYfDPh"
AMADEUS_API_SECRET = "n2luYirmCa7RNMNI"
TELEGRAM_TOKEN     = "8767742566:AAFYfn-rQJNweL--WWwbQEy1DsuI2jB4FB8"
TELEGRAM_CHAT_ID   = "5700288881"

ALERTAS = [
    {"nombre": "BUE → Miami",      "origen": "EZE", "destino": "MIA", "precio_max": 500},
    {"nombre": "BUE → Nueva York", "origen": "EZE", "destino": "JFK", "precio_max": 600},
    {"nombre": "BUE → Madrid",     "origen": "EZE", "destino": "MAD", "precio_max": 700},
]

FECHAS = ["2026-07-15", "2026-08-10", "2026-09-20", "2026-12-10"]

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

def buscar_vuelos(amadeus, alerta):
    resultados = []
    for fecha in FECHAS:
        try:
            response = amadeus.shopping.flight_offers_search.get(
                originLocationCode=alerta["origen"],
                destinationLocationCode=alerta["destino"],
                departureDate=fecha,
                adults=1,
                max=5,
                currencyCode="USD"
            )
            for oferta in response.data:
                precio = float(oferta["price"]["total"])
                if precio <= alerta["precio_max"]:
                    resultados.append({
                        "nombre":  alerta["nombre"],
                        "destino": alerta["destino"],
                        "origen":  alerta["origen"],
                        "fecha":   fecha,
                        "precio":  precio,
                        "link":    f"https://www.skyscanner.com.ar/transporte/vuelos/{alerta['origen'].lower()}/{alerta['destino'].lower()}/{fecha.replace('-', '')}/",
                    })
        except ResponseError as e:
            log.warning(f"Error {alerta['nombre']} {fecha}: {e}")
    resultados.sort(key=lambda x: x["precio"])
    return resultados

async def enviar_alertas():
    log.info("🔍 Buscando promos...")
    amadeus = Client(client_id=AMADEUS_API_KEY, client_secret=AMADEUS_API_SECRET)
    bot = Bot(token=TELEGRAM_TOKEN)
    cache = cargar_cache()
    nuevas = []

    for alerta in ALERTAS:
        log.info(f"Buscando: {alerta['nombre']}")
        for vuelo in buscar_vuelos(amadeus, alerta):
            clave = f"{vuelo['destino']}-{vuelo['fecha']}-{vuelo['precio']}"
            if clave not in cache:
                nuevas.append(vuelo)
                cache.add(clave)

    if nuevas:
        header = f"🚨 *¡{len(nuevas)} promo(s) nueva(s)!*\n📆 _{datetime.now().strftime('%d/%m/%Y %H:%M')}_"
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=header, parse_mode=ParseMode.MARKDOWN)
        for v in nuevas:
            msg = f"✈️ *{v['nombre']}*\n📅 `{v['fecha']}`\n💰 *USD {v['precio']:.0f}*\n🔗 [Ver vuelo]({v['link']})"
            await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=msg, parse_mode=ParseMode.MARKDOWN)
            await asyncio.sleep(0.5)
        guardar_cache(cache)
        log.info(f"✅ {len(nuevas)} alertas enviadas.")
    else:
        log.info("😴 No hay promos nuevas.")

if __name__ == "__main__":
    asyncio.run(enviar_alertas())
