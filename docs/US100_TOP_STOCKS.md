# US100 top-5 komponens-részvény — kutatási nyilvántartás

Az "ÚJ KUTATÁSI MÉRFÖLDKŐ: US100 top-5 komponens-részvény" (lásd `SESSION_LOG.md`, 2026-09-03)
irány adatait itt gyűjtjük, ahogy a vizsgálat halad — nem egy lezárt eredmény, hanem élő
munkatábla. A stratégia-specifikus, lezárt tanulságok (mi validált, mi bukott) a `PLAN.md` "2."
táblázatába kerülnek majd, ha idáig eljutunk; ez a fájl a köztes, nyers adatokat tartja.

---

## 1. Szimbólum-azonosítás

Szúrópróba (`research/us100_top_stocks_spotcheck.py`, 2026-09-03) — a `Stocks\US` csoportban
névtöredék-keresés, NEM feltételezett pontos név (lásd `broker_symbol_naming_mismatch` memória-
bejegyzés analóg tanulsága a Cash-indexeknél).

| Cég | Bróker szimbólumnév | Leírás (bróker) | Megjegyzés |
|---|---|---|---|
| Apple | `Apple` | Apple Inc (AAPL.OQ) | |
| Microsoft | `Microsoft` | Microsoft Corp (MSFT.OQ) | |
| Nvidia | `Nvidia` | NVIDIA Corp (NVDA.OQ) | |
| Amazon | `Amazon` | Amazon.com Inc (AMZN.OQ) | |
| Alphabet/Google | `Google` | Alphabet Inc (GOOG.OQ) | GOOG (nem GOOGL) osztály |
| Meta | `Facebook` | META PLATFORMS INC (META.OQ) | a bróker "Facebook" néven listázza |
| Broadcom | `Broadcom` | Broadcom Inc (AVGO.OQ) | |
| ~~Howmet Aerospace~~ | ~~`HowmetAerospace`~~ | Howmet Aerospace Inc (HWM.N) | **HAMIS TALÁLAT** — a "Meta" névtöredék véletlenül illeszkedett a "Howmet" szóba, NEM tech-részvény, kizárva |

## 2. Durva adatmélység (szúrópróba, néhány rögzített dátum, NEM bináris keresés — csak tájékozódás)

| Szimbólum | Legalább ettől visszamegy | Megjegyzés |
|---|---|---|
| Apple | 2017-06-08 | |
| Microsoft | 2017-06-22 | |
| Nvidia | 2017-06-05 | |
| Amazon | 2017-06-08 | |
| Google | 2016-05-03 | |
| Meta (Facebook) | 2017-06-22 | |
| Broadcom | 2016-04-22 | |

Mindegyik jóval mélyebb, mint a ma vizsgált Cash-indexek (~2023-10-28) — ez POZITÍV jel, bőven
elég adat lenne walk-forward-höz.

### 2.1 Pontos (bináris keresős) adatmélység H4-en

`research/us100_stocks_h4_data_depth_check.py` (2026-09-03) — ugyanaz a módszer, mint az
`index_data_depth_check.py`-nál:

| Szimbólum | Legkorábbi elérhető nap (H4) |
|---|---|
| Apple | 2011-12-22 |
| Microsoft | 2011-12-22 |
| Nvidia | 2011-12-22 |
| Amazon | 2011-12-22 |
| Google | 2011-12-22 |
| Meta (Facebook) | 2012-05-05 |
| **Broadcom** | **2014-09-19** (szűk keresztmetszet) |

**Közös (mind a 7 szimbólumra érvényes) legkorábbi indulódátum: 2014-09-19** — kb. **12 év**
H4-es adat, jóval mélyebb, mint a ma vizsgált indexek (~2023-10-28) VAGY a TaiwanCash-vizsgálat
(~2023-10-28). Bőven elég egy komoly walk-forward-höz.

## 3. Spread / tipikus mozgás (durva, utóbbi 90 nap, M10) — ⚠️ KRITIKUS FIGYELMEZTETÉS

