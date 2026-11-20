"""
MT5 adatlekérés — EGY helyen, hogy a regime_framework egyetlen más modulja se hívja közvetlenül
az MT5 API-t (lásd PLAN.md package-struktúra: data/mt5_source.py).

Több szimbólumot is támogat egy híváson belül (a session-fázis empirikus méréséhez kell, ahol
egyszerre több index-jelöltet — US-index, JP225, GER40, EU50 — akarunk mérni), és hibatűrő: ha egy
szimbólum nem elérhető a számlán (pl. egy elgépelt/eltérő névvariáció), azt jelzi és kihagyja,
nem szakítja meg a többi lekérést.
"""

import logging
import time

import MetaTrader5 as mt5
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# research/diagnose_large_range_fetch.py mérése (2026-08-20): egyetlen copy_rates_range() hívás
# M10-en 18 hónapnál (52 855 bar) még működött, 24 hónapnál már "Invalid params" hibát adott --
# ez egy kemény, a terminál/API oldali korlát az egy hívásban visszaadható bar-számra. Emiatt a
# fetch_rates() a teljes [start_date, end_date] tartományt ekkora darabokra (chunk) bontja, és
# összefűzi -- így a hívó oldal nem kell tudjon erről a korlátról, tetszőlegesen hosszú tartományt
# kérhet. 120 nap biztonságosan a mért, működő 6 hónapos (17 797 bar) szint alatt marad.
MAX_CHUNK_DAYS = 120

# research/diagnose_missing_early_folds.py fogta meg (2026-08-20): egy régebbi chunk (pl. 2022-es
# szakasz) az ELSŐ próbálkozásra None-t/üreset adhat vissza, mert a terminál még nem cache-elte le
# helyben -- utólagos hívásra (kis várakozás után, ami időt ad a terminálnak a háttérben letölteni)
# már sikeres. Enélkül a fetch_rates() CSENDBEN egy rövidebb, csonka tartományt adott volna vissza
# (a kevesebb sikeres chunk miatt), miközben a hívó "sikeres" letöltést látott (98090 gyertya, csak
# épp 2023-10-től, nem a kért 2022-01-01-től) -- ez egy alattomos, észrevétlen hiba volt.
CHUNK_RETRY_ATTEMPTS = 3
CHUNK_RETRY_DELAY_SECONDS = 1.5


def fetch_rates(symbol, timeframe, start_date, end_date):
    """Egyetlen szimbólum letöltése, szükség esetén több `copy_rates_range()` hívásra darabolva
    (lásd MAX_CHUNK_DAYS fent). Feltételezi, hogy mt5.initialize() már lefutott (lásd fetch_many)
    — ez a függvény nem inicializál/zár le semmit saját maga, hogy több szimbólumot egy
    kapcsolaton lehessen lekérni egymás után anélkül, hogy újra és újra csatlakoznánk."""
    if not mt5.symbol_select(symbol, True):
        logger.warning("  ⚠️ A szimbólum (%s) nem található / nem választható ki.", symbol)
        return None

    symbol_info = mt5.symbol_info(symbol)
    point = symbol_info.point if symbol_info is not None else None

    start_ts = pd.to_datetime(start_date)
    end_ts = pd.to_datetime(end_date)

    chunks = []
    missing_ranges = []
    chunk_start = start_ts
    while chunk_start < end_ts:
        chunk_end = min(chunk_start + pd.Timedelta(days=MAX_CHUNK_DAYS), end_ts)
        rates = None
        for attempt in range(CHUNK_RETRY_ATTEMPTS):
            candidate = mt5.copy_rates_range(symbol, timeframe, chunk_start, chunk_end)
            # research/verify_2022_data_authenticity.py fogta meg (2026-08-20): ha a kért
            # tartomány a szimbólum tényleges történelme ELŐTT van, az MT5 NEM None-t/üreset ad
            # vissza, hanem "rátapad" a legkorábbi elérhető bar-ra és AZT az 1 bar-t adja vissza —
            # ez `len(rates) > 0` miatt hamisan "van adat"-nak tűnne. Ezért itt explicit
            # ellenőrizzük, hogy a visszaadott bar-ok időbélyege ténylegesen a KÉRT ablakba esik-e.
            if candidate is not None and len(candidate) > 0:
                first_time = pd.Timestamp(candidate[0]["time"], unit="s")
                if chunk_start <= first_time < chunk_end:
                    rates = candidate
                    break
            if attempt < CHUNK_RETRY_ATTEMPTS - 1:
                time.sleep(CHUNK_RETRY_DELAY_SECONDS)

        if rates is not None and len(rates) > 0:
            chunks.append(pd.DataFrame(rates))
        else:
            missing_ranges.append((chunk_start, chunk_end))
        chunk_start = chunk_end

    if missing_ranges:
        logger.warning(
            "  ⚠️ %s: %d/%d chunk NEM adott adatot %d próbálkozás után sem — a visszaadott "
            "idősor CSONKA lehet a kért tartományhoz képest! Hiányzó szakaszok: %s",
            symbol, len(missing_ranges), len(missing_ranges) + len(chunks), CHUNK_RETRY_ATTEMPTS,
            ", ".join(f"{s.date()}–{e.date()}" for s, e in missing_ranges),
        )

    if not chunks:
        logger.warning("  ⚠️ Nincs adat (%s, %s - %s). MT5 hiba: %s",
                        symbol, start_date, end_date, mt5.last_error())
        return None

    df = pd.concat(chunks, ignore_index=True)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    # a chunk-határok (chunk_end == következő chunk_start) átfedhetik egymást egy bar erejéig,
    # mivel a copy_rates_range() mindkét végén zárt intervallumot ad -- ezt itt szűrjük ki
    df.drop_duplicates(subset='time', keep='first', inplace=True)
    df.sort_values('time', inplace=True)
    df.reset_index(drop=True, inplace=True)

    if point is not None and 'spread' in df.columns and df['spread'].max() > 0:
        df['spread_price'] = df['spread'] * point
    else:
        df['spread_price'] = np.nan

    return df


def fetch_many(symbols, timeframe, start_date, end_date):
    """Több szimbólum lekérése EGY MT5 kapcsolaton belül.

    Visszaad egy {symbol: DataFrame} szótárat — a nem elérhető szimbólumok egyszerűen kimaradnak
    belőle (nem dobnak kivételt), hogy egy rossz/hiányzó szimbólum-név-tipp ne akassza meg a többi
    instrumentum mérését."""
    if not mt5.initialize():
        logger.error("❌ MT5 inicializálás sikertelen: %s", mt5.last_error())
        return {}

    results = {}
    try:
        for symbol in symbols:
            logger.info("Letöltés: %s...", symbol)
            df = fetch_rates(symbol, timeframe, start_date, end_date)
            if df is not None:
                results[symbol] = df
                logger.info("  ✅ %d gyertya", len(df))
            else:
                logger.warning("  → kihagyva: %s", symbol)
    finally:
        mt5.shutdown()

    return results
