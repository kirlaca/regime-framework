"""
deployment/generate_holiday_mqh.py — a `data/market_holidays.json` egyetlen forrásból generálja az
MQL5-oldali `MarketHolidays.mqh` fejlécet, a `.set` preset-generálással megegyező minta szerint
(egy Python-oldali forrás, kézzel NEM szinkronizált MQL5-másolat helyett).

KONTEXTUS (2026-09-07): lásd `core/market_calendar.py` docstring-jét -- ez a script adja a
naptár Python->MQL5 hidat, hogy az élő EA (mindkét bróker: IC Markets és XM) ne nyithasson új
pozíciót olyan napon, amikor a mögöttes valós piac zárva van.

Kimenet: `MarketHolidays.mqh`, a metaTrader-EA-scripts repo `Experts/RegimeFramework/` mappájába
írva (ugyanoda, ahol a többi .mqh komponens és a .set preset-ek élnek).

Futtatás: python -m regime_framework.deployment.generate_holiday_mqh
(Nem igényel MT5-kapcsolatot, tisztán fájl->fájl generálás.)
"""

import json
from pathlib import Path

JSON_PATH = Path(__file__).resolve().parent.parent / "data" / "market_holidays.json"
OUT_PATH = Path(
    r"%APPDATA%\MetaQuotes\Terminal\<TERMINAL_ID>"
    r"\MQL5\Experts\RegimeFramework\MarketHolidays.mqh"
)


def _to_yyyymmdd(date_str):
    return date_str.replace("-", "")


def _blocked_dates(market_info):
    blocked = set()
    for key, values in market_info.items():
        if key.startswith("closed_") or key.startswith("early_close_"):
            blocked.update(values)
    return sorted(blocked)


def generate(calendar):
    markets = calendar["markets"]
    symbol_market = calendar["symbol_market_map"]

    lines = []
    lines.append("//+------------------------------------------------------------------+")
    lines.append("//| MarketHolidays.mqh -- AUTOMATIKUSAN GENERALVA, NE SZERKESZD KEZZEL |")
    lines.append("//| Forras: optuna_research/regime_framework/data/market_holidays.json  |")
    lines.append("//| Generator: regime_framework/deployment/generate_holiday_mqh.py      |")
    lines.append("//| Uj ev/nap felvetelehez a JSON-t bovitsd, majd futtasd ujra a         |")
    lines.append("//| generatort -- ez a fajl minden futtataskor teljesen ujrairodik.      |")
    lines.append("//+------------------------------------------------------------------+")
    lines.append("#property strict")
    lines.append("")
    lines.append("//--- piaconkenti, zart/csokkentett-kereskedesi napok (YYYYMMDD egeszkent) ---")

    for market_name, info in markets.items():
        blocked = _blocked_dates(info)
        arr_name = f"g_holidayDates_{market_name}"
        values = ", ".join(_to_yyyymmdd(d) for d in blocked)
        lines.append(f"// {market_name}: {info.get('description', '')} ({len(blocked)} nap)")
        lines.append(f"int {arr_name}[] = {{{values}}};")
        lines.append("")

    lines.append("//+------------------------------------------------------------------+")
    lines.append("//| true, ha a megadott szimbolum piaca zarva/csokkentett-kereskedesu   |")
    lines.append("//| a megadott naptari napon (szerveridő YYYYMMDD egesz alakban -- lasd  |")
    lines.append("//| DateToYyyymmdd()). Uj szimbolum hozzaadasakor a JSON                 |")
    lines.append("//| symbol_market_map-jet bovitsd, NE ide irj kezzel uj if-agat.          |")
    lines.append("//+------------------------------------------------------------------+")
    lines.append("bool IsMarketHoliday(string symbol, int yyyymmdd)")
    lines.append("  {")
    first = True
    for symbol_name, market_name in symbol_market.items():
        arr_name = f"g_holidayDates_{market_name}"
        keyword = "if" if first else "else if"
        lines.append(f'   {keyword}(symbol == "{symbol_name}")')
        lines.append("     {")
        lines.append(f"      for(int i = 0; i < ArraySize({arr_name}); i++)")
        lines.append(f"         if({arr_name}[i] == yyyymmdd)")
        lines.append("            return true;")
        lines.append("      return false;")
        lines.append("     }")
        first = False
    lines.append("   return false;   // ismeretlen szimbolum -- nincs naptar hozza, ne blokkoljon")
    lines.append("  }")
    lines.append("")
    lines.append("//+------------------------------------------------------------------+")
    lines.append("//| Segedfuggveny: a megadott datetime YYYYMMDD egeszkent (szerveridő). |")
    lines.append("//+------------------------------------------------------------------+")
    lines.append("int DateToYyyymmdd(datetime t)")
    lines.append("  {")
    lines.append("   MqlDateTime dt;")
    lines.append("   TimeToStruct(t, dt);")
    lines.append("   return dt.year * 10000 + dt.mon * 100 + dt.day;")
    lines.append("  }")
    lines.append("")

    return "\n".join(lines)


def main():
    with open(JSON_PATH, encoding="utf-8") as f:
        calendar = json.load(f)

    content = generate(calendar)
    OUT_PATH.write_text(content, encoding="utf-8")

    n_markets = len(calendar["markets"])
    n_symbols = len(calendar["symbol_market_map"])
    print(f"Kiirva: {OUT_PATH}")
    print(f"{n_markets} piaci csoport, {n_symbols} szimbolum lekepezve.")


if __name__ == "__main__":
    main()
