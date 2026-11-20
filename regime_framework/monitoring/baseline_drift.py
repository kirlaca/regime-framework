"""
monitoring/baseline_drift.py — élő teljesítmény összevetése a validált baseline-nal (2. fázis,
lásd PLAN.md 7. pont és a `live-vs-baseline-stat-monitoring-concept` memória). Tisztán számítási
réteg, se MT5-, se Tkinter-függőség -- `dashboard_web.py` hívja.

MIÉRT KÉTFÉLE MÓDSZER: a projekt már korábban rögzítette (PLAN.md), hogy a komponensek NEM
egyformán ítélhetők meg egyetlen mutatóval -- MeanReversion/LastHourContinuation/FridayShort
magas találati arányú, kis R:R stratégiák (a win-rate a releváns jelzőszám), TrendFollowing
viszont SZÁNDÉKOSAN alacsony találati arányú, nagy R:R (ott a win-rate-en mért drift hamis
riasztást adna -- Profit Factor a releváns jelzőszám). Ennek megfelelően:
  - win-rate-alapú komponenseknél (RF_MR/RF_LHC/RF_FS): egy-mintás arány-z-teszt, a baseline
    win-rate-et ismert populációs paraméternek tekintve (jóval nagyobb mintából jön: 77-355
    backtest-trade, a live ehhez képest kicsi).
  - RF_TF-nél: százalékos Profit Factor-eltérés küszöbökkel.

A küszöbök (lásd `_WINRATE_THRESHOLDS`/`_PF_DEVIATION_THRESHOLDS`) HEURISZTIKÁK, NEM formális
erő-analízisből levezetve -- ezt szándékosan nem állítjuk be másképp, mert a cél egy hasznos,
átlátható jelzés, nem egy áltudományosan pontos p-érték. Ez a modul docstring-je is jelzi, hogy
őszintén kell kezelni: a `classify_component_drift()` visszatérési `detail` mezője mindig
tartalmazza a nyers számokat, hogy a fogyasztó ne csak a pill-színben bízzon.
"""

import math

WIN_RATE_TAGS = ("RF_MR", "RF_LHC", "RF_FS")
PF_TAGS = ("RF_TF",)

MIN_LIVE_TRADES = 30  # ugyanaz, mint a projekt "Turnaround Tuesday" megbízhatósági szabálya

# |z| < 1.64 kb. 90%-os egyoldalas konfidencia; 1.64-2.33 kb. 90-98% közötti "gyanús" sáv.
_Z_OK_MAX = 1.64
_Z_CAUTION_MAX = 2.33

# Százalékos Profit Factor-eltérés küszöbök.
_PF_OK_MAX_PCT = 20.0
_PF_CAUTION_MAX_PCT = 40.0


def proportion_z_score(live_wins, live_count, baseline_win_rate_pct):
    """Egy-mintás arány-z-teszt: a `live_count` élő trade közül `live_wins` nyertes, a baseline
    win-rate-et (%) ismert populációs paraméternek tekintve. `None`, ha `live_count == 0` vagy a
    baseline arány 0/100% (a szórás nulla lenne, a z-score nem értelmezhető)."""
    if live_count == 0:
        return None
    p0 = baseline_win_rate_pct / 100.0
    if p0 <= 0.0 or p0 >= 1.0:
        return None
    p_live = live_wins / live_count
    se = math.sqrt(p0 * (1 - p0) / live_count)
    if se == 0.0:
        return None
    return (p_live - p0) / se


def pf_deviation_pct(live_pf, baseline_pf):
    """Előjeles százalékos eltérés a baseline Profit Factorhoz képest. `None`, ha bármelyik PF
    hiányzik (végtelen/nincs veszteséges trade) vagy a baseline PF 0."""
    if live_pf is None or baseline_pf is None or baseline_pf == 0:
        return None
    return (live_pf - baseline_pf) / baseline_pf * 100.0


def classify_component_drift(tag, live_stats, baseline_component, min_live_trades=MIN_LIVE_TRADES):
    """`live_stats`: {"count", "wins", "gross_profit", "gross_loss"} -- a nyers, MT5-ből pool-olt
    számláló (lásd `dashboard_web.py` `_component_stats()`). `baseline_component`: a
    `live_baselines.json`-beli `{"trade_count", "win_rate", "profit_factor", "reliable"}` dict.

    Visszatérés: {"status": "pending"|"ok"|"caution"|"drift", "detail": str} -- `detail` mindig
    tartalmazza a nyers számokat, sose csak a pill-színre kell hagyatkozni."""
    live_count = live_stats["count"]

    if live_count < min_live_trades:
        return {
            "status": "pending",
            "detail": f"élő: {live_count} trade (min. {min_live_trades} kell a megbízható "
                      f"összevetéshez)",
        }

    if tag in WIN_RATE_TAGS:
        live_win_rate = live_stats["wins"] / live_count * 100.0
        baseline_win_rate = baseline_component["win_rate"]
        z = proportion_z_score(live_stats["wins"], live_count, baseline_win_rate)
        detail = (f"élő: {live_win_rate:.1f}% (n={live_count}) · alap: {baseline_win_rate:.1f}% "
                  f"(n={baseline_component['trade_count']})")
        if z is None:
            return {"status": "pending", "detail": detail + " · z-teszt nem értelmezhető"}
        abs_z = abs(z)
        if abs_z < _Z_OK_MAX:
            status = "ok"
        elif abs_z < _Z_CAUTION_MAX:
            status = "caution"
        else:
            status = "drift"
        return {"status": status, "detail": f"{detail} · z={z:+.2f}"}

    if tag in PF_TAGS:
        gross_loss = live_stats["gross_loss"]
        live_pf = (live_stats["gross_profit"] / gross_loss) if gross_loss > 0 else None
        baseline_pf = baseline_component["profit_factor"]
        live_pf_str = f"{live_pf:.2f}" if live_pf is not None else "∞/n.a."
        baseline_pf_str = f"{baseline_pf:.2f}" if baseline_pf is not None else "n.a."
        detail = (f"élő PF: {live_pf_str} (n={live_count}) · alap PF: {baseline_pf_str} "
                  f"(n={baseline_component['trade_count']})")
        dev = pf_deviation_pct(live_pf, baseline_pf)
        if dev is None:
            return {"status": "pending", "detail": detail + " · eltérés nem számolható"}
        # Felülíró szabály: ha a profitábilitás oldalt vált, mindig legalább caution.
        crossed_profitability = (baseline_pf is not None and baseline_pf >= 1.0
                                  and live_pf is not None and live_pf < 1.0)
        abs_dev = abs(dev)
        if abs_dev >= _PF_CAUTION_MAX_PCT:
            status = "drift"
        elif abs_dev >= _PF_OK_MAX_PCT or crossed_profitability:
            status = "caution"
        else:
            status = "ok"
        return {"status": status, "detail": f"{detail} · eltérés={dev:+.1f}%"}

    return {"status": "pending", "detail": f"ismeretlen komponens-tag: {tag}"}