| Szimbólum | Átl. spread | Átl. bar-range | **Spread/bar-range %** | Átl. ár | Megjegyzés |
|---|---|---|---|---|---|
| Apple | 1.8393 | 0.7411 | **248.2%** | 309.02 | |
| Amazon | 1.5328 | 0.7025 | **218.2%** | 250.20 | |
| Microsoft | 2.6717 | 1.1520 | **231.9%** | 427.77 | |
| Meta | 4.0329 | 1.9651 | **205.2%** | 588.39 | |
| Nvidia | 1.2881 | 0.6750 | **190.8%** | 208.16 | |
| Google | 2.0063 | 1.1419 | **175.7%** | 348.44 | |
| Broadcom | 1.4648 | 1.8348 | **79.8%** (legjobb) | 385.04 | egyetlen 100% alatti |

**Mind a 7 részvénynél a spread MAGA nagyobb, mint egy átlagos M10 gyertya teljes (high-low)
mozgása** (6/7-nél 175-248%!) — ez ROSSZABB, mint bármelyik ma vizsgált index (a Taiwan-index
spread/ATR aránya nagyságrendekkel kedvezőbb volt). Broadcom az egyetlen kivétel (79.8%), de az is
jelentős. Ez már ELŐZETESEN nagyon rossz jel M10-es kereskedéshez — valószínűleg csak jóval
hosszabb tartási idejű (napon túli) stratégia férne bele ebbe a költség-szerkezetbe, ha egyáltalán.

### 3.1 DÖNTÉS UTÁNI MEGERŐSÍTÉS: spread/bar-range H1-en és H4-en

Felhasználói döntés (2026-09-03): M10 kizárva, swing-trade mechanizmus kell, H1-H4 vizsgálandó.
Gyors megerősítés (`research/us100_stocks_h1_h4_spread_check.py`, utóbbi 90 nap):

| Szimbólum | H1 spread/range % | **H4 spread/range %** |
|---|---|---|
| Apple | 92.1% | **52.4%** |
| Microsoft | 87.4% | **51.6%** |
| Nvidia | 72.6% | **42.1%** |
| Amazon | 82.0% | **47.3%** |
| Google | 70.5% | **36.2%** |
| Meta (Facebook) | 75.0% | **43.4%** |
| Broadcom | 32.7% | **17.4%** |

**A döntés megerősítve**: H4-en mind a 7 jelölt 100% ALATT van (17.4%-52.4%), drámai javulás az
M10-es 175-248%-hoz képest. H1 még mindig határeset néhány szimbólumnál (Apple 92.1%, Microsoft
87.4% — közel az 1:1 arányhoz), Broadcom és Google H1-en is rendben van. **H4 tűnik a biztonságosabb
kiindulási idősíknak.**

### 3.2 ÚJ KÖLTSÉGTÉNYEZŐ: overnight swap-becslés (felhasználói felvetés, 2026-09-03)

Mivel swing-trade napon túli tartással jár, az eddig figyelmen kívül hagyható swap-díj kritikussá
válik (`research/us100_stocks_swap_cost_check.py`). Mind a 7 részvény `INTEREST_CURRENT` swap-módot
használ (éves %-os kamat a nyitási áron, ÚJ eset a projektben — a `swap_cost_check.py` eredeti,
index-CFD-kre írt verziója ezt még nem kezelte, ki kellett egészíteni): **swap_long ≈ -8.65%/év,
swap_short ≈ -1.35%/év MINDEGYIKNÉL** (azonos bróker-szintű kamatláb, nem szimbólum-specifikus).
Hármas-szorzós nap: péntek (hétvégi fedezet).

| Szimbólum | LONG swap/3 éjszaka (H4-range %) | LONG swap/5 éjszaka (H4-range %) | SHORT swap/3 éjszaka |
|---|---|---|---|
| Apple | 66.7% | **111.2%** | 10.4% |
| Microsoft | 70.3% | **117.2%** | 11.0% |
| Nvidia | 53.4% | 89.1% | 8.3% |
| Amazon | 57.1% | 95.2% | 8.9% |
| Google | 44.1% | 73.5% | 6.9% |
| Meta | 47.0% | 78.3% | 7.3% |
| Broadcom (legjobb) | 30.8% | 51.3% | 4.8% |

