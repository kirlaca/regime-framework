"""
Lefuttatja a `MarketConditionClassifier.validate()`-jét minden jelölt indexen, valós MT5 adaton.
Mivel ez a rétegen univerzális (nem instrumentum-csoportos konfig, lásd regime/market_condition.py
docstringje), ugyanazt az osztályt futtatjuk mind az 5 szimbólumon.

Futtatás: python -m regime_framework.validation.validate_market_condition
(Élő MT5-terminál szükséges.)
"""

import logging

import MetaTrader5 as mt5

from regime_framework.data.mt5_source import fetch_many
from regime_framework.regime.market_condition import MarketConditionClassifier
from regime_framework.validation.report import print_validation_report

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

CANDIDATE_SYMBOLS = ["US100Cash#", "US500Cash#", "JP225Cash#", "GER40Cash#", "EU50Cash#"]
START_DATE = "2025-01-01"
END_DATE = "2026-08-01"


def main():
    logger.info("--- 🔎 MarketConditionClassifier VALIDÁCIÓ ---")
    logger.info("Szimbólumok: %s\n", ", ".join(CANDIDATE_SYMBOLS))

    data = fetch_many(CANDIDATE_SYMBOLS, mt5.TIMEFRAME_M10, START_DATE, END_DATE)

    if not data:
        logger.error("❌ Egyetlen szimbólumhoz sem sikerült adatot lekérni.")
        return

    classifier = MarketConditionClassifier()
    for symbol, df in data.items():
        report = classifier.validate(df)
        report.component_name = f"MarketConditionClassifier[{symbol}]"
        print_validation_report(report)


if __name__ == "__main__":
    main()
