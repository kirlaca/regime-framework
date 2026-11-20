# Regime Framework — tervdokumentum

**Státusz:** tervezési fázis, kód még nincs.
**Kapcsolódó, változatlanul megőrzött referencia-kód:** `main_optuna_anomaly.py`, `main_optuna_hybrid.py`,
és a hozzájuk tartozó összes validációs script (`regime_analysis.py`, `regime_conditional_backtest.py`,
`trend_leg_validation.py`, `turnaround_tuesday_validation.py`, `fold_trade_breakdown.py`,
`cross_fold_validation.py`, `spread_timeframe_analysis.py`, `timeframe_strategy_comparison.py`). Ezeket
**nem módosítjuk** — történeti/referencia anyagként megmaradnak, a bennük megtanult leckéket viszont
átvisszük ide.

---

## 0. Cél

Egy olyan rendszert kell építeni, amely **felméri a piaci helyzetet, és ez alapján dönt arról, melyik
komponens vezérelje éppen a kereskedést**. Ebből három, nem alkuképes tervezési követelmény következik:

1. **A komponensek és a réteg-szűrők (rezsim-osztályozók) önállóan tesztelhetők.** Egyik sem
   feltételezheti a másik jelenlétét ahhoz, hogy validálható legyen — egy komponens fix,
   rögzített piaci-állapot bemenettel is tesztelhető kell legyen, a rezsim-osztályozók pedig
   komponens nélkül, önmagukban (ahogy a `regime_analysis.py`/`regime_conditional_backtest.py`
   már most is teszi).
2. **A validáció a komponens/osztályozó szerves (inside) része, nem külső, utólagos script.**
   Minden komponens és minden réteg saját `validate()` metódussal bizonyítja a működését, mielőtt
   a főprogramba (`Engine`) bekötnénk — a validáció nem opcionális kiegészítés, hanem a
   "plug-and-play" szerződés kötelező eleme.
3. **Az MT5/MQL5 portolhatóság mindvégig, folyamatosan szem előtt tartandó szempont** — nem a végén
   megoldandó feladat. Lásd a 0.1 alpontot.

A lenti terv minden további pontja ennek a célnak van alárendelve.

### 0.1 Állandó szempont: MT5/MQL5 portolhatóság

Ezt a fejlesztés VÉGÉN már nem lehet olcsón pótolni — ha elfelejtjük útközben, káosz lesz belőle. Ezért
minden komponens/osztályozó tervezésekor explicit ellenőrizni kell az alábbiakat:

1. **Éles logika és kutatási logika szigorúan elváljon.** A `check_entry`/`check_exit` (és a hozzájuk
   szükséges indikátor-számítás) legyen minden komponensben olyan minimális, önmagában értelmezhető
   logika, ami elvben egy az egyben MQL5 osztályra fordítható (az MQL5 is támogat osztályokat,
   öröklődést, virtuális függvényeket). A `validate()`, az Optuna-objective és a walk-forward keret
   **sosem** megy élesbe — ezek maradhatnak tetszőlegesen Python-specifikusak, ez a modularitás
   természetes velejárója, nem külön munka.
2. **Indikátor-számítási mód tudatos dokumentálása.** Ha egy indikátort (pl. ATR) egy adott módszerrel
   számolunk (pl. egyszerű, nem Wilder-simított mozgóátlag), ezt a komponens kódjában/docstringjében
   rögzíteni kell — az MQL5 beépített függvényei (pl. `iATR()`) más módszert használhatnak, és ez már
   egyszer valós eltérést okozott az `AnomalyMeanReversion_EA.mq5` portolásakor.
3. **Ne épüljön be a stratégia-logikába Python/backtest-only mechanizmus.** Pl. a pesszimista SL/TP-
   feloldás (melyik sérül előbb egy gyertyán belül) egy backtest-specifikus közelítés — élőben a bróker
   valódi stop-megbízása dönt. A komponens `check_exit`-je ne feltételezzen ilyen backtest-csak
   viselkedést kőbe vésett szabályként.
4. **A paraméterek Optuna-ból "kész számokként" mennek át MQL5 `input` alapértékként** — maga a
   keresési folyamat nem portolódik, csak az eredménye.
5. **Minden komponens, ami eljut az EA-szintig, kötelezően újramegerősítendő az MT5 Strategy
   Testerében** — egy strukturálisan hű port sem garantáltan viselkedés-azonos a Python-verzióval.
   Portolhatóság (működik-e szerkezetileg) és validitás (van-e valós éle) két külön kérdés — az egyik
   megléte nem bizonyítja a másikat.

---

## 1. Miért egy új, önálló package?

A `main_optuna_anomaly.py` egyetlen nagy függvénybe (`simulate_trades`) zsúfolta a teljes kereskedési
logikát, szétszórt lokális állapot-változókkal (`rebalance_taken_today`, `tuesday_taken_today`,
`trend_extreme` stb.). Ez működött egyetlen, előre rögzített stratégia-kombinációra, de nem alkalmas
arra, amit most akarunk: **komponenseket önállóan kivenni, hangolni, cserélni**, miközben a vezérlés
(a "főprogram") univerzális marad.

**Alapelv:** a komponensek és a rezsim-osztályozók külön osztályok, külön tesztelhetők, és csak
**már bizonyítottan működő ("bereszelt") állapotban** kötjük be őket a főprogramba. A főprogram maga
sosem tartalmaz stratégia-specifikus logikát.

---

## 2. Amit a korábbi munkából tudunk (empirikus alap)

Ezt a szakaszt élő tudásbázisként kezeljük — bővítjük, ahogy új komponenseket validálunk.

| Megállapítás | Forrás | Következmény az új architektúrára |
|---|---|---|
| Az ADX szűk sávban mozgott mindkét eddig tesztelt indexen (US500: 35.13-36.83, US100: 35.71-36.51, fold-onként) | `regime_analysis.py` | Egyetlen abszolút ADX-küszöb nem ad erős megkülönböztetést → kell egy **relatív (percentilis-alapú)** volatilitás-dimenzió is, ne csak trend-erősség |
| A MeanReversion oldalazó napokon nyereséges (42.9% win-rate, +60.34 PnL), trendelőn veszteséges (25.4%, -166.97 PnL) | `regime_conditional_backtest.py` | Az egyetlen eddig **ténylegesen validált** komponens-jelölt — ez lesz a Komponens A kiindulása |
| Az EODRebalancing **minden** eddigi tesztben veszteséges volt, minden rezsimben, fix ÉS tanult paraméterekkel is | `fold_trade_breakdown.py`, `trend_leg_validation.py` | Nem viszünk át automatikusan — ha visszakerül, saját validációval kell újra bizonyítania magát |
| A TurnaroundTuesday csak 8 valódi független eseményt ad ~19 hónap alatt, 50% win-rate, paraméter-érzékeny (előjelet vált) | `turnaround_tuesday_validation.py` | Statisztikailag nem megbízható jelölt jelenlegi formájában — vagy elvetjük, vagy több adatra/instrumentumra összevonva kellene újramérni |
| Donchian-kitörés 3 független tesztben is bukott (profit factor <1, ~0.4 napos átlag tartás); EMA-keresztezés validált, szerény, valós élt mutatott elszigetelten, de a teljes rendszerbe építve semleges/enyhén negatív hatású volt US500-on ÉS US100-on is | `trend_leg_validation.py`, teljes walk-forward futások | A "komponens önmagában jó" NEM garantálja, hogy a teljes rendszerben is jó — ezt a validáció-rétegnek külön kell kezelnie (lásd 6. pont) |
| A "validálj fixen, MIELŐTT Optunára bíznád" fegyelem minden alkalommal kifizetődött (költség-paraméterek, trend-paraméterek) | Az egész eddigi folyamat | Ez a `validate()` metódus **kötelező** része lesz minden komponensnek, nem utólagos ellenőrzés |
| Kis mintaelemszámú (Fold 1, ~14000 bar) tanítóablakok konzisztensen rosszabbul általánosítottak | `cross_fold_validation.py` | A walk-forward keretnek figyelmeztetnie kell, ha egy fold tanítóablaka túl kicsi |
| Háromszög-kitörés (volatilitás-squeeze utáni irányított kitörés folytatódása) NEM mutat élt — 27 (szimbólum×squeeze-hossz×horizont) kombinációból csak 1 lépte át a |z|>=2 küszöböt, statisztikailag ennyi hamis pozitívat a véletlen is termelne | `research/triangle_squeeze_breakout_check.py` (2026-08-21) | Ugyanoda jutott, mint a Donchian-kitörés és a box-trading — ezeken az M10-es US-indexeken a "kitörés folytatódik" jellegű ötletek konzisztensen buknak; a teljes trendvonal-geometria (swing-pont detektálás, regresszió) NEM indokolt erre az alapra |
| US500/US30-on VALÓDI, erős rövid-távú (q=2-5 bar, ~20-50 perc) negatív autokorreláció van a hozamokban (variance ratio permutációs teszt, z=-4-től -7-ig), DE egy konkrét fade-szabály nettó profit factora mind a 27 tesztelt paraméter-kombinációban <1.0 — a spread felemészti. **Megerősítve**: a `tick_volume` alapú LOW/HIGH aktivitás-bontás kimutatta, hogy a hatás KONZISZTENSEN erősebb LOW aktivitáson mindhárom szimbólumon — ez definitív, adatokkal alátámasztott bizonyíték a bid-ask-bounce magyarázatra (nem csak elméleti sejtés) | `research/variance_ratio_scan.py` + `research/short_horizon_reversal_check.py` + `research/tick_volume_activity_check.py` (2026-08-21) | A jelenség STATISZTIKAILAG valódi, BIZONYÍTOTTAN Roll-féle bid-ask-bounce mikrostruktúra-effektus — GAZDASÁGILAG nem kiaknázható ezen a granularitáson/spread-en; NEM építünk rá komponenst, de érdemes újramérni, ha alacsonyabb spread-ű számlához/tick-adathoz jutunk |
| A puszta rezsim-átmenet pillanata (`trend_band` RANGING/TRANSITIONAL→TRENDING) NEM hordoz plusz előrejelző erőt — egyik szimbólumnál, egyik horizonton (12-96 bar) sem érte el a |z|>=2 küszöböt | `research/regime_transition_signal_check.py` (2026-08-21) | A TrendFollowing saját (EMA+RSI+Bollinger) szűrése marad az egyetlen bizonyított belépési logika a TRENDING rezsimhez — nincs korábbi/kiegészítő trigger a puszta átmenetben |
| Péntek 23:00-00:00 (szerveridő, ~NYSE-zárás) SHORT valódi, önálló komponens-jelölt — mindhárom US-szimbólumon nettó PF>1, ÉS egy szűk, csak erre a slotra vonatkozó napi-kvóta-kivétellel a trade-szám 5x-re nő az integrált rendszerben (13→61/26→67/29→72), a MeanReversion/TrendFollowing/LastHourContinuation trade-számának érintetlenül hagyása mellett | `research/day_hour_seasonality_scan.py` + `day_hour_confirmatory_check.py` + `friday_short_engine_conflict_check.py` + `friday_short_quota_exception_check.py` (2026-08-21) | **✅ TELJESEN MEGÉPÍTVE (2026-08-21/22)**: `FridayShortComponent` + Engine `quota_exempt_time_gated_components` + MQL5-port + Optuna-hangolás (pontszám 78.61→84.95 / 6.59→11.38 / 23.91→30.30) — lásd 8. szakasz és SESSION_LOG.md. Strategy Tester-es megerősítés MÉG HÁTRAVAN. |
| TaiwanCash-en (`optuna_research` workspace, saját stratégia-kísérlet) a lookback=100 bar/hold=20 bar idősoros momentum-jel statisztikailag VALÓDI (permutációs szignifikancia-teszt, z=6.33), DE egyetlen tesztelt percentilis-alapú (0-95) szelektivitási küszöbbel sem éri el a walk-forward kockázat-korrigált pontszáma a nullát (legjobb: 90. percentilis, score=-11.72, 3/11 pozitív fold) — a teljes-mintás aggregált teszt (nettó PF 0.97) csak azért tűnt majdnem nyereségesnek, mert a küszöböt visszamenőlegesen, a teljes időszakra számolta, ami a korai fold-okba szivárogtatott jövőbeli információt | `research/taiwan_variance_ratio_scan.py` + `taiwan_variance_ratio_fine_scan.py` + `taiwan_simple_momentum_significance_test.py` + `taiwan_momentum_prototype_backtest.py` + `taiwan_momentum_threshold_filter_test.py` + `taiwan_momentum_threshold_walkforward_grid.py` (2026-09-03) | A statisztikai szignifikancia és a kereskedhető, walk-forward-konzisztens él KÖZÖTT szakadék van — ez a KONKRÉT (lookback=100/hold=20, percentilis-küszöb) konstrukció NEM életképes; más lookback/hold pár vagy más mechanizmus (pl. Kalman/HP-szűrő) próbálandó, DE a walk-forward-öt a küszöb-/paraméter-választás RÉSZÉNEK kell tekinteni a kezdetektől, nem utólagos ellenőrzésnek (lásd JP225Cash ugyanezen a napon tapasztalt, azonos hiba-osztálya) |
| **🚫 XM bróker kereskedési feltételei (különösen a részvény-CFD overnight swap-szerkezete) NEM HASZNÁLHATÓK a többnapos tartású, statisztikai (mean-reversion/momentum) megközelítéshez.** Az US100/US30 top-részvényeken (7+82+29 jelölt, Nasdaq-100 ÉS Dow30 teljes villámszűrése, walk-forwarddal is megerősítve) EGYETLEN kombináció (mechanizmus × irány × horizont × index) sem érte el a pozitív kockázat-korrigált nettó pontszámot. Websearch-alapú összevetés kimutatta, hogy az XM implikált admin-felára (~±5%) 1.7-3.3x magasabb, mint a piac élvonalbeli brókereié (IBKR ±1.5%, CMC ±2.5%, IG ±3%), ÉS az XM SHORT-oldala SOSEM fizet jutalmat (szemben a reputable brókerekkel, ahol magas kamatkörnyezetben ez pozitív is lehet) | `research/us100_full_index_flash_screening.py` + `us30_full_index_flash_screening.py` + `us100_stocks_meanrev_walkforward_confirm.py` + a 2026-09-04-i bróker-összevetés (SESSION_LOG.md) | **DÖNTÉS (felhasználó, 2026-09-04): az XM bróker KIZÁRVA a további (többnapos tartású, statisztikai) kutatásból.** Ez NEM érinti a MEGLÉVŐ, élesben futó M10-es index-CFD production rendszert (US100/US500/US30 — ott nincs multi-napos swap-kitettség, minden pozíció napon belül zár). A következő irány: IC Markets (EU) demó-számla ellenőrzése (kedvezőbb, sőt SHORT-oldalon pozitív swap-szerkezet, MT5-kompatibilis) — lásd SESSION_LOG.md |

### 2.1 Session-fázis empirikus mérés (2026-08-19)

Az első `research/session_phase_exploration.py` futás (M10 idősík, ~19 hónap, 5 index-jelölt: US100,
US500, JP225, GER40, EU50 — mind az öt szimbólumnév stimmelt) óránkénti ATR/spread/irány-torzítás
bontást adott. **Három, egymástól élesen elkülönülő "session-alak" rajzolódott ki:**

| Csoport | Kiugró órák (ATR-arány ≥1.3x) | Értelmezés |
|---|---|---|
| US100, US500 | 17-21 (US500-nál 22-ig) | Egyetlen blokk — amerikai piacnyitás. Egybevág a régi kódban eddig is használt `is_american_session` (16:30-21:00) feltevéssel — most empirikusan is megerősítve. |
| JP225 | 3-5 | Teljesen más idősáv — saját (japán) piacnyitás. |
| GER40, EU50 | 11-12 ÉS 17-18 (kettős csúcs) | Saját (európai) nyitás + az amerikai nyitás átfedő hatása — két külön ablak. |

**Következmény:** a session-fázisok NEM univerzálisak, hanem piac-specifikusak — a
`SessionPhaseClassifier`-nek instrumentum- (vagy piac-csoport-) függő konfigurációt kell kapnia,
nem egyetlen, mindenre ráhúzott órahatárt.

**Egy korábbi feltevést módosító megfigyelés:** a spread nem 22:00-nál (amit korábban
`ROLLOVER_HOURS = {22}`-ként feltételeztünk US-indexekre a régi kódban), hanem GER40-nél és EU50-nél
a **23:00-ás órában** ugrik meg drasztikusan (GER40: 2.06→8.08, EU50: 1.65→5.66) — US100/US500-nál a
havi átlagban nem látszik ilyen éles spread-tágulás sem 22-nél, sem 23-nál. A rollover-óra tehát
szintén instrumentum-függőnek tűnik.

