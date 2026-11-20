"""
core/position_sizing.py — pozícióméretezési stratégiák az Engine számára (PRODUCTION_READINESS.md
P1 #3. pont, 2026-08-22/23).

A `FixedLotSizer` a jelenlegi (2026-08-22 előtti) viselkedés — MINDEN Engine-hívó, ami nem ad át
explicit `position_sizer`-t, ezt kapja alapértékként, byte-azonos eredménnyel a korábbi kóddal.

A `RiskBasedSizer`/`MarginBasedSizer` a `macdAUG_Long.mq5` (élő, más rendszerhez tartozó EA)
`calcLot()`-jából kivont, PORTOLHATÓ mag — a "páros EA" margin-megosztási logikáját
(`InpPairMagicNumber`/`InpMarginAllocationPair`) SZÁNDÉKOSAN NEM vettük át, mert ennek az
Engine-nek nincs "páros" komponense, egyszerre csak EGY pozíció fut a teljes rendszerben (lásd
core/engine.py docstring). A referencia EA a végső lotot `min(lotRisk, lotMargin)`-ként számolja —
ez a két külön sizer (`RiskBasedSizer`/`MarginBasedSizer`) éppen ennek a két összetevőnek felel
meg, külön-külön tesztelhetően.

⚠️ FONTOS, 2026-08-23-án talált korrekció: a `lot_step`/`min_lot`-nak NINCS alapértéke ebben a
modulban (kötelező, a hívónak KELL megadnia) — a 2026-08-22-i első körben `lot_step=0.01`
feltételezéssel futott a kalibráció, de a valós bróker `SYMBOL_VOLUME_STEP`/`SYMBOL_VOLUME_MIN`
MINDHÁROM szimbólumnál **0.1**, nem 0.01 (10x durvább kvantálás!) — ez érdemben módosíthatja a
korábbi eredményeket, lásd PRODUCTION_READINESS.md P1 #3 "Negyedik kör".

Mindkét sizer pontos, MT5-től mért konverziós tényezőt igényel (NEM a projekt eddigi, sok helyen
használt egyszerűsített feltételezéseket): `RiskBasedSizer`-hez `money_per_point_per_lot`
(`order_calc_profit()`-tal mérve, 0.8563 mindhárom szimbólumnál, egy FX-konverzió miatt, ami a
számla és a szimbólum profit-devizaneme közt van), `MarginBasedSizer`-hez `margin_per_lot_per_price`
(`order_calc_margin()`-nal mérve — lineáris az árban, lásd fájl végi megjegyzés, kb. 1:35 tőkeáttétel
mindhárom szimbólumnál)."""

import math
from dataclasses import dataclass


class FixedLotSizer:
    """A jelenlegi, 2026-08-22 előtti viselkedés: minden trade ugyanazt a fix lot-ot kapja,
    függetlenül az SL-távolságtól, a tőkétől vagy a szabad margintól. Ez az Engine alapértelmezett
    sizer-je."""

    def __init__(self, lot_size):
        self.lot_size = lot_size

    def calc_lot(self, equity, sl_distance, entry_price):
        return self.lot_size


def _round_and_clamp(raw_lot, lot_step, min_lot, max_lot):
    lot = math.floor(raw_lot / lot_step) * lot_step
    lot = max(min_lot, lot)
    if max_lot is not None:
        lot = min(max_lot, lot)
    return round(lot, 8)


@dataclass
class RiskBasedSizer:
    """Kockázat-alapú, SL-távolsághoz és aktuális tőkéhez igazodó lot-méretezés (a referencia EA
    `lotRisk`-jének megfelelője).

    `risk_pct`: a kockáztatott tőkehányad TRADE-enként (pl. 0.001 = 0.1%). A `research/
    risk_based_sizing_check.py`/`risk_pct_calibration.py` mérése szerint az iparági alapértelmezés
    (1%) TÚL agresszív ehhez a rendszerhez — lásd PRODUCTION_READINESS.md P1 #3 a kalibrált
    értékekért és a végkövetkeztetésért.

    `money_per_point_per_lot`: PONTOS, MT5 `order_calc_profit()`-tal mért pénz/pont/lot konverziós
    tényező (NEM feltételezett 1.0) — enélkül a kockázat-számítás rendszeresen alul/felülbecsülné
    a tényleges pénzben mért kockázatot.

    `lot_step`/`min_lot`/`max_lot`: a bróker `SYMBOL_VOLUME_STEP`/`SYMBOL_VOLUME_MIN`/
    `SYMBOL_VOLUME_MAX`-ja — KÖTELEZŐ megadni (nincs alapérték, lásd fájl fejléce, miért), a
    `max_lot=None` esetén nincs felső vágás."""

    risk_pct: float
    money_per_point_per_lot: float
    lot_step: float
    min_lot: float
    max_lot: float | None = None

    def calc_lot(self, equity, sl_distance, entry_price):
        if sl_distance <= 0 or self.money_per_point_per_lot <= 0 or equity <= 0:
            return self.min_lot
        risk_amount = equity * self.risk_pct
        raw_lot = risk_amount / (sl_distance * self.money_per_point_per_lot)
        return _round_and_clamp(raw_lot, self.lot_step, self.min_lot, self.max_lot)


