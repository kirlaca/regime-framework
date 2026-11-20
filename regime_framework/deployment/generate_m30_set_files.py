"""
deployment/generate_m30_set_files.py -- a `routing_m30.json`-ban rögzített végleges M30-konfiguráció
(lásd regime_deepdive/FINDINGS_LOG.md 36. bejegyzés) alapján legyártja a `.set` fájlokat a
`RegimeFramework_EA.mq5`-hez, egy megadott kezdőtőkéhez számolt, biztonságos fix lot-mérettel
(lásd `compute_m30_lot_size.py` -- ugyanaz a logika, itt beépítve).

A `.set` fájl formátuma: egyszerű `InpXxx=érték` sorok, UTF-8 (lásd `validation/mt5_set_parser.py`
fejléc-kommentje -- mindkét kódolást elfogadja MT5, ez az egyszerűbb út). MINDEN EA-inputot kiír,
nem csak a hangoltakat, hogy a fájl önmagában teljes és egyértelmű legyen (nincs "hallgatólagos
alapérték" bizonytalanság).

FONTOS, KIFEJEZETTEN ELLENŐRIZENDŐ ÉRTÉK: `InpLhcDstAware=false` -- az EA-forrás alapértéke ehhez
az inputhoz `true` (az élő M10-es LastHourContinuation DST-javításához, lásd SESSION_LOG.md
"KRITIKUS ELLENTMONDÁS FELTÁRVA"), DE a mai M30-as validáció (36. bejegyzés)
`dst_aware=False`-fal futott (a Python `LastHourContinuationComponent` alapértéke) -- a .set
fájlnak EXPLICITEN false-t kell írnia, különben egy SOSEM tesztelt viselkedést vinnénk élesbe.

Futtatás:
  python -m regime_framework.deployment.generate_m30_set_files --capital 2000
(Élő MT5-terminál szükséges a margin méréséhez.)
"""

import argparse
import json
import logging
from pathlib import Path

import MetaTrader5 as mt5

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

ROUTING_PATH = Path(__file__).parent / "routing_m30.json"
TERMINAL_PATH = r"D:\MT5\terminal64.exe"
OUTPUT_DIR = Path(
    r"%APPDATA%\MetaQuotes\Terminal\<TERMINAL_ID>"
    r"\MQL5\Experts\RegimeFramework\presets_m30"
)
LOT_STEP = 0.1
MIN_LOT = 0.1
DEFAULT_MAX_MARGIN_PCT = 25.0


