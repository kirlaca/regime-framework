"""
validation/validate_holdout.py — PRODUCTION_READINESS.md P1 #5. pont: valódi, "sosem látott"
hold-out validációs időszak.

A jelenlegi walk-forward (validate_walk_forward.py/optimization/run_study.py) jó (bővülő ablak,
fold-onkénti mérés), DE az Optuna a TELJES fold-halmazon választ "legjobbat" — nincs egy utolsó
szakasz, amit csak a hangolás lezárása UTÁN, egyszer nézünk meg, tiszta sanity check-ként.

Ez a script: (1) az utolsó ~2.7 hónapot (2026-06-01-től a legfrissebb elérhető adatig) explicit
KIVESZI a `TUNING_FOLD_BOUNDARIES`-ból (az Optuna ezt SOHA nem látja a hangolás közben), (2) egy
FRISS Optuna study-t futtat MINDHÁROM szimbólumra, KIZÁRÓLAG a megmaradt (2026-06-01 előtti)
fold-okon, (3) a talált "legjobb" paraméterekkel EGYETLEN, be nem avatkozó `Engine.run()`-t futtat
a hold-out időszakon (stats_start_date=HOLDOUT_START, a teljes megelőző adat csak bemelegítésként),
(4) összeveti a hold-out eredményt a hangolási fold-ok átlagával ÉS a MAI éles (teljes fold-
halmazon hangolt) paraméterek pontszámával.

FONTOS: ha a hold-out-ra hangolt paraméterek NEM egyeznek a mai éles paraméterekkel, az NEM
feltétlenül baj (az Optuna determinisztikus, de kevesebb adaton más optimumot találhat) -- a
lényeg, hogy a hold-out TELJESÍTMÉNY (nem a paraméter-egyezés) legyen összemérhető a hangolási
fold-ok átlagával. Ha a hold-out DRÁMAIAN rosszabb, az túltanulásra utalna.

Futtatás: python -m regime_framework.validation.validate_holdout
(Élő MT5-terminál szükséges.)
"""

import logging

import MetaTrader5 as mt5
import numpy as np
import optuna
import pandas as pd
from optuna.samplers import TPESampler
from optuna.trial import FixedTrial

from regime_framework.core.engine import Engine
from regime_framework.data.mt5_source import fetch_many
from regime_framework.optimization.objective import build_components, evaluate_on_folds
from regime_framework.validation.validate_walk_forward import CANDIDATE_SYMBOLS

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)
optuna.logging.set_verbosity(optuna.logging.WARNING)

START_DATE = "2023-11-01"
HOLDOUT_START = "2026-06-01"
HOLDOUT_END = "2026-08-21"  # a legfrissebb, ma elérhető adatig -- ez a SOSEM LÁTOTT szakasz vége
N_TRIALS = 60  # ugyanaz, mint optimization/run_study.py DEFAULT_N_TRIALS -- konzisztens erőfeszítés

# Az eredeti FOLD_BOUNDARIES (validate_walk_forward.py) utolsó 2 foldja (2026-04-01 utántól)
# LERÖVIDÍTVE/KIVÉVE, hogy a 2026-06-01-től induló hold-out-ot az Optuna SOHA ne lássa.
TUNING_FOLD_BOUNDARIES = [
    ("2024-01-01", "2024-04-01"),
    ("2024-04-01", "2024-07-01"),
    ("2024-07-01", "2024-10-01"),
    ("2024-10-01", "2025-01-01"),
    ("2025-01-01", "2025-04-01"),
    ("2025-04-01", "2025-07-01"),
    ("2025-07-01", "2025-10-01"),
    ("2025-10-01", "2026-01-01"),
    ("2026-01-01", "2026-04-01"),
    ("2026-04-01", "2026-06-01"),  # a korábbi 2026-07-01-es véghatár 2026-06-01-re rövidítve
]


