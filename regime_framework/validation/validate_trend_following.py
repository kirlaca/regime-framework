"""
Lefuttatja a `TrendFollowingComponent.validate()`-jét minden jelölt indexen, valós MT5 adaton.

Regresszió-ellenőrzés: a régi kódbázisban a trend_leg_validation.py (Donchian-kitörésre) és a
main_optuna_hybrid.py teljes walk-forward futtatása (EMA-keresztezésre) validálta ezt a szálat —
utóbbi ~60%-os javulást hozott a walk-forward átlagon (-2.99 -> -1.17) a puszta MeanReversion-
kikapcsoláshoz képest. Ez a script ugyanazokkal a vanilla (FIXED_TREND_*) paraméterekkel fut.

Futtatás: python -m regime_framework.validation.validate_trend_following
(Élő MT5-terminál szükséges.)
"""

import logging

import MetaTrader5 as mt5

from regime_framework.components.trend_following import TrendFollowingComponent
from regime_framework.data.mt5_source import fetch_many
from regime_framework.validation.report import print_validation_report

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

# Felhasználóval egyeztetve (2026-08-19): időzítés miatt ebben a körben CSAK a US-csoportra
# fókuszálunk. JP225/GER40/EU50 később, ha az US-kör összeáll.
# Felhasználóval egyeztetve (2026-08-20): 3 legismertebb ÉS legjobban teljesítő US-index
# (Nasdaq/US100, S&P500/US500, Dow Jones/US30) — US400/US2000 kiesett (gyenge Optuna-pontszám).
CANDIDATE_SYMBOLS = ["US100Cash#", "US500Cash#", "US30Cash#"]
# ⚠️ KORREKCIÓ (2026-08-20): eredetileg 2022-01-01 volt itt, de kiderült (research/
# diagnose_missing_early_folds.py + verify_2022_data_authenticity.py), hogy ez a dátum a
# szimbólumok tényleges történelme ELŐTTRE esik — a "Cash Ultra Low" termékcsalád (lásd
# symbol_info.path) csak kb. 2023-10-13-án indult ennél a brókernél. A `mt5_source.fetch_rates()`
# emiatt CSENDBEN csonka adatot adott vissza (a valós ~2023-10-19-től), amit az MT5 "rátapadó"
# viselkedése (tartományon kívüli kérésre a legkorábbi elérhető bar-t adja vissza, nem None-t)
# elrejtett — ez a hiba most javítva (lásd mt5_source.py). A validációk, amik "2022-01-01"-gyel
# futottak, VALÓS adaton futottak (csak a valós ~2023-10-19-es kezdettől) — nem kell újrafuttatni
# őket, csak a dátum-címkézés volt téves. 2023-11-01 egy biztonságos, a valós történelem indulása
# utáni, tisztán adatolt kezdőpont.
START_DATE = "2023-11-01"
END_DATE = "2026-08-01"


def main():
    logger.info("--- 🔎 TrendFollowingComponent VALIDÁCIÓ (regresszió-ellenőrzés) ---")
    logger.info("Szimbólumok: %s\n", ", ".join(CANDIDATE_SYMBOLS))

    data = fetch_many(CANDIDATE_SYMBOLS, mt5.TIMEFRAME_M10, START_DATE, END_DATE)

    if not data:
        logger.error("❌ Egyetlen szimbólumhoz sem sikerült adatot lekérni.")
        return

    component = TrendFollowingComponent()
    for symbol, df in data.items():
        report = component.validate(df)
        report.component_name = f"TrendFollowingComponent[{symbol}]"
        print_validation_report(report)


if __name__ == "__main__":
    main()