**FONTOS, ÚJ, STRUKTURÁLIS FELISMERÉS**: erős ASZIMMETRIA LONG és SHORT között — a LONG-tartás
swap-költsége kb. **6.4x akkora**, mint a SHORT-é (a bróker minden vizsgált részvényre azonos
-8.65%/-1.35% kamatlábat használ). 5 éjszakás LONG tartásnál Apple/Microsoft-nál a swap-költség
ÖNMAGÁBAN meghaladja egy tipikus H4-es gyertya teljes mozgását (111-117%!) — ez azt jelenti, hogy
egy hosszabb (több napos) LONG swing-pozíció rendkívül drága lehet, míg a SHORT oldal sokkal
olcsóbban tartható. Ez befolyásolhatja a leendő stratégia tervezését (pl. rövidebb LONG tartási
idő, vagy SHORT-preferencia figyelembevétele).

### 3.3 Kontroll-teszt: a meglévő (M10/US-index) TrendFollowing-logika 1:1 átültetve H4-re — MEGBUKOTT

`research/us100_stocks_h4_trend_screening.py` (2026-09-03): a MEGLÉVŐ, US-indexekre validált
`TrendFollowingComponent` (konstruktor-alapértelmezett paraméterekkel, `BARS_PER_DAY` H4-re
skálázva a `run_study_timeframe.py`-nál már bevált monkeypatch-technikával, session-szűrés
nélkül), közös 2014-09-19 — 2026-09-03 ablakban:

| Szimbólum | PF | Trade-szám | Win-rate |
|---|---|---|---|
| Apple | 0.47 | 111 | 49.5% |
| Microsoft | 0.72 | 115 | 51.3% |
| Nvidia | 0.52 | 109 | 49.5% |
| Amazon | 0.72 | 113 | 44.2% |
| Google | 1.14 | 101 | 54.5% |
| Facebook | 0.63 | 119 | 49.6% |
| Broadcom | 0.75 | 107 | 49.5% |

6/7-nél PF jóval 1.0 alatt, egyetlen kivétel (Google, PF 1.14) is borotvaélű (össz. PnL 0.59, 12
év alatt). **Ez a kontroll-teszt megbukott, ahogy vártuk** — a belső indikátor-logika (EMA-kereszt+
Bollinger+RSI+ATR-trailing) US-index-specifikus, nem transzferálható változtatás nélkül egyedi
részvényekre H4-en. Lásd 5. szakasz "ARCHITEKTÚRA-DÖNTÉS" — ez indokolta a döntést, hogy a belső
logikát újratervezzük, csak az architektúra-mintát tartjuk meg.

## 4. Osztalék (ex-date) információk

Websearch-csel gyűjtve (2026-09-03) — NEM kitalált dátumok, valós forrásokból. Ahol a forrás
"becsült"-nek/"még nem hivatalosan bejelentett"-nek jelezte a dátumot, azt külön jelöltük. Ezeket
frissíteni kell majd, ha a végleges top-5 kiválasztásra kerül, és a backtest ablak közelít a jelen
időhöz (a Q4-es dátumok többsége még nem hivatalos).

| Szimbólum | Q1 ex-date | Q2 ex-date | Q3 ex-date | Q4 ex-date | Megjegyzés |
|---|---|---|---|---|---|
| Apple | 2026-02-09 | 2026-05-11 | 2026-08-10 | 2026-11-10 | mind a 4 megerősített |
| Microsoft | 2026-02-19 | 2026-05-21 | 2026-08-20 | *nincs adat* | Q4 dátum nem található a keresésben, minta alapján kb. november közepe |
| Nvidia | 2026-03-11 ($0.01) | 2026-06-04 ($0.25) | 2026-09-10 ($0.25) | *nincs adat* | 2026-ban osztalék-EMELÉS $0.01→$0.25/negyedév |
| **Amazon** | — | — | — | — | **NEM fizet osztalékot** (sosem, az IPO óta) — ha Amazon bekerül a végleges top-5-be, az osztalék-korrekció kérdése NEM releváns rá |
| Alphabet/Google | 2026-03-09 | 2026-06-08 | 2026-09-04 | *még nem jelentették be* | |
| Meta | 2026-03-16 | 2026-06-15 | 2026-09-22 | 2026-12-15 (BECSÜLT) | |
| Broadcom | 2026-03-23 | 2026-06-22 | 2026-09-22 | *nincs adat* | fiskális negyedévek, nem feltétlenül naptári Q1-Q4 |