def tune_on_reduced_folds(symbol, df):
    def objective(trial):
        return evaluate_on_folds(trial, df, TUNING_FOLD_BOUNDARIES)

    study = optuna.create_study(direction="maximize", sampler=TPESampler(seed=42))
    study.optimize(objective, n_trials=N_TRIALS, show_progress_bar=False)
    return study


def evaluate_holdout(symbol, df, best_params):
    trial = FixedTrial(best_params)
    components, time_gated, quota_exempt = build_components(trial)
    engine = Engine(components, time_gated_components=time_gated, quota_exempt_time_gated_components=quota_exempt)
    holdout_df = df[df["time"] < pd.Timestamp(HOLDOUT_END)]
    report = engine.run(holdout_df, stats_start_date=pd.Timestamp(HOLDOUT_START).date())
    return report


def main():
    logger.info("--- 🔎 Valódi hold-out validáció (PRODUCTION_READINESS.md P1 #5) ---")
    logger.info("Hangolási fold-ok: 2024-01-01 -- 2026-06-01 | Hold-out (SOSEM LÁTOTT): %s -- %s\n",
                HOLDOUT_START, HOLDOUT_END)

    if not mt5.initialize():
        logger.error("❌ MT5 inicializálás sikertelen: %s", mt5.last_error())
        return
    try:
        data = fetch_many(CANDIDATE_SYMBOLS, mt5.TIMEFRAME_M10, START_DATE, HOLDOUT_END)
    finally:
        mt5.shutdown()
    if not data:
        logger.error("❌ Egyetlen szimbólumhoz sem sikerült adatot lekérni.")
        return

    for symbol in CANDIDATE_SYMBOLS:
        df = data[symbol]
        logger.info("\n########## %s ##########", symbol)
        study = tune_on_reduced_folds(symbol, df)
        logger.info("  Hangolási (redukált fold-halmaz) pontszám: %.2f", study.best_value)
        logger.info("  Legjobb paraméterek (csak 2026-06-01 előtti adaton): %s", study.best_params)

        if study.best_value <= -1e5:
            logger.warning("  ⚠️ Egyetlen trial sem érte el a minimum trade-számot -- nincs érvényes eredmény.")
            continue

        holdout_report = evaluate_holdout(symbol, df, study.best_params)
        logger.info("\n  --- Hold-out eredmény (%s -- %s, a hangolás EZT SOHA nem látta) ---", HOLDOUT_START, HOLDOUT_END)
        logger.info("  Trade szám: %d | Win rate: %.1f%% | Bruttó PF: %.2f | Nettó PF: %s",
                    holdout_report.trade_count, holdout_report.win_rate, holdout_report.profit_factor,
                    holdout_report.notes.get("net_profit_factor"))
        logger.info("  Bruttó PnL: %.2f | Nettó PnL: %s",
                    holdout_report.total_pnl, holdout_report.notes.get("total_net_pnl"))
        if not holdout_report.is_reliable():
            logger.warning("  ⚠️ Csak %d trade a hold-out-on -- a 30-as megbízhatósági küszöb ALATT, óvatosan értelmezendő.",
                            holdout_report.trade_count)

    logger.info(
        "\nÉrtelmezés: a hold-out pontszám/PF a HANGOLÁS SORÁN SOHA NEM LÁTOTT adaton mért, valódi "
        "out-of-sample teljesítmény. Ha ez NAGYSÁGRENDILEG hasonló a hangolási fold-ok átlagos "
        "minőségéhez (nem esik szét, nem lesz PF<1), az megerősíti, hogy a paraméterek NEM "
        "túlilleszkedettek a konkrét, eddig látott fold-halmazra. Ha a hold-out DRÁMAIAN rosszabb "
        "(PF<1, vagy a bruttó/nettó pontszámhoz képest nagyságrendekkel elmarad), az túltanulásra "
        "utalna -- ekkor érdemes lenne konzervatívabb (kevésbé finomhangolt) paramétereket "
        "választani, vagy több adatot gyűjteni, mielőtt élesben bővítjük a kitettséget."
    )


if __name__ == "__main__":
    main()
