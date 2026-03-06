"""
✈️ SearchElfla Bot - Alertas de Vuelos
Busca las mejores promos por región cada 2 horas y avisa por Telegram.
"""

import asyncio
import json
import os
import logging
from datetime import datetime, timedelta
from amadeus import Client, ResponseError
from telegram import Bot
from telegram.constants import ParseMode

AMADEUS_API_KEY    = os.getenv("AMADEUS_API_KEY", "eoCeI32NL91jlziH9NdkHlMKBlUYfDPh")
AMADEUS_API_SECRET = os.getenv("AMADEUS_API_SECRET", "n2luYirmCa7RNMNI")
TELEGRAM_TOKEN     = os.getenv("TELEGRAM_TOKEN", "8767742566:AAFYfn-rQJNweL--WWwbQEy1DsuI2jB4FB8")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "5700288881")

FECHAS_IDA = [
    "2026-07-10",
    "2026-08-07",
    "2026-10-09",
    "2026-12-05",
]
DURACIONES = [7, 14]

REGIONES = [
    {
        "nombre": "🌎 América",
        "precio_max": 600,
        "top": 3,
        "destinos": [
            {"ciudad": "Miami",            "codigo": "MIA", "emoji": "🌴"},
            {"ciudad": "Nueva York",       "codigo": "JFK", "emoji": "🗽"},
            {"ciudad": "Newark",           "codigo": "EWR", "emoji": "🗽"},
            {"ciudad": "Los Angeles",      "codigo": "LAX", "emoji": "🎬"},
            {"ciudad": "Cancún",           "codigo": "CUN", "emoji": "🏖️"},
            {"ciudad": "Bogotá",           "codigo": "BOG", "emoji": "🇨🇴"},
            {"ciudad": "Punta Cana",       "codigo": "PUJ", "emoji": "🌺"},
            {"ciudad": "Rio de Janeiro",   "codigo": "GIG", "emoji": "🇧🇷"},
            {"ciudad": "Ciudad de México", "codigo": "MEX", "emoji": "🌮"},
            {"ciudad": "San José CR",      "codigo": "SJO", "emoji": "🌿"},
        ],
    },
    {
        "nombre": "🌍 Europa",
        "precio_max": 800,
        "top": 3,
        "destinos": [
            {"ciudad": "Madrid",    "codigo": "MAD", "emoji": "🥘"},
            {"ciudad": "Barcelona", "codigo": "BCN", "emoji": "🏟️"},
            {"ciudad": "Lisboa",    "codigo": "LIS", "emoji": "🇵🇹"},
            {"ciudad": "Roma",      "codigo": "FCO", "emoji": "🍕"},
            {"ciudad": "París",     "codigo": "CDG", "emoji": "🗼"},
            {"ciudad": "Londres",   "codigo": "LHR", "emoji": "🇬🇧"},
            {"ciudad": "Amsterdam", "codigo": "AMS", "emoji": "🌷"},
            {"ciudad": "Berlín",    "codigo": "BER", "emoji": "🇩🇪"},
        ],
    },
    {
        "nombre": "🌏 Asia & Medio Oriente",
        "precio_max": 1200,
        "top": 3,
        "destinos": [
            {"ciudad": "Tokio",    "codigo": "NRT", "emoji": "🗾"},
            {"ciudad": "Bangkok",  "codigo": "BKK", "emoji": "🇹🇭"},
            {"ciudad": "Bali",     "codigo": "DPS", "emoji": "🌺"},
            {"ciudad": "Dubai",    "codigo": "DXB", "emoji": "🏙️"},
            {"ciudad": "Singapur", "codigo": "SIN", "emoji": "🦁"},
            {"ciudad": "Seoul",    "codigo": "ICN", "emoji": "🇰🇷"},
        ],
    },
]

