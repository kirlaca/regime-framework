# Újrahangolási útmutató (research → éles MQL5 EA)

Cél: egy konkrét, ismételhető lépéssor, hogy negyedévente (vagy amikor a teljesítmény indokolja)
ne kelljen a chat-historyból visszafejteni, hogyan is jutottunk el egy friss Optuna-hangolástól a
ténylegesen élesített `.set` fájlig. Ez a `optuna_research` (hangoló-gépezet) és a
`metaTrader-EA-scripts` (MQL5 forráskód) repók közötti hidat írja le — lásd
[[metatrader-ea-scripts-repo]] a repó-architektúra hátteréért.

**Mikor fusson le ez a folyamat**: negyedévente alapértelmezetten, VAGY ha egy adott index/
szimbólum teljesítménye tartósan (több egymást követő hónapban) elmarad a backtestben mért
walk-forward eredménytől, VAGY ha a bróker kondíciói (spread, session-órák, jutalék) érdemben
változnak.

## 1. Friss adat + melegindított Optuna-hangolás (`optuna_research` repóban)

A meglévő minta-scriptek (`research/icmarkets_us30_warmstart_retune.py`, `icmarkets_us500_
warmstart_retune.py`, `icmarkets_ustec_warmstart_retune.py`) egyenként, szimbólumonként
hardkódolt seed-paraméterekkel készültek — a KÖVETKEZŐ körben ezekből másolat indul, DE a seed
paraméterek MÁR NEM az XM-esek lesznek, hanem az ELŐZŐ kör IC Markets-en talált `best_params`-a
(lásd 3. pont — ezeket a `.set` fájlokból vagy a SESSION_LOG.md-ből lehet visszafejteni).

Lépések:
1. Másolj egy meglévő `icmarkets_<symbol>_warmstart_retune.py`-t az új körhöz (vagy — ha van rá
   idő — általánosítsd egy `--symbol`/`--seed-params-file` CLI-paraméteres közös scripté, ez még
   nincs megcsinálva, lásd "Nyitott fejlesztési ötlet" a végén).
2. `END_DATE`-et állítsd a friss dátumra, `START_DATE`-et hagyd (vagy told ki, ha közben bővült
   az elérhető historikus adat).
3. A seed (`XM_US*_PARAMS` dict) helyére az ELŐZŐ kör `best_params`-a kerüljön.
4. **Trial-szám: minimum 200** (`PLAN.md` §2.5 projektszabály, SOHA ne legyen kevesebb
   alapértelmezésként).
5. Futtatás: `python -m regime_framework.research.icmarkets_<symbol>_warmstart_retune`
   (mindig a `optuna_research` gyökeréből, `python -m` alakban — lásd [[regime-framework-gotchas]]
   5. pontja, MIÉRT nem szabad bare fájlként futtatni).
6. Nézd meg a kiírt `study.best_value`-t és a fold-onkénti bontást — hasonlítsd össze az előző
   kör pontszámával és a fold-pozitív aránnyal. Ha ROSSZABB, mint az előző kör, NE folytasd
   automatikusan — nézd át, mi változott (adat, piaci rezsim, bróker-kondíció).

## 2. `.set` fájl export (a talált `best_params`-ból)

Jelenleg kézi Python-snippettel készül (lásd a 2026-09-06-i SESSION_LOG.md bejegyzéseket a pontos
mintáért) — a `best_params` dict kulcsait (`mr_ema_period`, `tf_fast_ema_days` stb.) az EA
`Inp*` input-neveire kell fordítani (`InpMrEmaPeriod`, `InpTfFastEmaDays` stb. — lásd
`RegimeFramework_EA_ICMarkets.mq5` fejlécét a teljes névtérképért), majd UTF-16LE kódolással,
`Name=Value` soronként kiírni.

**Nyitott fejlesztési ötlet**: ezt érdemes lenne egy újrafelhasználható
`research/export_set_file.py` scripté tenni (bemenet: szimbólum + `best_params` dict vagy JSON,
kimenet: kész `.set` fájl a megfelelő mappába) — MÉG NINCS megírva.

