# Production Readiness — út az intézményi szintű minőséghez

Cél: nem amatőr munkát kiadni. Ez a fájl azokat a hiányosságokat listázza, amik a mai (2026-08-22)
őszinte állapotfelmérésből jöttek ki — mi kell ahhoz, hogy a `regime_framework` ne csak
"validált backtest", hanem valóban éles-kész, intézményi színvonalú rendszer legyen.

Minden pont: **Cél** (mi számít késznek) / **Miért fontos** (mi a kockázat, ha kihagyjuk) /
**Megközelítés** (hogyan mérnénk/építenénk, a projekt "validálj olcsón előbb" elve szerint) /
**Állapot**.

A pontok PRIORITÁS szerint vannak csoportosítva, nem felfedezési sorrendben.

---

## P0 — Kritikus, viszonylag olcsón megépíthető

### 1. Költség beépítése az Optuna célfüggvénybe

**Cél**: az `optimization/objective.py` `evaluate_on_folds()`-ja NETTÓ (spread-korrigált) PnL-en
optimalizáljon, ne bruttón.

**Miért fontos**: jelenleg a "legjobb" paraméterek a bruttó PnL-t maximalizálják — a spread csak
utólagos Strategy Tester-es ellenőrzés. Ez azt jelenti, hogy a ténylegesen kiválasztott paraméterek
NEM a költség-optimálisak. Lehet, hogy egy magasabb bruttó, de sűrűbben kereskedő paraméterezés
veszít a spreaddel szemben egy ritkábban kereskedő, alacsonyabb bruttójú változattal szemben — ezt
ma többször is láttuk közvetve (pl. a napi-kvóta-kísérletnél: több trade ≠ jobb nettó eredmény).

**Megközelítés**: minden komponens `entry_spread_price`-ot már felveszi a trade-logba (lásd
`cost_sensitivity_check.py`, `last_hour_continuation_experiment.py` mintája) — ezt be kell vezetni
az `Engine.run()` trade-logjába is (jelenleg nincs `entry_spread_price` mező a `trade_log`
dict-ekben), majd az `evaluate_on_folds()`-nak a NETTÓ `fold_pnls`-t kell használnia. Olcsón
tesztelhető: futtassuk le a MOST már meglévő legjobb paraméterekkel mindkét (bruttó/nettó) módot,
és nézzük meg, mennyit változik a rangsor.

**Állapot**: ✅ **MEGÉPÍTVE (2026-08-22), valós adatú megerősítés hátravan.**
`core/engine.py` `run()`-ja mostantól minden trade-hez rögzíti a belépéskori történelmi
`spread_price`-ot (`entry_spread_price`), a `trade_log` dict-ekben `cost`/`net_pnl` mezőket ad, a
`report.notes`-ban pedig `total_cost`/`total_net_pnl`/`net_win_rate`/`net_profit_factor` (globális
ÉS komponensenkénti bontásban is). A `report.total_pnl`/`profit_factor` TOVÁBBRA IS bruttó marad
(visszafelé kompatibilis minden meglévő hívóval — smoke teszttel megerősítve: byte-azonos bruttó
eredmény, mint a változtatás előtt). Az `optimization/objective.py` `evaluate_on_folds()`-ja
mostantól `report.notes["total_net_pnl"]`-en optimalizál, NEM a bruttón. Fontos elhatárolás a régi
`main_optuna_anomaly.py` hibájától: a spread itt FIX, valós MT5-adatból jövő KÜLSŐ bemenet, NEM
Optuna által tanulható paraméter — nincs "kigamelési" kockázat. Szintetikus adaton, kézzel
számolt referenciával kereszt-ellenőrizve (regresszió + korrektségi teszt egyaránt zöld).
**✅ Valós Optuna study MEGVAN mindhárom szimbólumra (2026-08-22) — tanulságos eredmény:**

| Szimbólum | Pontszám (bruttó→nettó) | Paraméterek |
|---|---|---|
| US100Cash# | 84.95→75.14 | AZONOSAK — ugyanaz a pont nyert mindkét célfüggvénnyel |
| US500Cash# | 11.38→11.76 | KÜLÖNBÖZŐEK — valódi új optimum, preset frissítve |
| US30Cash# | 30.30→10.71 | AZONOSAK — ugyanaz a pont, de a bruttó szám erősen megtévesztő volt |

US100/US30-nál a nettó célfüggvény ugyanazt a paramétert találta a legjobbnak — a fő haszon itt a
BECSÜLETES pontszám (US30 esetén a 30.30 nagyrészt a magas költségű trade-ek felfújt
látszateredménye volt, a valós minőség 10.71). US500-nál viszont ténylegesen MÁS paraméter-
kombináció bizonyult jobbnak nettó alapon — ez lett átvezetve a presetbe.
**✅ Strategy Tester-es megerősítés az ÚJ US500-as paraméterekkel MEGVAN (2026-08-22) — konkrét,
mérhető javulás:**

| Mutató | Bruttó-optimalizált (korábbi) | Nettó-optimalizált (most) |
|---|---|---|
| Net Profit | 148.67 | **167.11** |
| Profit Factor | 1.41 | **1.45** |
| Sharpe Ratio | 10.59 | **11.67** |
| Max Drawdown | 1.47% | 1.62% |

647 trade. Ez a P0 #1. pont TELJES, valós adatú lezárása — a költség beépítése az Optuna
célfüggvénybe nem csak elméletileg helyesebb, hanem US500-on gyakorlati, mérhető javulást is
hozott. US100/US30 presetje nem változott (ugyanaz a paraméter-pont nyert bruttó és nettó alapon
is), így azokat nem kellett újra Strategy Tester-ezni.

**Állapot: ✅ TELJESEN LEZÁRVA.**

### 2. Swap/finanszírozási költség vizsgálata és (ha releváns) modellezése

**Cél**: tudni, mekkora a valós swap-kitettség, és ha érdemi, beépíteni a költség-modellbe.

**Miért fontos**: a rendszer a 22-23 órás rollover-sáv körül aktív (FridayShort 23:00-kor lép be,
a napvégi kényszerzárás is 23:00-nál van) — ez pont az az idősáv, ahol a brókerek jellemzően
swap-ot/finanszírozási díjat számolnak (szerdánként gyakran TRIPLA a hétvégi rollover miatt). Ezt a
projekt EDDIG SOSEM vizsgálta.

**Megközelítés**: első lépés csak MÉRÉS, nem építés — nézzük meg MT5-ben a szimbólumok tényleges
swap-rátáját (`SymbolInfoDouble(SYMBOL_SWAP_LONG/SHORT)` vagy a szimbólum-specifikáció), és
számítsuk ki, mennyi pozíció esik ténylegesen a rollover-pillanatra (a legtöbb MR/TF/LHC pozíció
napon belül zár, de érdemes ellenőrizni, hány esetben nyúlik át). Ha a becsült hatás elhanyagolható
(mert a legtöbb pozíció zárva van addigra), dokumentáljuk és lezárjuk; ha nem, építsünk rá
költség-korrekciót.

**Állapot**: ✅ **LEZÁRVA (2026-08-22) — megmérve, elhanyagolható, nem építünk rá költség-modellt.**

Valós MT5 swap-paraméterek (CURRENCY_MARGIN mód, hármas-szorzós nap: Péntek):

| Szimbólum | swap_long | swap_short | 0.1 lot/éjszaka (LONG) |
|---|---|---|---|
| US100Cash# | -4.66 | +0.53 | -0.47 |
| US500Cash# | -1.21 | +0.14 | -0.12 |
| US30Cash# | -8.46 | +0.96 | -0.85 |

Naptári napváltáson átnyúló trade-ek (a teljes 2023.11.01–2026.08.01 idősoron): US100 3/606
(0.5%), US500 2/627 (0.3%), US30 6/565 (1.1%) — **összesen 11 trade, mindig MeanReversion vagy
LastHourContinuation-ból, SOHA FridayShort-ból**.

**Ok (nem hiba, architekturális jellemző)**: a `FridayShortComponent` nap-határ-korlátozása
ELŐRE, a `prepare_indicators()`-ben számolódik a teljes napi adatból (airtight). Az általános
napvégi kényszerzárás (MR/TF/LHC-nél) ÉLŐBEN, bar-ról bar-ra fut, csak a KÖVETKEZŐ bar-on tudja
ellenőrizni "vége a napnak" — ha egy belépés pont a nap UTOLSÓ bar-ján történik (ritkán, adatlyuk/
rövidített nap miatt), a pozíció csak másnap zár, mert nincs több aznapi bar a kényszerzáráshoz.

**Következtetés**: 11 trade a teljes idősoron, legrosszabb esetben (US30, LONG) kb. -0.85/trade —
összesen JÓVAL 10 valutaegység alatti swap-költség, miközben a rendszer százas-ezres nagyságrendű
nettó profitot termel negyedévenként. **Elhanyagolható — pontosan a PRODUCTION_READINESS.md-ben
rögzített döntési szabály szerint dokumentálva és lezárva, nincs szükség költség-modellre.**

---

## P1 — Éles bevezetés előtt szükséges