BONUS_TRACK = [
    {"nombre": "GRU → Los Angeles", "origen": "GRU", "destino": "LAX", "precio_max": 900,  "emoji": "🎬"},
    {"nombre": "EZE → Tokio",       "origen": "EZE", "destino": "NRT", "precio_max": 1300, "emoji": "🗾"},
    {"nombre": "AEP → Miami",       "origen": "AEP", "destino": "MIA", "precio_max": 650,  "emoji": "🌴"},
    {"nombre": "EZE → Bangkok",     "origen": "EZE", "destino": "BKK", "precio_max": 1100, "emoji": "🇹🇭"},
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


def buscar_vuelo(amadeus, origen, destino, precio_max):
    mejor = None
    for fecha_ida in FECHAS_IDA:
        for dias in DURACIONES:
            fecha_vuelta = (datetime.strptime(fecha_ida, "%Y-%m-%d") + timedelta(days=dias)).strftime("%Y-%m-%d")
            try:
                response = amadeus.shopping.flight_offers_search.get(
                    originLocationCode=origen,
                    destinationLocationCode=destino,
                    departureDate=fecha_ida,
                    returnDate=fecha_vuelta,
                    adults=1,
                    max=3,
                    currencyCode="USD"
                )
                for oferta in response.data:
                    precio = float(oferta["price"]["total"])
                    if precio <= precio_max:
                        if mejor is None or precio < mejor["precio"]:
                            mejor = {
                                "origen":       origen,
                                "destino":      destino,
                                "fecha_ida":    fecha_ida,
                                "fecha_vuelta": fecha_vuelta,
                                "dias":         dias,
                                "precio":       precio,
                                "link": (
                                    f"https://www.skyscanner.com.ar/transporte/vuelos/"
                                    f"{origen.lower()}/{destino.lower()}/"
                                    f"{fecha_ida.replace('-','')}/{fecha_vuelta.replace('-','')}/"
                                )
                            }
            except ResponseError as e:
                log.warning(f"  Error {origen}->{destino} {fecha_ida}: {e}")
    return mejor


def formatear_vuelo(vuelo, emoji, ciudad, origen_label=None):
    origen = origen_label or vuelo["origen"]
    return (
        f"{emoji} *{origen} → {ciudad}*\n"
        f"  📅 {vuelo['fecha_ida']} → {vuelo['fecha_vuelta']} _{vuelo['dias']} días_\n"
        f"  💰 *USD {vuelo['precio']:.0f}* ida y vuelta\n"
        f"  🔗 [Ver vuelo]({vuelo['link']})"
    )


async def enviar_alertas():
    log.info("🔍 Iniciando búsqueda de promos...")
    amadeus = Client(client_id=AMADEUS_API_KEY, client_secret=AMADEUS_API_SECRET)
    bot = Bot(token=TELEGRAM_TOKEN)
    cache = cargar_cache()
    hubo_algo = False

    for region in REGIONES:
        log.info(f"Región: {region['nombre']}")
        resultados = []
        for origen in ORIGENES:
            for dest in region["destinos"]:
                log.info(f"  {origen} → {dest['ciudad']}")
                vuelo = buscar_vuelo(amadeus, origen, dest["codigo"], region["precio_max"])
                if vuelo:
                    clave = f"{origen}-{dest['codigo']}-{vuelo['fecha_ida']}-{vuelo['precio']}"
                    if clave not in cache:
                        resultados.append({**vuelo, "ciudad": dest["ciudad"], "emoji": dest["emoji"], "clave": clave})

        resultados.sort(key=lambda x: x["precio"])
        top = resultados[:region["top"]]

        if top:
            hubo_algo = True
            header = f"{region['nombre']} — *Top {len(top)} promos*\n📆 _{datetime.now().strftime('%d/%m/%Y %H:%M')}_"
            await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=header, parse_mode=ParseMode.MARKDOWN)
            for v in top:
                msg = formatear_vuelo(v, v["emoji"], v["ciudad"])
                await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=msg, parse_mode=ParseMode.MARKDOWN)
                cache.add(v["clave"])
                await asyncio.sleep(0.5)

    log.info("Bonus Track...")
    bonus_encontrados = []
    for bt in BONUS_TRACK:
        log.info(f"  {bt['nombre']}")
        vuelo = buscar_vuelo(amadeus, bt["origen"], bt["destino"], bt["precio_max"])
        if vuelo:
            clave = f"BT-{bt['origen']}-{bt['destino']}-{vuelo['fecha_ida']}-{vuelo['precio']}"
            if clave not in cache:
                bonus_encontrados.append({**vuelo, "nombre": bt["nombre"], "emoji": bt["emoji"], "clave": clave})

    bonus_encontrados.sort(key=lambda x: x["precio"])
    bonus_top = bonus_encontrados[:2]

    if bonus_top:
        hubo_algo = True
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text="✨ *Bonus Track — Combinaciones especiales*", parse_mode=ParseMode.MARKDOWN)
        for v in bonus_top:
            partes = v["nombre"].split("→")
            msg = formatear_vuelo(v, v["emoji"], partes[1].strip(), partes[0].strip())
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
