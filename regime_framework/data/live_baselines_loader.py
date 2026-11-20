"""
data/live_baselines_loader.py — regime_framework/data/live_baselines.json betöltése (2. fázis,
lásd PLAN.md 7. pont). Ugyanaz a minta, mint `core/market_calendar.py` `load_calendar()`-je --
egy statikus, offline-generált JSON, amit a monitoring-réteg (`dashboard_web.py`) fogyaszt.

A `(broker, magic)` páros EGYÉRTELMŰEN azonosítja mind az 5 élő példányt (a `symbol` mezőre
nincs szükség a kereszthivatkozáshoz, lásd `generate_live_baseline.py`-ban dokumentált magic-szám-
ütközés: XM US100Cash# és IC Markets USTEC UGYANAZT a 202609-es magic-ot használja, csak a
`broker` különbözteti meg őket) -- `dashboard_web.py` ezt a két mezőt olvassa ki közvetlenül
minden `instances`-beli bejegyzésből, nincs szükség külön indexelő segédfüggvényre.
"""

import json
import sys
from pathlib import Path

# 2026-09-11, felhasznaloi keres: minden negyedevi baseline-ujragenralas eddig UJRAFORDITAST is
# igenyelt (lasd quarterly-baseline-refresh-checklist memoria), pedig csak ez a JSON valtozott --
# ugyanaz a "csak adat, minek forditani miatta" problema, mint a naptar-JSON-nal
# (`core/market_calendar.py`, lasd ott a reszletes indoklast). Frozen allapotban most az EXE
# MELLETT keressuk, dev-modban valtozatlanul a forraskoderd melletti fajlt.
if getattr(sys, "frozen", False):
    _LIVE_BASELINES_PATH = Path(sys.executable).resolve().parent / "live_baselines.json"
else:
    _LIVE_BASELINES_PATH = Path(__file__).resolve().parent / "live_baselines.json"


def load_live_baselines():
    """NEM gyorsítótárazott (2026-09-11 óta) -- lásd `market_calendar.load_calendar()` fejléc-
    kommentjét, ugyanaz az indoklás: elhanyagolható fájlméret, cserébe egy éles fájlcsere/scp az
    .exe újraindítása NÉLKÜL, a következő `refresh_loop`-ciklusban érvénybe lép."""
    with open(_LIVE_BASELINES_PATH, encoding="utf-8") as f:
        return json.load(f)