**Adatminőségi óvatosság:** a 0. óra US100/US500-nál csak ~210 bar-on alapul (a többi óra ~2436-tal
szemben) — valószínűleg csak az adatsor szélén lévő töredék-nap műterméke, ne építsünk rá.

**Stabilitás-ellenőrzés (két félidő összevetve) — MIND AZ 5 instrumentum stabilnak bizonyult:**

| Szimbólum | Korreláció | Jaccard | Megjegyzés |
|---|---|---|---|
| US100 | 0.977 | 0.67 | mag-órák (17-20) mindkét félidőben, a szélek (21-22) ingadoznak |
| US500 | 0.979 | 0.75 | mag-órák (17-21) mindkét félidőben |
| JP225 | 0.855 | 0.50 | leggyengébb, de még pozitív — mag (3-4) stabil, szélek (5, 18) ingadoznak |
| GER40 | 0.945 | **1.00** | tökéletes egyezés — [11,12,17,18] mindkét félidőben azonos |
| EU50 | 0.970 | **1.00** | tökéletes egyezés — [11,12,17,18] mindkét félidőben azonos |

Ezzel a 2.1 szakasz korábbi három session-alaka (US-blokk / JP225-sáv / GER40-EU50 kettős-csúcs)
**nemcsak aggregáltan, hanem időben stabilan is megerősített** — bizalommal átvihető kézzel írt
konfigba a `SessionPhaseClassifier`-hez. Célszerű a "mag"-órákat (amik mindkét félidőben megjelentek)
a fázis biztos részének tekinteni, a csak egyik félidőben megjelenő "szél"-órákat pedig puffer-
zónaként kezelni, nem éles határként.

**✅ MEGÍRVA ÉS VALIDÁLVA (2026-08-19):** a `regime/session_phase.py` `SessionPhaseClassifier`-e
elkészült a fenti konfiggal, és a `validation/validate_session_phase.py` mind az 5 szimbólumon
**figyelmeztetés nélkül** validált valós adaton:

| Szimbólum | opening_vs_core_ratio | rollover_vs_core_spread_ratio |
|---|---|---|
| EU50 | 1.48 | 3.34 |
| GER40 | 1.61 | 2.71 |
| JP225 | 1.52 | — (nincs rollover a csoportban) |
| US100 | 1.94 | — (nincs rollover a csoportban) |
| US500 | 1.95 | — (nincs rollover a csoportban) |

Ez a réteg lezártnak tekinthető a `main.py` bekötéséig — a build-sorrend (6. pont) 2. lépése kész,
következik a 3. lépés: `regime/market_condition.py`.

**Egy módszertani hiba, amit menet közben találtunk és javítottunk:** az első verzió M5 idősíkot
kért, ami "Invalid params" hibát adott ezen a szimbólumon/brókeren ilyen hosszú (~19 hónapos)
visszamenő tartományra — feltehetően nincs ilyen mélységű M5 historikus adat elérhető. M10-re
váltva (ugyanaz, amit a `main_optuna_anomaly.py` is használ) működött. **Tanulság:** ha egy MT5
lekérés "Invalid params"-szal hasal el, először a TIMEFRAME/tartomány kombinációt érdemes
gyanúsítani, nem a szimbólumnevet vagy a kapcsolatot.

### 2.2 Market-condition (2. réteg) empirikus mérés és a `MarketConditionClassifier` (2026-08-19)

A régi kód egyetlen, abszolút `AdxRangingThreshold`-ja helyett a 2. réteg mindkét dimenzióját
(trend-erősség ÉS volatilitás) **gördülő percentilis-ranggá** alakítottuk (~60 kereskedési nap,
8640 bar M10-en): "az elmúlt N bar között hol áll a jelenlegi ADX/ATR". Ez eredendően
instrumentum-független és look-ahead-mentes.

Rács: trend_percentile tercilis vágással (RANGING <0.33 / TRANSITIONAL 0.33-0.67, szándékos
"ne kereskedj" whipsaw-zóna / TRENDING >=0.67), vol_percentile medián vágással (LOW/HIGH,
automatikusan kiegyensúlyozott, mert már maga is percentilis).

**A `research/market_condition_exploration.py` mérése mind az 5 indexen kivételesen konzisztens
eredményt adott** (~45-47 ezer bar/szimbólum, a gördülő ablak miatti veszteség után):
- **Cella-gyakoriság:** minden cella 12.3-21.1% között, egyik sem ritka.
- **Perzisztencia:** medián futamhossz **pontosan 8 bar mindegyik szimbólumnál** — nem véletlen
  egyezés, hanem a percentilis-rang transzformáció + az ablakhossz jellemzője, nagyrészt
  instrumentum-független.
- **Stabilitás:** a trend-sáv arányok félidők közötti eltérése mindenhol ≤2.2 pont.

**✅ MEGÍRVA ÉS VALIDÁLVA:** a `regime/market_condition.py` `MarketConditionClassifier`-e — mivel
a percentilis-rang eredendően instrumentum-független, ez **UNIVERZÁLIS osztályozó**, NEM
instrumentum-csoportos konfig (ellentétben a `SessionPhaseClassifier`-rel). A
`validation/validate_market_condition.py` mind az 5 szimbólumon **figyelmeztetés nélkül**
validált.

**Nyitott pont a jövőre (nem blokkoló):** a `classify_series()` batch (pandas `.rolling()`)
implementáció — jó backteszthez/validációhoz, de élő kereskedéshez egy gördülő puffer alapú,
bar-onkénti streaming verzió kell majd (lásd PLAN.md 0.1, MT5 portolhatóság). Ezt szándékosan NEM
építjük meg most, amíg nincs kész `core/engine.py`, ami ténylegesen igényelné.

A build-sorrend (6. pont) 3. lépése is KÉSZ.

### 2.3 ⚠️ PROJEKTSZINTŰ KORLÁT: a historikus adatmélység határa (2026-08-19)

A `research/data_history_check.py` fokozatos próbálkozással (2018/2020/2021/2022/2023/2024/2025-ös
kezdő dátumokkal) tesztelte, meddig nyúlik vissza a ténylegesen elérhető M10 adat. Az eredmény
**egyértelmű és mind az 5 szimbólumnál azonos**: minden 2018-2024 közötti kezdő dátum "Invalid
params" hibával elhasal, **kizárólag a 2025-01-01-től kért adat sikerül**, mindegyiknél
2025-01-02-től kezdődően.

**Ez fiók-/platform-szintű korlát, nem instrumentum-tulajdonság** — ha instrumentum-specifikus
lenne, nem esne pontosan egybe mind az 5, egymástól független index-jelöltnél. Feltehetően a
jelenlegi (demó?) fiók adatmegőrzési szabálya.

**Következmény, amit a jövőben mindig szem előtt kell tartani:** a "range bővítés kockázat vs.
előny" korábbi elméleti megbeszélés (lásd a beszélgetés-történetet) jelenleg **tárgytalan** — nincs
mit bővíteni, a jelenlegi ~19 hónapos ablak (2025.01-2026.08) gyakorlatilag a teljes elérhető
történelem. Ez azt jelenti, hogy **minden eddigi és jövőbeli stabilitás-ellenőrzésünk egyetlen,
folytonos makro-időszakon belül történik** — nem tudjuk tesztelni, hogy a talált mintázatok
(session-fázisok, market-condition rács) más piaci rezsimben (pl. eltérő kamatkörnyezet,
válság-időszak) is tartanák-e magukat. Ha valaha élő/demó számlát váltunk, vagy más adatforráshoz
férünk hozzá, érdemes újra megmérni.

**Mellékes, valószínűleg ártalmatlan megfigyelés:** a GER40/EU50-nél talált hézagok (április közepe,
december vége, április eleje) egybeesnek a tipikus európai tőzsdei ünnepekkel (húsvét, karácsony/
újév) — mivel US100/US500/JP225-nél UGYANEZEKEN a dátumokon nincs hézag, ez valós piaci
zárvatartásra utal, nem adatminőségi hibára.

### 2.4 IC Markets vs XM — a hármas index-összevetés lezárva, mindhárom index javult (2026-09-05)

XM-en a kereskedési feltételek (lásd SESSION_LOG.md 2026-09-04, "BRÓKER-ÖSSZEVETÉS") miatt a
többnapos statisztikai kutatás ki lett zárva, de a jelenlegi ÉLES M10-es
index-CFD rendszert (nincs swap-kitettség, minden ugyanaznap zár) ez nem érinti — a felhasználó
felvetette, érdemes-e emiatt magát az éles rendszert is máshova költöztetni. Az összevetés a
production Optuna célfüggvénnyel (`optimization/objective.py`), a jelenlegi 3 index-jelölten,
melegindított (`enqueue_trial()` a már XM-en hangolt paraméterekkel + 200 trial) újrahangolással:

| Index | XM saját pontszám | IC Markets (melegindított) | Javulás |
|---|---|---|---|
| US30 | 10.71 | **40.89** | ~4x |
| US500 | 11.76 | **13.81** | ~1.17x (mind a 11 fold nettó pozitív) |
| USTEC | 75.14 | **91.03** | ~1.21x (mind a 11 fold nettó pozitív, monoton növekvő equity) |

**Mindhárom index javult, egyik sem romlott.** Módszertani tanulság útközben: egy NEM
melegindított (véletlen TPE-seedelt) 60 trial-os keresés önmagában nem elég egy ~20+ dimenziós
térben, hogy megbízhatóan megtalálja a valódi felső korlátot (lásd US30: egy nem melegindított
keresés 11.78-at adott, rosszabbat, mint a puszta XM-paraméter-transzfer 21.62-je) — a
paraméter-VÁLASZTÁST is walk-forward-alapon, ELÉG keresési büdzsével (vagy melegindítással) kell
végezni, nem csak a végső validációt.

**Nyitott döntés** (a felhasználó terve szerint): a végleges migráció-döntés a teljes
vizsgálatsorozat (a részvény-kutatás is) lezárása után esedékes, nem csak ez alapján.

### 2.5 ⚠️ PROJEKTSZABÁLY: Optuna trial-szám minimum 200, sose 60 (2026-09-05)

A 2.4-ben leírt US30 melegindítás egy általánosabb, minden jövőbeli Optuna-hangolásra (KUTATÁS ÉS
ÉLES egyaránt) érvényes módszertani szabályt fed fel: **egy NEM melegindított, 60 trial-os keresés
ebben a ~15-20 dimenziós paraméctérben NEM megbízható** — konkrét bizonyíték: US30-on egy friss
60 trial-os keresés 11.78-at adott, ROSSZABBAT, mint a puszta (semmilyen keresés nélküli)
paraméter-transzfer (21.62), miközben UGYANAZ a keresési tér 200 trial-lal (vagy melegindítással)
40.89-et ér el — majdnem a négyszeresét.

