"""
optimization/run_study.py — Optuna study futtatása a MeanReversion + TrendFollowing komponensek
paramétereire, szimbólumonként külön (a régi kódbázis is per-szimbólum optimalizált, és az egyes
indexek eltérő karakterisztikája — lásd PLAN.md 2.1/2.2 empirikus mérések — indokolja, hogy ne egy
globális paraméterkészletet keressünk).

A study a walk-forward fold-okon (validate_walk_forward.py ugyanazon FOLD_BOUNDARIES-ével) mért,
kockázat-korrigált pontszámot maximalizálja (lásd optimization/objective.py) — NEM egyetlen
aggregált backtesztet, hogy elkerüljük a projekt korábbi túl-illeszkedési tanulságát.

A study végén a legjobb paraméterekkel újra lefuttatjuk a TELJES walk-forwardot (fold-onkénti
bontással, print_validation_report-tal), hogy közvetlenül összevethető legyen a vanilla (eddig
validált) baseline eredményével — nem elég a puszta Optuna-pontszám, a tényleges fold-onkénti
viselkedést is látni kell (lásd a "Fontos szabály" PLAN.md 6. pont végén).

Futtatás: python -m regime_framework.optimization.run_study
Opcionális argumentumok: --symbols US100Cash# US500Cash# ... --trials 200
(Élő MT5-terminál szükséges.)

⚠️ TRIAL-SZÁM PROJEKTSZABÁLY (2026-09-05): sose fusson 200 alatt alapértelmezésként — lásd a
DEFAULT_N_TRIALS melletti kommentet és PLAN.md 2.5 az empirikus indoklásért (US30: egy nem
melegindított 60 trial-os keresés ROSSZABB eredményt adott, mint a puszta paraméter-transzfer).
"""

import argparse
import logging

import MetaTrader5 as mt5
import optuna
from optuna.samplers import TPESampler
from optuna.trial import FixedTrial

from regime_framework.data.mt5_source import fetch_many
from regime_framework.optimization.objective import build_components, evaluate_on_folds
from regime_framework.core.engine import Engine
from regime_framework.validation.report import print_validation_report
from regime_framework.validation.validate_walk_forward import FOLD_BOUNDARIES

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)
optuna.logging.set_verbosity(optuna.logging.WARNING)

# Felhasználóval egyeztetve (2026-08-20): a US-kör 5 szimbólumból 3-ra szűkítve — a 3 legismertebb
# ÉS legjobban teljesítő US-index (Nasdaq/US100, S&P500/US500, Dow Jones/US30). US400Cash#/
# US2000Cash# kiesett (gyenge Optuna-pontszám: 3.81 / 3.09, lásd SESSION_LOG.md). JP225/GER40/EU50
# később, ha ez a kör összeáll.
DEFAULT_SYMBOLS = ["US100Cash#", "US500Cash#", "US30Cash#"]
# ⚠️ KORREKCIÓ (2026-08-20): eredetileg 2022-01-01 volt itt — lásd validate_walk_forward.py
# fejléc-docstringje a teljes indoklásért: a szimbólumok valós története csak kb. 2023-10-13-tól
# kezdődik, 2022-01-01 a valós adat előttre esett (MT5 "rátapadó" viselkedése miatt észrevétlenül).
# 2023-11-01-re javítva, összhangban a FOLD_BOUNDARIES-szel.
# ⚠️ PROJEKTSZABÁLY (felhasználóval egyeztetve, 2026-09-05 — lásd PLAN.md 2.5): a korábbi 60-as
# alapérték NEM elég ebben a ~15-20 dimenziós paraméctérben — az IC Markets US30 melegindítás
# empirikusan bebizonyította, hogy egy NEM melegindított 60 trial-os keresés akár ROSSZABB
# eredményt adhat, mint a puszta paraméter-transzfer (11.78 vs 21.62), miközben ugyanaz a
# keresési tér 200 trial-lal (vagy melegindítással) 40.89-et ér el. A 60-as érték innentől
# TILOS alapértékként — ha egy adott futtatásnál mégis kevesebb kell (pl. gyors villámteszt),
# azt EXPLICIT `--trials` argumentummal, indoklással kell kérni, nem hallgatólagosan.
START_DATE = "2023-11-01"
END_DATE = "2026-08-21"
DEFAULT_N_TRIALS = 200


def run_for_symbol(symbol, df, n_trials):
    logger.info("\n########## %s — Optuna study (%d trial, walk-forward fold-okon) ##########",
                symbol, n_trials)

    def objective(trial):
        return evaluate_on_folds(trial, df, FOLD_BOUNDARIES)

    study = optuna.create_study(direction="maximize", sampler=TPESampler(seed=42))
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)

    logger.info("  Legjobb kockázat-korrigált pontszám: %.2f", study.best_value)
    logger.info("  Legjobb paraméterek: %s", study.best_params)

    if study.best_value <= -1e5:
        logger.warning("  ⚠️ Egyetlen trial sem érte el a minimum trade-számot — nincs érvényes eredmény.")
        return

    logger.info("\n  --- Legjobb paraméterekkel újrafuttatott TELJES walk-forward ---")
    best_trial = FixedTrial(study.best_params)
    components, time_gated_components, quota_exempt_time_gated_components = build_components(best_trial)

    for fold_start, fold_end in FOLD_BOUNDARIES:
        fold_df = df[df["time"] < pd.Timestamp(fold_end)]
        if len(fold_df) == 0:
            continue
        engine = Engine(components, time_gated_components=time_gated_components,
                         quota_exempt_time_gated_components=quota_exempt_time_gated_components)
        report = engine.run(fold_df, stats_start_date=pd.Timestamp(fold_start).date())
        report.component_name = f"Optimalizált Engine[{symbol}] {fold_start[:7]}"
        print_validation_report(report)


def main():
    parser = argparse.ArgumentParser(description="Optuna hangolás a MeanReversion/TrendFollowing komponensekre.")
    parser.add_argument("--symbols", nargs="+", default=DEFAULT_SYMBOLS)
    parser.add_argument("--trials", type=int, default=DEFAULT_N_TRIALS)
    args = parser.parse_args()

    logger.info("--- 🔎 OPTUNA-HANGOLÁS (walk-forward fold-okon, kockázat-korrigált pontszám) ---")
    logger.info("Szimbólumok: %s | Trial/szimbólum: %d\n", ", ".join(args.symbols), args.trials)

    data = fetch_many(args.symbols, mt5.TIMEFRAME_M10, START_DATE, END_DATE)
    if not data:
        logger.error("❌ Egyetlen szimbólumhoz sem sikerült adatot lekérni.")
        return

    for symbol, df in data.items():
        run_for_symbol(symbol, df, args.trials)


if __name__ == "__main__":
    main()
