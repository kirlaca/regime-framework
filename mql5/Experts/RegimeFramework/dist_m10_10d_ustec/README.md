# RegimeFramework -- USTEC M10 (10 napos klasszifikátor-ablak) végleges csomag

**Állapot (2026-09-17): kutatás + Strategy Tester valós tick megerősítés MEGTÖRTÉNT (IC Markets:
PF=2,06 vs Python-validáció PF=2,08 -- ~99%-os egyezés). ÉLESÍTÉS MÉG NEM TÖRTÉNT MEG.**

Forrás: `D:\XM\optuna_research\timeframe_deepdive\` (Optuna-hangolás + klasszifikátor-ablak
vizsgálat), `FINDINGS_LOG.md` 4-8. bejegyzés. Ez a mappa a TELJES, önmagában futtatható MQL5
csomagot tartalmazza -- forrás, fordított bináris és `.set` egyben.

## 1. Mit tartalmaz ez a mappa

| Fájl | Szerep |
|---|---|
| `RegimeFramework_EA_M10_10d.mq5` | Fő EA forrás -- a kanonikus `RegimeFramework_EA.mq5` másolata, EGYETLEN strukturális eltéréssel: `RegimeClassifier_M10_10d.mqh`-t használja (lásd lent, MIÉRT kellett külön bináris). |
| `RegimeFramework_EA_M10_10d.ex5` | Lefordított bináris (`MetaEditor64.exe /compile`, 0 hiba/0 figyelmeztetés). |
| `RegimeClassifier_M10_10d.mqh` | A klasszifikátor 1320 bar-os (10 kereskedési nap) ablakkal -- lásd a fájl fejléc-kommentjét az include-guard trükkért. |
| `MeanReversion.mqh`, `TrendFollowing.mqh`, `LastHourContinuation.mqh`, `FridayShort.mqh`, `MarketHolidays.mqh`, `SpreadAnomalyGuard.mqh`, `UsDst.mqh` | VÁLTOZATLAN, a kanonikus EA-val közös komponens-fájlok -- csak a teljesség kedvéért vannak itt másolva, hogy ez a mappa önmagában elegendő legyen egy újrafordításhoz. |
| `RegimeFramework_EA_M10_10d_USTEC.set` | A validált, végleges USTEC-paraméterek. Lot=0,3 (biztonságos max $2000 tőkénél, 1:20 tőkeáttétel-feltevéssel -- lásd 5. pont). Magic=101001. |

**KRITIKUS, MIÉRT KÜLÖN BINÁRIS**: a standard `RegimeFramework_EA.mq5` klasszifikátora
(`RegimeClassifier.mqh`) a `REGIME_ROLLING_WINDOW_BARS`-t fordítás-időben `#define`-ként 8640-re
(60 nap) rögzíti -- ez NEM állítható runtime/`.set`-ből. A ma validált USTEC-konfiguráció viszont
1320 bar-os (10 napos) ablakra épül (empirikusan megerősítve M10-en, `FINDINGS_LOG.md` 8.
bejegyzés). **Ha a standard EA-ra töltöd be ezt a `.set`-et, CSENDBEN rossz (8640 bar-os)
klasszifikációval fog futni** -- mindig `RegimeFramework_EA_M10_10d`-t válaszd ehhez a
paraméter-készlethez, SOHA a sima `RegimeFramework_EA`-t.

## 2. Telepítés / Strategy Tester