A kész `.set` fájl helye: `<MT5 terminál>\MQL5\Experts\RegimeFramework\presets\<SYMBOL>.set` —
ez a mappa NEM verziókövetett (build-artifact), mindig a legfrissebb hangolást tükrözi.

## 3. Strategy Tester megerősítés (kötelező, PLAN.md 0.1 szabály)

1. MetaTrader Strategy Tester: Expert = `RegimeFramework_EA_ICMarkets` (vagy a mindenkori
   aktuális változat), Symbol = a hangolt szimbólum, Period = **M10**, dátumablak = ugyanaz, mint
   amin a Python-hangolás futott.
2. Model: **"Every tick based on real ticks"** ha van hozzá elég mély tick-adat, egyébként
   "Every tick".
3. Inputs tab → Load → a friss `.set` fájl.
4. Optimization: KIKAPCSOLVA (ez megerősítés, nem keresés).
5. Deposit: mindegy (a lot-méretezés fix, nem tőke-arányos) — de a DOLLÁR eredményt a Python
   `total_net_pnl`/`final_equity` értékeivel vesd össze, ne a %-os hozamot (lásd 2026-09-06-i
   USTEC/US500/US30 összevetés a SESSION_LOG.md-ben, miért).
6. Elvárás: a Strategy Tester dollár-eredménye legyen **ugyanabban a nagyságrendben és irányban**,
   mint a Python walk-forward kumulált nettó profitja. Ha jelentősen (pl. >30%) eltér vagy
   ELLENTÉTES irányú, ÁLLJ MEG — ne élesíts, nézd át, mi tér el (végrehajtási modell, adat-
   eltérés, hiba a `.set`-ben).

## 4. Dokumentálás + commit (mindkét repóban)

1. `optuna_research`: új bejegyzés a `docs/SESSION_LOG.md` tetejére (dátum, eredmény, Strategy
   Tester összevetés), ha durable finding, `PLAN.md` §2-be is. `git add` + `git commit` + `git
   push`.
2. Ha az EA forráskódja is változott (nem csak a `.set`): `metaTrader-EA-scripts` repóban
   (`<MT5 terminál>\MQL5`) `git add`/`commit`/`push` — lásd [[metatrader-ea-scripts-repo]].

## 5. Élesítés

Kézi lépés MetaTraderben: az élesíteni kívánt EA-t (vagy annak megfelelő változatát) rátenni a
megfelelő szimbólum chartjára, Inputs → Load a friss `.set`-tel, `AutoTrading` bekapcsolása.
**Ellenőrizd a magic number-t** — ha több EA-példány fut egyszerre ugyanazon a számlán, mindegyik
egyedi `InpMagicNumber`-rel kell hogy induljon (lásd a 2026-09-06-i USTEC/US500/US30 202609/610/611
kiosztást mintaként).

## 6. Lot-méret / margin — KÜLÖN döntés, NEM hangolási kérdés

A lot-méret (`InpLotSize`) és a margin-allokáció tisztán számla-szintű, tőke-függő döntés — NEM
igényel újrahangolást, bármikor módosítható közvetlenül a `.set` fájlban (lásd a 2026-09-06-i
28.1%-os margin-döntést mintaként: USTEC 0.2 lot + US30 0.1 lot). Csak arra figyelj, hogy a
lot-lépésköz (`SYMBOL_VOLUME_STEP`, jellemzően 0.1 index-CFD-knél) korlátozza, milyen finoman
állítható be egy célzott margin-hányad.

---

**Nyitott fejlesztési ötletek** (egyik sincs még megcsinálva, csak jelölve):
- Egy generikus `research/run_warmstart.py --symbol X --seed-file Y.json --trials 200` script,
  ami kiváltja a jelenlegi, szimbólumonként külön-külön másolt warm-start scripteket.
- Egy `research/export_set_file.py` a `.set` export automatizálására (lásd 2. pont).
