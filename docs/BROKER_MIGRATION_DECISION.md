# Broker-migráció döntési előkészítő: XM → IC Markets

Cél: egy helyen összegyűjteni mindent, ami a végleges döntéshez kell — a felhasználó eredeti
kérdésére ("javul-e az él az XM-hez képest, lehet hogy brókert kell váltani") adott bizonyítékot,
a nyitott kockázatokat és a konkrét átállási lépéseket. Ez NEM maga a döntés — a döntést a
felhasználó hozza meg, ez a dokumentum a döntéshez szükséges tényanyagot rendszerezi.

## 1. A bizonyíték: mindhárom jelenleg élesen futó index javult

A production Optuna célfüggvénnyel (`optimization/objective.py`), melegindított (`enqueue_trial()`
az XM-en már hangolt paraméterekkel + 200 trial) újrahangolással, ugyanazon a walk-forward
módszertanon, mint az élesben:

| Index | XM saját pontszám | IC Markets (melegindított) | Javulás | Fold-konzisztencia |
|---|---|---|---|---|
| US30 | 10.71 | **40.89** | ~4x | 8/11 fold nettó pozitív |
| US500 | 11.76 | **13.81** | ~1.17x | **11/11 fold nettó pozitív** |
| USTEC | 75.14 | **91.03** | ~1.21x | **11/11 fold nettó pozitív**, monoton növekvő equity |

Mindhárom javult, egyik sem romlott. Részletek: `PLAN.md` §2.4.

**✅ MQL5/Strategy Tester megerősítés, MIND A HÁROM INDEXRE (2026-09-06)**: a Python-eredményt a
valódi MQL5 EA (`RegimeFramework_EA_ICMarkets.mq5`) is megerősítette, valódi tick-adaton (60-190M
tick szimbólumonként, "Every tick based on real ticks"):

| Index | Python (kumulált nettó $) | Strategy Tester (valódi tick) | Egyezés |
|---|---|---|---|
| USTEC | ~$1 569 | $1 547.08 (PF 1.74, 712 trade) | ~99% |
| US500 | ~$230.64 | $178.32 (PF 1.39, 736 trade) | ~77% |
| US30 | ~$1 139.62 | $1 148.91 (PF 1.40, 645 trade) | ~101% |

Ez NEM csak backtest-modellezett, hanem a valódi bróker natív SL/TP-megbízásaival futtatott
megerősítés — teljesíti a `PLAN.md` 0.1 "MQL5-portolási megerősítés kötelező" szabályát mindhárom
indexre. Ez a legerősebb eddigi bizonyíték a migrációs döntéshez: a Python-oldali eredmény nem
backtest-artifact.

**✅ XM Strategy Tester összevetés, UGYANEZEN a ponton (2026-09-06)**: megtalálva a korábbi
(2026-08-21/26/31-i) XM Strategy Tester riportok (`RegimeFramework_EA.mq5`, XM fiók 27558071,
US100Cash#/US500Cash#/US30Cash#, mindhárom 2023.11.01–2026.08.22 ablakon — ~13 nappal rövidebb,
mint a mai IC Markets teszt, ez nem tökéletesen szinkron összevetés, de irányában informatív):

| Index | XM Strategy Tester | IC Markets Strategy Tester | Változás |
|---|---|---|---|
| USTEC/US100 | $1 039.22 (PF 1.54, 680 trade) | $1 547.08 (PF 1.74, 712 trade) | +48.9% nettó profit |
| US500 | $169.61 (PF 1.43, 711 trade) | $178.32 (PF 1.39, 736 trade) | +5.1%, PF kicsit gyengébb |
| US30 | $718.76 (PF 1.25, 568 trade) | $1 148.91 (PF 1.40, 645 trade) | +59.8% nettó profit |

Ez most már MINDKÉT brókeren valódi MQL5/Strategy Tester szintű összevetés — ugyanaz a minta,
mint a Python walk-forwardnál: USTEC és US30 egyértelműen, jelentősen jobb; US500-nál a javulás
szerény, és MQL5 szinten a Profit Factor enyhén romlik is (1.43→1.39), csak a trade-szám növekedése
miatt nő a nettó dollár-profit.

## 2. Költségmodell teljességének ellenőrzése (2026-09-06)