1. Másold a teljes mappa tartalmát a célterminál `MQL5\Experts\RegimeFramework\` alá (vagy
   fordítsd újra a `.mq5`-t helyben -- lásd 4. pont).
2. MetaTrader: nyisd meg USTEC M10 chartot, húzd rá a `RegimeFramework_EA_M10_10d` EA-t.
3. Inputs fül → Load → `RegimeFramework_EA_M10_10d_USTEC.set`.
4. Strategy Tester megerősítéshez: Symbol=USTEC, Period=M10, dátum=2025.11.14--2026.09.15 (a
   lezárt validációs ablak), Model="Every tick based on real ticks", Deposit=2000, Leverage=1:20
   (lásd 5. pont, a real teszt 1:200-at mutatott, ami valószínűleg a teszt-fiók alapértéke, NEM a
   valós, szabályozott index-CFD limit).
5. Elvárt eredmény (referencia, 2026-09-17-i valós teszt): PF≈2,06, nettó profit≈$1167 (0,3
   lotnál), n≈193 trade, max equity DD≈8,3%.

## 3. Élesítés előtt MÉG hátralévő nyitott pontok

- **DST-kérdés lezáratlan** -- `InpLhcDstAware=false` szándékosan (lásd `dst_contradiction_
  unresolved` memória). NE kapcsold be, amíg a novemberi (DST-vég utáni) szerver-offset
  újramérés le nem zárja az ellentmondást.
- **Broker-választás**: a mai összevetés (`FINDINGS_LOG.md`, SESSION_LOG.md 2026-09-17) IC
  Markets-en PF=2,06-ot, XM-en (US100Cash) PF=1,71-et adott UGYANARRA a `.set`-re -- ez egybevág
  a 2026-09-06-i broker-migrációs döntés mintázatával. **IC Markets javasolt az élesítéshez.**
- **Élő USTEC M10 példány ütközés-ellenőrzés**: az élő, jelenleg futó USTEC M10 EA magic-je
  202609 (60 napos ablakkal) -- ez a csomag SZÁNDÉKOSAN más magic-et (101001) használ, mert
  ténylegesen más stratégia (más klasszifikátor-ablak). Ha ez váltja a jelenlegi élő példányt,
  a régit előbb le kell állítani/törölni a chartról, NEM egyszerre futtatni ugyanazon a
  szimbólumon két EA-t ugyanazzal a tőkével.
- Lot-méret/tőke végleges hozzárendelése (0,3@$2000 vagy 0,6@$4000) -- lásd `timeframe_deepdive/
  FINDINGS_LOG.md` 7. bejegyzés a teljes érzékenységi táblázatért.

## 4. A KÖVETKEZŐ újrahangolás menete (runbook)

Ez a szakasz azt írja le, hogyan kell ELÖLRŐL végigcsinálni ezt a folyamatot, ha ez a
konfiguráció elavul (negyedéves újrahangolás, vagy tartósan romló élő teljesítmény esetén) --
lásd az általános `regime_framework/docs/RETUNING.md`-t is, ez ANNAK a kiegészítése, a ma
felfedezett, ezt a konkrét (nem-alapértelmezett ablakméretű) hangolási ágat érintő
lépésekkel/csapdákkal.

### 4.1 Klasszifikátor-ablak ellenőrzés ELŐSZÖR (ne feltételezd, hogy a régi ablak még jó)

Mielőtt bármilyen komponens-paramétert újrahangolnál, futtasd újra a klasszifikátor-ablak
robusztussági vizsgálatot a FRISS adaton:

```
python timeframe_deepdive/scripts/06_m10_classifier_window_robustness.py
```

(A `D:\XM\Optuna\venv\Scripts\python.exe`-vel, lásd `mt5_set_file_parser` memória -- rendes
system python nem tartalmazza a `MetaTrader5` csomagot.) Ez a script a `timeframe_deepdive/
lock_config.py` LEZÁRT feltáró ablakán fut, 5-120 napos jelöltekkel, mind a 3 szimbólumon. Nézd
meg, hogy a fél-idős/negyedéves drift minimuma MÉG mindig 10 nap körül van-e -- ha egy más
ablakméret lesz a legjobb, a `RegimeClassifier_M10_10d.mqh` `REGIME_ROLLING_WINDOW_BARS`
konstansát (ÉS a `CLASSIFIER_WINDOW_BARS` Python-oldali megfelelőjét a hangoló scriptben) ennek
megfelelően kell módosítani, ÚJRA lefordítani, és a régi eredményeket EL KELL VETNI (más
klasszifikátor-ablak = más rezsim-besorolás = a régi hangolt paraméterek érvénytelenek rá).

### 4.2 Per-szimbólum, FÜGGETLEN Optuna-hangolás (SOHA ne ossz meg egy keresést szimbólumok közt)

```
python timeframe_deepdive/scripts/04_m10_joint_optuna_full.py --symbols USTEC --trials 500
```

**Fontos, korábban elkövetett hiba, amit el kell kerülni**: a script korábbi verziója
tévedésből EGY, mindkét szimbólumra közös worst-case keresést futtatott -- MINDIG külön
`run_for_symbol()` hívás/study szimbólumonként, ugyanaz a live rendszer saját konvenciója
(`run_study.py` docstring). 70/30 feltáró/validáció felosztás, a teljes szakasz a FUTTATÁS
napjáig menjen (lásd `lock_config.py` `M10_EXPLORATION_START/END`/`M10_VALIDATION_START/END`
frissítése az aktuális dátumokra).

Ha egy paraméter a keresési tartomány szélén landol (`boundary_warnings()` figyelmeztet rá),
**terjeszd ki azt a tartományt és futtasd újra** (`PER_SYMBOL_SEARCH_SPACE_OVERRIDES` dict a
scriptben) -- ne fogadj el egy határon landoló eredményt elsőre. Ha a kiterjesztés UGYANAZT az
eredményt adja (csak az érintett paraméter mozdul, semmi más), az a paraméter valójában
irreleváns (mint `lhc_min_trend_bars` ma) -- ez rendben van, nem kell tovább görgetni. Ha a
kiterjesztés ÉRDEMBEN jobb/rosszabb eredményt ad, az azt jelenti, hogy az előző kör NEM
konvergált -- ismételd, amíg stabilizálódik két egymást követő kiterjesztésen át.

### 4.3 Lezárt validáció + józansági ellenőrzés

A validációs ablakot csak EGYSZER, a `lock_config.get_m10_validation_window(confirm_final_
check=True)` hívással szabad megnyitni, és csak akkor, ha a feltáró eredmény már stabil (4.2
vége). Ha a validáció rosszabb, mint a feltáró eredmény jelentős mértékben, NE ess pánikba
azonnal, de NE is fogadd el -- nézd át, hogy overfitting történt-e (lásd a mai USTEC-nél: két
kiterjesztési kör is stabil maradt, ez adott bizalmat).

### 4.4 EA-bináris frissítés, HA a klasszifikátor-ablak változott

Ha a 4.1 lépés MÁS ablakméretet talált, mint a jelenlegi 1320: módosítsd a
`RegimeClassifier_M10_10d.mqh` `REGIME_ROLLING_WINDOW_BARS` értékét (VAGY hozz létre egy ÚJ,
megfelelően elnevezett `.mqh`-t, ha több változatot is párhuzamosan futtattok), fordítsd újra
(`MetaEditor64.exe /compile:"<path>" /log:"<path>"`), ellenőrizd "0 errors, 0 warnings"-re.

Ha CSAK a paraméterek változtak (az ablakméret NEM), nem kell újrafordítani -- elég egy új
`.set` fájl.

### 4.5 `.set` export + Strategy Tester megerősítés + dokumentálás

Ugyanaz, mint az általános `RETUNING.md` 2-4. pontja: `.set` export a `best_params`-ból (lásd a
formátumot ennek a mappának a `.set` fájljában mintaként), Strategy Tester valós tick
megerősítés (elvárás: a PF/nettó profit 1 nagyságrenden belül és egyező előjelű legyen, mint a
Python-validáció -- lásd a 2. pontban a mai referenciaszámokat), majd dokumentálás
(`timeframe_deepdive/FINDINGS_LOG.md` + `regime_framework/docs/SESSION_LOG.md` + memória).

### 4.6 Élesítés

Csak a fenti 3. pont nyitott kérdéseinek lezárása UTÁN, kizárólag zárt piacon (lásd az általános
projektszabály a kockázatos VPS-műveletekről), a régi (ha van) élő példány leállítása/törlése
ELŐTT az újat betölteni ugyanarra a symbolra.
