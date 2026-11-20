"""
core/us_session.py — közös segédfüggvény az amerikai DST (nyári időszámítás) figyelembevételéhez
a MeanReversion/TrendFollowing/LastHourContinuation komponensek fix, szerveridőben megadott
session-óráihoz.

KONTEXTUS (2026-09-14, felhasználói észlelés + `research/last_hour_continuation_dst_check.py`
empirikus megerősítése): a bróker szervere FIX UTC+3-on fut, NEM követi a DST-t
(`research/check_server_timezone_offset.py`, 2026-08-20) -- emiatt a valós amerikai piacnyitás
(9:30 America/New_York) szerveridőben 16:30 (amerikai nyári időszámítás, DST aktív) és 17:30
(amerikai téli időszámítás, DST inaktív) között vándorol. A komponensek jelenlegi, ÉLESBEN futó
fix órái (16:30 kezdet, LastHourContinuation-nál 20:00/21:00 is) a NYÁRI esethez vannak
kalibrálva -- a `last_hour_continuation_dst_check.py` empirikusan megerősítette, hogy ez a
DST-inaktív (téli) hónapokban mérhető teljesítmény-romlást okoz (USTEC PF 1.61→1.08, US30 PF
1.48→1.16, ugyanazon a fix konfigon).

HASZNÁLAT: `us_dst_hour_shift(date)` 0-t ad vissza DST-aktív (nyári) napokon -- ilyenkor a
jelenlegi, hardkódolt órák VÁLTOZATLANOK maradnak --, és 1-et DST-inaktív (téli) napokon, amikor
a session-óráknak +1 órával el kell tolódniuk, hogy kövessék a valós amerikai nyitást/zárást.

FONTOS, SZÁNDÉKOS ELKÜLÖNÍTÉS: egyetlen komponens sem használja ezt alapértelmezetten -- mindegyik
`dst_aware=False` alapértelmezésű konstruktor-paramétert kapott, hogy a jelenlegi ÉLŐ (paraméter
nélkül hívott) viselkedés BIT-PONTOSAN változatlan maradjon, amíg ezt valaki explicit be nem
kapcsolja. Ez ugyanaz a biztonsági elv, mint a `MarketConditionClassifier.rolling_window_bars`
alapértelmezettjének érintetlenül hagyása a `regime_deepdive` M30-kalibrációjánál.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

_NY = ZoneInfo("America/New_York")


def us_dst_hour_shift(date):
    """0, ha az adott naptári napon amerikai nyári időszámítás (DST) van érvényben -- a jelenlegi,
    hardkódolt session-órák erre vannak kalibrálva --, 1, ha nincs (téli, a valós amerikai nyitás
    egy órával később esik a FIX UTC+3-on futó szerver idejéhez képest). Dél (12:00 New York-i
    idő) az összehasonlítási pont, hogy elkerüljük a váltás-napi, éjfél körüli határeseteket --
    ugyanaz a minta, mint a `dst_aware_orb_premarket_recheck.py`-ban."""
    ny_noon = datetime(date.year, date.month, date.day, 12, 0, tzinfo=_NY)
    return 0 if ny_noon.dst() else 1
