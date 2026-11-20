"""
Lefuttatja a `MeanReversionComponent.validate()`-jét minden jelölt indexen, valós MT5 adaton.

Regresszió-ellenőrzés: a régi kódbázis regime_conditional_backtest.py-ja oldalazó napokon
42.9% win-rate-et és +60.34 összesített PnL-t mért US500Cash#-en (fix, "vanilla" paraméterekkel,
nem Optuna-hangolva). Ez a script ugyanazokkal a vanilla paraméterekkel fut — ha a portolás
helyes, a szám nagyságrendileg hasonló irányt kell mutasson (a pontos érték eltérhet, mert a régi
mérés más regime-osztályozást és eltérő historikus tartományt használt — lásd PLAN.md 2.3).

Futtatás: python -m regime_framework.validation.validate_mean_reversion
(Élő MT5-terminál szükséges.)
"""

import logging

import MetaTrader5 as mt5

from regime_framework.components.mean_reversion import MeanReversionComponent
from regime_framework.data.mt5_source import fetch_many
from regime_framework.validation.report import print_validation_report

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

# Felhasználóval egyeztetve (2026-08-19): időzítés miatt ebben a körben CSAK a US-csoportra
# fókuszálunk. JP225/GER40/EU50 később, ha az US-kör összeáll.
# Felhasználóval egyeztetve (2026-08-20): 3 legismertebb ÉS legjobban teljesítő US-index
# (Nasdaq/US100, S&P500/US500, Dow Jones/US30) — US400/US2000 kiesett (gyenge Optuna-pontszám).
CANDIDATE_SYMBOLS = ["US100Cash#", "US500Cash#", "US30Cash#"]
# ⚠️ KORREKCIÓ (2026-08-20): lásd validate_trend_following.py azonos konstansának kommentjét —
# a "2022-01-01" téves volt (a szimbólumok valós története csak kb. 2023-10-13-tól kezdődik),
# 2023-11-01-re javítva.
START_DATE = "2023-11-01"
END_DATE = "2026-08-01"


def main():
    logger.info("--- 🔎 MeanReversionComponent VALIDÁCIÓ (regresszió-ellenőrzés) ---")
    logger.info("Szimbólumok: %s\n", ", ".join(CANDIDATE_SYMBOLS))

    data = fetch_many(CANDIDATE_SYMBOLS, mt5.TIMEFRAME_M10, START_DATE, END_DATE)

    if not data:
        logger.error("❌ Egyetlen szimbólumhoz sem sikerült adatot lekérni.")
        return

    component = MeanReversionComponent()
    for symbol, df in data.items():
        report = component.validate(df)
        report.component_name = f"MeanReversionComponent[{symbol}]"
        print_validation_report(report)


if __name__ == "__main__":
    main()
