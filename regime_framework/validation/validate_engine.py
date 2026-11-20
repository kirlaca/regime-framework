"""
Lefuttatja a teljes `Engine`-t (MeanReversion + TrendFollowing a trend_band-XOR-on, plusz
LastHourContinuation mint time_gated, plusz FridayShort mint quota_exempt_time_gated komponens)
minden jelölt indexen, valós MT5 adaton.

Ez az ELSŐ pont, ahol a korábban KÜLÖN-KÜLÖN validált komponensek EGYÜTT futnak. A PLAN.md 6.
build-sorrend pontja explicit figyelmeztet: egy komponens elszigetelt validációja NEM garantálja,
hogy a teljes rendszerben is jól teljesít — ezért a riport komponensenkénti bontást is ad, hogy
összevethető legyen a korábban külön mért eredményekkel (validate_mean_reversion.py /
validate_trend_following.py / research/last_hour_continuation_experiment.py /
research/day_hour_confirmatory_check.py).

A LastHourContinuation `time_gated_components`-ként van bekötve (2026-08-21), NEM a rendes
`components` listában — lásd core/engine.py modul-docstringje: csak akkor kap esélyt a
check_entry()-re, ha a rendes trend_band-komponens az adott bar-on nem jelzett. A
research/last_hour_engine_conflict_check.py mérése szerint ez várhatóan a standalone (elszigetelt)
teszthez képest az esetek ~70-76%-ára szorítja vissza a trade-számát — ez SZÁNDÉKOS, nem hiba.

A FridayShort `quota_exempt_time_gated_components`-ként van bekötve (2026-08-21) — a normál
`time_gated_components` sorrend ennél a KÉSŐI (23:00-ás) triggernél túl kevés szabad napot hagyott
volna (lásd research/friday_short_engine_conflict_check.py: 11.5-25.7%). A quota_exempt út egy
SZŰK, csak erre a slotra vonatkozó napi-kvóta-kivétellel dolgozik (lásd core/engine.py
modul-docstringje és research/friday_short_quota_exception_check.py) — ez a MeanReversion/
TrendFollowing/LastHourContinuation trade-számát BIZONYÍTOTTAN nem érinti.

Futtatás: python -m regime_framework.validation.validate_engine
(Élő MT5-terminál szükséges.)
"""

import logging

import MetaTrader5 as mt5

from regime_framework.components.friday_short import FridayShortComponent
from regime_framework.components.last_hour_continuation import LastHourContinuationComponent
from regime_framework.components.mean_reversion import MeanReversionComponent
from regime_framework.components.trend_following import TrendFollowingComponent
from regime_framework.core.engine import Engine
from regime_framework.data.mt5_source import fetch_many
from regime_framework.validation.report import print_validation_report

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

# Felhasználóval egyeztetve (2026-08-19): időzítés miatt ebben a körben CSAK a US-csoportra
# fókuszálunk. JP225/GER40/EU50 később, ha az US-kör összeáll.
# Felhasználóval egyeztetve (2026-08-20): 3 legismertebb ÉS legjobban teljesítő US-index
# (Nasdaq/US100, S&P500/US500, Dow Jones/US30) — US400/US2000 kiesett (gyenge Optuna-pontszám).
CANDIDATE_SYMBOLS = ["US100Cash#", "US500Cash#", "US30Cash#"]
START_DATE = "2025-01-01"
END_DATE = "2026-08-01"


def main():
    logger.info("--- 🔎 Engine VALIDÁCIÓ (MeanReversion + TrendFollowing együtt, XOR-dispatch) ---")
    logger.info("Szimbólumok: %s\n", ", ".join(CANDIDATE_SYMBOLS))

    data = fetch_many(CANDIDATE_SYMBOLS, mt5.TIMEFRAME_M10, START_DATE, END_DATE)

    if not data:
        logger.error("❌ Egyetlen szimbólumhoz sem sikerült adatot lekérni.")
        return

    for symbol, df in data.items():
        engine = Engine(
            components=[MeanReversionComponent(), TrendFollowingComponent()],
            time_gated_components=[LastHourContinuationComponent()],
            quota_exempt_time_gated_components=[FridayShortComponent()],
        )
        report = engine.run(df)
        report.component_name = f"Engine[{symbol}]"
        print_validation_report(report)


if __name__ == "__main__":
    main()