@dataclass
class MarginBasedSizer:
    """Margin-alapú, a szabad tőkéhez (nem az SL-távolsághoz!) igazodó lot-méretezés (a referencia
    EA `lotMargin`-jának megfelelője, a "páros EA" rész nélkül) — 2026-08-23, a felhasználó
    felvetése: egy professzionális rendszer a szabad marginhoz igazítja a méretet, nem (csak) a
    trade-enkénti kockázathoz.

    KULCSKÜLÖNBSÉG a `RiskBasedSizer`-hez képest: ez a lot-méret NEM reagál az SL-távolságra —
    csak az equityvel/marginnal skálázódik. Ez elkerülheti a `RiskBasedSizer`-nél megfigyelt
    problémát (szűk SL-ű trade-ek aránytalanul felnagyítása, ami rontotta a Sharpe-ot — lásd
    PRODUCTION_READINESS.md P1 #3), mert minden trade UGYANAKKORA hányadát kockáztatja a
    rendelkezésre álló marginnak, függetlenül a stratégia aznapi stop-távolságától.

    ⚠️ BIZTONSÁG (2026-08-23, felhasználói felvetés: "ne lehessen margin call, ez kritikus pont"):
    a valós élő számlán (2026-08-23-án lekérdezve) `margin_so_call=100%`/`margin_so_so=50%`
    (margin-hívás/kényszerzárás szintje), egyenleg ~1000 EUR. Ennél az egyenlegnél a kalibrált
    `alloc_pct` (~0.3-1.1%) ÖNMAGÁBAN a bróker minimum lotja (0.1) ALÁ esne — azaz a méretezés MA
    egyszerűen a mai fix lotra kerekítene fel, csak akkor kezdene ELTÉRNI, ha az egyenleg a mostani
    tőkeáttétel/margin-igény mellett kb. 7800 EUR fölé nő (lásd PRODUCTION_READINESS.md P1 #3).
    A VESZÉLY tehát nem a mai állapotban van, hanem abban, ha az `alloc_pct` idővel (hangolási hiba,
    vagy nagyra nőtt egyenleg mellett) TÚL nagy hányadot allokálna. Emiatt a `max_margin_
    utilization_pct` egy MÁSODIK, `alloc_pct`-től FÜGGETLEN kemény felső korlát — bármekkora is az
    `alloc_pct`, a ténylegesen felhasznált margin-hányad SOSEM lépheti túl ezt (pl. 0.2 = 20%, ami
    100%-os margin-szintet, azaz margin-hívást csak akkor okozna, ha az ÖSSZES ilyen tétnyi pozíció
    EGYSZERRE, egyidejűleg 100%-ot veszítene — ez a projekt Engine-jénél eleve kizárt, mert
    egyszerre csak EGY pozíció fut, lásd core/engine.py docstring). Élő, TÖBB szimbólumos
    üzemeltetésnél az EA-nak a VALÓS `AccountInfoDouble(ACCOUNT_MARGIN_FREE)`-t kell `equity`
    helyett használnia (nem ezt a Python-modellt, ami leegyszerűsítve equity-vel közelít) — így
    minden szimbólum automatikusan "látja" a többi szimbólum lekötött marginját, és arányosan
    kisebb lotot számol, ha már van nyitott pozíció máshol.

    `alloc_pct`: a szabad margin hányada, amit egy trade-re allokálnánk (pl. 0.1 = 10%) — a
    kalibrált, teljesítmény-optimalizált érték.
    `max_margin_utilization_pct`: KÖTELEZŐ, `alloc_pct`-től FÜGGETLEN kemény biztonsági felső
    korlát a ténylegesen felhasznált margin-hányadra — a `calc_lot()` mindig `min(alloc_pct,
    max_margin_utilization_pct)`-ot használ, tehát ez a korlát bármikor FELÜLÍRHATJA (szigorúbbá
    teheti) az `alloc_pct`-et, sose fordítva. Védelem hangolási hiba/extrém equity-növekedés ellen.
    `margin_per_lot_per_price`: PONTOS, MT5 `order_calc_margin()`-nal mért margin/lot/árfolyamegység
    tényező (lineáris az árban ezeknél a szimbólumoknál, kb. 1:35 tőkeáttétel — lásd fájl fejléce).
    `free_margin`: ha `None`, `equity`-t használja közelítésként (helyénvaló, amíg egyszerre csak
    EGY pozíció fut az egész rendszerben — lásd core/engine.py docstring — így a "szabad margin"
    gyakorlatilag megegyezik a teljes equity-vel; több, PÁRHUZAMOSAN futó szimbólum esetén ez a
    közelítés MÁR NEM helyes, mert nem veszi figyelembe a többi szimbólum lekötött marginját — élő
    EA-ban a valós szabad marginnal helyettesítendő, lásd fent)."""

    alloc_pct: float
    max_margin_utilization_pct: float
    margin_per_lot_per_price: float
    lot_step: float
    min_lot: float
    max_lot: float | None = None

    def calc_lot(self, equity, sl_distance, entry_price):
        margin_per_lot = self.margin_per_lot_per_price * entry_price
        if margin_per_lot <= 0 or equity <= 0:
            return self.min_lot
        effective_pct = min(self.alloc_pct, self.max_margin_utilization_pct)
        budget = equity * effective_pct
        raw_lot = budget / margin_per_lot
        return _round_and_clamp(raw_lot, self.lot_step, self.min_lot, self.max_lot)