**Szabály, felhasználóval megerősítve (2026-09-05, "ez legyen projekt szabály? az élesben is ez
kell majd")**:
1. Minden Optuna hangolás alapértelmezett trial-száma **legalább 200** — a korábbi 60-as érték
   mostantól TILOS alapértékként (lásd `optimization/run_study.py` `DEFAULT_N_TRIALS`, javítva
   2026-09-05-én 60→200-ra). Ha egy konkrét futtatásnál mégis kevesebb indokolt (pl. gyors
   villámteszt/prototípus, NEM végleges paraméter-választás), azt EXPLICIT `--trials` érvvel,
   dokumentált indoklással kell kérni, sose hallgatólagos alapértékként.
2. Amikor egy már ismert, korábban validált paraméterkészlet létezik ugyanarra vagy egy rokon
   piacra (pl. brókerváltás ugyanazon instrumentumon), azt `optuna.Study.enqueue_trial()`-lal
   ÉRDEMES a keresés első pontjaként megadni (melegindítás) — ez NEM helyettesíti a 200-as
   minimumot, hanem KIEGÉSZÍTI.
3. **ÉLESRE IS ÉRVÉNYES** — lásd `docs/LIVE_PROJECT_TODO.md` 3. pontja: ha az élő projekt saját
   Optuna-hangoló scriptje is 60-as (vagy alacsonyabb) alapértéket használ, azt is 200-ra kell
   emelni, mielőtt bármilyen új paraméter-hangolást élesben elfogadnánk.

### 2.6 IC Markets részvény-CFD-k: fix ~$0,01-es spread-padló, NEM az ár számít (2026-09-06)

Empirikus mérés (`research/icmarkets_stocks_spread_comparison.quick_spread_check()`) megmutatta:
IC Markets US részvény-CFD-inél sok likvid mega-cap (Ford, AT&T, Pfizer, BAC, Cisco, Intel, AAPL,
NVDA) átlagos spreadje PONTOSAN $0.01 — egy fix minimum-spread-padló, ami NEM csökken az árral.
**Következmény: az olcsó, alacsony-volatilitású blue-chipeknél (kis abszolút dollár-mozgás
gyertyánként) a fix padló ARÁNYOSAN sokkal nagyobb teher** (Ford 21.92%, AT&T 15.55%, Pfizer
17.37% spread/bar-range), **mint a drágább/volatilisebb részvényeknél** (AAPL 1.12%, Intel 1.19%,
NVDA 1.21%), ahol a nagyobb abszolút gyertya-mozgás feloldja ugyanazt a fix költséget. **A helyes
szűrési szempont jövőbeli részvény-kutatásnál: abszolút dollár-gyertya-mozgás mérete a ~$0.01-es
padlóhoz képest, NEM az árszint.** (MPWR/MS ettől független, külön eset: náluk a spread a padló
FÖLÖTT van, valódi, piac-vezérelt szélesebb spread — lásd 2026-09-05/06 SESSION_LOG bejegyzések.)

Emellett kiderült egy eddig NEM modellezett valós költség: IC Markets $0.02/részvény jutalékot
számol fel NASDAQ/NYSE részvény-CFD-knél (ASX-en 0.10%) — a jelenlegi 0.1-es lot-mérettel
elhanyagolható (~$0.002/oldal), de nagyobb pozícióméretezésnél (pl. `RiskBasedSizer`) számításba
veendő.

### 2.7 ⚠️ MÓDSZERTANI VAKFOLT: a walk-forward pontszám nem bünteti az intra-fold drawdown mélységét — SA40 ELVETVE (2026-09-07)

SA40 (South Africa 40) a `icmarkets_world_indices_flash_screening.py` (2026-09-06) villámszűrésen
és az azt követő teljes walk-forward-ELŐSZÖR Optuna-hangoláson (`icmarkets_sa40_walkforward_
optuna.py`) is erős, ígéretes eredményt adott: **17.76 kockázat-korrigált pontszám, 19/23 fold
nettó pozitív (83%)** — a legjobb "új" (nem US-index) jelölt eddig, összemérhető US500-zal.

**A Strategy Tester-es megerősítés (`ReportTester-<ICM_DEMO_LOGIN>a.html`, real ticks, 2020.01.01–
2026.09.05) viszont ELLENTMOND ennek**: PF=1.08 (gyenge), **Max Drawdown 30.88% balance / 33.21%
equity** (messze a legmélyebb a négy vizsgált index közül — USTEC 5.13%, US500 1.63%, US30
10.95%), **Recovery Factor=0.55** (a teljes futamidő nettó profitja alig haladja meg a legrosszabb
visszaesést), Sharpe=2.53 (alacsony a többiek 11.67-23.17-es tartományához képest). Win rate
80.62% magas, de átlagos nyereség (+4.87) és átlagos veszteség (-18.77) kb. 3.85x aszimmetrikus,
és a Z-Score (-18.95, 99.74%) statisztikailag igazolja, hogy a nyerő/vesztő szekvencia erősen
csomósodik (10 egymást követő veszteség egyszerre).

**Diagnózis**: a jelenlegi kockázat-korrigált célfüggvény (`mean(fold_pnl) - 0.5*std(fold_pnl)`)
csak a fold-OK KÖZÖTTI PnL-szórást bünteti, VAK arra, hogy egy adott fold-on/negyedéven BELÜL
milyen mély és hosszan tartó, csomósodó veszteség-sorozat fordulhat elő. Egy magas találati arányú,
negatív ferdeségű kifizetés-profilú (sok kicsi nyereség, ritka nagy veszteség) komponens ezt a
célfüggvényt simán "átveri" — negyedévenként átlagosan pozitív marad, miközben a valós,
tick-alapú végrehajtásban egyetlen rossz sorozat a felhalmozott profit nagy részét elviszi.

**Következtetés — SA40 ELVETVE a live pilot számára jelenlegi formájában**, a walk-forward
pontszám ellenére. Ez a második eset (az első: 2.4-es US30 60-vs-200-trial tanulság), hogy a
puszta walk-forward pontszám önmagában megtévesztő tudott lenni — itt viszont fordítva: a
pontszám TÚL optimista volt a valós kockázathoz képest, nem a keresési büdzsé volt elégtelen.

**Nyitott, jövőbeli kutatási irány (NEM prioritás)**: a célfüggvénybe intra-fold drawdown-alapú
büntetőtag (pl. max intra-fold drawdown vagy Recovery Factor) beépítése, hogy hasonló eset
korábban kiszűrhető legyen villámszűrés/Optuna szinten, mielőtt Strategy Tester-ig eljutna.

**Második vakfolt, ugyanebben a témában (2026-09-07, DE40) — a Strategy Tester "History Quality"
mezőjét MINDIG ellenőrizni kell**: a világindex-villámszűrés másik ígéretes jelöltje, DE40, saját
session-fázis kutatás után (majdnem egésznapos piac — lásd `icmarkets_de40_session_exploration.py`,
az XM-es GER40 2.1-es kettős-csúcs mintázatát reprodukálta stabilan IC Marketsen is) gyengébb
walk-forward pontszámot adott (6.39, 8/11 fold), MINT SA40 (17.76), de az ELSŐ Strategy Tester-es
futtatás (3 éves periódus, 2023.10-2026.09) FORDÍTOTT eredményt hozott: PF=1.30, DD=9.25%, Recovery
Factor=4.17, Sharpe=8.37, Z-Score=0.73 (véletlenszerű, nincs csomósodás) — jóval egészségesebbnek
tűnt, mint SA40. **EZ AZ ELSŐ EREDMÉNY MEGTÉVESZTŐ VOLT**: a History Quality mező csak **14% real
ticks**-et mutatott, és a helyi tick-cache vizsgálata (`bases/ICMarketsEU-Demo/ticks/DE40/`)
kiderítette, hogy a bróker csak ~6 hónapra visszamenőleg tárol valós tick-történetet — a 3 éves
teszt 86%-a M1-bar-ból SZINTETIZÁLT tick volt. Egy megerősítő futtatás CSAK a valós-tick-
lefedettségű ablakra (2026.04.01-2026.09.05, **100% real ticks**) sokkal gyengébb, marginális
eredményt adott: **PF=1.04, Recovery Factor=0.14, Sharpe=0.73** — közelebb TSLA (0.10) szintjéhez,
mint a pilot-index-ekéhez. A max. egymást követő veszteség-sorozat (11 trade, -41.87) PONTOSAN
AZONOS volt mindkét tesztben, vagyis a teljes 3 éves teszt legrosszabb szakasza teljes egészében
ebbe a valós-tick ablakba esett — a szintetikus szakasz mesterségesen simította a képet.

**Összesített módszertani szabály (a 2.7-es vakfolt-sorozatból)**: (1) a nyers walk-forward
pontszám NAGYSÁGA önmagában nem elég a rangsoláshoz, a Strategy Tester-es megerősítés
(különösen a Z-Score/Recovery Factor) fontosabb minőségi jelzés; (2) **a Strategy Tester "History
Quality" mezőjét MINDIG ellenőrizni kell** — ha alacsony (<50%), a teljes-periódusú eredmény
megbízhatatlan lehet, és a valós-tick-lefedettségű részablakra KÜLÖN újra kell futtatni a tesztet,
mielőtt bármilyen élesítési döntés születne.

**AUS200-nál (2026-09-07) ugyanez a minta megismétlődött, harmadszor**: a session-mintázat itt is
instabil volt (Jaccard=0.33, lásd `icmarkets_aus200_session_exploration.py`), a walk-forward
pontszáma (7.80, 6/6 fold pozitív, de 3/6 fold 30 trade alatt) kis mintás, óvatosan kezelendő
eredmény volt. A teljes-periódusú Strategy Tester (40% real-tick) erős képet adott (PF=1.38,
Recovery Factor=2.92, Sharpe=6.90), DE a valós-tick-lefedettségű részablakra (2026.01-2026.09,
99% real-tick) megismételt teszt UGYANÚGY sokkal gyengébb eredményt hozott, mint DE40-nél:
**PF=1.08, Recovery Factor=0.31, Sharpe=1.31**.

**Végső állapot (2026-09-07) — egyik új nem-US index sem éri el a piloton lévő 3 index
megbízhatósági szintjét valós-tick-alapon**: SA40 ELVETVE (csomósodó veszteség), DE40 és AUS200
MARGINÁLIS (nem élesítve, de nem is véglegesen elvetve — a bróker tick-cache-e hónapról hónapra
bővül, később újra megerősíthetők lesznek, ha elég valós tick-történet gyűlik össze). UK100 szintén
ELVETVE (negatív walk-forward pontszám, a spread felemészti az élt). A live pilot változatlanul a
jelenlegi 3 index (USTEC+US30, US500 nélkül) marad.

### 2.8 🛡️ Ünnepnap- és spread-anomália-védelem — MINDKÉT élő EA-t érintő, első "live-file" változtatás (2026-09-07)

A felhasználó jelezte, hogy az IC Markets EA a mai US Labor Day-en (a valós NYSE/NASDAQ zárva,
ellenőrizve nyse.com hivatalos naptárán keresztül) mégis nyitott pozíciót — a CFD-bróker
ilyenkor is árazza a terméket, csak szélesebb spreaddel/vékonyabb likviditással, nem "valódi"
piaci mozgásból. **Két, egymást kiegészítő védelmi réteg épült be, MINDKÉT brókerre (IC Markets ÉS
XM) egyaránt**:

1. **Statikus, piaconkénti ünnepnap-naptár**: `data/market_holidays.json` (egyetlen forrás) →
   `core/market_calendar.py` (Python-oldali lekérdezés/szűrés) → `deployment/
   generate_holiday_mqh.py` generálja az MQL5-oldali `MarketHolidays.mqh`-t (metaTrader-EA-scripts
   repo) — ugyanaz a "Python forrás → generált MQL5" minta, mint a `.set` preset-eknél.
2. **Futásidejű spread-anomália-védelem** (`SpreadAnomalyGuard.mqh`): karbantartás nélküli,
   gördülő napi-átlag-spread bázisra épülő futásidejű "circuit breaker" — BÁRMILYEN rendellenes
   napot elkap, nemcsak a naptárban szereplőket.

Mindkét réteg CSAK az ÚJ belépéseket blokkolja, a meglévő pozíciók kezelését nem érinti. Bekötve
mindkét élő EA-ba (`RegimeFramework_EA.mq5` — élő XM — ÉS `RegimeFramework_EA_ICMarkets.mq5`),
mindkettő hibátlanul fordul. **Ez az ELSŐ eset a projektben, hogy egy változtatás közvetlenül az
élő XM `RegimeFramework_EA.mq5` fájlt módosítja** (eddig minden élő-kockázatú változtatás — pl. a
napvégi kényszerzárás-javítás — csak az elkülönített IC Markets másolatba került) — indoklás: ez a
változtatás tisztán védekező jellegű, nem nyúl meglévő belépési/kilépési logikához, és a
felhasználó explicit mindkét brókerre kérte. **Az élő XM terminálon az EA-t újra kell tölteni**,
hogy az újrafordított .ex5 életbe lépjen. Részletek: `docs/SESSION_LOG.md` 2026-09-07.

**Kapcsolódó, ugyanaznap felmerült felismerés — US-vs-EU nyári időszámítás eltérése**: a
felhasználó felvetette, okozhat-e problémát, hogy a téli/nyári időszámítás-váltás dátuma eltér
USA és Európa között. Hivatalos forrásból megerősítve (icmarkets.eu blog + XM dokumentáció): **mindkét
bróker szervereje SZÁNDÉKOSAN az AMERIKAI DST-naptárt követi** (GMT+2 US-télen / GMT+3 US-nyáron,
a váltás az amerikai dátumon, nem az európain) — ez tudatos bróker-tervezés, nem véletlen. **Ennek
következménye**: a jelenlegi élő US-index-ek (USTEC/US30/US500, mindkét brókeren) session-órái
biztonságban vannak, egész évben helyesen igazodnak — DE a ma vizsgált nem-US jelöltek (DE40/
UK100/AUS200/SA40) fix session-óra paraméterei kockázatosak lennének élesítés esetén: DE40/UK100
(EU-DST-et követő piacok) kb. 1-3 hetes "rés-ablakban" csúsznának el évente kétszer (2026: márc.
8-29 és okt. 25-nov. 1, amikor EU és US DST-dátum nem esik egybe), AUS200 (ellentétes féltekei,
saját DST-naptár) még inkább, SA40 (nincs DST-je egyáltalán) a legrosszabb eset — az év kb.
felében lenne rossz órában. **NEM aktív probléma jelenleg** (egyik nem-US jelölt sincs élesítve),
de ha bármelyiket később megfontolnánk, a fix session-óra paraméterek DST-tudatos kezelést
igényelnének.

---

## 3. Architektúra — két réteg + komponens-regisztráció

```
                    ┌─────────────────────────┐
                    │   1. RÉTEG              │
                    │   SessionPhaseClassifier │   naptár-vezérelt, ár-független
                    └───────────┬─────────────┘
                                │ (csak "kereskedhető" fázisokban folytatódik)
                    ┌───────────▼─────────────┐
                    │   2. RÉTEG              │
                    │   MarketConditionClassifier │  trend-erősség × volatilitás-percentilis
                    └───────────┬─────────────┘
                                │ RegimeState
                    ┌───────────▼─────────────┐
                    │   ComponentRegistry      │   XOR-választás: első illeszkedő komponens
                    │   (StrategyComponent[])  │
                    └───────────┬─────────────┘
                                │
                    ┌───────────▼─────────────┐
                    │   Engine (főprogram)     │   bar-onkénti univerzális ciklus,
                    │                           │   pozíció-kezelés, kifutási állapotok
                    └──────────────────────────┘
```

Ez pontosan a korábban elkészített blokkvázlat (Artifact) logikáját követi, csak most kódszerkezetként.

---

## 4. Package-struktúra

```
regime_framework/
  PLAN.md                        # ez a dokumentum
  __init__.py
  core/
    __init__.py
    types.py                     # BarContext, Position, Signal, RegimeState, ValidationReport
    component_base.py            # StrategyComponent absztrakt alaposztály + megosztott validációs segédek
    engine.py                    # a főprogram — univerzális bar-onkénti vezérlés
  regime/
    __init__.py
    session_phase.py             # 1. réteg — önállóan tesztelhető
    market_condition.py          # 2. réteg — önállóan tesztelhető
  components/
    __init__.py
    mean_reversion.py            # Komponens A — a main_optuna_anomaly.py logikájának adaptálása
    # trend_following.py, component_b.py, ... — csak validáció után kerülnek be
  data/
    __init__.py
    mt5_source.py                # adatlekérés + walk-forward szeletelés, EGY helyen
  validation/
    __init__.py
    report.py                    # ValidationReport formázása/kiírása (közös formátum minden komponensnek)
  optimization/
    __init__.py
    objective.py                 # Optuna-objective a regisztrált komponensekből összeállítva
    walk_forward.py              # újrahasznosított walk-forward keret, fold-méret figyelmeztetéssel
  main.py                        # belépési pont — csak bekötés, stratégia-logika NINCS benne
```

---

## 5. Interfész-vázlat (nem végleges kód, csak a szerződés)

```python
# core/types.py
@dataclass
class BarContext:
    close: float; high: float; low: float
    hour: int; minute: int; day_of_week: int; date: date
    regime: "RegimeState"
    # ... amit a komponensek ténylegesen igényelnek

@dataclass
class RegimeState:
    session_phase: str          # "OFF_HOURS" | "OPENING_RANGE" | "CORE_SESSION" | "PRE_CLOSE" | "ROLLOVER"
    trend_band: str | None      # "RANGING" | "TRANSITIONAL" | "TRENDING" (None, ha nem kereskedhető fázis)
    vol_band: str | None        # "LOW" | "HIGH"

@dataclass
class Signal:
    direction: str               # "LONG" | "SHORT"
    sl_price: float
    tp_price: float | None       # None = trailing-stop jellegű, nincs fix TP

@dataclass
class ValidationReport:
    component_name: str
    trade_count: int
    win_rate: float
    profit_factor: float
    warnings: list[str]          # pl. "minta < 30 trade", "PnL előjel-érzékeny paraméterre"


# core/component_base.py
class StrategyComponent(ABC):
    name: str
    applicable_states: set[tuple[str, str]]   # mely (trend_band, vol_band) cellákban aktív

    @abstractmethod
    def check_entry(self, ctx: BarContext) -> Signal | None: ...

    @abstractmethod
    def check_exit(self, ctx: BarContext, position) -> ExitDecision | None: ...

    @abstractmethod
    def suggest_params(self, trial) -> dict: ...   # Optuna-paraméterek, amiket ez a komponens hoz

    def validate(self, df, params) -> ValidationReport:
        """Alapértelmezett implementáció a megosztott segédekkel (trade-log kinyerés,
        win-rate/profit-factor/tartási-idő). A df-et és a params-ot KÍVÜLRŐL kapja —
        a komponens sosem éri el maga az MT5-öt."""
        ...  # felülírható/bővíthető komponens-specifikus ellenőrzésekkel
             # (pl. TurnaroundTuesday-nél: előfeltétel-gyakoriság, paraméter-érzékenység)


# regime/session_phase.py
class SessionPhaseClassifier:
    def classify(self, hour: int, minute: int) -> str: ...
    def validate(self, df) -> ValidationReport: ...   # időszak-persistencia, gyakoriság

# regime/market_condition.py
class MarketConditionClassifier:
    def classify(self, adx: float, vol_percentile: float) -> tuple[str, str]: ...
    def validate(self, df) -> ValidationReport: ...   # cella-gyakoriság, perzisztencia
```

---

## 6. Építési sorrend (alulról felfelé — csak bizonyított elemek kerülnek beljebb)

1. ✅ **`core/types.py`** — a közös szerződések, kód nélkül még nem futtatható, de mindenki erre épít. KÉSZ.
2. ✅ **`regime/session_phase.py`** — önállóan validálva (időszak szerinti volatilitás/spread/irány-torzítás
   mérés, ahogy korábban terveztük — ez adja meg a sávhatárokat empirikusan, nem találgatva). KÉSZ, mind
   az 5 szimbólumon figyelmeztetés nélkül validált — lásd 2.1 szakasz.
3. ✅ **`regime/market_condition.py`** — önállóan validálva (rács-cella gyakoriság + perzisztencia-
   ellenőrzés, mind az 5 index-jelölten egyszerre). KÉSZ, mindegyiken figyelmeztetés nélkül
   validált — lásd 2.2 szakasz. Univerzális (nem instrumentum-csoportos), a percentilis-rang
   módszer miatt.
4. ✅ **`components/mean_reversion.py`** — a már validált logika átemelve az új interfészbe
   (`check_entry`/`check_exit`/`suggest_params`/`validate`), regime-kapuval (`applicable_trend_bands
   = {"RANGING"}`), saját `validate()`-tel (elszigetelt, egy-komponenses backtest-hurok, mert az
   Engine még nem létezik). KÉSZ — determinisztikus egységtesztek (6 eset: TRENDING/TRANSITIONAL
   kizárás, csatorna-áttörés mindkét irányban, csatornán belüli semleges zóna, session-órán kívüli
   kizárás) mind lefutottak, `validate()` szintetikus adaton hibamentesen végigfutott.
   ⚠️ **Fontos, a teszteléskor felfedezett nüánsz a `MarketConditionClassifier`-ről**: a
   `trend_band` egy **relatív, gördülő percentilis-rangon** alapul (lásd 2.2), NEM abszolút ADX-
   küszöbön. Ebből következik, hogy EGY TARTÓSAN TRENDELŐ időszaknak IS lesz kb. egyharmada
   "RANGING"-nek címkézve (mert a rangsorolás mindig a saját ~60 napos gördülő ablakán belüli
   alsó harmadot jelöli ki, függetlenül attól, hogy az abszolút értelemben tényleg oldalazás-e).
   Ez azt jelenti, hogy a `MeanReversion` komponens `validate()`-je valós adaton NEM feltétlenül
   mutat kevesebb trade-et egy makro-szinten trendelő szakaszban — a "RANGING" címke lokális
   relatív állapotot jelent, nem globális piaci karaktert. Ezt szem előtt kell tartani a jövőbeli
   validációk értelmezésénél, és érdemes lesz egy külön, abszolút-szintű "macro trend" jelzőt is
   fontolóra venni, ha ez a torzítás a valós MT5 adaton is megerősítést nyer.

   **Valós MT5 regresszió-futtatás eredménye (2026-08-19, `validate_mean_reversion.py`, vanilla
   paraméterek, 2025-01-02 – 2026-08 tartomány):**

   | Szimbólum | Trade | Win-rate | Profit factor | Össz. PnL |
   |---|---|---|---|---|
   | US100Cash# | 244 | 36.5% | 1.16 | +168.15 |
   | US500Cash# | 217 | 35.0% | 0.99 | -2.11 |
   | JP225Cash# | 239 | 38.9% | 1.05 | +93.75 |
   | GER40Cash# | 230 | 35.2% | 0.87 | -94.75 |
   | EU50Cash# | 210 | 34.3% | 0.96 | -6.11 |

   Ez ALACSONYABB, mint a régi `regime_conditional_backtest.py` 42.9% win-rate-je — DE ez **nem
   alma-alma összehasonlítás**: a régi kód nyers, Optuna-hangolt ADX-küszöböt használt kapuként
   (`adx < AdxRangingThreshold`), az új komponens pedig a `MarketConditionClassifier` relatív
   percentilis-rangú `RANGING` sávját — ez szándékos architektúra-csere, nem regresszió. Csak
   US100Cash# egyértelműen nyereséges (PF 1.16); US500/EU50 gyakorlatilag nullszaldós, GER40
   veszteséges. **Következtetés: a MeanReversion önmagában, ezzel a regime-kapuval még NEM
   bizonyítottan nyereséges egyik indexen sem elég meggyőzően** — ez nem blokkolja a build-
   sorrendet (a validate() működik, a portolás technikailag helyes), de figyelmeztető jel, hogy a
   komponens paraméterezését/kapuját érdemes lesz hangolni, mielőtt bármi élesbe menne.

   **Döntés (2026-08-19, felhasználóval egyeztetve): a keddi kizárást (régi kód `d != 1`-je)
   SZÁNDÉKOSAN nem replikáljuk most.** Az eredeti kizárás célja a TurnaroundTuesday szállal való
   ütközés elkerülése volt — amíg az a komponens nem létezik ebben a rendszerben, nincs mivel
   ütköznie. A kizárást majd akkor adjuk hozzá (komponens- vagy Engine-szintű XOR-szabályként),
   amikor a TurnaroundTuesday megépül.
5. **Új komponens-jelöltek** (B/C/D cellák, nyitási logika) — mindegyik csak azután kerül a
   `components/` mappába, hogy a saját `validate()`-je lefutott és értelmes eredményt adott.
   - ✅ **`components/trend_following.py`** — a TRENDING trend_band-ra (mindkét vol_band, tehát a
     "C/D" cellák együtt, ugyanúgy, ahogy a MeanReversion is mindkét RANGING-cellát lefedi egyelőre).
     A `main_optuna_hybrid.py` EMA-viszony + ATR trailing stop szálának portolása.

     **Első valós MT5 futtatás (2026-08-19, még a pontos-keresztezés-alapú belépéssel, napvégi
     zárás NÉLKÜL) nagyon kevés trade-et adott: 9-17 szimbólumonként, ~0.3-0.6 nap átlagos tartási
     idővel.** Kiderült, hogy ez STRUKTURÁLIS hiba: a keresztezés ritka, egyetlen-bar esemény, amit
     a szűk 16:30-21:00 session-ablak tovább szűkített — ha a keresztezés az ablakon KÍVÜL történt,
     a jel véglegesen elveszett. A felhasználóval egyeztetve (döntés: overnight fee miatt a
     többnapos tartás NEM prioritás M10-M30-on, azt H1-H4-en érdemes keresni) a komponens
     ÁTALAKULT:
     1. Belépés ÁLLAPOT-alapú lett (bármelyik session-órás, TRENDING bar számít, ahol a gyors EMA
        már a lassú felett/alatt van — nem csak a pontos átmeneti bar).
     2. Napvégi kényszerzárás bekerült (mint a MeanReversionnél) — napi max. egy belépéssel
        (`trade_taken_today`), hogy egy korai kiütés után ne nyisson újra aznap.

     Ez a MOST érvényes viselkedés — determinisztikus egységtesztek (5+1 eset) és a `validate()`
     szintetikus adatos végigfutása mind lefutottak, a trade-szám nagyságrendekkel nőtt (0→56 a
     szintetikus smoke teszten).

     **Második valós MT5 futtatás (2026-08-19, az átalakítás után) — MIND AZ 5 SZIMBÓLUMON
     NYERESÉGES, figyelmeztetés nélkül:**

     | Szimbólum | Trade | Win-rate | Profit factor | Össz. PnL | Átl. tartás |
     |---|---|---|---|---|---|
     | US100Cash# | 244 | 41.0% | 1.20 | +232.81 | 0.01 nap |
     | US500Cash# | 252 | 40.5% | 1.13 | +32.57 | 0.00 nap |
     | JP225Cash# | 245 | 43.3% | 1.29 | +622.37 | 0.00 nap |
     | GER40Cash# | 238 | 45.4% | 1.18 | +150.75 | 0.00 nap |
     | EU50Cash# | 231 | 43.3% | 1.04 | +6.62 | 0.00 nap |

     Ez a legerősebb eredmény eddig ebben a rendszerben — minden indexen nyereséges, ~230-250
     trade/szimbólum (megbízható minta). Az átlagos tartás (~0 nap) meglepően rövid, de konzisztens
     a döntéssel (overnight-elkerülés): a trailing stop + EOD-zárás kombinációja gyakorlatilag
     napon-belüli momentum-stratégiává alakította — a legtöbb trade (75-80%) TRAIL_SL-lel zár, jóval
     a nap vége előtt (`trail_sl_exits` >> `eod_forced_exits`).

     **RSI-momentum-szűrő hozzáadva (2026-08-19, külön lépésként, miután a fenti két változtatás
     hatása külön ismert volt).** `core/indicators.py` bővült `compute_rsi()`-vel (egyszerű, nem
     Wilder-simított, ugyanaz a konvenció, mint az ATR/ADX-nél).

     **1. verzió (SÁV, mindkét oldalról korlátozva: LONG 50-70, SHORT 30-50)** valós MT5 adaton a
     win-rate-et mindenhol javította/stagnálta, de az ÖSSZ. PnL-t ~31%-kal rontotta (1045→721
     összesítve mind az 5 szimbólumon) — a két legerősebb szimbólumnál (JP225: 622→376, GER40:
     151→55) esett a legtöbbet. Diagnózis: a felső sávhatár (RSI<=70) éppen a legerősebb
     trend-szakaszokat vágta ki — erős trendben az RSI tartósan szélsőértéken maradhat, ami NEM
     kifulladás jele.

     **2. verzió, JELENLEGI, VALIDÁLT (felhasználóval egyeztetve): a felső határ megszűnt.** LONG
     csak `RSI >= rsi_long_min` (alapértelmezetten 50, nincs felső korlát), SHORT csak
     `RSI <= rsi_short_max` (alapértelmezetten 50, nincs alsó korlát) — csak a gyenge/bizonytalan
     momentumú belépéseket zárja ki, a túlfutást nem tekinti kizáró oknak. 6 determinisztikus
     egységteszt (a szélsőséges RSI-értékeknél is engedi a belépést, csak a felezővonal rossz
     oldalán tiltja) mind lefutott.

     **Valós MT5 eredmény (2026-08-19) — MEGHALADJA az eredeti (RSI nélküli) baseline-t is:**

     | Szimbólum | Trade | Win-rate | PF | Össz. PnL | (baseline PnL) |
     |---|---|---|---|---|---|
     | US100Cash# | 207 | 44.4% | 1.43 | +384.16 | (+232.81) |
     | US500Cash# | 208 | 41.3% | 1.13 | +25.14 | (+32.57) |
     | JP225Cash# | 192 | 45.3% | 1.52 | +798.44 | (+622.37) |
     | GER40Cash# | 192 | 49.0% | 1.18 | +109.39 | (+150.75) |
     | EU50Cash# | 180 | 46.7% | 1.22 | +26.00 | (+6.62) |

     Összesített PnL: **1343.13** (RSI nélküli baseline: 1045.12; kétoldali sávos verzió: 721.33).
     3/5 szimbólumon (US100/JP225/EU50) mind a win-rate, mind a PF, mind a PnL javult a baseline-hoz
     képest; a másik kettőnél (US500/GER40) a win-rate/PF javult/stagnált, csak az abszolút PnL esett
     vissza kicsit a kevesebb trade miatt. **A `TrendFollowingComponent` ezzel a konfigurációval
     LEZÁRTNAK tekinthető egy első, validált verzióként** — a további finomítás (paraméter-hangolás)
     az `optimization/` (Optuna) feladata lesz, nem kézi próbálgatás.

     **⚠️ Felhasználói kérdés és válasz (2026-08-19): "bear piacon nem lesz fordított hatása?"**
     A komponens logikája szimmetrikus, de a validáció csak a 2.3 szakaszban dokumentált 19 hónapos
     ablakon fut. `validate()` kapott egy LONG/SHORT bontást (`report.notes`), ami megmutatta:
     a LONG/SHORT arány következetesen ~60/40 minden szimbólumon (megerősíti, hogy ez az ablak
     inkább emelkedő-torzítású volt), és GER40-nél a SHORT oldal NETTÓ VESZTESÉGES (-26.38), míg a
     többi 4 szimbólumnál (a JP225 SHORT-ja kifejezetten jól, +510.93-mal) nagyságrendileg hasonló
     a LONG-hoz. **Ez STANDING, FELOLDHATATLAN korlát marad** (nem hiba — az adat határa): egy
     tartós, valódi medvepiaci szakaszt még sosem láttunk ebben az adatban, ezért nem zárható ki,
     hogy elhúzódó lefelé irányuló piacon a SHORT oldal eltérően teljesítene.
   - Nyitva marad: kell-e KÜLÖN komponens a HIGH-vol altípusokhoz (pl. szélesebb SL a RANGING+HIGH
     cellához, vagy egy önálló volatilitás-kitörés jelöltség a TRENDING+HIGH-hoz), vagy elég-e, hogy
     az ATR-alapú számítás (mind a MeanReversion, mind a TrendFollowing csatorna/SL/trailing
     távolsága) már eredendően skálázódik a volatilitással. Ezt csak azután érdemes eldönteni, hogy
     mindkét meglévő komponens valós adatos eredménye ismert.
6. ✅ **`core/engine.py`** — a két validált komponens (MeanReversion, TrendFollowing) XOR-dispatch
   alapú összekötése a `trend_band`-en keresztül. KÉSZ:
   - Induláskor ellenőrzi, hogy a komponensek `applicable_trend_bands` halmazai kölcsönösen
     kizáróak-e (átfedésnél `ValueError`) — ez maga az XOR-dispatch garanciája.
   - `_prepare_combined_df()`: minden komponens saját `prepare_indicators()`-ét (a korábbi privát
     `_prepare_indicator_df()`-ből lett nyilvános metódus) egy közös, idő szerint összefésült
     DataFrame-re vezeti, majd a `MarketConditionClassifier` EGYSZER fut le a végén (nem
     komponensenként duplán).
   - A bar-onkénti hurok komponens-független/generikus (mindkét jelenlegi komponens ugyanazt az
     orkesztrálási mintát követi: napi max. egy belépés + napvégi kényszerzárás), mert ez a minta
     korábban tudatosan lett egységesítve a TrendFollowing átalakításakor.
   - A riport komponensenkénti bontást is ad (`{ComponentName}_trades/_win_rate/_pnl/_pf`) — ez
     teszi lehetővé az összevetést a korábbi, elszigetelt `validate()`-eredményekkel, ahogy a
     "Fontos szabály" (lentebb) megköveteli.
   - Determinisztikus egységteszt (átfedő komponensekkel `ValueError`) + szintetikus adatos
     végpontig-futtatás (85 trade, 31 MeanReversion + 54 TrendFollowing, összeg stimmel, no-trade-
     zóna bar-ok helyesen számolva) mind lefutott.

     **Valós MT5 eredmény (2026-08-19) — a LEGERŐSEBB eredmény eddig a projektben:**

     | Szimbólum | Trade | Win-rate | PF | Engine PnL | (elszigetelt MR+TF összeg) |
     |---|---|---|---|---|---|
     | US100Cash# | 299 | 43.5% | 1.59 | +715.19 | (552.31) |
     | US500Cash# | 290 | 39.7% | 1.13 | +34.95 | (23.03) |
     | JP225Cash# | 281 | 39.5% | 1.40 | +909.76 | (892.19) |
     | GER40Cash# | 277 | 42.2% | 1.19 | +157.82 | (14.64 — drasztikus javulás!) |
     | EU50Cash# | 258 | 40.3% | 1.07 | +13.49 | (19.89 — kicsit alacsonyabb) |

     Mind az 5 szimbólumon nyereséges, figyelmeztetés nélkül, 4/5-nél MEGHALADVA a két komponens
     elszigetelt eredményének puszta összegét is. A globális (nem komponensenkénti) napi max. egy
     belépés kb. felére csökkentette mindkét komponens trade-számát, DE a megmaradt trade-ek
     minősége (win-rate/PF) 3/5 szimbólumon a TrendFollowing oldalon is JAVULT — a napi egyetlen
     slot-ért való versengés valószínűleg kiszűri a gyengébb minőségű napokat. **A
     `core/engine.py` + a két komponens egy első, teljes rendszerként LEZÁRTNAK tekinthető.**

     **Walk-forward validáció (2026-08-19):** `Engine.run()` kapott egy opcionális
     `stats_start_date` paramétert — bővülő ablakos (expanding window) fold-oknál a teljes eddigi
     adat bemelegítésként szolgál, de a riport metrikái csak az adott fold dátumtartományában
     nyitott trade-eket számolják. `validation/validate_walk_forward.py`: negyedéves fold-ok
     2025-04-től (a MarketConditionClassifier ~3 hónapos gördülő ablaka előtte nem termel érvényes
     besorolást), fold-onkénti riport + összegzés. Szintetikus adaton hibamentesen lefutott.

     **Valós MT5 eredmény (2026-08-19) — ÁRNYALTABB kép, mint az aggregált futtatás sugallta:**

     | Negyedév | US100 | US500 | JP225 | GER40 | EU50 |
     |---|---|---|---|---|---|
     | 2025-04 | + | + | + | + | + |
     | 2025-07 | **–** | **–** | **–** | **–** | **–** |
     | 2025-10 | + | – | + | + | + |
     | 2026-01 | + | – | + | – | – |
     | 2026-04 | + | + | + | – | – |
     | 2026-07 | – | + | + | + | + |

     Pozitív negyedévek: JP225 5/6, US100 4/6, US500/GER40/EU50 mind 3/6. **A 2025-07 negyedév MIND
     AZ 5 szimbólumon veszteséges volt** (US100 -3.39, US500 -18.62, JP225 -72.38, GER40 -26.97,
     EU50 -5.75) — egy valós, KORRELÁLT makro-esemény lenyomata, ami egyszerre érintette az összes
     indexet és mindkét komponenst. Ez tompítja a korábbi aggregált (19 hónapos) eredményt: a
     három leggyengébb szimbólumnál (US500/GER40/EU50) a negyedévek FELE veszteséges volt. **Egy
     éles rendszernek túl kellene élnie az olyan negyedéveket, mint a 2025-07** — ez pontosan az a
     fajta kockázat, amit egy aggregált backtest elrejt, a walk-forward validáció viszont felszínre
     hoz. Nyitott kérdés (felhasználóval megbeszélendő): a 2025-07 esemény vizsgálata, drawdown-
     védelem hozzáadása, vagy elfogadás mint ismert, dokumentált kockázat.

     **Gyors diagnózis eredménye (`research/q3_2025_diagnosis.py`, 2026-08-19):** a 2025-07
     negyedév MIND AZ 5 szimbólumon feltűnően alacsonyabb volatilitású volt a szomszédos
     negyedévekhez képest (-40% és -60% között a Q2-höz mérve) — klasszikus "nyári uborkaszezon"
     jelenség. A heti PnL-bontás sok kicsi, szétszórt vesztes hetet mutat, NEM egy katasztrofális
     eseményt. Valószínű (nem bizonyított) mechanizmus: alacsony, de zajos volatilitású piacon az
     ATR-alapú SL-táv relatíve túl szoros lehet. Ez most MEGÉRTETT, dokumentált kockázat — a
     felhasználóval egyeztetve nem megyünk mélyebbre, de ha az alábbi 5. pont (HIGH/LOW-vol
     altípusok) valaha megépül, ez a megfigyelés a kiindulópontja.
   - Amit MOST még nem tartalmaz (tudatosan, "csak bizonyított elemek kerülnek beljebb" elv):
     `SessionPhaseClassifier` bekötése (minden bar `CORE_SESSION`-nek számít, mint eddig
     mindegyik komponens saját validate()-jében is), `vol_band`-alapú finomabb dispatch,
     költség-modellezés.

     **Empirikus megerősítés a költség-modellezés hiányára (2026-09-01, kézi + script-alapú
     teszt XM demo számlán, US500Cash):** két független 0.1 lotos kereskedés (egy azonnali
     script-driven nyitás/zárás, egy ~8.5 percig kézzel nyitva tartott, valós áringadozást is
     tartalmazó ügylet) mindkét esetben `HistoryDealGetDouble(DEAL_COMMISSION)` szerint
     PONTOSAN 0.0000 USD jutalékot mutatott. A Symbol Specification ablak sem tartalmaz
     Commission mezőt ennél a szimbólumnál. **Következtetés: az XM-nél az index CFD-k
     (US100/US500/US30 Cash) mindig tisztán spread-alapúak, FÜGGETLENÜL a számlatípustól**
     (a "Zero" számlatípus jutalék-komponense a Forex-párokra vonatkozik, nem az indexekre) —
     tehát a jelen keretrendszer "élő spread = teljes költség, nincs külön jutalék-tag" modellje
     NEM egy egyszerűsítő hiányosság, hanem empirikusan igazolt, helyes feltételezés ezekre a
     szimbólumokra. Ha valaha más eszközosztályra (pl. Forex) is kiterjesztenénk a keretrendszert,
     ott ez a feltételezés ÚJRA-ELLENŐRZENDŐ, mert valószínűleg NEM állja meg a helyét.
7. ✅ **`optimization/`** — Optuna-keret a MeanReversion/TrendFollowing paramétereire, a MÁR
   VALIDÁLT walk-forward fold-okon (nem egyetlen aggregált backteszten, hogy elkerüljük a projekt
   korábbi, dokumentált költség-paraméter-gaming hibáját — lásd PLAN.md 2. táblázat). KÉSZ:
   - `optimization/objective.py`: `evaluate_on_folds()` a fold-onkénti PnL-ek ÁTLAGÁT egy
     szórás-büntetéssel (`RISK_PENALTY_LAMBDA=0.5`) kombinálja — NEM a puszta összesített PnL,
     mert az egy negyedév kiugrásának engedne túl nagy súlyt (lásd a 2025-07 "nyári uborkaszezon"
     felismerést, ami minden szimbólumon egyszerre rontott). Kemény minimum-trade-szám őrző
     (`MIN_TOTAL_TRADES_FOR_VALID_SCORE=30`) a Turnaround Tuesday tanulság alapján.
   - `build_components(trial)`: EGYETLEN függvény szolgál élő Optuna-optimalizáláshoz ÉS a
     legjobb paraméterek visszajátszásához is (`optuna.trial.FixedTrial` a study befejezése után),
     hogy ne legyen két, egymástól eltérő, idővel szétdriftelő logika.
   - `optimization/run_study.py`: szimbólumonként külön study (a régi kódbázis is per-szimbólum
     optimalizált), a study végén a legjobb paraméterekkel újrafuttatja a TELJES walk-forwardot
     fold-onkénti bontással — nem elég a puszta Optuna-pontszám, a tényleges fold-onkénti
     viselkedést is látni kell.
   - Szintetikus adatos végpontig-futtatás (5 trial) hibamentesen lefutott.

     **Valós MT5 eredmény (2026-08-19, 60 trial/szimbólum) — mérhető ROBUSZTUSSÁG-javulás:**

     | Szimbólum | Pozitív fold-ok (vanilla → optimalizált) |
     |---|---|
     | US100Cash# | 4/6 → 6/6 (mind pozitív) |
     | US500Cash# | 3/6 → 6/6 (mind pozitív) |
     | JP225Cash# | 5/6 → 5/6 (2025-07 marad negatív, kicsit rosszabb: -72.38→-79.70) |
     | GER40Cash# | 3/6 → 5/6 |
     | EU50Cash# | 3/6 → 5/6 |

     Összesen: 18/30 → 27/30 fold pozitív (60% → 90%). A 2025-07 ("nyári uborkaszezon", lásd
     fentebb) GER40/EU50-nél sokkal kevésbé fájt, US100/US500-nál eltűnt — csak JP225-nél maradt
     és romlott, megerősítve, hogy ott strukturális piaci jelenségről van szó, amit paraméter-
     hangolás nem old meg teljesen. A win-rate-ek/trade-számok a vanilla baseline-hoz hasonló
     tartományban maradtak (nem degenerálódtak extrém megoldásokká) — a valós piaci adat
     komplexitása természetesen fékezte a túl-illeszkedést. **A keret (két rezsim-réteg + két
     komponens + Engine + walk-forward + Optuna) egy első, teljes, empirikusan validált és
     hangolt rendszerré állt össze.**
8. **`main.py`** — a legvégső bekötés.

**Fontos szabály, amit eddig is tanultunk:** egy komponens elszigetelt validációja NEM garantálja, hogy a
teljes rendszerben is jól teljesít (lásd a TrendFollowing esetét). Ezért a 6-7. lépés után **mindig**
vissza kell térni egy teljes walk-forward futtatásra, mielőtt bármit "késznek" nyilvánítanánk.

---

## 7. Nyitott kérdések

- **📊 ÉLŐ TELJESÍTMÉNY STATISZTIKAI ÖSSZEVETÉSE A VALIDÁLT ALAPPAL -- 1. FÁZIS KÉSZ ÉS LEFUTTATVA
  (2026-09-09)**: a cél, hogy a dashboard ne csak nyers P&L-t mutasson, hanem jelezze, ha az élő
  teljesítmény statisztikailag eltér a validációtól (a projekt saját "retail szint fölötti"
  erőssége -- lásd a felhasználó explicit kérését erről a szempontrendszerről). Két fázisra
  bontva:
  - **✅ 1. fázis -- Referencia-generátor, MEGÉPÍTVE ÉS LEFUTTATVA**:
    `regime_framework/validation/generate_live_baseline.py` a JELENLEG ÉLESÍTETT szimbólum+
    komponens kombinációkra (a ténylegesen élő `.set`/EA `input` paraméterekkel, NEM újra-
    optimalizálva) előállítja a baseline win-rate/PF/trade-count számokat egy generált JSON-ba
    (`regime_framework/data/live_baselines.json`, ugyanaz a minta, mint `market_holidays.json` →
    `MarketHolidays.mqh`-nál). Ténylegesen lefuttatva az IC Markets USTEC pilótára -- mind a 4
    komponens (RF_MR/RF_TF/RF_LHC/RF_FS) messze a 30-as megbízhatósági küszöb felett, mind PF>1.
    **✅ Kibővítve még aznap: IC Markets US30 (magic 202611) is bekerült** -- a $2000-os pilot
    másik lába, ugyanazon a már csatlakoztatott terminálon elérhető. (IC Markets US500 TUDATOSAN
    NEM került be -- a 2026-09-06-i döntés kihagyta a pilotból, nem élő.)

    **✅ TELJES: mind az 5 élő példány lefedve (2026-09-09, ugyanaznap)** -- a felhasználó
    átjelentkeztette a kutatási terminált XM demó fiókra, így a 3 XM-es élő példány (US100Cash#/
    US500Cash#/US30Cash#) is bekerült. Ehhez a script két javítást kapott: (a) merge-elő logika
    (`_load_existing_instances()`) -- egy futtatás csak az ÉPPEN elérhető bróker példányait
    frissíti, a többit érintetlenül megőrzi, mert a terminál egyszerre csak egy fiókhoz tud
    kapcsolódni; (b) `live_symbol`/`fetch_symbol` szétválasztás a bróker-szimbólum-eltérés miatt
    ([[broker-symbol-naming-mismatch]] -- az élő XM `#`-es nevet használ, a kutatási demó nem,
    felhasználó megerősítette, hogy ugyanaz a szimbólum). **Mind az 5 példány × mind a 4 komponens
    (20 kombináció) megbízható és PF>1** -- lásd `SESSION_LOG.md` 2026-09-09 legfrissebb bejegyzése
    a teljes táblázatért.

    **✅ Utólag megszűnt korlát (2026-09-09, ugyanaznap folytatás): valódi `.set`-parser** --
    `regime_framework/validation/mt5_set_parser.py`, a kézzel átmásolt paraméter-dict helyett
    közvetlenül a terminál `.set` fájljából olvas minden futtatáskor (regresszió-tesztelve: a
    parszolt USTEC.set bájtra megegyezik a korábbi kézi dict-tel). Felfedezés közben: a
    projektben KÉTFÉLE `.set`-kódolás van (BOM-os UTF-16LE az újabb, BOM nélküli UTF-8 a
    régebbi XM-fájloknál) -- a parser mindkettőt kezeli, hangosan hibázva ismeretlen kódolásnál.
    **Azonosított és kezelt buktatók**: (a) szintetikus-tick csapda -- a teljes elérhető
    történelmen futtatva hamisan jó számot adhat, lásd a DE40/AUS200 real-tick-tanulságot,
    [[regime-framework-gotchas]] 6. pont; (b) walk-forward kell, nem egyetlen teljes-periódusú
    futtatás -- a `FOLD_BOUNDARIES`-t importálja, nem duplikálja; (c) komponensenkénti minta-
    méret -- a `reliable` mező jelzi, ha egy komponens 30 trade alatt van ("Turnaround Tuesday"
    szabály); (d) backtest-vs-élő mechanizmus-eltérés (pl. a MeanReversion SL/TP-je élőben natív
    bróker-megbízás, NEM a Python `resolve_fixed_exit()` pesszimista feloldása) -- explicit
    dokumentálva a script fejlécében, mint tudatosan elfogadott közelítés; (e) bróker-specifikus
    adat -- a helyes (IC Markets EU demó) terminálhoz kötve fut, lásd [[broker-symbol-naming-mismatch]].
    Menet közben kiderült egy hatodik, korábban nem azonosított buktató is: az `optuna_research`
    csak kutatási másolat, a ténylegesen élesített Python-kód (`D:\XM\Optuna`) még nem kapta meg
    a napvégi-kényszerzárás-javítást -- felhasználóval egyeztetve az ITTENI (javított) Engine-t
    használtuk mérvadónak.
  - **✅ 2. fázis -- Élő összevetés a dashboardon, MEGÉPÍTVE (2026-09-09)**: a webes dashboard
    "Rezsim" tabján új szekció ("Élő teljesítmény vs. validált alap"), példányonként (mind az 5
    élő) és komponensenként pill-jelvénnyel (Várakozik/OK/Figyelendő/Eltérés) + a nyers számokkal.
    A tervezéskor kiderült: a Wald-Wolfowitz runs-test ROSSZ illeszkedés lett volna (a nyerő/
    vesztő sorozat véletlenszerűségét vizsgálja, nem a baseline-tól való eltérést) --
    felhasználóval egyeztetve helyette **egy-mintás arány-z-teszt** (MeanReversion/
    LastHourContinuation/FridayShort, win-rate-alapú) és **PF-eltérés-százalék küszöbök**
    (TrendFollowing, szándékosan alacsony találati arányú/nagy R:R, ott PF a jelzőszám) --
    `regime_framework/monitoring/baseline_drift.py`. Sparkline/gauge helyett egyszerű pill + nyers
    szám (kisebb scope, de a `detail` mindig tartalmazza a számokat, sose csak a szín számít).
    Menet közben egy második buktató is előkerült: a meglévő `_component_stats()` az ÖSSZES
    terminál/bróker/magic trade-jét egyetlen tag-kulcs alá pool-olta -- ez a magic-szám-ütközés
    miatt (XM US100Cash# és IC Markets USTEC mindkettő 202609) veszélyes lett volna
    példányonkénti összevetéshez; javítva `(terminal, magic, tag)` kulcsra, a régi portfólió-
    kártya kimenete változatlan maradt. Részletek: `SESSION_LOG.md` 2026-09-09 bejegyzései.

    **✅ Kitelepítve és éles adaton megerősítve (2026-09-09, ugyanaznap folytatás)**: a VPS-en
    lefutott `.exe`, a tunnelen keresztül valós trade-adattal tesztelve. Menet közben egy valódi
    hiba is előkerült és javításra került: XM US500Cash# élő EA-ja magic=2026091-et jelent be
    (nem 202629-et, amit a `.set` fájl tartalmazott) -- felhasználóval egyeztetve az élő EA a
    mérvadó, javítva a baseline-ban (csak azonosító, backtest-szám változatlan). Ellenőrizve: az
    5 példány pontosan a régi aggregált kártyával egyező 12 trade-et ad ki összesen. NYITVA
    maradt: XM US30Cash#-hoz nincs heartbeat-fájl a VPS-en -- valószínűleg nem fut jelenleg.

  - **⚠️ KARBANTARTÁSI TEENDŐ, minden negyedévi validáláskor (rögzítve 2026-09-09)**: a
    `live_baselines.json` (a monitor "Élő teljesítmény vs. validált alap" szekciójának alapja)
    egy PILLANATKÉP -- a `FOLD_BOUNDARIES` (`validation/validate_walk_forward.py`) jelenleg
    2026-08-01-ig tart, NEM "a mai napig", és a benne lévő 5 baseline a 2026-09-09-i élesített
    paraméterekkel készült. Amikor a következő negyedévi walk-forward validáció megtörténik
    (új fold hozzáadása a `FOLD_BOUNDARIES`-hez ÉS/VAGY a live paraméterek újrahangolása), a
    monitorban lévő baseline-t IS frissíteni kell, különben a dashboard egyre elavultabb
    referenciához hasonlítja az élő teljesítményt -- ez CSENDBEN, hibaüzenet nélkül történne
    (a `classify_component_drift()` nem tudja, hogy a baseline-ja elavult, csak azt látja, amit
    kap). Frissítési lépések (lásd `SESSION_LOG.md` 2026-09-09 bejegyzései a részletes mintáért):
    1. `python -m regime_framework.validation.generate_live_baseline` -- KÉTSZER kell futtatni,
       egyszer IC Markets-re, egyszer XM-re bejelentkezett kutatási terminállal (a script
       merge-eli a `live_baselines.json`-t, nem írja felül a másik bróker adatait, lásd
       `_load_existing_instances()`).
    2. HA egy élő EA `InpMagicNumber`-je időközben megváltozott (ahogy XM US500Cash#-nél is
       történt, lásd fent) -- ellenőrizni a VPS heartbeat-fájljait (`magic=` mező), nem elég a
       `.set` fájlra hagyatkozni, az elavulhat.
    3. **ELAVULT LÉPÉS, 2026-09-11 óta NEM kell** (lásd `SESSION_LOG.md` 2026-09-11 "monitor
       refaktor" bejegyzése): a `live_baselines.json` már NINCS becsomagolva az .exe-be, hanem
       az .exe MELLETT álló, önállóan cserélhető fájl (`C:\MT5-Demo\MONITOR\live_baselines.json`
       a VPS-en) -- elég a frissített JSON-t `scp`-vel felmásolni, az .exe-t sem újrafordítani,
       sem újraindítani nem kell, a `refresh_loop` legfeljebb 90 mp-en belül felveszi.
    4. Ellenőrzés a valós tunnelen keresztül: az 5 példány összesített trade-száma egyezzen a
       meglévő "Komponensek szerinti bontás" kártya összegével (ez fogta ki a magic-hibát is).

- **✅ TELEFONOS DASHBOARD-HOZZÁFÉRÉS -- KÉSZ, ÉLESBEN MŰKÖDIK (2026-09-08)**: a PWA-támogatás
  (`monitoring/webapp/`) elkészült, tesztelve, kitelepítve a VPS-re, a felhasználó Edge-ben
  ténylegesen feltelepítette asztali gépen ÉS Androidon (ConnectBot + KÜLÖN, korlátozott
  `D:\_RDP_RACKFOREST\android_key` -- VPS-oldalon `command="cmd.exe /c echo no-shell-access",
  restrict,port-forwarding,permitopen="127.0.0.1:8765"`, háromirányúan tesztelve: dashboard-
  forward működik, RDP-forward és shell-hozzáférés tiltva). A felhasználó megerősítette: "app
  elkészült". Lásd `SESSION_LOG.md` 2026-09-08 bejegyzéseit a technikai részletekért (manifest,
  ikon, mobil-reszponzív CSS, egy frozen-exe-only build-hiba a `WEBAPP_DIR`-nál, és a ConnectBot
  gyorskapcsolódás-mező `ssh://`-prefix csapdája). **EGYETLEN, NEM BLOKKOLÓ NYITOTT PONT**: a
  ConnectBot saját keep-alive/ping-interval beállítása -- a felhasználó éppen teszteli, leszakad-e
  a telefon-tunnel is inaktivitás után (mint a desktop `plink`-nél); ha igen, ezt kell majd
  beállítani a ConnectBot hoszt-beállításaiban.
- **✅ TÁVOLI "ALGO TRADING" LE/FEL-KAPCSOLÓ A WEB-DASHBOARDRÓL -- MEGÉPÍTVE, ÉLESBEN TESZTELVE
  (2026-09-09)**: a `dashboard_web.py`-ból most már le/felkapcsolható egy adott EA-példány ÚJ
  belépése (a natív MT5 "Algo Trading" gomb TERMINÁL-szintű, kívülről nem kapcsolható, ezért egy
  SAJÁT, vezérlő-fájl-alapú "soft" letiltás épült -- `RegimeFramework_control_<szimbólum>_
  <magic>.txt` a `Common\Files`-ban, létezés=tiltva/hiány=normál, ugyanaz a fail-open elv, mint a
  naptár-guard-nál). HARMADIK élő EA-módosítás mindkét brókeren (`metaTrader-EA-scripts`, commit
  `4126f1f`), a dashboard ELSŐ ÍRÓ végpontja (`POST /api/control`), kliens-oldali `confirm()` a
  véletlen kattintás ellen. Dev-módban, lefordított .exe-ben ÉS a valódi VPS-en/tunnelen keresztül
  is végponttól-végpontig megerősítve. Lásd `SESSION_LOG.md` 2026-09-09 bejegyzését a teljes
  tervért/részletekért. **EGYETLEN NYITOTT PONT**: az élő XM/IC Markets terminálokon (a TÉNYLEGES
  kereskedési fiókokon, nem a kutatási terminálon) az EA-t kézzel újra kell tölteni, hogy az
  újrafordított `.ex5` életbe lépjen -- ez még nem történt meg.
- **✅ IDŐSÍK-VIZSGÁLAT MEGISMÉTELVE IC MARKETS-EN, ADATMENNYISÉG-TORZÍTÁSTÓL TISZTÁN IS M10
  NYER (2026-09-12)**: az eredeti (2026-09-02, másik bróker) mérés M10-győzelme torzított
  lehetett az idősíkonként eltérő adatmélység miatt. Megismételve IC Markets-en (USTEC+US30):
  ELŐSZÖR `research/icmarkets_timeframe_data_depth_check.py` térképezte fel idősíkonként a valós
  (nem visszatöltött/szintetikus) OHLC-bar-adat határát (M6/M10: ~2023-10/11-től ÉS csak
  2025-01-02-től folyamatosan sűrű a valóságban — ezt csak a tényleges összehasonlító futtatás
  fedte fel, mert a térkép csak visszafelé, nem előre ellenőrzött; M15: ~2022-07-től; M30: ~2018-04-
  től; H1: ~2017-07-től), majd `research/icmarkets_timeframe_comparison.py` az M10 bar-számához
  igazított AZONOS mintaméretű discovery-szakaszt futtatta minden idősíkon (nem hangolt, közös
  paraméterekkel, USTEC+US30-on). **Eredmény: M10 egyértelműen nyer még ezen, adatmennyiségre
  kontrollált összevetésben is** (Össz. PnL disc/hold: M10 534/400, M15 305/49, M6 202/147 [nem érte
  el a cél bar-számot], M30 -114/243 [hold n<30, megtévesztő], H1 -2/-12 [TF teljesen halott,
  degenerált bar-szám-alapú indikátorperiódusok]). **VÉGLEGES: M10 marad a nyertes idősík, nincs
  indok idősík-váltásra.** Lásd `SESSION_LOG.md` 2026-09-12 bejegyzéseit a teljes indoklásért
  (két, útközben talált és javított saját hibával: adathatár-vakfolt + egy célmérték-számítási
  sorrendi kódhiba).
- **🛢️ ÚJ VIZSGÁLATI IRÁNY (2026-09-02): Cash Energies (BRENTCash, NGASCash, OILCash) bevonása a
  TrendFollowing-vizsgálatba** (felhasználói kezdeményezés). Adatmélység-ellenőrzés
  (`research/check_energy_symbols_data_depth.py`, a `fetch_rates()` validált snap-detektálásával,
  nem naiv lekéréssel) mindhárom szimbólumra:

  | Szimbólum | Első bar | Utolsó bar | Becsült kereskedési nap | Bar-szám |
  |---|---|---|---|---|
  | BRENTCash | 2023-09-01 | 2026-09-02 | ~783 | 99 941 |
  | NGASCash | 2023-10-25 | 2026-09-01 | ~744 | 99 933 |
  | OILCash | 2023-10-27 | 2026-09-01 | ~743 | 99 933 |

  Mindhárom bőven a 60 kereskedési napos bemelegítési minimum fölött, és nagyságrendileg
  megegyezik az index-vizsgálat ablakával (2023-11-01–2026-08-21). **Érdekesség**: mindhárom
  energiaszimbólum valós adata is 2023 szept-okt környékén indul — ugyanaz az időszak, mint az
  indexek "Cash Ultra Low" termékcsaládjának indulása (lásd fent) — valószínűleg a bróker egy
  közös, egyszerre bevezetett "Cash" termékcsaládjáról van szó, index+energia együtt, nem
  külön-külön időzített bevezetésekről.

  **Figyelmeztetés a tervezett vizsgálathoz**: ez az ablak (~2.9 év) RÖVIDEBB, mint az US30
  hosszú-ablakos újravalidálásnál használt 4.7 év (2022-től), ahol pont a rövidebb ablak
  bizonyult torzítottnak (lásd fent, "US30 rövid ablakon nyereséges, hosszún nem"). Nincs mód
  hosszabb ablakra (ennyi a valós adat), de a walk-forward fold-ok kis mintaelemszámát emiatt
  fokozott óvatossággal kell kezelni.

  **TrendFollowing kiindulómérés eredménye (2026-09-02, `research/energy_trend_following_
  baseline.py`)** — a validált, kettős-megerősítéses (Bollinger+EMA) index-logika VÁLTOZATLAN
  paraméterekkel, a teljes elérhető ablakon (2023-11-01–2026-09-02), költség nélkül:

  | Szimbólum | Trade | Win-rate | Profit Factor | Össz. PnL |
  |---|---|---|---|---|
  | BRENTCash | 103 | 30.1% | 0.46 | -1.83 |
  | NGASCash | 65 | 38.5% | 0.64 | -0.05 |
  | OILCash | 93 | 36.6% | 0.95 | -0.12 |

  Mindhárom PF<1, MÉG KÖLTSÉG NÉLKÜL is. Felmerült, hogy a session-ablak (16:30-21:00 szerveridő,
  US-index-nyitásra kalibrálva) tévesen szűkíti a belépéseket egy más likviditási ciklusú
  instrumentum-osztályon — utóellenőrzés (`research/energy_trend_following_no_session_gate.py`,
  ugyanaz a logika, session-kapu KIKAPCSOLVA):

  | Szimbólum | PF (kapuval) | PF (kapu nélkül) | Trade (előtte→utána) |
  |---|---|---|---|
  | BRENTCash | 0.46 | 0.75 | 103→379 |
  | NGASCash | 0.64 | 1.06 | 65→412 |
  | OILCash | 0.95 | **0.82 (romlott)** | 93→379 |

  A VEGYES irány (2 javult, 1 romlott) cáfolja, hogy a session-ablak lenne a fő ok — ha az lenne,
  mindháromnak egy irányba kellett volna mozdulnia. A legjobb eredmény (NGASCash PF 1.06) is még
  mindig költség nélküli, és a win-rate-ek végig alacsonyak (30-33%) maradtak kapu nélkül is.

  **VÉGSŐ VERDIKT (a "kettős megerősítés" AND-kombinációra): a validált index-TrendFollowing
  logika, változatlan paraméterekkel, NEM mutat robusztus élet a Cash Energies instrumentumokon**
  (BRENTCash/NGASCash/OILCash), sem a session-ablakkal, sem anélkül.

  **⚠️ FELHASZNÁLÓI VISSZAKÉRDEZÉS NYOMÁN PONTOSÍTVA (2026-09-02): a fenti verdikt csak az AND-
  kombinációra (Bollinger ÉS EMA EGYSZERRE) igaz, NEM jelenti azt, hogy nincs semmilyen él ezeken
  az instrumentumokon** — lásd lent a "🔬 Komponens-dekompozíció" bejegyzést, ami ezt a kérdést
  a nemesfémekkel együtt, alaposabban körüljárja. NGASCash-nél kiderült, hogy a KOMPONENSEK
  ÖNMAGUKBAN (nem AND-olva) erősebb élt mutatnak, mint az AND — ez az egyszerű "energiákon nincs
  él" lezárás emiatt FÉLREVEZETŐ volt a maga idejében. A további vizsgálat (egyedi szűrők
  szignifikancia-tesztje) folyamatban, lásd lent.

- **🪙 Nemesfém-instrumentumok (GOLD., SILVER., XAUEUR., XAUCNH., XAUJPY., XPDUSD., XPTUSD.,
  GAUCNH., GAUUSD., GOLD24-7.) — ugyanaz a vizsgálat (2026-09-02)**: adatmélység rendben
  (GOLD24-7. kivételével, ~44 kereskedési nap, kihagyva; XAUCNH./XAUJPY./GAUCNH./GAUUSD. csak
  ~249 kereskedési napos, újabb keresztek; a többi ~738-741 napos, a teljes ablakkal egyező).
  TrendFollowing (kettős megerősítés, session-kapu nélkül) kiindulómérés: 7/9 szimbólum PF<1,
  két kivétel épphogy 1.0 fölött (XAUEUR 1.02, XPTUSD 1.08) — mind a fenti energiás mintázattal
  egybevágó, gyenge kép.

  **🔬 Komponens-dekompozíció (2026-09-02, `research/component_decomposition_check.py`,
  felhasználói visszakérdezés nyomán: "biztos, hogy nincs bug, nem csak túl szigorú az AND más
  eszközosztályra?")**: (1) `trend_band` frekvencia-ellenőrzés — mindenhol egészséges ~33/33/33%,
  a `MarketConditionClassifier` NEM degenerált ezeken az instrumentumokon, kizárva egy lehetséges
  hibaforrást. (2) A "kettős megerősítés" szétbontva a két alkotóelemére (csak Bollinger, csak
  EMA), UGYANAZON a futáson, 5 szimbólumon:

  | Szimbólum | Csak Bollinger | Csak EMA | Kettős (AND) |
  |---|---|---|---|
  | GOLD. | 0.98 | **1.11** | 0.91 ⬇ |
  | XAUEUR. | 1.09 | 1.02 | 1.02 |
  | XPTUSD. | 0.95 | 0.94 | **1.08** ⬆ |
  | OILCash | 0.76 | 0.89 | 0.82 |
  | NGASCash | **1.24** | **1.25** | 1.06 ⬇ |

  **GOLD-nál és NGASCash-nél a két komponens ÖNMAGÁBAN erősebb élt mutat, mint az AND-kombináció**
  — az AND-kombináció (ami indexeknél a validált, jó döntésnek bizonyult) itt éppen ELFEDI a
  meglévő, szerényebb élt, nem erősíti. XPTUSD-nél fordítva (AND segít), OILCash-nél egyik
  kombináció sem ment 1.0 fölé (genuinely gyenge). **NINCS egyetlen univerzális szabály
  ("mindig AND" vagy "mindig OR") — eszközosztályonként eltér, melyik kombinációs logika a jó.**

  **Tanulság módszertani szempontból**: egy indexre validált KOMBINÁCIÓS logikát (nem csak
  paramétert) más eszközosztályra átvinni, változtatás nélkül, ÖNMAGÁBAN torzíthatja a mérést —
  a "nincs él" következtetés levonása előtt a komponenseket egyenként is meg kell nézni, nem
  elég a végső (AND-olt) számot nézni. Ez ugyanaz a fajta lecke, mint a DST-torzítás esete
  (ORB-fejezet fent) — egy örökölt, korábban máshol validált feltevés (ott: session-óra; itt:
  kombinációs logika) csendben torzíthatja az új kontextusban vett mérést.

  **⚠️ MÓDSZERTANI ÖNKORREKCIÓ (2026-09-02): az első szignifikancia-teszt-próbálkozás
  (`research/single_filter_significance_test.py`) HIBÁS volt** — egy rövid, fix (6 bar/1 óra)
  horizontú irány-találati arányt mért (a `dst_aware_orb_premarket_recheck.py`-nál bevált
  sablont követve), de ez NEM ugyanaz a mechanizmus, mint a PF, ami trailing-stoppal, VÁLTOZÓ
  hosszúságú, ASZIMMETRIKUS kifizetésű trade-eket futtat (alacsony találati arány, de nagyobb
  átlagos nyertes, mint vesztes — klasszikus trend-követő szerkezet). A fix-horizontú teszt ezért
  tiszta nullát adott (GOLD-EMA 50.0%, NGASCash-Bollinger 45.3%, NGASCash-EMA 50.3%, mind
  p>=0.05) — ez FÉLREVEZETŐ volt, mert rossz kérdést tett fel. **Tanulság: egy bevált
  teszt-sablon más kifizetési szerkezetű stratégiára való kritikátlan átvitele saját maga is
  torzítást okozhat — pontosan ugyanaz a hibaosztály, mint a DST- vagy a kombinációs-logika-
  átvitel, csak most a validáció OLDALÁN.**

  **Helyes teszt (`research/single_filter_holdout_bootstrap.py`): a TÉNYLEGES, trailing-stop-
  alapú trade-logot osztottuk kronologikus discovery/holdout részre, bootstrap-CI-vel:**

  | Szimbólum/Szűrő | Discovery PF | Bootstrap 90% CI | Holdout PF |
  |---|---|---|---|
  | GOLD. (csak-EMA) | 1.10 | [0.85, 1.40] | 1.11 |
  | NGASCash (csak-Bollinger) | 0.98 | [0.70, 1.33] | **1.81** |
  | NGASCash (csak-EMA) | 0.97 | [0.76, 1.22] | **1.71** |

  A discovery-szakasz CI-je mindhárom esetben átfedi az 1.0-t (a minta méretéből adódóan nem
  zárható ki magabiztosan a véletlen), DE mindhárom esetben a HOLDOUT PF>1, és NGASCash-nél
  erős (1.71-1.81) — a KEDVEZŐ irányba tér el a discoverytől (nem a korábbi premarket-irány
  esetnél látott túlilleszkedési minta, ahol a holdout összeomlott). NGASCash-nél két különböző
  szűrő (Bollinger és EMA) is hasonló, erős holdout-eredményt ad, ami nem tűnik véletlen
  egybeesésnek. **Ez NEM lezárható "nincs él" eset, de nem is "biztosan van él" — a projekt
  szabálya szerint a következő lépés a Strategy Tester-es, valós spreddel futó megerősítés**
  (ugyanaz a lépés, ami az indexeknél is a végső döntést hozta LastHourContinuation-nél).
  **✅ LEZÁRVA (2026-09-12)**: a hiányzó permutációs teszt pótolva (`research/single_filter_
  permutation_test.py`), IC Markets-en (XAUUSD=GOLD., XNGUSD=NGASCash). Egyedül XAUUSD/csak-EMA
  ment át mind a 3 kritériumon (discovery p=0,033, hold-out PF=1,15 konzisztens, n=665) — MQL5-be
  portolva (`XAUUSD_EMA_Candidate_EA.mq5`) és Strategy Tester-rel megerősítve: a teljes periódusú
  futtatás PF=1 volt, DE History Quality csak 15% (szintetikus-tick csapda, lásd
  `regime_framework_gotchas` 6. pont) — a tisztán valós-tick-es ablakra (2026-04-01–2026-09-11)
  szűkített újrafuttatás **PF=0**-t adott. **XNGUSD mindkét szűrője már a permutáción megbukott**
  (gyanús, egy piaci eseményre visszavezethető hold-out-kiugrás). **A teljes szál VÉGLEGESEN
  ELUTASÍTVA** — lásd `SESSION_LOG.md` 2026-09-12 bejegyzéseit a teljes indoklásért. Tanulság: a
  költség nélküli Python-mérés, még a legszigorúbb (permutáció+hold-out) szűrőn átjutva is,
  szisztematikusan túlbecsülheti az élt — a Strategy Tester valós-tick-es lépés nem elhagyható.

- **📐 KERESZT-PROJEKT VALIDÁCIÓS SZABVÁNY (2026-08-30, a forex testvér-projektből átvéve)**: a
  forex-adaptáció (`d:\XM\optuna_forex\regime_framework\docs\VALIDATION_METHODOLOGY.md`) rögzítette
  a nála 2026-08-30-ig kialakult, ennél a projektnél a build-fázis KEZDETEKOR (2026-08-19) még HIÁNYZÓ
  szigorú validációs láncot (permutációs teszt + kronologikus hold-out + koncentráció-teszt +
  kereszt-instrumentum-konzisztencia, elejétől fogva alkalmazva). **A KÖVETKEZŐ újrahangolásnál (kb.
  2026-10, negyedéves ütemezés) ezt a láncot kell követni**, nem a 2026-08-19-i, permutáció/hold-out
  nélküli szintű validációt megismételni — lásd a fenti dokumentumot a teljes indoklásért, és
  `SESSION_LOG.md` 2026-08-30-i bejegyzését a kontextusért.
- **🟢✅ ÚJ, VALIDÁLT MECHANIZMUS (2026-08-20): "utolsó óra folytatódás" — MÁSODIK teljesen
  validált, mindhárom szimbólumon nyereséges eredmény a mai munkamenetben.** UP-trend napokon
  (16:30-20:00 session-szakasz pozitív hozammal) LONG a session utolsó órájára (20:00-21:00
  szerver-idő). Kiindulómérés + önálló szabály + durva költségbecslés is mindhárom szimbólumon
  pozitív: NETTÓ PF US100 1.59, US500 1.42, US30 **1.35 (a legnagyobb abszolút nettó profittal,
  +360.23 — ELSŐ eset, hogy US30 genuinely jól teljesít, nem csak "kevésbé rosszul")**. Fontos
  tisztázás: ez NEM a régi, mindig veszteséges "EODRebalancing" (az egy másik, durvább mechanizmus
  volt egyetlen órára). **Hátralévő: formális komponens + architekturális döntés (IDŐALAPÚ
  aktiválás, nem trend_band-regime — hogyan illeszkedik a meglévő komponensek mellé) + Strategy
  Tester-es megerősítés.** Lásd SESSION_LOG.md a teljes indoklásért.
- **⚠️⚠️ KRITIKUS KORREKCIÓ (2026-08-20): a "2022-01-01-ig kiterjesztett ablak" TÉVES volt.** Az
  MT5 `copy_rates_range()` a szimbólum tényleges története ELŐTTI kérésre a legkorábbi elérhető
  bar-ra "tapad rá" (hamis pozitívot adva, nem None-t), ez rejtette el, hogy a valós adat csak
  ~2023-10-13-tól létezik ("Cash Ultra Low" termékcsalád indulása ennél a brókernél). Javítva
  (`data/mt5_source.py`: bar-időbélyeg validáció + retry + hangos figyelmeztetés). **A korábban
  "2022-01-01"-gyel futtatott mérések EREDMÉNYEI ÉRVÉNYESEK maradnak** (a lekért adat valós volt,
  csak a valós ~2023-10-19-es kezdettől) — a START_DATE konstansok 2023-11-01-re javítva mindenhol.
  Lásd SESSION_LOG.md a teljes indoklásért.
- **🕐 ÚJ, NYITOTT PONT (2026-08-20): az MT5 szerver FIX UTC+3-on fut (nem követi a DST-t)** —
  `research/check_server_timezone_offset.py` méréssel megerősítve. Emiatt a US500 valós nyitása
  (9:30 US-keleti idő) évszaktól függően szerver-idő szerint 16:30 (US nyári időszámítás) és 17:30
  (US téli időszámítás) között vándorol — a `session_phase.py` GROUPS fix "17 órás" US
  opening_range_core konfigja az év egyik felében fél-egy órával elcsúszhat a valós nyitástól.
  Érdemes lenne DST-tudatosra bővíteni (a hónap alapján 16 vagy 17 órás kezdettel), ha valaha újra
  bekötnénk a `SessionPhaseClassifier`-t komponens-kapuzásra. Az éles komponensek fix 16:30-as
  session-ablaka (Optuna-hangolt) véletlenül közelebb esik a nyári időszak valós nyitásához.
- **🔬 [az alábbi bejegyzés dátum-címkézése elavult, lásd fent — az EREDMÉNYEK érvényesek] US30
  gyengesége megerősítve, NEM mintavételi zaj.** A 2025-01-01 óta tartó rövid (~19 hónap) ablak túlnyomórészt bullish volt
  (LONG/SHORT egyensúlytalanság-figyelmeztetések) — 2022-01-01-re (4,7 év, lefedi a 2022-es
  medvepiacot) kiterjesztve mindkét fő komponens validációja. Eredmény: **US100/US500 mindkét
  komponensen stabilan tartja magát** (TF PF 2.39/1.26, MR PF 1.24/1.07), **US30 viszont MINDKÉT
  komponensen gyenge/negatív marad** (TF PF 1.00 — nulla él, MR PF 0.87, PnL -323.78 — a rövid
  ablakhoz képest NŐTT a veszteség). A korábbi "US30 is nyereséges lett a kettős megerősítéssel"
  eredmény (rövid ablakon PF 1.21) nagyrészt a kedvező, rövid ablak torzítása volt. **Javaslat: élő
  bevezetésnél fontolóra venni US30 kizárását vagy külön újrahangolását.** Emellett egy valódi bug
  is előkerült és javítva lett: `data/mt5_source.py` `fetch_rates()` 24+ hónapos egyetlen
  `copy_rates_range()` hívásra hibázott (kemény terminál-oldali bar-szám-korlát, lásd
  `research/diagnose_large_range_fetch.py`) — mostantól automatikusan ≤120 napos darabokra bontva
  kéri le és fűzi össze, ez minden jövőbeli hosszú-ablakú lekérésre vonatkozik.
- **⚠️ ÚJ, FONTOS MÓDSZERTANI KORLÁT (2026-08-20): a 3 US-szimbólum (US100/US500/US30) erősen
  korrelált, NEM kezelhető 3 független validációs pontként.** `research/us_index_correlation_
  check.py` valós MT5-adaton: hozam-korreláció 0.78-0.95 a teljes idősoron, 0.83-0.96 az
  OPENING_RANGE órákban (MÉG magasabb). Lag-korreláció ~0 (nincs kihasználható vezetés-lemaradás
  M10-en). Ez visszamenőleg árnyalja a korábbi "mindhárom szimbólumon pozitív" eredményeket
  (statisztikailag kb. 1 fő jel + 2 visszhang, nem 3 független bizonyíték), és élő bevezetésnél
  figyelmeztet: a 3 szimbólumon egyszerre nyitott pozíciók KONCENTRÁLT kockázatot jelentenek, nem
  diverzifikációt.
- ~~Pontos sávhatárok a `SessionPhaseClassifier`-hez~~ — **részben megválaszolva**, lásd 2.1: három
  eltérő session-alak (US / JP225 / EU-dupla-csúcs), ÉS a stabilitás-ellenőrzés (két félidő
  összevetve) mind az 5 instrumentumnál megerősítette — GER40/EU50 tökéletes (Jaccard 1.00),
  US100/US500 erős (0.67/0.75), JP225 a leggyengébb, de még mindig pozitív (0.50).
- **DÖNTÉS: a `SessionPhaseClassifier` kézzel karbantartott, instrumentum-csoportos konfigot kap**
  (nem automatikus kalibrációt) — a `research/session_phase_exploration.py` mérés+stabilitás
  eredménye alapján feltöltve. A "mag"-órákat (mindkét félidőben megjelentek) a fázis biztos
  részének vesszük, a csak egyik félidőben megjelenő "szél"-órákat puffer-zónaként. Ezzel a
  `regime/session_phase.py` osztály megírható — ez a következő konkrét lépés.
- Trend-sáv határai (hány sáv, hol legyen az "átmeneti/whipsaw" zóna).
- Volatilitás-percentilis ablakának hossza (hány napos/bar-os historikus referencia).
- Komponens B/C/D tartalma — teljesen nyitott. **A TRANSITIONAL-zóna dedikált komponensét NEM
  folytatjuk** — kiindulókísérlet (2026-08-20, `research/transitional_zone_experiment.py`, mind a
  3 US-szimbólumon valós MT5-adaton) megerősítette, hogy a meglévő komponensek logikája 5/6 esetben
  egyértelműen rosszabbul teljesít TRANSITIONAL-ban (a legdrámaibb: US30 TrendFollowing marginális
  PnL-hozzájárulása -250.97) — az eredeti "ne kereskedj" tervezési feltevés empirikusan
  megerősítve. Egyetlen kivétel (US30 MeanReversion, +166.26) gyenge alap folytatáshoz.
  A `HIGH vol_band`-ra célzó dimenziót is megvizsgáltuk (2026-08-20) — mindkét komponens
  `validate()`-je kapott egy tartós `vol_band`-bontást (LOW/HIGH trade-ek win-rate/PnL-je). Valós
  MT5-eredmény: **NINCS konzisztens minta** — US100-nál a két komponens EGYMÁSSAL ELLENTÉTES
  irányba mutat (MR-nél LOW jobb, TF-nél HIGH jobb), a LOW-vol minta mindenhol kicsi (8-30 trade,
  jórészt a 30-as küszöb alatt). Strukturális ok: mindkét komponens belépési mechanizmusa
  eredendően magasabb volatilitású pillanatokban aktiválódik gyakrabban (megerősítve a
  `MarketConditionClassifier` kontroll-futtatásával: a bar-eloszlás kiegyensúlyozott, a torzítás a
  belépési mechanizmusból ered). **Dedikált HIGH/LOW-vol komponens tervezése NEM folytatódik** —
  ez már a MÁSODIK eset (TRANSITIONAL után), ahol egy olcsó diagnosztika időben leállított egy
  valószínűleg kifizetődés nélküli fejlesztést.
  **ORB (Opening Range Breakout) irányban is három kiindulókísérletet futtattunk (2026-08-20,
  mind US500Cash#-en, a fenti korrelációs korlát miatt csak egy szimbólumon) — mind a három
  NEGATÍV:** (1) klasszikus range-kitörés+folytatódás (`research/orb_exploration.py`) — 356 napból
  48 (13,5%) zárult kitöréssel, followthrough-arány 43,8% (véletlen alatt), átlagos kitörés-utáni
  mozgás -0,105 ATR (visszafordulás, nem folytatódás); (2) premarket-irány előrejelzi-e a nyitás
  utáni irányt (felhasználói ötlet) — 47,5% találati arány (n=356), gyakorlatilag véletlen szint;
  (3) maga a premarket/aftermarket (CORE_SESSION) szakasz trendszerű-e Kaufman Efficiency Ratio-val
  mérve (felhasználói ötlet, `research/premarket_trendiness_check.py`, "azonos lépésméret, véletlen
  előjel" null-hipotézissel) — excess ER -0,0073 (nulla körüli), a blokkoknak csak 39,8%-a haladta
  meg a véletlen-bolyongás alapvonalat. **ORB-irányú fejlesztés NEM folytatódik** — ez a
  HARMADIK-NEGYEDIK-ÖTÖDIK eset egymás után, ahol olcsó mérő-script (nem teljes komponens) zárta
  le az ágat kódolási munka nélkül.

  **🔁 ÚJRAELLENŐRZÉS (2026-09-02): a fenti három ORB-mérés a `session_phase.py` STATIKUS,
  DST-tudatlan óra-konfigján futott (fix 17-22 órás US opening_range) — miközben időközben kiderült
  (fent, 2026-08-20-i "NYITOTT PONT"), hogy a szerver fix UTC+3, a valós US-nyitás pedig DST miatt
  16:30/17:30 között vándorol. Gyanú: kb. az év felében (274/409 nap) a statikus konfig KÉSŐN
  kezdte az OPENING_RANGE-et, ami szennyezhette a fenti méréseket. Új script
  (`research/dst_aware_orb_premarket_recheck.py`, `zoneinfo`-alapú, pontos dátumú DST-számítással)
  UGYANAZON az adaton, egy futáson belül összevetette a statikus és a DST-tudatos besorolást:
  - (1) klasszikus kitörés+followthrough: **változatlan** (43.8%→43.3% followthrough, ha valami,
    kicsit MÉG inkább visszafordulás) — **elutasítás megerősítve**.
  - (3) CORE_SESSION Kaufman ER perzisztencia: enyhén kevésbé negatív (excess ER -0.0079→-0.0038,
    pozitív blokkok 38.3%→43.0%), de nem éri el a saját (>55-60%) küszöböt — **elutasítás
    megerősítve**.
  - (2) **premarket-irány → nyitás utáni irány: 47.5%→57.4% (n=356→230)** — érdemi ugrás, átlépi a
    saját küszöböt. **Ez indokolta a szigorúbb utóvizsgálatot** (lásd alább).

  **Szigorú utóvizsgálat (2026-09-02, `research/premarket_direction_significance_test.py`,
  kronologikus discovery/holdout felosztás + permutációs teszt, a 2026-08-30-i kereszt-projekt
  validációs szabvány szerint):** a discovery szakaszon (n=161, 2025-03-31–2026-04-22) a találati
  arány 61.5%-ra ugrott, permutációs p-érték 0.0058 (statisztikailag szignifikáns) — DE a holdout
  szakaszon (n=69, 2026-04-23–2026-07-31, EGYETLEN, tuningmentes ellenőrzés) a találati arány
  **47.8%-ra esett vissza, azaz a véletlen szint ALÁ** — ellentmond a discovery jelzésnek.
  **VÉGSŐ VERDIKT: a premarket-irány hipotézis NEM éli túl a hold-out ellenőrzést — az elutasítás
  fennmarad**, de most már tudjuk, hogy ez NEM a korábbi DST-mérési torzítás miatt van (azt a
  DST-javítás valóban felfedte és korrigálta), hanem mert a discovery-szakaszbeli 61.5%-os
  mintázat valószínűleg egy nem-stacionárius, adott időszakra jellemző jelenség volt, nem tartós
  statisztikai él. **ORB-irányú fejlesztés továbbra sem folytatódik**, ezt a kérdést mostantól
  lezártnak tekintjük.

  **🟢✅ DE: egy MÁSIK ág (kettős megerősítés — Bollinger-kitörés ÉS EMA-keresztezés egyszerre)
  sikeres volt, és 2026-08-20-án BEÉPÜLT a `TrendFollowingComponent`-be** (nem külön komponens —
  a `DoubleConfirmationComponent` és validációs scriptje törölve, mert a beépítés után szó szerint
  duplikálták volna ugyanazt a logikát). Öt validációs kapun ment át: Bollinger-kitörés önmagában
  pozitív (US100 PF 1.66, US500 PF 1.50) → a Bollinger/TrendFollowing jelei <60-70%-ban fedik át
  (nem redundáns) → ELLENTÉTES napokon egyik komponensnek sincs éle → EGYETÉRTŐ napokon MINDKÉT
  komponens érdemben jobban teljesít (US30-nál negatívból pozitívba fordul) → önálló kettős-
  megerősítés MINDHÁROM szimbólumon nyereséges (US100 PF 2.66, US500 PF 1.40, US30 PF 1.21) →
  durva költség-becslés után is NETTÓ PF>1.0 mindhárom szimbólumon (2.56/1.33/1.15) → a
  `TrendFollowingComponent`-be építve (RSI-vel együtt) valós MT5 adaton PONTOSAN ugyanezt adta —
  az RSI-redundancia élesben is megerősítve.
  **✅✅ MINDEN HÁTRALÉVŐ LÉPÉS MEGTÖRTÉNT (2026-08-20)**: MQL5-port szinkronizálva, `.set`
  preset-ek Optuna-újrahangolva a korrigált (2023-11-01-től valós) adaton, Strategy Tester valós
  spreaddel megerősítette: **US100 (PF 1.37, Sharpe 8.30, DD 6.43%) és US500 (PF 1.10, Sharpe 2.75,
  DD 2.35%) megbízhatóan pozitív, US30 (PF 0.83, nettó -618.74, DD 45.10%) VESZTESÉGES valós
  költséggel.** Javaslat: US30 kizárása élő bevezetésnél. Lásd SESSION_LOG.md a teljes táblázatért.
- ~~Melyik instrumentum(ok)on történjen az első teljes validáció~~ — a 2.1 mérés már mind az 5
  jelölten (US100, US500, JP225, GER40, EU50) lefutott, mind az öt szimbólumnév él a számlán.
- EODRebalancing és TurnaroundTuesday sorsa — kimaradnak-e teljesen, vagy egy módosított
  formában (pl. több instrumentum összevont adatán) újra próbálkozunk velük.

---

## 8. MQL5/MT5 EA port állapota

A build-sorrend (6. pont) lezárása és az Optuna-hangolás (7. pont) után a felhasználóval egyeztetve
megkezdődött az élő portolás — lásd PLAN.md 0.1 (állandó szempont, nem a végén megoldandó feladat).

**Módszertan minden portolt darabnál:** mivel MQL5-kódot nem lehet erről a gépről lefordítani/
tesztelni, minden darabnál előbb egy Python REFERENCIA-implementáció épül (kézi ciklusokkal, NEM
pandas-vektorizált eszközökkel — pontosan úgy, ahogy az MQL5 verzió is fog működni), amit bar-onként
összevetünk a már validált batch-verzióval. Csak a BIZONYÍTOTTAN egyező algoritmust írjuk át MQL5-re.
A szintaxis-ellenőrzés (MetaEditor compile) és a Strategy Tester-es újramegerősítés (PLAN.md 0.1, 5.
szabály) mindig a felhasználó feladata marad — ezt Python-oldali munkával nem lehet kiváltani.

| Darab | Fájl | Státusz |
|---|---|---|
| `MarketConditionClassifier` élő verziója | `RegimeClassifier.mqh` | ✅ Algoritmus Pythonban bizonyítva (0 eltérés 23014 bar-on a batch verzióhoz képest), MQL5-re átírva. Fordítás/Strategy Tester még hátravan. |
| `MeanReversionComponent` MQL5 portja | `MeanReversion.mqh` | ✅ `CheckEntry()` portolva. Nincs `check_exit()` — a natív broker SL/TP váltja ki a Python pesszimista `resolve_fixed_exit()`-jét (lásd 0.1, 3. szabály). ✅ Fordítás sikeres. Strategy Tester még hátravan. |
| `TrendFollowingComponent` MQL5 portja | `TrendFollowing.mqh` | ✅ `CheckEntry()` + `ComputeTrailSl()` portolva. A trailing stop élesben is megmarad (nem backtest-csak mechanizmus), `PositionModify()`-n keresztül a fő EA-ban. Egyszerű, kézzel számolt RSI (nem `iRSI()`). ✅ Fordítás sikeres. Strategy Tester még hátravan. |
| XOR-dispatch fő EA | `RegimeFramework_EA.mq5` | ✅ RANGING→MeanReversion / TRENDING→TrendFollowing / TRANSITIONAL→egyik sem, ugyanaz a mintázat, mint `core/engine.py` `_select_component()`-je. Napi max. egy belépés + napvégi kényszerzárás. ✅ Fordítás sikeres. **✅ Strategy Tester-es megerősítés MINDHÁROM US-szimbólumra megtörtént, lásd lent.** |
| `SessionPhaseClassifier` élő verziója | — | Python oldalon kipróbálva komponens-kapuzásra, VISSZAVONVA (lásd 6. build-sorrend pont) — MQL5 port emiatt nem is releváns többé, az EA a fix óraablakot használja. |
| `LastHourContinuationComponent` MQL5 portja (2026-08-21) | `LastHourContinuation.mqh` | ✅ `IsRegimeEligible()` szándékosan MINDIG `true` (time_gated, trend_band-független — lásd `core/engine.py` docstring). `ComputeTrendReturn()` a lezárt barokból, bar[1]-től visszafelé építi a napi kumulált log-hozamot. Saját, korábbi zárási határidő (`IsSessionEndBar()`), amit a fő EA `OnTick()`-je a `_select_component()`-alapú dispatch UTÁN, fallback-ként hív meg — ugyanaz az elsőbbségi szabály, mint a Python `Engine.run()`-ban. Optuna-hangolás MÉG NEM történt, alapértékekkel megy élesben. ✅ Fordítás sikeres (projekt-mappa ÉS élő terminál is). **✅ Strategy Tester-es megerősítés MINDHÁROM US-szimbólumra megtörtént, lásd lent.** |
| `FridayShortComponent` MQL5 portja (2026-08-21/22) | `FridayShort.mqh` | ✅ `quota_exempt_time_gated` komponens (lásd `core/engine.py` docstring) — csak akkor kap esélyt, ha a napi kvóta már elfogyott. Fontos MQL5-specifikus felfedezés: `MqlDateTime.day_of_week` (0=Vasárnap) ELTÉR a Python pandas `dayofweek`-től (0=Hétfő) — az EA `(dt.day_of_week+6)%7`-tel konvertál. A belépés (23:00) egybeesik az általános `InpForceCloseHour`-ral, ezért saját, elsőbbséges `IsFsHoldEnd()` zárási szabályt kapott, kizárva az általános kényszerzárás alól. ✅ Optuna-hangolás MEGTÖRTÉNT (2026-08-22), a preset-ek/EA-alapértékek a hangolt értékeket tartalmazzák. ✅ Fordítás sikeres (projekt-mappa ÉS élő terminál is). **✅ Strategy Tester-es megerősítés MINDHÁROM US-szimbólumra megtörtént (2026-08-22)** — US500 tiszta javulás, US100 vegyes/pozitív, US30 magasabb profit de romló kockázati profil (Sharpe 10.57→5.60, DD 6.44%→9.07%) — lásd SESSION_LOG.md. |

**Strategy Tester-es megerősítés — MINDHÁROM US-szimbólumra (2026-08-19/20, M10, 2025.01.01–
2026.08.15, `.set` preset-ekkel, lásd `presets/` mappa):**

| Szimbólum | Python pontszám | MT5 PF | MT5 profit | Max DD (equity) | Sharpe | Recovery Factor | Trades |
|---|---|---|---|---|---|---|---|
| US100Cash# (Nasdaq) | 99.11 | 1.64 | +656.80 | 5.38% | 11.08 | 5.76 | 286 |
| US500Cash# (S&P500) | 9.46 | 1.11 | +28.63 | 2.53% | 2.28 | 0.74 | 320 |
| US30Cash# (Dow Jones) | 36.65 | 1.13 | +209.69 | 11.02% | 2.12 | 1.06 | 297 |

US100 egyértelműen kiemelkedik mindkét oldalon (Python ÉS MT5). US30/US500 hasonló profit factorral
fut, de US30-nál a drawdown több mint négyszerese US500-énak — a magasabb abszolút profit nagyobb
kockázat mellett jön, érdemes ezt figyelembe venni pozícióméretezésnél éles bevezetéskor. **Ez
teljesíti a PLAN.md 0.1, 5. szabályát** ("minden komponens, ami eljut az EA-szintig, kötelezően
újramegerősítendő az MT5 Strategy Testerében") mindhárom aktív US-szimbólumra.

**Strategy Tester-es megerősítés — kettős-megerősítés + LastHourContinuation EGYÜTT (2026-08-21,
M10, 2023.11.01–2026.08.01, valós spreaddel, 1500 EUR induló tőke):**

| Szimbólum | PF | Sharpe | Max DD | Net Profit | Trades (MR/TF/LHC) |
|---|---|---|---|---|---|
| US100Cash# | 1.70 | 13.89 | 4.21% | +1120.55 | 543 (256/161/126) |
| US500Cash# | 1.40 | 8.52 | 1.66% | +141.57 | 533 (252/158/123) |
| US30Cash# | 1.05 | 1.05 | 22.18% | +134.32 | 523 (248/171/104) |

A LastHourContinuation trade-aránya mindhárom szimbólumon 20-23% körül stabil, és mindenhol
JAVÍTOTT a csak-kettős-megerősítéses állapothoz képest (részletes előtte/utána bontás:
`docs/SESSION_LOG.md` 2026-08-21 bejegyzései).

**Optuna-hangolás a LastHourContinuation-nel EGYÜTT (2026-08-21) — a preset-ek/EA-alapértékek
mostantól ezeket az értékeket tartalmazzák:**

| Szimbólum | WF pontszám (előtte→utána) | PF (előtte→utána) | Sharpe (előtte→utána) | Max DD (előtte→utána) |
|---|---|---|---|---|
| US100Cash# | 54.70→78.61 | 1.70→1.62 | 13.89→11.04 | 4.21%→4.30% |
| US500Cash# | 6.97→6.59 | 1.40→1.36 | 8.52→**9.15** | 1.66%→**1.37%** |
| US30Cash# | 18.22→**23.91** | 1.05→**1.34** | 1.05→**10.57** | 22.18%→**6.44%** |

**US30Cash# a korábban egyértelműen veszteséges (-618.74, PF 0.83) állapotból a mai kettős
körön át (alapértékes LHC → hangolt hármas) drámaian javult (+557.46, PF 1.34, DD 6.44%) — a
korábbi "kizárandó, kockázatos szimbólum" megítélés FELÜLVIZSGÁLANDÓ.** US100/US500-nál a
walk-forward pontszám és a teljes-periódusú Strategy Tester nem mindig mozog együtt (a
célfüggvény a fold-onkénti konzisztenciát optimalizálja, nem a nyers profitot) — ez elfogadható,
szándékos tervezési döntés, nem hiba.

**SessionPhaseClassifier Python-oldali bekötése (2026-08-19):** mindkét komponens a hardcode-olt,
US-specifikus "amerikai session" (16:30-21:00) óraablak helyett mostantól a `RegimeState.
session_phase == "CORE_SESSION"` feltételt nézi (OPENING_RANGE/ROLLOVER kizárva) — a
`SessionPhaseClassifier`-t az `Engine`/az egyes komponensek `validate()`-je tölti fel (mindkettő
kapott egy kötelező `symbol` paramétert). Indoklás: a régi hardcode-olt US-ablakot változtatás
nélkül alkalmaztuk JP225/GER40/EU50-re is, holott ezeknek egészen más az empirikusan mért aktív
session-ablakuk — plauzibilis, azonosítható forrása lehetett a gyengébb GER40/EU50 eredménynek.
Determinisztikus egységteszt + végpontig-futtatás hibamentes.

**Valós MT5 eredmény (2026-08-19, Optuna újrafuttatva) — ÖSSZESSÉGÉBEN ROSSZABB lett, csak
részben igazolta a hipotézist:**

| Szimbólum | Kockázat-korrigált pontszám (előtte→utána) | Pozitív fold-ok |
|---|---|---|
| US100Cash# | 99.11 → **5.14** (összeomlás) | 6/6 → 5/6 |
| US500Cash# | 9.46 → 7.86 | 6/6 → 6/6 |
| JP225Cash# | 117.92 → **6.82** (összeomlás) | 5/6 → 4/6 |
| GER40Cash# | 23.15 → **30.20** (javult) | 5/6 → 6/6 |
| EU50Cash# | 5.52 → 8.78 (javult) | 5/6 → 5/6 |

Összesített pontszám ~255→~59 (~-77%). **Diagnózis:** a régi, "hibás" US-ablak (16:30-21:00)
VÉLETLENÜL majdnem pontosan egybeesett a `SessionPhaseClassifier` "OPENING_RANGE" óráival az
US-csoportnál — US100/JP225-nél éppen az OPENING_RANGE órákban volt a tényleges él, NEM annak
ellenére. Az "OPENING_RANGE rossz" feltevés sosem volt empirikusan megalapozott (szemben a
ROLLOVER-rel, amire VAN mért spread-tágulás bizonyíték).

**Javítás (felhasználóval egyeztetve): `is_regime_eligible()` mostantól CSAK a ROLLOVER fázist
zárja ki, az OPENING_RANGE-et NEM.** Determinisztikus egységteszt frissítve, lefutott.

**Valós MT5 eredmény (2. verzió) — MÉG ROSSZABB, összesítve negatívba fordult:**

| Szimbólum | v0 (eredeti) | v1 (CORE_SESSION-only) | v2 (csak ROLLOVER) |
|---|---|---|---|
| US100Cash# | 99.11 | 5.14 | 4.27 |
| US500Cash# | 9.46 | 7.86 | 7.86 |
| JP225Cash# | 117.92 | 6.82 | **-46.13** |
| GER40Cash# | 23.15 | 30.20 | 25.81 |
| EU50Cash# | 5.52 | 8.78 | 7.83 |
| **Összesen** | **~255** | **~59** | **~-0.4** |

Ok: US/JP csoportnál a `rollover` halmaz a `GROUPS` konfigban ÜRES — a v2 szabály ezekre a
szimbólumokra gyakorlatilag "nincs szűrés"-t jelentett. Felhasználói megfigyelés árnyalta tovább a
képet: nem egységes "US-session mindent visz" jelenség (GER40/EU50 javult a fix ablak nélkül),
inkább szimbólum-specifikus (JP225-nél valószínűleg a globálisan domináns US-szakasz számít, mert
0-24h kereskedett CFD; GER40/EU50-nek saját, valódi éle van a saját óráiban).

**VÉGSŐ DÖNTÉS (felhasználóval egyeztetve): a SessionPhaseClassifier-alapú kapuzást TELJESEN
VISSZAVONTUK** — mindkét komponens és az Engine visszaállt az eredeti, fix 16:30-21:00 óraablakra.
`symbol` paraméter eltávolítva a `validate()`/`run()`-ból (nem szükséges többé). Smoke teszt
megerősítette a helyes visszaállítást. **Nyitott ötlet jövőre:** a session-ablak határait Optuna-
tanulhatóvá tenni szimbólumonként (nem implementálva).

**Kör-szűkítés US-indexekre (2026-08-19):** időzítés miatt a felhasználóval egyeztetve ebben a
körben CSAK a US-csoportra fókuszálunk (JP225/GER40/EU50 később). Bővítve: `US30Cash#`,
`US400Cash#`, `US2000Cash#`. Valós MT5 újrafuttatás megerősítette a revert helyességét (US100/US500
pontszáma PONTOSAN egyezik a v0 baseline-nal: 99.11 / 9.46). Az új szimbólumok: US30Cash# ígéretes
(36.65, 4/6 fold pozitív), US400Cash#/US2000Cash# gyenge/határeset (3.81/3.09) — vanilla
komponens-logikával, további finomítás nyitott kérdés.

**Fejlesztői környezet (2026-08-19):** a 4 MQL5-fájl éles helye
`%APPDATA%\MetaQuotes\Terminal\<TERMINAL_ID>\MQL5\Experts\
RegimeFramework\` (a "<TERMINAL_ID>..." terminál — ez a `D:\MT5` telepítésre mutat, ez volt aktív a mai
Python MT5-adatlekéréseknél is). A `d:\XM\Optuna` mappa NEM alkalmas közvetlen MQL5-fejlesztésre a
VSCode "MQL Tools" kiterjesztéssel (annak a workspace-mappa nevének kötelezően `MQL5`-nek kell
lennie) — ezért `d:\XM\Optuna\regime_framework.code-workspace` egy multi-root workspace-t hoz létre,
ami EGYÜTT nyitja meg a Python-projektet és a fenti MQL5-mappát. A fordításhoz szükséges kiterjesztés-
beállítások (`mql_tools.Metaeditor.Metaeditor5Dir`/`Include5Dir`) az ottani `.vscode/settings.json`-
ban vannak.

**Fontos tervezési javítás a portolás közben:** a `Signal` struct eredetileg ABSZOLÚT SL/TP árat
számolt a lezárt bar close-ához képest (mint egy Python backtest) — élőben ez helytelen volna, mert
a tényleges fill ár az aktuális ask/bid. Átalakítva TÁVOLSÁG-alapúra (`slDistance`/`tpDistance`),
amit a fő EA az ÉLŐ ask/bid-hez ad hozzá — ugyanaz a minta, mint a meglévő
`AnomalyMeanReversion_EA.mq5` `OpenLong()`/`OpenShort()`-ja. Mindhárom `.mqh` fájl kapott
include-guard-ot (`#ifndef`/`#define`/`#endif`) a többszörös `#include` miatt (a fő EA közvetlenül
ÉS a `TrendFollowing.mqh` a `MeanReversion.mqh`-n keresztül is includeolja a közös fájlokat).
