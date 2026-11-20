"""
core/market_calendar.py — known market-closed / early-close date lookups, backed by
regime_framework/data/market_holidays.json.

KONTEXTUS (2026-09-07): a felhasználó jelezte, hogy az IC Markets EA ma (US Labor Day, a
mögöttes NYSE/NASDAQ piac zárva) mégis nyitott pozíciót -- a CFD-bróker ilyenkor is árazza a
terméket (szintetikus/tovább-gördített feed, szélesebb spreaddel, vékonyabb likviditással), csak
ez már nem "valódi" piaci mozgás. Ez a modul adja a Python-oldali (walk-forward backtest-tisztítási)
felét egy két-rétegű védelemnek -- az élő MQL5 EA-oldalt lásd
`metaTrader-EA-scripts/Experts/RegimeFramework/MarketHolidays.mqh` (generálva:
`regime_framework/deployment/generate_holiday_mqh.py`).
"""

import json
import sys
from pathlib import Path

# 2026-09-11, felhasznaloi keres: a monitoring .exe-k (dashboard_web.py, heartbeat_dashboard.py)
# korabban PyInstaller --add-data-val BECSOMAGOLTAK ezt a fajlt, ami azt jelentette, hogy minden
# evvaltaskor (uj naptari ev = uj market_holidays.json) UJRA KELLETT FORDITANI es kitelepiteni az
# EGESZ exe-t egy tisztan adat-frissitesert. Frozen allapotban a fajlt most az EXE MELLETT
# keressuk (`sys.executable` konyvtaraban) -- ugyanaz a minta, mint a `TERMINALS_CONFIG_PATH`
# `heartbeat_dashboard.py`-ban -- igy egy sima fajlcsere/scp eleg, forditas nelkul. Dev-modban
# (`python -m ...`) valtozatlanul a forraskoderd melletti `data/`-bol olvas, ugyanugy, mint eddig
# (ezt hasznaljak a validacios/generator szkriptek is).
if getattr(sys, "frozen", False):
    _HOLIDAYS_PATH = Path(sys.executable).resolve().parent / "market_holidays.json"
else:
    _HOLIDAYS_PATH = Path(__file__).resolve().parent.parent / "data" / "market_holidays.json"


def load_calendar():
    """NEM gyorsítótárazott (2026-09-11 óta) -- a fájl mérete elhanyagolható, a hívók (a két
    monitoring dashboard `refresh_loop`-ja) amúgy is csak percenkénti ciklusidőben hívják, cserébe
    egy éles fájlcsere/scp az .exe ÚJRAINDÍTÁSA NÉLKÜL, a következő frissítési ciklusban érvénybe
    lép. Hot-loop backtest/generator kód NEM ezen a függvényen keresztül olvas (lásd fejléc)."""
    with open(_HOLIDAYS_PATH, encoding="utf-8") as f:
        return json.load(f)


def market_for_symbol(symbol, calendar=None):
    calendar = calendar or load_calendar()
    return calendar["symbol_market_map"].get(symbol)


def _blocked_dates_for_market(market_name, calendar):
    info = calendar["markets"].get(market_name, {})
    blocked = set()
    for key, values in info.items():
        if key.startswith("closed_") or key.startswith("early_close_"):
            blocked.update(values)
    return blocked


def is_market_holiday(symbol, dt, calendar=None):
    """True if `symbol`'s underlying market is fully closed or in early-close on date `dt`
    (a `date`/`Timestamp`/ISO-string). Unknown symbols return False (no calendar => no gate)."""
    calendar = calendar or load_calendar()
    market = market_for_symbol(symbol, calendar)
    if market is None:
        return False
    d = dt.date().isoformat() if hasattr(dt, "date") else str(dt)[:10]
    return d in _blocked_dates_for_market(market, calendar)


def filter_holiday_bars(df, symbol, calendar=None, time_col="time"):
    """Drop bars falling on a known holiday/early-close date for `symbol`'s market. Use before
    walk-forward scoring to avoid contaminating results with thin-liquidity holiday sessions --
    unknown symbols are returned unchanged (no calendar => no filtering)."""
    calendar = calendar or load_calendar()
    market = market_for_symbol(symbol, calendar)
    if market is None:
        return df
    blocked = _blocked_dates_for_market(market, calendar)
    if not blocked:
        return df
    mask = ~df[time_col].dt.date.astype(str).isin(blocked)
    return df[mask]