### 3. Kockázat-alapú pozícióméretezés (jelenleg fix 0.1 lot)

**Cél**: a lot-méret ne fix legyen, hanem a kockázathoz (pl. az adott trade SL-távolságához és a
számla tőkéjéhez) igazodjon — pl. "kockáztasd a tőke X%-át" logika, ATR-alapú SL-távolságból
visszaszámolva a lot-méretet.

**Miért fontos**: fix lot-méret mellett a kockázat szimbólumonként ÉS időben is változó (a
volatilitás/ár szintje mozog), miközben a tőke sem állandó. Ez a legfontosabb hiányzó réteg egy
valódi tétnél — enélkül a drawdown-számok (amiket ma mértünk) nem transzferálhatók megbízhatóan
más tőkeméretre.

**Megközelítés**: `core/engine.py`/`RegimeFramework_EA.mq5` mindkét oldalán a `lot_size` jelenleg
konstans paraméter — ki kell egészíteni egy `calculate_lot(sl_distance, risk_pct, equity)` jellegű
függvénnyel. Előbb Python-oldali kutatás: mennyit változna a mai eredmények kockázat-korrigált
minősége, ha a lot-méret ATR-arányosan skálázódna?

**Állapot**: 🔄 **kutatás elvégezve (2026-08-22), vegyes/nem egyértelmű eredmény — az építés
egyelőre NEM indokolt.**

`research/risk_based_sizing_check.py`: a mai éles rendszer valós trade-sorozatát (entry_price/
sl_price/pnl, `core/engine.py` `trade_log`-ja kiegészítve ezekkel a mezőkkel) utólag újraskálázta
kockázat-alapú lot-mérettel (`lot = risk_pct * equity / SL-távolság`, compounding), és
összehasonlította a mai fix 0.1 lottal.

Első kör (iparági alapértelmezés, `risk_pct=1%`): mindhárom szimbólumon DRÁMAIAN megnövelte a max
drawdown-t (pl. US500: 0.20%→12.69%) ÉS rosszabb trade-szintű Sharpe-ot adott — az 1% túl agresszív
ehhez a rendszerhez, a compounding önmagában felfújja a hozamot ÉS a kockázatot is.

Második kör (tisztességes összevetés: `risk_pct` DD-illesztve a mai rendszer max drawdown-jára):

| Szimbólum | Max DD (mindkettő) | Profit factor (fix→kockázat-alapú) | Sharpe-szerű (fix→kockázat-alapú) |
|---|---|---|---|
| US100Cash# | 1.36% | 1.70→**3.21** | **0.166**→0.063 |
| US500Cash# | 0.20% | 1.62→**2.40** | **0.140**→0.117 |
| US30Cash# | 1.97% | 1.25→1.25 | **0.070**→0.045 |

**Vegyes kép**: US100/US500-on azonos kockázati szinten a profit factor és a teljes hozam is jobb
kockázat-alapú méretezéssel, DE a trade-szintű Sharpe mindhárom szimbólumon ROSSZABB (a compounding
egyenetlenebbé teszi a hozam-eloszlást), és US30-on (ami már eddig is a legingatagabb komponens-
viselkedésű szimbólum, lásd korábbi bejegyzések) semmilyen javulás nincs. **Következtetés**: az
ATR/SL-arányos pozícióméretezés MUTAT potenciált, de nem egyértelmű, azonnal bevezetendő javítás —
finomhangolást (pl. lot-változékonyság korlátozása, szimbólumonkénti eltérő risk_pct, US30 esetleges
kizárása) igényelne, mielőtt tényleges Engine/EA-beépítés indokolt lenne. A projekt elve szerint
("ne építsünk kétértelmű jelre") ez a pont egyelőre NYITVA marad, alacsonyabb prioritással —
később, ha lesz idő finomhangolásra, érdemes visszatérni rá.

**🔄 Harmadik kör (2026-08-22, folytatás — FÉLBESZAKADT ÁLLAPOT, holnap folytatandó):**

A felhasználó megmutatott egy másik (nem ehhez a rendszerhez tartozó) élő EA-t
(`macdAUG_Long.mq5`), aminek `calcLot()`-ja `OrderCalcProfit()`-tal PONTOSAN számolja a pénz/pont
konverziót (a projekt eddig MINDENHOL hallgatólagosan 1.0-t feltételezett: `pnl = lot *
árkülönbség`). A "páros EA" margin-megosztási logikáját (`InpPairMagicNumber`) a felhasználó
kifejezetten IRRELEVÁNSNAK jelölte ehhez az Engine-hez (nincs "páros" komponensünk) — ezt NEM
vettük át.

**Valódi, mért korrekció**: `mt5.order_calc_profit()`-tal lekérdezve mindhárom szimbólumnál a
pénz/pont/lot tényező **0.8563**, NEM 1.0 — egy FX-konverzió miatt (számla vs. szimbólum
profit-devizaneme), azonos mindhárom szimbólumnál. Ez NEM változtatja meg a korábbi Optuna-
rangsorolásokat (állandó szorzó, nem torzítja a relatív összehasonlítást), DE a kockázat-alapú
lot-számításhoz elengedhetetlenül PONTOS kell legyen.

**Megépítve és smoke teszttel megerősítve**:
- `core/position_sizing.py` (ÚJ): `FixedLotSizer` (a jelenlegi, változatlan viselkedés) és
  `RiskBasedSizer` (a `macdAUG_Long.mq5`-ből kivont, portolható mag — pontos pénz/pont konverzió +
  `lot_step`-re kerekítés + `min/max_lot` vágás, páros-EA logika NÉLKÜL).
- `core/engine.py`: ÚJ `position_sizer`/`equity_start` konstruktor-paraméter — alapértéken
  `FixedLotSizer(lot_size)`, BYTE-AZONOS eredmény a régi kóddal (smoke teszttel megerősítve). A
  `trade_log` ÚJ mezői: `lot` (a trade tényleges lot-mérete), `entry_sl_price` (a BELÉPÉSKORI SL,
  a lot-számításhoz). **Menet közben talált és javított kétértelműség**: a régi `sl_price` mező a
  pozíció ZÁRÁSKORI (trailing stop által esetleg elmozdított) SL-t tárolta — a
  `TrendFollowingComponent` trailing stopja UGYANAZT a `Position.sl_price`-t mutálja, amit a
  belépéskori kockázat-számításnak kellene használnia. Ezt egy smoke teszt fedte fel (51/205 trade
  "hibásnak" tűnt egy kézi újraszámításban) — kiderült, hogy a smoke teszt volt hibás (rossz mezőt
  használt), nem az Engine, de az `entry_sl_price` mező hozzáadása véglegesen megszünteti ezt a
  jövőbeli félreértési kockázatot.