**Sources:**
- [Apple (AAPL) Dividend History, Dates & Yield](https://stockanalysis.com/stocks/aapl/dividend/)
- [Microsoft announces quarterly dividend](https://news.microsoft.com/source/2026/06/10/microsoft-announces-quarterly-dividend-29/)
- [NVIDIA CORP - Form 8-K - FY2026](https://www.sec.gov/Archives/edgar/data/0001045810/000104581026000051/q1fy27pr.htm)
- [The $200 Billion Question: Is Amazon Finally Ready to Pay a Dividend?](https://finance.yahoo.com/news/200-billion-amazon-finally-ready-000002011.html)
- [Alphabet Inc. Class C (GOOG) Dividend History, Yield & Ex-Dividend](https://www.tipranks.com/stocks/goog/dividends)
- [Meta Platforms (META) Dividend History, Dates & Yield](https://stockanalysis.com/stocks/meta/dividend/)
- [Broadcom (AVGO) Dividend History, Dates & Yield](https://stockanalysis.com/stocks/avgo/dividend/)

## 5. Következő lépések

- [x] Szúrópróba lefuttatva és a fenti táblák feltöltve (2026-09-03)
- [x] Osztalék-naptár beszerzése (mind a 7 jelöltre, websearch-csel, 2026-09-03 — Q4-es dátumok
      egy része még nem hivatalos, frissítendő)
- [x] **DÖNTÉS (felhasználó, 2026-09-03)**: M10 KIZÁRVA a spread/bar-range eredmény (6/7-nél
      175-248%) miatt — swing-trade mechanizmus kell, ehhez illő időtáv vizsgálata **H1-H4**
- [x] Spread/bar-range újraszámolása H1/H4-en (2026-09-03) — **MEGERŐSÍTVE**: H4-en mind a 7
      jelölt 100% alatt (17.4%-52.4%), H4 a biztonságosabb kiindulási idősík (lásd 3.1)
- [x] Overnight swap-költség becslése (2026-09-03, felhasználói felvetés) — **ERŐS LONG/SHORT
      ASZIMMETRIA feltárva** (LONG ~6.4x drágább, mint SHORT), lásd 3.2
- [x] Pontos (bináris keresős) adatmélység H4-en (2026-09-03) — **közös indulódátum 2014-09-19**
      (kb. 12 év, szűk keresztmetszet Broadcom), lásd 2.1
- [x] Olcsó trend-illeszkedési kontroll-teszt H4-en, a MEGLÉVŐ (M10/US-index) TrendFollowing-logika
      1:1 átültetésével (2026-09-03) — **MEGBUKOTT** (6/7-nél PF<1, egyetlen kivétel Google PF=1.14
      is borotvaélű) — megerősítette, hogy a belső indikátor-logika NEM transzferálható változtatás
      nélkül, lásd 3.3
- [x] **ARCHITEKTÚRA-DÖNTÉS (felhasználó, 2026-09-04)**: az eredeti mechanizmus BELSŐ logikáját
      (EMA-kereszt, Bollinger, ATR-csatorna stb.) NEM visszük át — azt statisztikai eszközökkel
      (variance ratio stb.) újraépítjük ERRE a piacra. A meglévő rendszer ARCHITEKTÚRA-SZINTŰ
      mintáját viszont megtartjuk: (1) TrendFollowing komponens, (2) MeanReversion komponens, (3)
      rezsim-alapú váltó-mechanizmus közöttük (ugyanaz az elv, mint a `MarketConditionClassifier`
      trend_band-alapú XOR-kapuzása a production Engine-ben) — csak a komponensek SAJÁT belső
      logikáját tervezzük újra, nem az architektúrát.
- [ ] Variance ratio scan H4-en, mind a 7 részvényre (a `taiwan_variance_ratio_scan.py` mintája
      szerint) — milyen időtávon van egyáltalán kihasználható lineáris struktúra?
