"""
Lefuttatja a `SessionPhaseClassifier.validate()`-jét minden ismert (GROUPS-ban szereplő)
szimbólumra, valós MT5 adaton. Ez a "külön tesztelhető" követelmény (PLAN.md 0. Cél 1. pont)
konkrét megvalósítása erre az osztályozóra.

Futtatás: python -m regime_framework.validation.validate_session_phase
(Élő MT5-terminál szükséges.)
"""

import logging

from regime_framework.data.mt5_source import fetch_many
from regime_framework.regime.session_phase import GROUPS, SessionPhaseClassifier
from regime_framework.validation.report import print_validation_report

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

START_DATE = "2025-01-01"
END_DATE = "2026-08-01"


def main():
    import MetaTrader5 as mt5

    all_symbols = sorted(s for group in GROUPS.values() for s in group["symbols"])
    logger.info("--- 🔎 SessionPhaseClassifier VALIDÁCIÓ ---")
    logger.info("Szimbólumok: %s\n", ", ".join(all_symbols))

    data = fetch_many(all_symbols, mt5.TIMEFRAME_M10, START_DATE, END_DATE)

    if not data:
        logger.error("❌ Egyetlen szimbólumhoz sem sikerült adatot lekérni.")
        return

    for symbol, df in data.items():
        classifier = SessionPhaseClassifier(symbol)
        report = classifier.validate(df)
        print_validation_report(report)


if __name__ == "__main__":
    main()