- `research/risk_pct_calibration.py` (ÚJ): a `risk_pct` MEGKERESÉSÉRE két módszert próbáltunk:
  1. **Szabad Optuna-keresés** (walk-forward fold-onkénti %-os hozamon, "átlag − 0.5×szórás"
     pontszámmal) — **MÓDSZERTANI KUDARC, fontos tanulság**: mindkét szimbólumnál (US100, US500) a
     keresési tartomány FELSŐ határára (0.5%) futott ki. Ok: kompoundoló rendszernél ez a
     pontszám-forma a risk_pct-tel LINEÁRISAN skálázódik (nagyobb tét arányosan növeli az átlagot
     ÉS a szórást is), ezért korlát nélkül MINDIG a nagyobb kockázat felé tolna — nem egy hiba a
     kódban, hanem a pontszám-forma alapvető tulajdonsága kompoundoló méretezésnél. **Tanulság: a
     risk_pct-et NEM szabad szabad optimalizálással keresni, csak explicit kockázati korláttal.**
  2. **DD-illesztés** (a helyes módszer, ugyanaz az elv, mint a korábbi, egyszerűsített modellel
     futtatott második körben, most a PONTOS konverziós tényezővel és a valódi Engine-mechanizmussal):

  | Szimbólum | risk_pct (DD-illesztett) | Max DD (mindkettő) | Teljes hozam (fix→kockázat-alapú) | PF (fix→kockázat-alapú) | Sharpe-szerű (fix→kockázat-alapú) |
  |---|---|---|---|---|---|
  | US100Cash# | 0.1222% | 1.36%→1.37% | 13.74%→**16.09%** | **1.72**→1.55 | **0.172**→0.159 |
  | US500Cash# | 0.0113% | 0.20%→0.20% | **2.43%**→1.39% | **1.63**→1.38 | **0.141**→0.121 |

  **✅ TELJES EREDMÉNY, EGYÉRTELMŰ KÖVETKEZTETÉS (2026-08-22 este, a futás lezárult)**: a PONTOS
  konverziós tényezővel US500-nál MINDEN mutató ROSSZABB azonos kockázati szinten (a teljes hozam
  is CSÖKKEN, 2.43%→1.39% — nem csak a Sharpe/PF). US100-nál a hozam nő, de a PF és a Sharpe itt is
  romlik. **Ez egyértelműen rosszabb kép, mint a korábbi, egyszerűsített (1.0 konverziós
  tényezőt feltételező) becslés mutatott** — ott még mindkét szimbólumnál jobb PF-et találtunk
  azonos DD-n. A pontosabb mérés lerontotta a korábbi, kedvezőbb látszatot.

  **Döntés (2026-08-22 este): a kockázat-alapú pozícióméretezés BEVEZETÉSE NEM INDOKOLT
  US100/US500-ra.** A mai fix 0.1 lotos rendszer azonos kockázati szinten JOBB profit factor-t és
  Sharpe-öt ad, mint a tesztelt kalibráció. A mechanizmus (`core/position_sizing.py`,
  `core/engine.py` `position_sizer` paramétere) MEGÉPÍTVE és smoke teszttel megerősítve marad a
  kódbázisban (visszafelé kompatibilis, nem aktív, ha egy hívó nem ad át explicit `position_sizer`-t).

  **⚠️ 2026-08-23-i KORREKCIÓ**: a fenti mérés `lot_step=0.01`/`min_lot=0.01` feltételezéssel futott
  — kiderült, hogy a valós bróker `SYMBOL_VOLUME_STEP`/`SYMBOL_VOLUME_MIN` MINDHÁROM szimbólumnál
  **0.1**, nem 0.01! Emellett a felhasználó felvetése alapján ("professzionális rendszer a free
  marginhoz nézné a kereskedési méretet") bevezettünk egy MÁSODIK sizert is: `MarginBasedSizer`
  (`core/position_sizing.py`) — a lot-méret a SZABAD MARGINHOZ/equityhez igazodik, NEM az adott
  trade SL-távolságához (a referencia EA `lotMargin`-jának megfelelője, "páros EA" logika nélkül).
  Pontos `order_calc_margin()`-nal mérve: mindhárom szimbólumnál ~1:35 tőkeáttétel
  (margin/lot/ár ≈ 0.028551).

  **VÉGLEGES, HELYES lot-lépésközzel (0.1) újramért eredmény**:

  | Szimbólum | Mutató | fix 0.1 lot | risk-alapú (DD-illesztett) | margin-alapú (DD-illesztett) |
  |---|---|---|---|---|
  | US100Cash# | risk_pct/alloc_pct | — | 0.0774% | 1.073% |
  | US100Cash# | teljes hozam | 13.74% | **14.64%** | **19.40%** |
  | US100Cash# | max DD | 1.36% | 1.37% | 1.36% |
  | US100Cash# | Sharpe-szerű | 0.172 | **0.177** | 0.164 |
  | US100Cash# | profit factor | 1.72 | 1.73 | **1.78** |
  | US500Cash# | risk_pct/alloc_pct | — | 0.0127% | 0.297% |
  | US500Cash# | teljes hozam | **2.43%** | 2.40% | **3.17%** |
  | US500Cash# | max DD | 0.20% | 0.20% | 0.19% |
  | US500Cash# | Sharpe-szerű | **0.141** | 0.135 | 0.123 |
  | US500Cash# | profit factor | 1.63 | 1.55 | **1.74** |

  **Értékelés**: a HELYES lépésközzel a kép megváltozott a tegnapi (hibás) mérésekhez képest.
  US100-nál a risk-alapú méretezés MOST tisztán, minden mutatóban (kicsivel) jobb, mint a fix
  lot — de a különbség KICSI (0.005 Sharpe, 0.01 PF, ~1 százalékpont hozam), a zaj határán belül
  lehet. US500-nál a risk-alapú TOVÁBBRA IS kicsit rosszabb minden mutatóban. A margin-alapú
  méretezés MINDKÉT szimbólumnál érdemben növeli a hozamot és a profit factor-t, DE rontja a
  Sharpe-szerű mutatót (a nagyobb, egyenletesebb tét kevésbé "sima" hozam-eloszlást ad).

  **Következtetés**: nincs egyértelmű, nagy hatású javulás egyik teszelt módszerrel sem — a
  legjobb eset (US100 risk-alapú) is csak marginális javulás. A margin-alapú méretezés
  professzionális szempontból (skálázódás a számla méretével, biztonsági felső korlát) indokolt
  lehetne, DE ez egy ÜZLETI/kockázatvállalási döntés (magasabb hozam vs. kevésbé sima equity-görbe),
  nem egyértelmű teljesítmény-javulás — ez a felhasználóval egyeztetendő MIELŐTT bármelyik
  bevezetésre kerülne.

  **Állapot: 🔄 ÚJRAÉRTÉKELVE (2026-08-23) — PONTOS méréssel a kép kiegyensúlyozottabb, de
  a javulás marginális/vegyes. Felhasználói döntés (2026-08-23): a margin-alapú méretezést
  szeretnénk bevezetni, DE a felhasználó explicit biztonsági követelménnyel: "ne lehessen margin
  call, ez kritikus pont" — lásd "Ötödik kör" lentebb a biztonsági tervezésért.**

  **🔄 Ötödik kör (2026-08-23) — biztonsági tervezés, "sose legyen margin call":**

  A demó élő számla (2026-08-23-án lekérdezve, `mt5.account_info()`) valós paraméterei:
  egyenleg ~1000 EUR, `margin_so_call=100%` (margin-hívás), `margin_so_so=50%` (kényszerzárás).
  **Fontos kontextus (a felhasználó megerősítette): ez a demó egyenleg csak fejlesztési célra
  van** — DE mivel az `alloc_pct`/`max_margin_utilization_pct` SZÁZALÉK-alapú, a tervezett
  mechanizmus a tényleges számlamérettől FÜGGETLENÜL ugyanúgy működik (ez pont a "professzionális,
  skálázódó" tulajdonság lényege).

  **Konkrét számítás a demó adatokkal (csak illusztráció, nem a döntés alapja)**: a tegnap
  kalibrált `alloc_pct` (~0.3–1.1%) ennél a fajta egyenlegnél A BRÓKER MINIMUM LOTJA (0.1) ALÁ
  esne — a méretezés tehát ADDIG egyszerűen a mai fix lotra kerekítene fel, amíg az egyenleg (a
  mostani árszinteken) kb. **7800 EUR fölé** nem nő. A méretezés tehát NEM változtat semmit a
  közeljövőben — ez egy hosszú távú, a tőke növekedésével fokozatosan aktiválódó mechanizmus.

  **Biztonsági tervezés — `MarginBasedSizer` kiegészítve `max_margin_utilization_pct`-tel**
  (`core/position_sizing.py`): ez egy MÁSODIK, az `alloc_pct`-től FÜGGETLEN kemény felső korlát —
  `calc_lot()` mindig `min(alloc_pct, max_margin_utilization_pct)`-ot használ, tehát a biztonsági
  korlát BÁRMIKOR felülírhatja (szigoríthatja) a kalibrált értéket, sose fordítva. Ez védelmet ad
  hangolási hiba vagy extrém tőkenövekedés esetére is — nem KELL megbízni abban, hogy az
  `alloc_pct` mindig ésszerű marad.

  **Smoke teszttel bizonyítva (`smoke_test_no_margin_call.py`)**: `max_margin_utilization_pct=20%`
  mellett, equity=100 EUR-tól 10 millió EUR-ig és mindhárom szimbólum árszintjén tesztelve, A
  BRÓKER MINIMUM LOTJA FELETT (ahol a képlet ténylegesen érvényesül, nem a bróker-korlát dominál) a
  margin-szint SOSEM esik a margin-hívási szint (100%) duplája (200%) alá — tehát a mechanizmus
  matematikailag garantáltan távol tartja a rendszert a margin-hívástól/kényszerzárástól,
  FÜGGETLENÜL az egyenleg méretétől vagy az árfolyam-szinttől.

  **Valós, hasznos mellékfelfedezés — MINIMUM biztonságos számlaméret szimbólumonként** (a bróker
  minimum lotja miatt, 300%-os margin-szint célt véve, ami már a 100%-os hívási szint 3x-os
  tartaléka; 2026-08-23-i árszinteken):

  | Szimbólum | 0.1 lot margin-igénye | Min. ajánlott önálló egyenleg |
  |---|---|---|
  | US100Cash# | 83.64 EUR | ~251 EUR |
  | US500Cash# | 21.90 EUR | ~66 EUR |
  | US30Cash# | 152.07 EUR | ~456 EUR |
  | **Mindhárom EGYSZERRE** (worst case) | 257.61 EUR | **~773 EUR** |

  A mai 1000 EUR demó-egyenleg ELEGENDŐ ahhoz, hogy mindhárom szimbólumot EGYSZERRE, minimum
  lottal biztonságosan (388%-os margin-szinttel, jócskán a célzott 300% fölött) fusson — ez a
  MAI fix-lotos élő rendszer implicit biztonságát is megerősíti, nem csak a jövőbeli margin-alapú
  tervét.

  **Élő EA-implementációs követelmény (rögzítve, még nem kódolva)**: a `free_margin`-t az EA-nak a
  VALÓS `AccountInfoDouble(ACCOUNT_MARGIN_FREE)`-ből kell vennie, NEM equity-közelítéssel (ahogy a
  Python-modell egyszerűsítve teszi) — így TÖBB, párhuzamosan futó szimbólum esetén minden EA
  automatikusan "látja" a többi szimbólum lekötött marginját, és arányosan kisebb lotot számol,
  ha már van nyitott pozíció máshol. Ez a mechanizmus SZÁNDÉKOSAN NEM a referencia EA "páros EA"
  magic-number-alapú megoldását követi (azt a felhasználó irrelevánsnak jelölte) — a valós
  szabad margin lekérdezése önmagában, koordináció NÉLKÜL is helyesen működik minden szimbólumra.

  **Állapot: 🔄 biztonsági tervezés LEZÁRVA és bizonyítva (smoke teszttel) — a mechanizmus
  bevezetése MOST már biztonságosnak tekinthető bármilyen jövőbeli számlaméretnél. Hátravan: (1)
  végleges `alloc_pct`/`max_margin_utilization_pct` érték kiválasztása US100/US500-ra, (2) MQL5
  portolás a valós `ACCOUNT_MARGIN_FREE`-vel, (3) Strategy Tester-es megerősítés.**

  **✅ MQL5 port MEGÉPÍTVE, fordítva (2026-08-23)**: `RegimeFramework_EA.mq5` új
  `CalcMarginBasedLot()` függvénnyel — a referencia EA `lotMargin`-jának megfelelője, "páros EA"
  logika NÉLKÜL, a VALÓS `AccountInfoDouble(ACCOUNT_MARGIN_FREE)`-vel (nem equity-közelítéssel).
  Új input-csoport: `InpUseMarginBasedSizing` (alapérték `false` — VÁLTOZATLAN, fix-lotos
  viselkedés, amíg explicit be nem kapcsoljuk), `InpMarginAllocPct`, `InpMaxMarginUtilizationPct`
  (a Python `MarginBasedSizer` `max_margin_utilization_pct`-jének megfelelője — `calc_lot()`
  mindig `min(alloc, max_util)`-ot használ), `InpMinSafeMarginLevelPct` (VÉGSŐ biztonsági kapu:
  ha még a bróker minimum lotja is ez alá vinné a margin-szintet, a függvény 0.0-t ad vissza, az
  `OpenPosition()` pedig KIHAGYJA a belépést, nem erőlteti). Lefele kerekítés (`MathFloor`, NEM
  `MathRound`) a lot-lépésközre, hogy a tényleges margin-igény sose léphesse át a budget-et.
  **Fordítás: 0 hiba, 0 figyelmeztetés**, mind a projekt-mappában, mind az élő MT5-terminálban.

  **Presetek elkészítve**: `RegimeFramework_EA_US100Cash.set`/`_US500Cash.set`/`_US30Cash.set`
  kiegészítve az új inputokkal (`InpUseMarginBasedSizing=false` — a mai élő viselkedés
  VÁLTOZATLAN marad). Két ÚJ, dedikált A/B-teszt preset: `RegimeFramework_EA_US100Cash_
  MarginSizing.set` (`alloc_pct=1.073%`) és `RegimeFramework_EA_US500Cash_MarginSizing.set`
  (`alloc_pct=0.297%`), mindkettő `InpMaxMarginUtilizationPct=10%`-kal — mindkét élő
  MT5-terminál `MQL5/Presets/RegimeFramework/` mappájában elérhetők.

  **Hátravan (felhasználói futtatást igényel)**: Strategy Tester-es A/B összevetés US100/US500-ra
  a `_MarginSizing` presettel a jelenlegi (fix lotos) preset ellenében — a Python-oldali becslés
  (P1 #3 negyedik kör táblázata) szerint várható: valamivel magasabb Net Profit/Profit Factor,
  hasonló Max Drawdown, valamivel alacsonyabb Sharpe Ratio. Ha a Strategy Tester ezt megerősíti,
  a `_MarginSizing` preset éles bevezetése mérlegelhető.

  **⚠️ Hatodik kör (2026-08-23) — az első Strategy Tester-es teszt NEM mutatott eltérést, ok
  megtalálva és javítva.** A felhasználó lefuttatta az US500 `_MarginSizing` presetet 1500 EUR
  kezdő egyenleggel — az eredmény BYTE-AZONOS volt a fix lotos alapállapottal (167.11 Net Profit,
  647 trade, stb.) Ok: a `alloc_pct` (0.297%) a korábbi, 10 000 EUR-os feltételezésre volt
  kalibrálva — 1500 EUR-nál ez a bróker minimum lotja (0.1) ALÁ esett, a mechanizmus a teszt
  TELJES idejére "befagyott" a fix lotra. A felhasználó helyesen mutatott rá: a kalibrálásnak a
  VALÓS, teszteléshez használt tőkeszinthez kell igazodnia, nem egy tetszőleges nagy referenciához.

  **Konkrét küszöbszámítás (mai árszinten, illusztráció)**: 1000 EUR egyenlegnél a KÖVETKEZŐ
  lot-lépcső (0.1→0.2) eléréséhez szükséges `alloc_pct`: US100 **16.73%** (!), US500 **4.38%**,
  US30 **30.41%**. Mivel US100/US30 küszöbe MEGHALADJA a 10%-os biztonsági korlátot, ezeknél a
  szimbólumoknál 1000 EUR körüli egyenlegnél a mechanizmus STRUKTURÁLISAN nem tud elmozdulni a
  minimumtól (ez a bróker lot-lépésköze [0.1] és az instrumentum árszintje miatti fizikai korlát,
  nem hiba) — US500 kedvezőbb (alacsonyabb margin/lot), ott a 10%-os korláton belül maradva is
  van mozgástér.

  **Újrakalibrálva REALISZTIKUS, 1500 EUR-os induló tőkével** (`research/risk_pct_calibration.py`,
  `START_EQUITY=1500`, keresési felső határ = a valós 10%-os biztonsági korlát):

  | Szimbólum | alloc_pct (1500 EUR-ra kalibrálva) | fix hozam/DD/Sharpe/PF | margin-alapú hozam/DD/Sharpe/PF |
  |---|---|---|---|
  | US100Cash# | **5.348%** | 91.59% / 5.45% / 0.181 / 1.72 | **119.50%** / 5.18% / 0.159 / **1.77** |
  | US500Cash# | **1.762%** | 16.22% / 1.17% / 0.143 / 1.63 | **20.07%** / 1.23% / 0.122 / **1.76** |

  Mindkét érték kényelmesen a 10%-os biztonsági korlát ALATT maradt (a korlát nem ütközött). A
  minőségi kép UGYANAZ, mint a korábbi (10 000 EUR-os) kalibrációnál: magasabb hozam/profit
  factor, alacsonyabb Sharpe-konzisztencia — ez megerősíti, hogy ez egy valódi, a kompoundolás
  természetéből fakadó kompromisszum, nem a referencia-tőke véletlen műterméke.

  **Presetek frissítve** (`RegimeFramework_EA_US100Cash_MarginSizing.set`: `alloc_pct=5.348%`,
  `RegimeFramework_EA_US500Cash_MarginSizing.set`: `alloc_pct=1.762%`, mindkettő az élő terminál
  Presets mappájában is), EA újrafordítva (0 hiba/0 figyelmeztetés, mindkét helyen).

  **Fontos figyelmeztetés a KÖVETKEZŐ Strategy Tester-futtatáshoz**: mivel az árszint historikusan
  változott (2023-2026 közt), és a küszöb-számítás árfüggő, egy RÖVID, csak a MAI (magas) árszintet
  lefedő tesztidőszak ismét nem feltétlenül mutatna eltérést — a TELJES (2023-11-01 - 2026-08-21)
  idősoron kell futtatni, ugyanazzal az induló tőkével (1500 EUR), amivel a fenti Python-becslés
  készült, az alma-almával összevetéshez.

  **✅ VALÓS STRATEGY TESTER-ES MEGERŐSÍTÉS — US500Cash# (2026-08-23) — EGYÉRTELMŰ, TISZTA
  JAVULÁS MINDEN MUTATÓBAN**, teljes 2023.11.01–2026.08.22 időszak, 1500 EUR induló tőke:

  | Mutató | fix 0.1 lot | margin-alapú (alloc_pct=1.762%) |
  |---|---|---|
  | Net Profit | 167.11 | **224.86** (+34.6%) |
  | Profit Factor | 1.45 | **1.58** |
  | Sharpe Ratio | 11.67 | **12.24** |
  | Balance DD | 1.62% | **1.57%** |
  | Equity DD | 1.72% | **1.66%** |
  | Trade szám | 647 | 647 |

  **Fontos, pozitív meglepetés**: a valós MT5 Sharpe Ratio (napi hozam-alapú számítás) MOST
  JAVULT, ellentétben a Python-oldali, trade-szintű "Sharpe-szerű" proxy-val, ami romlást jósolt —
  a két metrika NEM ugyanazt méri (a proxy trade-enkénti szórásra épül, az MT5 mutató a napi
  equity-görbe volatilitására), és ez esetben a VALÓS, hivatalos mutató a kedvezőbb. Ez a mai
  legerősebb, minden szempontból (profit, PF, Sharpe, DD EGYSZERRE jobb, nincs kompromisszum)
  megerősített eredmény a teljes P1 #3 vizsgálat során.

  **Hátravan**: ugyanez a teszt US100Cash#-re (`RegimeFramework_EA_US100Cash_MarginSizing.set`,
  `alloc_pct=5.348%`, ugyanaz az időszak/induló tőke) a teljes megerősítéshez.

  **🛑 VALÓS STRATEGY TESTER-ES MEGERŐSÍTÉS — US100Cash# (2026-08-23) — RIASZTÓ ELTÉRÉS A
  PYTHON-MODELLTŐL, NEM AJÁNLOTT BEVEZETNI.** Teljes 2023.11.01–2026.08.22 időszak, 1500 EUR
  induló tőke, mindkét preset ugyanazon a beállításon:

  | Mutató | fix 0.1 lot | margin-alapú (alloc_pct=5.348%) | Változás |
  |---|---|---|---|
  | Net Profit | 1108.75 | **1710.71** | +54.3% |
  | Profit Factor | 1.54 | 1.51 | kicsit rosszabb |
  | Sharpe Ratio | 12.93 | 11.44 | rosszabb |
  | Balance DD | 5.39% | **8.69%** | **+61% (!)** |
  | Equity DD | 5.66% | **9.11%** | **+61% (!)** |

  A Python-kalibráció (fenti táblázat) AZONOS drawdown-ot jósolt (5.45%→5.18%, a margin-alapú
  MÉG JOBB is lett volna a modell szerint) — a VALÓSÁGBAN a drawdown 61%-kal MEGNŐTT. Ez egy
  éles, minőségi eltérés a Python-modell és a valós MT5-végrehajtás közt, KIFEJEZETTEN US100-nál
  (az US500-nál a modell és a valóság jól egyezett, lásd fentebb). Feltételezett ok: az US100-hoz
  tartozó `alloc_pct` (5.348%) sokkal nagyobb, mint az US500-é (1.762%) — minél nagyobb az
  `alloc_pct`, annál erősebben nagyítja fel a lot-méretet a tőke növekedésével, ami felerősíti a
  Python-modell egyszerűsítéseinek (spread/szlippázs-becslés, ár-lineáris margin-közelítés) és a
  valós MT5-végrehajtás közti kis eltéréseket, pont a legnagyobb-lotos (legkésőbbi, legnagyobb
  tőkéjű) trade-eknél — ahol egy váratlanul nagy veszteség aránytalanul nagy valós drawdown-ot
  okoz, amit a modell nem látott előre.

  **Döntés: az US100-ra a jelenlegi kalibráció (5.348%) NEM AJÁNLOTT bevezetésre — a Python-modell
  itt megbízhatatlannak bizonyult, a valós kockázat lényegesen (61%-kal) nagyobb, mint tervezve
  volt.** Az US500-as eredmény (kétszeresen megerősítve, konzisztensen jó) VÁLTOZATLANUL
  megbízhatónak tekinthető és bevezethető. Az US100-nál VAGY (a) alacsonyabb `alloc_pct`
  EMPIRIKUS (közvetlenül Strategy Tester-ben tesztelt, nem csak Python-modellezett) újrakeresése
  szükséges, VAGY (b) az US100 marad fix lotos, amíg nincs megbízhatóbb kalibrációs módszer rá.

  **✅ VÉGLEGES FELHASZNÁLÓI DÖNTÉS (2026-08-23): US100 MARAD FIX LOTOS.** Nem indokolt tovább
  finomhangolni egy már bizonyítottan megbízhatatlan modellt erre a szimbólumra — az US500-as,
  kétszeresen megerősített javulás önmagában is értékes eredmény.

  **Bevezetve**: `RegimeFramework_EA_US500Cash.set` (a FŐ, éles preset — nem csak a `_MarginSizing`
  A/B-teszt-variáns) frissítve `InpUseMarginBasedSizing=true`-ra, `alloc_pct=1.762%`,
  `max_margin_utilization_pct=10%`-kal — ez mostantól az ÉLES US500 konfiguráció, feltöltve az
  élő terminál Presets mappájába is. `RegimeFramework_EA_US100Cash.set` VÁLTOZATLAN marad
  (`InpUseMarginBasedSizing=false`), a megvizsgált-de-elvetett `alloc_pct=5.348%` érték csak
  dokumentációs referenciaként maradt a fájlban, sosem aktiválódik.

  **Állapot: ✅ P1 #3 LEZÁRVA (2026-08-23).** Összefoglalás: a kockázat-alapú (SL-távolság-alapú)
  méretezés elvetve (nem egyértelmű javulás). A margin-alapú méretezés MEGÉPÍTVE, biztonsági
  korláttal (max_margin_utilization_pct, "sose margin call" smoke teszttel bizonyítva),
  US500-ra ÉLESBEN BEVEZETVE (valós Strategy Tester-rel kétszer megerősített, tiszta javulás),
  US100-ra ELVETVE (a Python-modell megbízhatatlannak bizonyult ennél a szimbólumnál — fontos,
  dokumentált tanulság: a DD-illesztéses kalibráció csak MÉRSÉKELT `alloc_pct`-nél megbízható,
  nagy `alloc_pct`-nél a modell/valóság-eltérés felnagyítódik). US30 nem volt vizsgálva, marad
  fix lotos.

### 4. Portfólió-szintű vészfék / kill-switch

**Cél**: egy közös, minden komponensre/szimbólumra kiterjedő max-napi-veszteség és/vagy
max-drawdown limit, ami leállítja az új belépéseket (vagy zár mindent), ha átlépjük.

**Miért fontos**: a 3 US-szimbólum ERŐSEN korrelált (0.78-0.95, mérve 2026-08-20-án) — ha egyszerre
fut több szimbólumon, egy rossz nap egyszerre üt mindegyiken. Jelenleg nincs semmilyen közös
vészfék, csak a komponensek saját, elszigetelt SL-jei.

**Megközelítés**: EA-szinten egy napi/heti equity-figyelő, ami leállítja az `OnTick()` új-belépés
ágát (de a meglévő pozíciók SL/exit-logikáját nem), ha egy előre beállított küszöböt átlép a napi/heti
veszteség. Olcsón tesztelhető Python-oldalon is: mennyit ér egy ilyen limit a már meglévő
walk-forward adatokon (mennyi rossz napot fogott volna el, mennyi jó napot vágott volna le tévesen).

**Állapot**: 🔄 **kiindulómérés megvan (2026-08-23) — a korrelációs kockázat MATERIÁLISNAK
bizonyult, folytatás indokolt.**

`research/portfolio_circuit_breaker_check.py`: a 3 szimbólumot (US100/US500/US30) EGYMÁSTÓL
FÜGGETLENÜL futtatva (a mai éles logika, vészfék NÉLKÜL), napi bontásban összesítette a realizált
nettó PnL-t, és megmérte, hány "rossz nap" TÖBB szimbólumra EGYSZERRE koncentrálódik ("pile-up"),
szemben az elszigetelt, egy-szimbólumos rossz napokkal. ⚠️ Módszertani korlát: a `trade_log` csak
NAPI granularitású, a lezárások napon belüli SORRENDJÉT nem ismerjük — ez FELSŐ BECSLÉS, nem a
vészfék tényleges, garantált haszna (lásd fájl fejléce).

**Eredmény (teljes 2023-11-01–2026-08-21 időszak, 637 nap, legalább 1 trade zárt)**:
- 324 negatív (összesített) nap, ebből **231 (71%) "pile-up"** (2+ szimbólum EGYSZERRE veszít),
  csak 93 elszigetelt.
- **A teljes negatív napi PnL 86.7%-a pile-up napokból jön** — a 0.78-0.95-ös korreláció
  (SESSION_LOG.md 2026-08-20) TÉNYLEGESEN materializálódik közös rossz napokban, nem csak
  elméleti szám.
- **REALISZTIKUS, 1500 EUR-os referenciatőkénél** (nem az irreális 10 000 EUR-nál, lásd P1 #3
  tanulsága): `-1%` (-15) alatt 103 nap (95 pile-up), `-2%` (-30) alatt 17 nap (MIND pile-up),
  `-3%` (-45) alatt 4 nap (MIND pile-up), `-5%` (-75) alatt 1 nap (a valaha volt legrosszabb nap,
  2025-04-04, mindhárom szimbólum egyszerre veszített).
- **Minden 2%-nál nagyobb napi veszteség-esemény kizárólag pile-up napokból jött** — ez erős
  jelzés, hogy egy portfólió-szintű vészfék NEM csak elméletileg, hanem a gyakorlatban is
  releváns kockázatot kezelne.

**Következő lépés**: egy bar-szintű, TÖBB szimbólumot lezárási sorrendben szimuláló mérés
(a jelenlegi napi-granularitású felső becslés helyett), ami a TÉNYLEGES, blokkolással elérhető
megtakarítást mérné — ez indokolná (vagy cáfolná) a tényleges EA-szintű megépítést.

**🛑 Bar-szintű, lockstep szimuláció (2026-08-23) — A NAPI BECSLÉS NEM IGAZOLÓDOTT, NEM AJÁNLOTT
BEVEZETNI.** `research/portfolio_lockstep_breaker_check.py`: mindhárom szimbólumot TÉNYLEGESEN
lockstep-ben (közös időtengelyen, bar-ról bar-ra) szimulálva, közös napi vészfékkel (blokkolja az
ÚJ belépéseket, ha a nap MÁR realizált összesített PnL-je küszöb alá esik — a nyitott pozíciók
exit-logikája változatlan). Regresszió: vészfék nélkül BYTE-AZONOS eredményt ad, mint a 3
független Engine-futtatás összege (smoke teszttel megerősítve) — a szimuláció hűen tükrözi a mai
éles logikát.

| | trade | net PnL | max DD | PF |
|---|---|---|---|---|
| Vészfék nélkül | 1830 | 2307.82 | 8.46% | 1.44 |
| -1%-os napi vészfék | 1754 | 2319.80 | **8.62%** | 1.45 |
| -2%-os napi vészfék | 1818 | 2309.99 | 8.58% | 1.44 |
| -3%-os napi vészfék | 1826 | 2298.57 | 8.59% | 1.44 |

**A max drawdown NEM csökkent, minimálisan még NŐTT is a vészfékkel** — a nettó PnL/PF
gyakorlatilag változatlan minden küszöbön. Ok: a vészfék csak a nap MÁR realizált vesztesége UTÁN
tud blokkolni; a blokkolt lehetőségek (5-171 db küszöbönként) vegyesen nyerő/vesztes trade-ek is
lehettek volna, a nettó hatásuk semleges-enyhén negatív. A napi-granularitású korreláció (86.7%
pile-up) VALÓS jelenség, de EZ a fajta (napi-küszöbös, új-belépés-blokkoló) vészfék NEM tudja
kiaknázni — a napi felső becslés megbízhatatlannak bizonyult a tényleges hatás előrejelzésére.

**Döntés: EZT a vészfék-mechanizmust NEM ajánlott bevezetni** — a mért haszon nem indokolja a
komplexitást. Alternatív tervek (heti küszöb, meglévő pozíciók zárása is, előrejelző indikátor
használata blokkolás helyett) ELVILEG szóba jöhetnének, de ÚJ, külön validációt igényelnének —
jelenleg nincs indíték rájuk anélkül, hogy valamelyik konkrétan jobb eredményt ígérne.

**🔍 Felhasználói kiegészítő ötlet (2026-08-23): kereszt-eszköz piaci stressz jelzés EGYETLEN
kereskedett szimbólumra.** "Ha csak egy instrumentumon kereskedünk, akkor is van értelme az
egyszerre esés piaci hatását vizsgálni, ha csak az egyikre lesz hatással" — azaz a MÁSIK KÉT (nem
kereskedett) szimbólum egyidejű vesztesége JELZÉSKÉNT hasznos lehet a ténylegesen kereskedett
szimbólumra, anélkül, hogy azokat is kereskednénk.

`research/cross_asset_stress_signal_check.py` — két verzió: (1) "aznapi" jelzés (a másik kettő
AZNAPI összesített PnL-je), (2) "tegnapi" jelzés (a másik kettő ELŐZŐ napi PnL-je, szigorúan
ok-okozati, look-ahead NÉLKÜL). **Az aznapi verzió LÁTVÁNYOS hatást mutatott** (pl. US100 win rate
64.4%→43.2%, US30 win rate 54.9%→34.2% "stressz" napokon) — DE ez ⚠️ LOOK-AHEAD KOCKÁZATOS: a
másik két szimbólum lezárása a nap KÉSŐBBI részében történhetett, mint a kereskedett szimbólum
belépése, tehát ez az infó a valóságban MÉG NEM lett volna elérhető a döntés pillanatában.

**A szigorúan ok-okozati (tegnapi) verzióval a hatás NAGYRÉSZT ELTŰNT**:

| Szimbólum | Aznapi különbség (⚠️ look-ahead) | Tegnapi különbség (valós idejű) |
|---|---|---|
| US100Cash# | -5.453 | -1.352 (mérsékelt) |
| US500Cash# | -1.253 | **-0.032 (gyakorlatilag nulla)** |
| US30Cash# | -7.635 | **+0.458 (megfordul!)** |

**Döntés**: a kezdeti, látványos eredmény NAGYRÉSZT look-ahead torzítás volt — ez PONTOSAN az a
fajta hiba, amit a projekt szigorú (ok-okozatiságot ellenőrző) validációs fegyelme hivatott
elkapni. A valós idejű, ténylegesen implementálható verzió **US500-ra (az élesben bevezetett
szimbólumra) gyakorlatilag HASZNAVEHETETLEN** jelzést ad (a különbség nulla közeli). **Ezt a
szűrőt NEM ajánlott bevezetni.** (US100-nál maradt egy mérsékelt hatás, de US100 amúgy is fix
lotos marad, és önmagában ez a hatás sem elég erős egy külön szűrő indokolásához.)

**Tanulság a jövőre**: bármilyen "korrelált piaci jelzés" ötletet MINDIG a szigorúan ok-okozati
(csak múltbeli, ténylegesen elérhető információt használó) formában kell tesztelni ELŐSZÖR — az
"aznapi"/aggregált verzió megtévesztően erősnek tűnhet pusztán a lezárási sorrend miatt.

**Állapot: ✅ P1 #4 TELJESEN LEZÁRVA (2026-08-23).** Összefoglalás: a korreláció (0.78-0.95) VALÓS
és a napi PnL-ben is materializálódik (86.7% pile-up-ból jön), DE egyik vizsgált kiaknázási
mechanizmus sem bizonyult életképesnek: (1) a napi-küszöbös, új-belépés-blokkoló portfólió-vészfék
a bar-szintű szimulációban NEM csökkentette a drawdown-ot; (2) a kereszt-eszköz "piaci stressz"
jelzés a szigorúan ok-okozati (look-ahead-mentes) formában gyakorlatilag hasznavehetetlennek
bizonyult. Jelenleg NINCS olyan, méréssel alátámasztott portfólió-szintű védelmi mechanizmus, amit
érdemes lenne beépíteni — a komponensek saját, elszigetelt SL/exit-logikája marad az elsődleges
kockázatkezelés.

### 5. Valódi, "sosem látott" hold-out validációs időszak

**Cél**: egy utolsó, kizárólag végső ellenőrzésre fenntartott időszak, amit az Optuna/walk-forward
folyamat SOHA nem lát a paraméterkeresés közben.

**Miért fontos**: a jelenlegi walk-forward jó (bővülő ablak, fold-onkénti mérés), DE az Optuna a
TELJES fold-halmazon választ "legjobbat" — nincs egy utolsó szakasz, amit csak a végén, egyszer
nézünk meg, a paraméterek lezárása UTÁN, tiszta sanity check-ként.

**Megközelítés**: pl. az utolsó 2-3 hónapot (ami eddig is a leggyengébb/legkisebb mintás fold volt
minden mérésben) explicit módon kivenni az Optuna `FOLD_BOUNDARIES`-ből, a hangolás lezárása UTÁN
egyetlen, be nem avatkozó futtatással megnézni rajta a végleges paramétereket.

**Állapot**: ✅ **LEZÁRVA (2026-08-23) — elvégezve, US100/US500 megbízhatóan kiállta, US30
megbukott.**

`validation/validate_holdout.py`: a 2026-06-01–2026-08-21 időszakot (kb. 2.7 hónap) explicit
KIVETTÜK a hangolási fold-halmazból (`TUNING_FOLD_BOUNDARIES`, az eredeti `FOLD_BOUNDARIES` utolsó
foldja 2026-07-01-ről 2026-06-01-re rövidítve), egy FRISS, 60 trial-es Optuna study-t futtattunk
KIZÁRÓLAG ezen a redukált fold-halmazon mindhárom szimbólumra, majd a talált legjobb
paraméterekkel EGYETLEN, be nem avatkozó `Engine.run()`-t a hold-out időszakon.

| Szimbólum | Trade szám | Win rate | Bruttó PF | **Nettó PF** | Nettó PnL |
|---|---|---|---|---|---|
| US100Cash# | 55 | 49.1% | 2.20 | **2.13** | +272.88 |
| US500Cash# | 52 | 38.5% | 1.27 | **1.19** | +8.65 |
| US30Cash# | 47 | 46.8% | 0.89 | **0.82** | **-47.03** |

Mindhárom szimbólumnál megbízható mintaelemszám (≥30 trade). **US100 kiemelkedően jól teljesített**
egy teljesen sosem látott időszakon — erős megerősítés, hogy a paraméterek nem illeszkedtek túl a
hangolási adatra. **US500 pozitív maradt** (vékonyabb haszonkulccsal, ami összhangban van a
historikus, mérsékelt PF-jével). **US30 ELBUKTA a tesztet** (nettó veszteséges, PF 0.82,
megbízható mintán) — ez konkrét, számszerű MEGERŐSÍTÉSE a projekt eddigi, ismételt US30-
óvatosságának (lásd korábbi bejegyzések: FridayShort volatilis US30-on, magasabb DD a
4-komponenses újrahangolás után stb.), nem új probléma, mivel US30 amúgy sincs élesítve.

**Következtetés**: a jelenlegi élesítési terv (US100 fix lotos, US500 margin-alapú) MINDKÉT
aktívan használt szimbólumra megerősítést kapott egy valódi, a hangolás által SOHA nem látott
időszakon. US30 továbbra sem ajánlott élesítésre — ez a hold-out teszt önmagában is elegendő ok
lenne rá, ha korábban nem lett volna már amúgy is ez a döntés.

---

## P2 — Robusztusság és bizalom növelése

### 6. Paraméter-stabilitás / érzékenység-vizsgálat

**Cél**: tudni, mennyire "éles" vagy "lapos" az Optuna által talált optimum — mennyit romlik a
teljesítmény, ha a legjobb paramétereket ±10-20%-kal elmozdítjuk.

**Miért fontos**: a 2026-08-22-i 3→4 komponenses újrahangolásnál US30 TrendFollowing trade-száma
48→177-re ugrott egyetlen újrafuttatás között — ez erős jele annak, hogy az optimalizálási felszín
zajos, nem egy stabil optimum köré rendeződik. Ha egy paraméter kis elmozdítása drámaian más
viselkedést ad, az élő rendszer törékenyebb, mint amilyennek a pontszám mutatja.

**Megközelítés**: a legjobb trial körül egy kis rácsos/véletlen perturbációs scan (pl. ±15%,
5-10 pont), és megnézni, mennyire szór a walk-forward pontszám — ha nagyon szór, a "legjobb" trial
inkább szerencse, mint stabil optimum.

**Állapot**: ✅ **LEZÁRVA (2026-08-23) — US100 robusztus, US500 törékenyebb optimum, dokumentálva.**

`research/parameter_stability_check.py`: a MOSTANI, éles US100/US500 paraméterek körül ±15%-os
véletlen perturbációs scan (20 trial szimbólumonként, MINDEN paraméter egyszerre jitterelve),
ugyanazon a teljes `FOLD_BOUNDARIES`-en, amin a hangolás eredetileg történt.

| Szimbólum | Éles pontszám | Perturbált átlag | Szórás | Relatív szórás | <70%-ra esett |
|---|---|---|---|---|---|
| US100Cash# | 75.14 | 65.11 | 10.95 | 14.6% | 4/20 (20%) |
| US500Cash# | 11.76 | 5.89 | 2.48 | 21.1% | **17/20 (85%)** |

**US100 viszonylag "lapos" (robusztus) optimum**: a szórás mérsékelt, egyetlen perturbáció sem lett
érvénytelen, a legjobb perturbáció (81.23) még a bázist is meghaladta.

**US500 ÉLESEBB (törékenyebb) optimum**: a perturbációk 85%-a a bázisérték 70%-a alá esett, a
minimum NEGATÍV lett (-2.02), a legjobb perturbáció (9.12) sem érte el a bázist (11.76). Ez
összhangban van az US500 eddig is megfigyelt vékonyabb haszonkulcsával (PF konzisztensen az
1.2-1.6-os tartományban minden eddigi mérésben, lásd P1 #5 hold-out is) — NEM új, meglepő
probléma, hanem egy MEGERŐSÍTŐ, számszerűsített jel ugyanarra a mintázatra.

**Következtetés**: US100 hangolása stabilnak tekinthető. US500-nál a paraméterek egy viszonylag
keskeny csúcs közelében vannak — érdemes ezt SZEM ELŐTT TARTANI a jövőbeli monitorozásnál (ha az
élő teljesítmény hirtelen romlana, ez segít megérteni, miért — nem feltétlenül hiba, hanem a
mögöttes optimalizálási felszín jellemzője). Nem indokol azonnali beavatkozást (US500 minden más
teszten átment), de a P3 "üzemeltetési monitoring" pontnál érdemes visszatérni rá.

### 7. Rövid adattörténet — nyitott, nem teljesen megoldható korlát

**Cél**: tudatosítani (dokumentálni, nyomon követni), hogy a validáció ~2.75 évet fed le
(2023-11-01-től, a bróker termékcsalád indulásától), és sosem tesztelődött valódi medvepiacon/
válságban/más kamatkörnyezetben.

**Miért fontos**: ez nem "hiba", amit meg lehetne építeni — a broker adattörténete fizikai korlát.
DE fontos explicit kockázatként kezelni, nem elfelejteni.

**Megközelítés**: nem javítható most — de érdemes lehet később (ha más adatforráshoz/hosszabb
történethez jutunk) újramérni, VAGY tudatosan kisebb pozícióval indítani, amíg a rendszer nem lát
át egy teljes piaci ciklust élőben.

**Állapot**: 📌 dokumentálva, nem megoldható rövid távon — figyelemmel kísérendő.

---

## P3 — Üzemeltetés, élesítés előtti utolsó lépések

### 8. Demó/élő forward-test időszak (tőke nélkül)

**Cél**: 1-3 hónapos, valós idejű (demó vagy nagyon kicsi tétes) megfigyelési időszak, mielőtt
érdemi tőke kerülne be — a backtest-előrejelzések és a valós, élő viselkedés összevetése.

**Miért fontos**: minden eddigi eredmény backtest-alapú (a Strategy Tester adatminősége is csak
37-38% valós tick). Ez a szokásos utolsó kapu bármilyen komoly kereskedési rendszernél, mielőtt
valódi pénz kerülne mögé.

**Megközelítés**: az EA MÁR éles-kész (4 komponens, lefordítva, presetek megvannak) — ez tisztán
IDŐ kérdése, nem építési feladat. Érdemes előre rögzíteni, milyen eltérést tekintenénk
"elfogadhatónak" a backtest-hez képest (pl. win-rate/PF ±X%-on belül maradjon).

**✅ Elfogadási kritériumok ELŐRE RÖGZÍTVE (2026-08-26), MIELŐTT a forward-teszt elindulna** (a
mai valós MT5/Strategy Tester/hold-out mérésekből származtatva, lásd P1 #3/#5, P2 #6):

| Szimbólum | Min. trade a kiértékeléshez | Nettó PF riasztási küszöb | Win rate elfogadható sáv | Extra megjegyzés |
|---|---|---|---|---|
| US100Cash# | 30 (a projekt szokásos megbízhatósági küszöbe) | < 1.3 esetén review | 35–65% | Robusztus (lapos) optimum — szűkebb sáv indokolt (P2 #6) |
| US500Cash# | 30 | < 1.0 (nullszaldó alatt) esetén review | 30–60% | Törékenyebb (éles) optimum (P2 #6) — SZÉLESEBB sáv indokolt, nagyobb szórás VÁRHATÓ |

**Kiegészítő szabály MINDKÉT szimbólumra**: ha a demó equity drawdown meghaladja a backtest-ben
mért max DD **kétszeresét** (US100: ~11%, US500: ~3.1%), az AZONNALI review-t indokol, függetlenül
a trade-számtól (ez nem vár meg 30 trade-et — a tőkevédelem elsőbbséget élvez a statisztikai
megbízhatósággal szemben). 30 trade ALATT bármilyen mérés csak tájékoztató jellegű, NEM vezethet
végleges döntéshez (lásd `ValidationReport.is_reliable()`, a Turnaround Tuesday tanulság).

**Időtartam**: 1–3 hónap, VAGY amíg mindkét szimbólum eléri a 30 trade-es küszöböt (amelyik előbb
következik be, de min. 1 hónap mindenképpen, hogy időbeli lefedettség is legyen, ne csak trade-szám).

**🛑 Kritikus felismerés + javítás (2026-08-26)**: a felhasználó rákérdezett, meddig tart a
bemelegedés — kiderült, hogy `RegimeFramework_EA.mq5`-ben a rezsim-osztályozó `OnNewBar()`-ja
KIZÁRÓLAG élőben, `OnTick()`-ből kapott, egyenkénti bar-okon melegedett be, `OnInit()`-ben SEMMILYEN
historikus visszatöltés nem volt. Ez azt jelentette volna, hogy egy MA felhelyezett EA-nak VALÓS,
~3 NAPTÁRI HÓNAPOT kellett volna várnia (60 kereskedési nap × M10), FÜGGETLENÜL attól, hogy a
charton már megvan a teljes 2.75 éves historikus adat — ez a teljes tervezett 1-3 hónapos
forward-teszt ablakot felemésztette volna NULLA trade-del. (FONTOS: ez NEM érinti az eddigi
backtest/Strategy Tester-eredményeket — azok több éves ablakon futottak, ahol a bemelegedés eleve
belefért, és a Python walk-forward módszertan is mindig ezt figyelembe véve, a bemelegedés UTÁN
kezdte a fold-mérést.)

**Javítás**: `OnInit()`-ben új `BackfillClassifier()` — `CopyRates()`-szel lekéri a chart már
elérhető ~8670 historikus bar-ját, és egy ciklusban azonnal betáplálja a klasszifikátorba induláskor
— a bemelegedés a chart meglévő adatával AZONNAL megtörténik, valós várakozás nélkül. Fordítás:
0 hiba/0 figyelmeztetés, mindkét helyen (projekt-mappa + élő terminál).

**Állapot**: 🔄 **kritériumok rögzítve, bemelegedési hiba javítva, a tényleges forward-teszt még
NINCS elindítva** — a demó
számlán jelenleg (2026-08-26) nincs nyitott pozíció, nincs aktivitás az elmúlt 14 napban (ellenőrizve
`mt5.positions_get()`/`history_deals_get()`-tal). Az EA-t manuálisan kell felhelyezni a megfelelő
chartokra (US100Cash#/US500Cash#, M10 időkeret) a megfelelő presettel — ez a felhasználó
következő, MT5 terminálban elvégzendő lépése.

**✅ Ütemterv rögzítve (2026-08-26): mikor fusson újra a `run_study.py`?**

*Alapelv*: a fold-szerkezet negyedéves, és a paraméter-stabilitás vizsgálat (P2 #6) megmutatta,
hogy US500-nál a "legjobb" paraméterek elmozdulhatnak új adattal — de túl gyakori újrahangolás
zajra illesztene. Naptári ütemezés + esemény-alapú kiváltó okok kombinációja:

1. **Rendszeres, negyedéves**: legközelebb **~2026. október 1. után** (amint a 2026 Q3 [júl-szept]
   adat teljesen lezárt — ez a `2026-07-01–2026-10-01` fold, amit a mostani hangolás még nem
   látott), utána minden negyedév elején (jan/ápr/júl/okt). Minden futtatásnál: `END_DATE`
   bővítése a legfrissebb dátumig, US100/US500-ra (US30 opcionálisan, monitorozásra, élesítés
   nélkül), MAJD a P1 #5-ös hold-out fegyelem MEGISMÉTLÉSE (utolsó ~2-3 hónap kihagyása a
   hangolásból, csak utána egyetlen ellenőrző futtatás rajta) — ez legyen ÁLLANDÓ gyakorlat,
   nem egyszeri lépés.
2. **Esemény-alapú, azonnali**: ha a fenti P3 #8 elfogadási kritériumok bármelyike sérül élőben/
   demón (US100 nettó PF<1.3, US500 nettó PF<1.0, vagy DD > a backtest max DD kétszerese), VAGY
   ha bróker-oldali változás történik (spread/margin/kontraktus-specifikáció módosul).
3. **Mit NE**: ne fusson hetente/havonta "csak hogy lássuk" — a 30 trade-es megbízhatósági küszöb
   és a törékeny (US500) optimum miatt túl kevés új adat között a "legjobb" paraméter inkább
   zajt, mint valódi javulást találna.

### 9. Üzemeltetési/monitoring infrastruktúra

**Cél**: riasztás (pl. Telegram/email), ha az EA leáll, egy megbízás elutasításra kerül, a
VPS/kapcsolat megszakad, vagy a rezsim-osztályozó bemelegítése valamiért újraindul.

**Miért fontos**: jelenleg semmilyen automatikus felügyelet nincs — egy csendes leállás vagy
elakadás észrevétlen maradhatna napokig.

**Megközelítés**: MQL5-ben egy egyszerű "heartbeat" + hibakezelés (pl. `OrderSend` hiba esetén
explicit log + push notification `SendNotification()`-nel), és egy külső (nem az EA-n belüli)
figyelő, ami jelez, ha nem kap friss heartbeat-et.

**✅ Állapot: LEZÁRVA (2026-08-26) — megépítve, fordítva, smoke teszttel megerősítve.**

**EA-oldal** (`RegimeFramework_EA.mq5`): minden ÚJ M10-baron (`OnTick()`, a warmup ALATT is)
`WriteHeartbeat()` egy közös (`FILE_COMMON`), terminál-független fájlba írja: szerver idő, utolsó
feldolgozott bar ideje, heartbeat-számláló, rezsim-osztályozó `IsReady()` állapota, nyitott
pozíciók száma, kereskedési hiba-számláló + utolsó hibaüzenet, equity/szabad margin. Két szintű
hibakezelés: `NotifyTradeError()` (belépés/zárás sikertelenségnél — PUSH értesítést is küld
`SendNotification()`-nel, mert ezek ritkák és kritikusak) vs. `LogTradeError()` (trailing stop
módosítás sikertelenségénél — csak log+számláló, PUSH NÉLKÜL, mert ez gyakori/ártalmatlan okokból
[pl. "nincs változás"] hibázhat minden baron, és telefon-spam lenne). Fordítás: 0 hiba/0
figyelmeztetés, mindkét helyen (projekt-mappa + élő terminál).

**Külső figyelő** (`monitoring/heartbeat_watchdog.py`, ÚJ modul, NEM igényel MT5-kapcsolatot,
csak a közös Files mappa elérését): beolvassa az ÖSSZES `RegimeFramework_heartbeat_*.txt` fájlt,
és jelez, ha (1) STALE — a fájl 30 percnél (3× M10 bar-idő) régebbi (VPS/terminál/EA-leállás
gyanúja — de hétvégén/piaci zárás idején ez VÁRHATÓ, a kimenet ezt jelzi is), (2) HIBA —
`trade_error_count > 0`. Kilépési kód 0/1 (scheduláláshoz/scriptezéshez). Smoke teszttel
megerősítve (friss/elavult/hibás szintetikus heartbeat-fájlokkal).

**⚠️ Amit a felhasználónak KELL tennie, hogy ez ÉLESBEN is működjön** (ez nem oldható meg
kódból/távolról):
1. **Push értesítések bekapcsolása**: MT5 Terminal → Eszközök → Beállítások → Értesítések fül —
   MetaQuotes ID megadása + a MetaTrader mobil app párosítása. E nélkül a `SendNotification()`
   csendben, hibaüzenet nélkül nem csinál semmit.
2. **`heartbeat_watchdog.py` ütemezése**: pl. Windows Feladatütemezővel, 15-30 percenként — ez a
   MÁSODIK, FÜGGETLEN védelmi réteg arra az esetre, ha maga a terminál/VPS/EA teljesen leáll (amikor
   a `SendNotification()` már nem tud lefutni). A script kilépési kódja (`if errorlevel 1`)
   köthető egy saját értesítési csatornához (pl. e-mail/Telegram), ha ezt a felhasználó akarja —
   ehhez hitelesítő adatok/beállítás kellenének, amit én nem tudok helyette elvégezni.
3. **Első valós ellenőrzés**: amint az EA fel van helyezve egy chartra, érdemes egyszer manuálisan
   lefuttatni a `heartbeat_watchdog.py`-t, hogy lássuk, a heartbeat-fájl valóban a várt formátumban
   íródik-e (ezt én csak szintetikus fájllal tudtam tesztelni, MT5-chart nélkül).

**✅ Önálló `.exe` a VM/VPS-es telepítéshez (2026-08-26)**: mivel a `heartbeat_watchdog.py`
KIZÁRÓLAG beépített Python-modulokat használ (nincs `regime_framework`/MT5-függőség), PyInstaller-
rel egyetlen, Python-telepítést NEM igénylő futtatható fájllá csomagolható —
**`dist/RegimeFramework_HeartbeatWatchdog.exe`** —, ez lefuttatva megerősítetten helyesen működik
(a valós Windows `%APPDATA%` útvonalat helyesen olvassa, hiányzó heartbeat-fájl esetén a várt
figyelmeztetést adja, kilépési kód 1). A VM-re/VPS-re ELÉG ezt az egy `.exe`-t átvinni a
monitoringhoz (a Python-forrás/telepítés nem szükséges ott) — újrafordításhoz (ha a script
változik): `pip install pyinstaller`, majd `python -m PyInstaller --onefile --name
RegimeFramework_HeartbeatWatchdog regime_framework/monitoring/heartbeat_watchdog.py`.

---

## Összefoglaló táblázat

| # | Pont | Prioritás | Állapot |
|---|---|---|---|
| 1 | Költség az Optuna célfüggvényben | P0 | ✅ TELJESEN LEZÁRVA |
| 2 | Swap/finanszírozási költség vizsgálata | P0 | ✅ LEZÁRVA (elhanyagolható) |
| 3 | Kockázat-alapú pozícióméretezés | P1 | ✅ LEZÁRVA — margin-alapú ÉLESBEN US500-ra, US100/US30 marad fix lotos |
| 4 | Portfólió-szintű vészfék | P1 | ✅ LEZÁRVA — mindkét vizsgált mechanizmus elvetve (nem éri meg / look-ahead) |
| 5 | Valódi hold-out validációs időszak | P1 | ✅ LEZÁRVA — US100/US500 megerősítve, US30 megbukott |
| 6 | Paraméter-stabilitás vizsgálat | P2 | ✅ LEZÁRVA — US100 robusztus, US500 törékenyebb (dokumentálva) |
| 7 | Rövid adattörténet | P2 | 📌 dokumentálva |
| 8 | Demó/élő forward-test | P3 | 🔄 kritériumok rögzítve, indítás hátravan |
| 9 | Üzemeltetési monitoring | P3 | ✅ LEZÁRVA — heartbeat+hibakezelés+watchdog megépítve, felhasználói lépések hátravannak |

Frissítve: 2026-08-26.
