"""
Walk-forward validáció: az Engine-t nem csak a TELJES 19 hónapos ablakon átlagosan nyereséges-e
vizsgáljuk (lásd validate_engine.py), hanem konzisztensen az egymás utáni negyedéves
részidőszakokban is. Ez a projekt egyik legkorábbi, legfontosabb tanulsága (main_optuna_anomaly.py/
main_optuna_hybrid.py) — egy puszta aggregált backtest elrejtheti, hogy az eredmény csak néhány
kiugró, szerencsés szakasznak köszönhető, miközben a legtöbb részidőszak valójában veszteséges.

BŐVÜLŐ ABLAK (expanding window): minden fold a df-ben elérhető TELJES eddigi historikus adatot
felhasználja a regime-osztályozás/indikátorok bemelegítéséhez (nem dob el korábbi adatot csak azért,
hogy "tiszta" fold-határt kapjon), de a riport metrikái CSAK az adott fold dátumtartományában
NYITOTT trade-eket számítják bele — lásd `Engine.run(stats_start_date=...)`.

Az első fold a START_DATE utáni 3. hónapban indul, mert a MarketConditionClassifier gördülő ablaka
(~60 kereskedési nap ≈ 8640 M10 bar ≈ 3 naptári hónap) előtte nem termel érvényes trend_band/
vol_band besorolást — lásd regime/market_condition.py.

Felhasználóval egyeztetve (2026-08-20): START_DATE 2025-01-01-ről kiterjesztve (a rövidebb ablak a
TrendFollowing SHORT-oldalán a 30-as megbízhatósági küszöb alatt maradt, túlnyomórészt bullish
időszak volt). ⚠️ KORREKCIÓ: eredetileg 2022-01-01-re lett állítva, DE kiderült (research/
diagnose_missing_early_folds.py + verify_2022_data_authenticity.py), hogy a szimbólumok valós
története csak kb. 2023-10-13-tól kezdődik ennél a brókernél ("Cash Ultra Low" termékcsalád) — a
2022-01-01 dátum a valós történelem ELŐTTRE esett, amit az MT5 egy alattomos viselkedése (a
tartományon kívüli kérésre a legkorábbi elérhető bar-ra "rátapad", nem None-t ad) elrejtett, a
`mt5_source.fetch_rates()` csendben csonka adatot adott vissza. Ez most javítva (lásd
mt5_source.py) — START_DATE 2023-11-01-re korrigálva (biztonságos, valós adat utáni kezdet), a
FOLD_BOUNDARIES 2024-01-01-től indul (a klasszifikátor ~3 hónapos bemelegítése miatt). Az EZZEL A
(hibásan címkézett, de valós adatú) ablakkal futtatott korábbi validációk/Optuna-hangolás EREDMÉNYEI
ÉRVÉNYESEK maradnak (a ténylegesen lekért adat helyes volt, ~2023-10-19-től) — csak a dátum-
címkézésük volt téves, nem kell újrafuttatni őket.

Futtatás: python -m regime_framework.validation.validate_walk_forward
(Élő MT5-terminál szükséges.)
"""

import logging

import MetaTrader5 as mt5
import pandas as pd

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
START_DATE = "2023-11-01"
END_DATE = "2026-08-01"

FOLD_BOUNDARIES = [
    ("2024-01-01", "2024-04-01"),
    ("2024-04-01", "2024-07-01"),
    ("2024-07-01", "2024-10-01"),
    ("2024-10-01", "2025-01-01"),
    ("2025-01-01", "2025-04-01"),
    ("2025-04-01", "2025-07-01"),
    ("2025-07-01", "2025-10-01"),
    ("2025-10-01", "2026-01-01"),
    ("2026-01-01", "2026-04-01"),
    ("2026-04-01", "2026-07-01"),
    ("2026-07-01", "2026-08-01"),
]


def run_symbol(symbol, df):
    logger.info("\n########## %s ##########", symbol)
    fold_reports = []
    for fold_start, fold_end in FOLD_BOUNDARIES:
        fold_df = df[df["time"] < pd.Timestamp(fold_end)]
        if len(fold_df) == 0:
            continue
        engine = Engine([MeanReversionComponent(), TrendFollowingComponent()])
        report = engine.run(fold_df, stats_start_date=pd.Timestamp(fold_start).date())
        report.component_name = f"Engine[{symbol}] {fold_start[:7]}"
        print_validation_report(report)
        fold_reports.append(report)

    positive_folds = sum(1 for r in fold_reports if r.trade_count > 0 and r.total_pnl > 0)
    reliable_folds = [r for r in fold_reports if r.is_reliable()]
    logger.info(
        "  --- Összegzés %s: %d/%d fold pozitív PnL-lel, %d/%d fold éri el a 30-as "
        "megbízhatósági küszöböt ---",
        symbol, positive_folds, len(fold_reports), len(reliable_folds), len(fold_reports),
    )
    if positive_folds < len(fold_reports):
        logger.warning(
            "  ⚠️ Nem minden fold pozitív — az aggregált (validate_engine.py) eredmény "
            "részben egy-két kiugró szakasznak köszönhető lehet."
        )


def main():
    logger.info("--- 🔎 WALK-FORWARD VALIDÁCIÓ (Engine, negyedéves fold-ok, bővülő ablak) ---")
    logger.info("Szimbólumok: %s", ", ".join(CANDIDATE_SYMBOLS))
    logger.info("Fold-határok: %s\n", FOLD_BOUNDARIES)

    data = fetch_many(CANDIDATE_SYMBOLS, mt5.TIMEFRAME_M10, START_DATE, END_DATE)
    if not data:
        logger.error("❌ Egyetlen szimbólumhoz sem sikerült adatot lekérni.")
        return

    for symbol, df in data.items():
        run_symbol(symbol, df)


if __name__ == "__main__":
    main()
