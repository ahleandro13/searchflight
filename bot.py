"""
✈️ SearchElfla Bot - Amadeus API optimizada
1 corrida por día, destinos fijos + comodín rotativo.
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
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "-5243665537")

# ─── FECHAS Y DURACIONES (reducido para no pasarse del límite) ────────────────
FECHAS_IDA = ["2026-07-10", "2026-12-05"]
DURACIONES = [7, 14]

# ─── DESTINOS FIJOS ───────────────────────────────────────────────────────────
DESTINOS_FIJOS = [
    {"ciudad": "Rio de Janeiro", "codigo": "GIG", "emoji": "🇧🇷", "precio_max": 600},
    {"ciudad": "Nueva York",     "codigo": "JFK", "emoji": "🗽", "precio_max": 600},
    {"ciudad": "Newark",         "codigo": "EWR", "emoji": "🗽", "precio_max": 600},
    {"ciudad": "Tokio",          "codigo": "NRT", "emoji": "🗾", "precio_max": 1200},
    {"ciudad": "Madrid",         "codigo": "MAD", "emoji": "🥘", "precio_max": 800},
]

# ─── COMODÍN ROTATIVO (uno por día de la semana) ──────────────────────────────
COMODINES = [
    {"ciudad": "Marruecos",    "codigo": "CMN", "emoji": "🇲🇦", "precio_max": 900},   # Lunes
    {"ciudad": "París",        "codigo": "CDG", "emoji": "🗼", "precio_max": 800},   # Martes
    {"ciudad": "Porto",        "codigo": "OPO", "emoji": "🇵🇹", "precio_max": 800},  # Miércoles
    {"ciudad": "Los Angeles",  "codigo": "LAX", "emoji": "🎬", "precio_max": 700},   # Jueves
    {"ciudad": "Corea del Sur","codigo": "ICN", "emoji": "🇰🇷", "precio_max": 1200}, # Viernes
    {"ciudad": "China",        "codigo": "PEK", "emoji": "🇨🇳", "precio_max": 1200}, # Sábado
    {"ciudad": "Marruecos",    "codigo": "CMN", "emoji": "🇲🇦", "precio_max": 900},  # Domingo
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
    mejor_absoluto = None
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
                    vuelo = {
                        "origen": origen, "destino": destino,
                        "fecha_ida": fecha_ida, "fecha_vuelta": fecha_vuelta,
                        "dias": dias, "precio": precio,
                        "link": (
                            f"https://www.skyscanner.com.ar/transporte/vuelos/"
                            f"{origen.lower()}/{destino.lower()}/"
                            f"{fecha_ida.replace('-','')}/{fecha_vuelta.replace('-','')}/"
                        )
                    }
                    if precio <= precio_max:
                        if mejor is None or precio < mejor["precio"]:
                            mejor = vuelo
                    if mejor_absoluto is None or precio < mejor_absoluto["precio"]:
                        mejor_absoluto = vuelo
            except ResponseError as e:
                log.warning(f"  Error {origen}->{destino} {fecha_ida}: {e}")
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
    log.info("🔍 Iniciando búsqueda de promos...")
    amadeus = Client(client_id=AMADEUS_API_KEY, client_secret=AMADEUS_API_SECRET)
    bot = Bot(token=TELEGRAM_TOKEN)
    cache = cargar_cache()
    hubo_algo = False

    # Comodín del día
    dia_semana = datetime.now().weekday()  # 0=Lunes, 6=Domingo
    comodin = COMODINES[dia_semana]
    log.info(f"🎲 Comodín de hoy ({datetime.now().strftime('%A')}): {comodin['ciudad']}")

    todos_destinos = DESTINOS_FIJOS + [comodin]
    resultados = []
    mejores_absolutos = []

    for dest in todos_destinos:
        for origen in ORIGENES:
            log.info(f"  {origen} → {dest['ciudad']}")
            vuelo, vuelo_abs = buscar_vuelo(amadeus, origen, dest["codigo"], dest["precio_max"])

            if vuelo:
                clave = f"{origen}-{dest['codigo']}-{vuelo['fecha_ida']}-{vuelo['precio']}"
                if clave not in cache:
                    resultados.append({**vuelo, "ciudad": dest["ciudad"], "emoji": dest["emoji"], "clave": clave, "precio_max": dest["precio_max"]})
            elif vuelo_abs:
                clave = f"{origen}-{dest['codigo']}-{vuelo_abs['fecha_ida']}-{vuelo_abs['precio']}"
                if clave not in cache:
                    mejores_absolutos.append({**vuelo_abs, "ciudad": dest["ciudad"], "emoji": dest["emoji"], "clave": clave})

    resultados.sort(key=lambda x: x["precio"])

    if resultados:
        hubo_algo = True
        header = (
            f"✈️ *SearchElfla — Promos del día*\n"
            f"📆 _{datetime.now().strftime('%d/%m/%Y')}_\n"
            f"🎲 Comodín: *{comodin['ciudad']}* {comodin['emoji']}"
        )
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=header, parse_mode=ParseMode.MARKDOWN)

        for v in resultados[:6]:  # máximo 6 promos
            msg = formatear_vuelo(v, v["emoji"], v["ciudad"])
            await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=msg, parse_mode=ParseMode.MARKDOWN)
            cache.add(v["clave"])
            await asyncio.sleep(0.5)

    # Si no hubo nada dentro del precio, mandar el mejor disponible
    if not resultados and mejores_absolutos:
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