def load_routing():
    with open(ROUTING_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def get_margin_per_lot(symbol):
    mt5.symbol_select(symbol, True)
    tick = mt5.symbol_info_tick(symbol)
    margin = mt5.order_calc_margin(mt5.ORDER_TYPE_BUY, symbol, 1.0, tick.ask)
    return margin


def find_safe_lot(margins_per_lot, capital, max_margin_pct):
    worst_case_per_unit_lot = sum(margins_per_lot)
    lot = MIN_LOT
    while True:
        next_lot = round(lot + LOT_STEP, 8)
        if (worst_case_per_unit_lot * next_lot) / capital * 100 > max_margin_pct:
            break
        lot = next_lot
    return lot, (worst_case_per_unit_lot * lot) / capital * 100


def build_set_lines(instance, lot):
    comps = instance["components"]
    mr = comps.get("MeanReversion", {})
    tf = comps.get("TrendFollowing", {})
    lhc = comps.get("LastHourContinuation", {})
    fs = comps.get("FridayShort", {})

    mr_p = mr.get("params", {})
    tf_p = tf.get("params", {})
    lhc_p = lhc.get("params", {})
    fs_p = fs.get("params", {})

    lines = [
        f"; RegimeFramework_EA.mq5 -- M30, {instance['symbol']} (magic {instance['magic']})",
        "; Automatikusan generálva: regime_framework/deployment/generate_m30_set_files.py",
        "; Forrás: regime_framework/deployment/routing_m30.json (lásd regime_deepdive/FINDINGS_LOG.md 36. bejegyzés)",
        "",
        f"InpEnableMeanReversion={'true' if mr.get('enabled') else 'false'}",
        f"InpEnableTrendFollowing={'true' if tf.get('enabled') else 'false'}",
        f"InpEnableLastHourContinuation={'true' if lhc.get('enabled') else 'false'}",
        f"InpEnableFridayShort={'true' if fs.get('enabled') else 'false'}",
        "",
        f"InpMrEmaPeriod={mr_p.get('ema_period', 40)}",
        f"InpMrMultiplier={mr_p.get('mr_multiplier', 1.9061195)}",
        f"InpMrSlMultiplier={mr_p.get('sl_multiplier', 2.0771436)}",
        f"InpMrRiskRewardRatio={mr_p.get('risk_reward_ratio', 1.8391435)}",
        "",
        f"InpTfFastEmaDays={tf_p.get('fast_ema_days', 0.4404634)}",
        f"InpTfSlowEmaDays={tf_p.get('slow_ema_days', 3.6701403)}",
        f"InpTfSlAtrMultiplier={tf_p.get('sl_atr_multiplier', 1.8956209)}",
        f"InpTfTrailAtrMultiplier={tf_p.get('trail_atr_multiplier', 4.7461750)}",
        f"InpTfRsiLongMin={tf_p.get('rsi_long_min', 44.8983746)}",
        f"InpTfRsiShortMax={tf_p.get('rsi_short_max', 44.9799269)}",
        "InpTfRsiPeriod=14",
        "InpTfBollingerPeriod=14",
        "InpTfBollingerK=1.5654510",
        f"InpTfBarsPerDay={tf_p.get('bars_per_day', 44)}",
        "",
        f"InpLhcSlAtrMultiplier={lhc_p.get('sl_atr_multiplier', 1.7916306)}",
        "InpLhcFinalHourStart=20",
        "InpLhcSessionEndHour=21",
        f"InpLhcMinTrendBars={lhc_p.get('min_trend_bars', 3)}",
        "InpLhcDstAware=false",
        "",
        f"InpFsTargetDayOfWeek={fs_p.get('target_day_of_week', 4)}",
        f"InpFsTargetHour={fs_p.get('target_hour', 23)}",
        f"InpFsSlAtrMultiplier={fs_p.get('sl_atr_multiplier', 1.1892803)}",
        f"InpFsHoldBars={fs_p.get('hold_bars', 11)}",
        "InpFsSafetyCloseHour=23",
        "InpFsSafetyCloseMinute=49",
        "",
        "InpSessionStartHour=16",
        "InpSessionStartMinute=30",
        "InpSessionEndHour=21",
        "InpForceCloseHour=23",
        "InpForceCloseMinute=49",
        f"InpLotSize={lot}",
        "InpSlippagePoints=20",
        f"InpMagicNumber={instance['magic']}",
        "",
        "InpUseMarginBasedSizing=false",
        "InpMarginAllocPct=5.348",
        "",
    ]
    return lines


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--capital", type=float, required=True)
    parser.add_argument("--max-margin-pct", type=float, default=DEFAULT_MAX_MARGIN_PCT)
    args = parser.parse_args()

    routing = load_routing()
    logger.info("--- M30 .set fájlok generálása (kezdőtőke: %.2f USD) ---\n", args.capital)

    if not mt5.initialize(path=TERMINAL_PATH):
        logger.error("MT5 inicializálás sikertelen: %s", mt5.last_error())
        return

    margins = []
    try:
        for instance in routing["instances"]:
            margin = get_margin_per_lot(instance["symbol"])
            margins.append(margin)
            logger.info("%-8s margin/1.0 lot: %.2f USD", instance["symbol"], margin)
    finally:
        mt5.shutdown()

    lot, margin_pct = find_safe_lot(margins, args.capital, args.max_margin_pct)
    logger.info("\nKözös lot-méret: %.1f (worst-case margin-kihasználtság: %.2f%%)\n", lot, margin_pct)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for instance in routing["instances"]:
        lines = build_set_lines(instance, lot)
        out_path = OUTPUT_DIR / f"RegimeFramework_EA_M30_{instance['symbol']}.set"
        out_path.write_text("\n".join(lines), encoding="utf-8")
        logger.info("Kiírva: %s", out_path)

    logger.info("\nKész. Lásd a Strategy Tester beállítási útmutatót a konzol-kimenet alatt.")


if __name__ == "__main__":
    main()