**Fontos, MOST megerősített tény**: IC Markets hivatalos oldala szerint ("IC Markets applies
commissions in Forex and Precious Metals") a Raw Spread számlán a jutalék KIZÁRÓLAG Forex és
nemesfém instrumentumokra vonatkozik (a részvény-CFD-knél külön, $0.02/részvény díj van — lásd
PLAN.md §2.6) — **index-CFD-kre (US30/US500/USTEC) NEM számít fel jutalékot**, csak spread-et.
Ez azt jelenti, hogy a fenti táblázat backtestjeiben használt költségmodell (`entry_spread_price *
entry_lot`, lásd `core/engine.py`) **TELJES és PONTOS** az index-CFD-kre — nincs rejtett, ki nem
mutatott költség, ami módosítaná a fenti eredményeket.

## 3. Fontos korlátok/kockázatok, amiket a döntés előtt figyelembe kell venni

1. **A teljes összevetés DEMO számlán történt** (`ICMarketsEU-Demo`, `trade_mode=0`), a Strategy
   Tester-es megerősítés is ide értve (valódi tick-adaton, de a demó szerver kondícióival). A demó
   spread/kitöltési minőség TIPIKUSAN közel van az éleshez jól szabályozott brókereknél, de ez
   NINCS közvetlenül megerősítve — érdemes lehet egy rövid élő/paper-trading megfigyelési
   időszakot beiktatni, mielőtt valódi tőkét mozgatnánk.
2. **IC Markets adatmélysége rövidebb**, mint XM-é ezekre az indexekre (~2023-11-től, szemben XM
   hosszabb történetével) — a walk-forward így kevesebb, "fiatalabb" piaci rezsimen lett tesztelve.
3. **A teljes vizsgálatsorozat (a felhasználó eredeti terve szerint) NEM zárult le teljesen** —
   a részvény-kutatási ág nyitva maradt (TSLA gyenge pozitív eredményt adott, NVDA/AMD/MSFT
   tesztelése hátravan). A felhasználó 2026-09-06-án explicit döntött úgy, hogy ETTŐL FÜGGETLENÜL
   előre lép a migrációs döntés előkészítésével — ez rögzítve, nem hallgatva el.
4. **ETÜ (magyar egyéni vállalkozói adózás) jogosultság IC Marketsnél NEM megerősített** — a
   CySEC-szabályozás (EU/EGT-tagság) megalapozza az alapfeltételt, de a tényleges minősítés
   attól függ, hogy IC Markets ténylegesen kiállítja-e a megfelelő igazolást; ezt közvetlenül
   IC Marketsszel vagy magyar adótanácsadóval kell tisztázni, ez ITT NEM ellenőrizhető.
5. **Tőkeáttétel — JAVÍTVA (2026-09-06)**: a demó számla API-ban látott `leverage=30` a
   SZÁMLA-szintű alapérték, NEM a tényleges, indexekre vonatkozó korlát. IC Markets hivatalos
   "Leverage and Margin Policy" dokumentuma (v3.0, 2026 június, `cdn.icmarkets.eu/uploads/
   EU-Leverage-Policy.pdf`, 7. pont) szerint retail ügyfeleknek **1:20 a fő indexekre**
   (30:1 csak a fő devizapároknál van). Margin-számítás ezzel a helyes értékkel (0.1 lot,
   jelenlegi árak): USTEC $147.46, US500 $38.55, US30 $266.15 — **összesen $452.16, ha
   mindhárom pozíció EGYSZERRE nyitva lenne**. $2000 tőkénél ez ~77% szabad margint hagy, a
   margin-hívás (100% szint) messze nincs veszélyben ebből a szempontból — a tényleges kockázat
   a normál kereskedési drawdown (backtestben US30-nál volt a legnagyobb, ~11%), nem a
   tőkeáttétel.

## 4. Konkrét átállási lépések (ha a döntés IGEN)

1. **Szimbólum-átnevezés**: `US100Cash#`/`US500Cash#`/`US30Cash#` (XM) → `USTEC`/`US500`/`US30`
   (IC Markets) — minden élő kódban, ahol a szimbólumnevek hardkódolva vannak.
2. **Új, IC Markets-re hangolt paraméterek** — a fenti melegindított futtatások `study.
   best_params`-a (lásd `research/icmarkets_us30_warmstart_retune.py`, `icmarkets_us500_
   warmstart_retune.py`, `icmarkets_ustec_warmstart_retune.py` kimenete) váltja fel az XM-en
   hangolt régi paramétereket — NEM elég csak a brókert cserélni, a paramétereket is át kell
   venni.

   **✅ Ehhez .set fájlok már elkészültek (2026-09-06)**: `USTEC.set`, `US500.set`, `US30.set`
   a MetaTrader terminál saját mappájában,
   `...\MQL5\Experts\RegimeFramework\presets\` alatt — a `RegimeFramework_EA.mq5` pontos
   `Inp*` input-neveire fordítva a fenti Python `best_params`-okból. Ez a Python `regime_framework`
   kódot NEM érinti (a research-kódtól elkülönül) — a terminál saját mappájába írt, önmagában
   inert fájlok, amíg valaki kézzel be nem tölti őket egy EA Inputs fülén. A magic number
   (`InpMagicNumber`) saját választás volt (USTEC=202609 megtartva az eredeti értéket, US500=202610,
   US30=202611 — hogy 3 párhuzamos EA-példány ne ütközzön), ha már van más konvenció, felülírandó.
   Minden más (session-órák, lot-méret, RSI-periódus stb.) VÁLTOZATLAN maradt az EA jelenlegi
   alapértékeihez képest — a Python-oldali hangolás ezeket nem érintette.
3. **A két már flag-elt kódjavítás átvezetése** — lásd `docs/LIVE_PROJECT_TODO.md`:
   - Napvégi kényszerzárás bug fix (`core/engine.py` és a komponensek).
   - Optuna trial-szám minimum 200 (`optimization/run_study.py`-nak megfelelő élő script).

   **✅ MQL5-oldalon elindult (2026-09-06)**: a `RegimeFramework_EA.mq5` élő EA-ban a napvégi
   zárás egy MÁSIK (óra-küszöbös, nem napváltás-alapú), analóg, potenciálisan súlyosabb
   kockázatot rejt — lásd SESSION_LOG.md 2026-09-06. Javítva egy ELKÜLÖNÍTETT másolaton
   (`RegimeFramework_EA_ICMarkets.mq5`, sikeresen fordul), az ÉLŐ EA-t nem érintve. Strategy
   Tester validáció megtörtént (lásd fent, 1. pont). **Az MQL5-forráskód KÜLÖN git repóban van
   verziókövetve**: `github.com/kirlaca/metaTrader-EA-scripts` (a terminál `MQL5` mappája maga egy
   git repo) — ez a `optuna_research`-től FÜGGETLEN, harmadik repo. Az új
   `RegimeFramework_EA_ICMarkets.mq5` már commitolva/pusholva van oda; a `.set` fájlok és Strategy
   Tester riportok szándékosan NINCSENEK verziókövetve (build-artifact, `.gitignore` kizárja).
4. **MT5-kapcsolat átállítása**: XM szerver/login → IC Markets szerver/login (demóról élőre
   váltáskor egy ÉLŐ IC Markets számla nyitása szükséges — eddig minden teszt demón történt).
5. **ETÜ-jogosultság megerősítése** IC Marketsszel/adótanácsadóval, MIELŐTT valódi tőkét
   mozgatnánk (lásd 3.4 pont).
6. **Rövid megfigyelési/paper-trading időszak** javasolt élő IC Markets számlán, a demó-alapú
   backtest-eredmények megerősítésére, mielőtt a teljes tőkét átvinnénk.

## 5. Nyitott kérdés a felhasználó felé

A fenti bizonyíték (mindhárom index javult, teljes és pontos költségmodell) alapján a migráció
melletti érvek erősek. A nyitott kérdés: a felhasználó a RÉSZVÉNY-kutatás lezárása előtt szeretné-e
meghozni a végleges döntést (a mai nap választása szerint igen, ezt előkészítjük), vagy inkább
megvárja a maradék részvény-jelöltek (NVDA/AMD/MSFT) tesztjét is, mielőtt lezárja a teljes
vizsgálatsorozatot.

## 6. VÉGLEGES DÖNTÉS (felhasználó, 2026-09-06)

**A felhasználó döntött**: a bizonyíték alapján egyértelmű, hogy érdemes IC Marketsre váltani.
Konkrét terv:

- **Élő IC Markets Raw Spread számla, $2000 tőkével**, kis összegű "produktív teszt" jelleggel.
- **Időtartam: 1 hónap, beavatkozás nélkül** (a heartbeat-fájlok passzív figyelésével, de kézi
  trade-felülbírálás nélkül).
- **Csak USTEC és US30** — **US500 KIHAGYVA** ebből a körből. Indoklás: minden mérés (Python
  melegindítás +17%, MQL5 Strategy Tester csak +5.1% nettó profit ÉS a Profit Factor ténylegesen
  romlik 1.43→1.39) azt mutatja, hogy US500-nál a IC Markets-előny a mérési zaj szintjén van, nem
  egyértelmű — egy 1 hónapos, alacsony trade-számú ablakban ez nem adna értékelhető jelet, csak
  zajt. Nem végleges elvetés — később, hosszabb megfigyeléssel visszatérhető.
- **AZ XM-es élő rendszer MELLETT fut, nem helyette** — párhuzamos kiegészítés, a meglévő éles
  rendszert nem érinti.
- A `RegimeFramework_EA_ICMarkets.mq5` (javított, napváltás-alapú kényszerzárással) és a
  megfelelő `USTEC.set`/`US30.set` fájlok kerülnek élesítésre.

**Lot-méretezés véglegesítve (2026-09-06)**: a felhasználó a margin-hányadot 30%-ig engedte volna
felfelé (a $2000 tőke növelése helyett) — a lot-lépésköz (0.1, nem 0.01) miatt tiszta arányos
skálázás nem lehetséges e plafonon belül (0.2/0.2 már 41.4%-ra ugrana). Végleges: **USTEC 0.2 lot
+ US30 0.1 lot → 28.1% margin** (a legközelebb a 30%-hoz túllépés nélkül) — aszimmetrikus,
tudatosan USTEC felé tolt allokáció, ami kockázati szempontból inkább kedvező (USTEC historikus
max DD-je kisebb, 5.13% vs US30 10.95%). `presets/USTEC.set` frissítve (`InpLotSize` 0.1→0.2).

**Még nyitott, a tényleges élesítés előtt**: ETÜ-jogosultság megerősítése IC Marketsszel/
adótanácsadóval (lásd 3.4 pont) — ezt a felhasználónak kell elvégeznie, ez a workspace-ből nem
ellenőrizhető.
