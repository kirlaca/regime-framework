"""
optimization/objective.py — Optuna célfüggvény a MeanReversion + TrendFollowing komponensek
paramétereinek hangolásához.

A WALK-FORWARD fold-okon mérünk (nem egyetlen aggregált backteszten), hogy elkerüljük a projekt
korábbi, dokumentált hibáját (költség-paraméter "gaming", lásd main_optuna_anomaly.py története és
PLAN.md 2. táblázat: "a monoton ösztönző mindig a modellezett költség minimalizálása felé tolja a
paramétert, függetlenül attól, hogy az reális-e").

A pontszám NEM a puszta összesített PnL — az egy negyedév kiugrásának engedne túl nagy súlyt (lásd
a 2025-07 "nyári uborkaszezon" felismerést a walk-forward validációból, ami minden szimbólumon
EGYSZERRE rontott — PLAN.md 6. build-sorrend pont). Helyette a fold-onkénti PnL-ek ÁTLAGÁT egy
szórás-büntetéssel kombinálja (kockázat-korrigált pontszám: konzisztensen közepes jobb, mint kiugróan
jó de szórásos), plusz egy kemény minimum-trade-szám őrző (a Turnaround Tuesday tanulság — lásd
core/types.py ValidationReport.is_reliable() ugyanerről az elvről).

✅ NETTÓ (spread-korrigált) PnL-en optimalizál (hozzáadva 2026-08-22, lásd PRODUCTION_READINESS.md
1. pont) — korábban a `report.total_pnl` (BRUTTÓ) ment be a pontszámba, a spread csak utólagos
Strategy Tester-es ellenőrzés volt. ⚠️ FONTOS KÜLÖNBSÉG a `main_optuna_anomaly.py` régi, dokumentált
hibájához képest ("a monoton ösztönző mindig a modellezett költség minimalizálása felé tolja a
paramétert, függetlenül attól, hogy az reális-e"): OTT a költség/szlippázs MAGA volt tanulható
paraméter, amit Optuna szabadon "kigamelhetett". ITT a költség egy FIX, a valós MT5 történelmi
`spread_price`-ból számolt, KÜLSŐ bemenet — Optuna a stratégia-paramétereket (EMA-periódus, küszöb,
stb.) tanulja, a spread-et NEM. Ez azonos elven működik, mint a napi-kvóta-kísérlet (`research/
daily_trade_cap_check.py`) is már megmutatta: a rendszer helyesen bünteti a sok, alacsony-élű
trade-et, nem "csal" egy szabadon állítható költség-modellel.
"""

import numpy as np
import pandas as pd

from regime_framework.components.friday_short import FridayShortComponent
from regime_framework.components.last_hour_continuation import LastHourContinuationComponent
from regime_framework.components.mean_reversion import MeanReversionComponent
from regime_framework.components.trend_following import TrendFollowingComponent
from regime_framework.core.engine import Engine

MIN_TOTAL_TRADES_FOR_VALID_SCORE = 30
RISK_PENALTY_LAMBDA = 0.5   # a fold-onkénti szórás büntetésének súlya a fold-átlaghoz képest
INVALID_SCORE = -1e6        # kemény büntetés kevés-mintás trial-eknél, nem csak alacsony pontszám


def build_components(trial):
    """Trial (élő Optuna optimalizáláskor) VAGY `optuna.trial.FixedTrial` (a legjobb paraméterek
    visszajátszásakor, lásd run_study.py) alapján felépíti a komponenseket — ugyanez a függvény
    szolgál mindkét esetben, hogy ne legyen két, egymástól eltérő, idővel szétdriftelő logika.

    Visszatérési érték `(components, time_gated_components, quota_exempt_time_gated_components)` —
    a LastHourContinuation `time_gated_components`-ként, a FridayShort (2026-08-21 óta hangolt)
    `quota_exempt_time_gated_components`-ként megy az Engine-be, egyik sem a rendes trend_band-XOR
    listába (lásd core/engine.py modul-docstringje)."""
    mr = MeanReversionComponent(**MeanReversionComponent().suggest_params(trial))
    tf = TrendFollowingComponent(**TrendFollowingComponent().suggest_params(trial))
    lhc = LastHourContinuationComponent(**LastHourContinuationComponent().suggest_params(trial))
    fs = FridayShortComponent(**FridayShortComponent().suggest_params(trial))
    return [mr, tf], [lhc], [fs]


def evaluate_on_folds(trial, df, fold_boundaries):
    """Bővülő ablakos (expanding window) walk-forward kiértékelés — ugyanaz a mechanizmus, mint a
    validate_walk_forward.py-ban: minden fold a teljes eddigi adatot használja bemelegítésként, de
    csak a saját dátumtartományában nyitott trade-eket számítja a statisztikájába.

    A fold-onkénti PnL-ek a `report.notes["total_net_pnl"]`-ből jönnek (NETTÓ, spread-korrigált —
    lásd fájl fejléc), NEM a `report.total_pnl`-ből (BRUTTÓ)."""
    components, time_gated_components, quota_exempt_time_gated_components = build_components(trial)
    engine = Engine(components, time_gated_components=time_gated_components,
                     quota_exempt_time_gated_components=quota_exempt_time_gated_components)

    fold_pnls = []
    total_trades = 0

    for fold_start, fold_end in fold_boundaries:
        fold_df = df[df["time"] < pd.Timestamp(fold_end)]
        if len(fold_df) == 0:
            continue
        report = engine.run(fold_df, stats_start_date=pd.Timestamp(fold_start).date())
        fold_pnls.append(report.notes["total_net_pnl"])
        total_trades += report.trade_count

    if total_trades < MIN_TOTAL_TRADES_FOR_VALID_SCORE or not fold_pnls:
        return INVALID_SCORE

    mean_pnl = float(np.mean(fold_pnls))
    std_pnl = float(np.std(fold_pnls))
    return mean_pnl - RISK_PENALTY_LAMBDA * std_pnl
