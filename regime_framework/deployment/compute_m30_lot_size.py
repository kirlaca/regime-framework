"""
deployment/compute_m30_lot_size.py -- a `routing_m30.json`-ban rögzített M30-instanciákhoz
(lásd regime_deepdive/FINDINGS_LOG.md 32. bejegyzés) biztonságos, FIX lot-méretet számol egy
megadott kezdőtőkéhez.

MIÉRT fix lot, nem dinamikus margin-alapú méretezés: a 32. bejegyzés DD-illesztett kalibrációja
kimutatta, hogy $2000 kezdőtőkénél a margin-alapú méretezés VAGY strukturálisan a 0.1 lot
minimumon ragad (USTEC/US30, a 0.1-es lot-lépésköz durvasága miatt), VAGY (US500) rosszabb
kockázat-arányos teljesítményt ad ugyanazon a kockázati szinten -- a felhasználó döntése: marad a
fix lot, amíg ez nem változik.

MIT SZÁMOL ez a script: a `routing_m30.json` MINDHÁROM instanciája UGYANAZON a számlán, EGYSZERRE
fut -- a 32. bejegyzés szerint történelmileg (2 éven át) 27 napon volt mindhárom EGYSZERRE nyitva.
Ez a script a MEGADOTT kezdőtőkéhez megkeresi a LEGNAGYOBB, 0.1-es lépésközű lotot, amire a
HÁROMSZOROS (worst-case, mindhárom instancia egyszerre nyitva) margin-lekötés ARÁNYA a
kezdőtőkéhez képest NEM lépi túl a megadott biztonsági küszöböt (`--max-margin-pct`, alapértéken
25% -- ez a margin_so_call=100% szinttől bőséges, kb. 4x-es tartalékot hagy).

FONTOS: ez a margin/lot értéket MT5-től méri (order_calc_margin), az AKTUÁLIS árszinten -- az
árszint idővel változik, ezért ezt a scriptet ÉRDEMES időnként újrafuttatni (pl. minden negyedéves
baseline-frissítéskor, lásd quarterly_baseline_refresh_checklist memória), nem egyszeri, örökre
rögzített számításnak tekinteni.

Futtatás:
  python -m regime_framework.deployment.compute_m30_lot_size --capital 2000
  python -m regime_framework.deployment.compute_m30_lot_size --capital 2000 --max-margin-pct 25
(Élő MT5-terminál szükséges -- alapból az IC Markets terminál útvonalát próbálja, lásd
TERMINAL_PATH lent, ha ez a gépen máshol van, módosítsd vagy add át --terminal-path-ot.)
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
LOT_STEP = 0.1
MIN_LOT = 0.1
DEFAULT_MAX_MARGIN_PCT = 25.0


def load_routing():
    with open(ROUTING_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def get_margin_per_lot(symbol):
    mt5.symbol_select(symbol, True)
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        raise RuntimeError(f"Nincs tick {symbol}-ra: {mt5.last_error()}")
    margin = mt5.order_calc_margin(mt5.ORDER_TYPE_BUY, symbol, 1.0, tick.ask)
    if margin is None:
        raise RuntimeError(f"order_calc_margin sikertelen {symbol}-ra: {mt5.last_error()}")
    return margin, tick.ask


def find_safe_lot(margins_per_lot, capital, max_margin_pct):
    """A legnagyobb, LOT_STEP-lépésközű, KÖZÖS lot, amire a HÁROMSZOROS (worst-case, mind az N
    instancia egyszerre nyitva -- lásd FINDINGS_LOG.md 32. bejegyzés, empirikusan mért worst
    case) össz-margin/capital arány NEM lépi túl a küszöböt. Ha még a MIN_LOT (0.1) is túllépi,
    ezt jelezzük -- NEM erőltetjük 0.1 alá (az a bróker abszolút minimuma)."""
    worst_case_margin_per_unit_lot = sum(margins_per_lot)  # ha mindenki UGYANAZT a lotot futtatja
    lot = MIN_LOT
    while True:
        next_lot = round(lot + LOT_STEP, 8)
        next_margin_pct = (worst_case_margin_per_unit_lot * next_lot) / capital * 100
        if next_margin_pct > max_margin_pct:
            break
        lot = next_lot
    current_margin_pct = (worst_case_margin_per_unit_lot * lot) / capital * 100
    return lot, current_margin_pct, worst_case_margin_per_unit_lot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capital", type=float, required=True, help="Kezdőtőke (a routing_m30.json instanciáit futtató számlán, USD)")
    parser.add_argument("--max-margin-pct", type=float, default=DEFAULT_MAX_MARGIN_PCT,
                         help=f"Biztonsági küszöb: a worst-case (mind az N instancia egyszerre nyitva) "
                              f"margin-lekötés MAX ekkora %%-a lehet a kezdőtőkének (alapérték {DEFAULT_MAX_MARGIN_PCT}%%)")
    parser.add_argument("--terminal-path", default=TERMINAL_PATH, help="MT5 terminal64.exe útvonala")
    args = parser.parse_args()

    routing = load_routing()
    logger.info("--- M30 lot-méret számítás (kezdőtőke: %.2f USD, biztonsági küszöb: %.1f%%) ---\n",
                args.capital, args.max_margin_pct)

    if not mt5.initialize(path=args.terminal_path):
        logger.error("MT5 inicializálás sikertelen: %s", mt5.last_error())
        return

    margins_per_lot = []
    try:
        for instance in routing["instances"]:
            symbol = instance["symbol"]
            margin, price = get_margin_per_lot(symbol)
            margins_per_lot.append(margin)
            leverage = price * 1.0 / margin  # contract_size=1.0 ezeknél a szimbólumoknál
            logger.info("%-8s: ár=%.2f, margin/1.0 lot=%.2f USD (kb. 1:%.1f tőkeáttétel)",
                        symbol, price, margin, leverage)
    finally:
        mt5.shutdown()

    lot, margin_pct, worst_case_per_unit = find_safe_lot(margins_per_lot, args.capital, args.max_margin_pct)

    logger.info("\nWorst-case margin/1.0 lot (MIND a %d instancia egyszerre nyitva): %.2f USD",
                len(margins_per_lot), worst_case_per_unit)
    logger.info("Ajánlott KÖZÖS lot-méret: %.1f", lot)
    logger.info("Ezzel a worst-case margin-kihasználtság: %.2f USD (%.2f%% a kezdőtőkéből)",
                worst_case_per_unit * lot, margin_pct)

    if lot <= MIN_LOT and margin_pct > args.max_margin_pct:
        logger.warning(
            "\n[!] FIGYELEM: MÉG A BRÓKER MINIMUM LOTJA (%.1f) IS TÚLLÉPI a %.1f%%-os biztonsági "
            "küszöböt (%.2f%%) worst-case esetben. Ez a kezdőtőke (%.2f USD) TÚL ALACSONY ehhez "
            "a 3-instanciás portfólióhoz -- vagy nagyobb tőke szükséges, vagy a küszöböt kell "
            "tudatosan (és dokumentáltan) megemelni, vagy kevesebb instanciát kell egyszerre futtatni.",
            MIN_LOT, args.max_margin_pct, margin_pct, args.capital,
        )
    else:
        logger.info(
            "\nÉrtelmezés: ez a lot minden instanciára (%s) egyformán alkalmazandó -- lásd "
            "FINDINGS_LOG.md 32. bejegyzés, miért KÖZÖS/fix lot, nem margin-alapú dinamikus "
            "méretezés. A margin_so_call (stop-out) szint 100%% -- ez a %.2f%%-os worst-case "
            "kihasználtság bőséges tartalékot hagy.",
            ", ".join(i["symbol"] for i in routing["instances"]), margin_pct,
        )


if __name__ == "__main__":
    main()
