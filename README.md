# Regime Framework

Rezsim-vezérelt, moduláris kereskedési keretrendszer **MetaTrader 5**-re, index-CFD-kre
(US30, US500, USTEC/US100, DE40, AUS200, SA40). A rendszer felméri a piaci helyzetet
(trend / oldalazás, volatilitás-sáv, session-fázis), és ez alapján dönti el, melyik komponens
kereskedhet éppen.

A projekt két, egymással paritásban tartott fele:

- **Python kutató- és validáló motor** (`regime_framework/`): backtest-engine, komponensek,
  rezsim-osztályozók, Optuna-hangolás, walk-forward / holdout validáció, MT5-port-hűség ellenőrzés.
- **MQL5 Expert Advisorok** (`mql5/`): a validált logika éles/demó futtatásra portolt változata,
  Strategy Testerben valós tickeken visszaigazolva.

> **Figyelem:** kutatási projekt, nem befektetési tanács. A múltbeli (backtest- és
> Strategy Tester-) eredmények nem garantálják a jövőbeli teljesítményt. Saját felelősségre használd,
> először mindig demószámlán.

## Komponensek

| Komponens | Python | MQL5 |
|---|---|---|
| Mean Reversion (EMA ± ATR-sáv) | `components/mean_reversion.py` | `MeanReversion.mqh` |
| Trend Following | `components/trend_following.py` | `TrendFollowing.mqh` |
| Last Hour Continuation (DST-tudatos) | `components/last_hour_continuation.py` | `LastHourContinuation.mqh` |
| Friday Short | `components/friday_short.py` | `FridayShort.mqh` |
| Rezsim-osztályozó (piaci állapot) | `regime/market_condition.py` | `RegimeClassifier*.mqh` |
| Session-fázis | `regime/session_phase.py`, `core/us_session.py` | `UsDst.mqh` |
| Tőzsdeszünnapok | `core/market_calendar.py`, `data/market_holidays.json` | `MarketHolidays.mqh` |
| Spread-anomália szűrő | – | `SpreadAnomalyGuard.mqh` |

## Mappaszerkezet

```
regime_framework/          Python csomag
  core/                    engine, indikátorok, pozícióméretezés, típusok, session/naptár
  components/              kereskedési komponensek
  regime/                  rezsim- és session-osztályozók
  data/                    MT5 adatforrás, élő baseline-ok, ünnepnapok
  optimization/            Optuna objective + study futtató
  validation/              walk-forward, holdout, MT5-port-hűség, .set-parser
  monitoring/              heartbeat-dashboard (Tk + web), watchdogok, baseline-drift
  deployment/              .set / holiday-.mqh generálás, lot-méretezés, VPS-csomagolás
mql5/Experts/RegimeFramework/
  RegimeFramework_EA.mq5          kanonikus EA (M10, minden bróker)
  RegimeFramework_EA_M30.mq5      M30-változat (MR + LHC, US30/US500)
  RegimeFramework_EA_M10_10d.mq5  M10, 10 napos osztályozó-ablak (USTEC)
  RF_TF_EA.mq5                    csak TrendFollowing, a v2.01-ből leválasztva
  SignalCopier/                   publisher/slave EA pár (master → slave számla másolás)
  dist_m10_10d_ustec/             önálló, lefordított deploy-csomag (forrás + .ex5 + .set + README)
  presets*/                       validált .set paraméterfájlok
reports/strategy_tester/   MT5 Strategy Tester riportok (valós tick) a fenti presetekhez
docs/                      terv (PLAN.md), production readiness, döntési dokumentumok
packaging/                 PyInstaller .spec-ek a monitor-eszközökhöz
tools/regime_parity.ps1    Python ↔ MQL5 paritás-ellenőrző
```

## Használat

### Python

```bash
python -m venv venv
venv\Scripts\activate
pip install -e .
```

A motor adatforrása a `MetaTrader5` Python csomag, így Windows-on, futó és bejelentkezett MT5
terminállal működik. A validációs scriptek modulként futnak, pl.:

```bash
python -m regime_framework.validation.validate_walk_forward
python -m regime_framework.optimization.run_study
```

A monitorhoz másold a `monitoring/terminals.example.json` és `monitoring/live_instances.example.json`
fájlokat `.example` nélkül, és írd át a saját terminál-útvonalaidra (ezek gitignore-oltak).

### MQL5

1. Másold a `mql5/Experts/RegimeFramework/` mappát a terminál adatmappájába
   (`%APPDATA%\MetaQuotes\Terminal\<TERMINAL_ID>\MQL5\Experts\`).
2. Fordítsd MetaEditorral a kívánt `.mq5`-öt.
3. A charton Inputs → Load → a megfelelő `.set` a `presets*/` mappából.
   **A `presets_m10_10d` paraméterei csak a `RegimeFramework_EA_M10_10d` EA-val érvényesek**
   (az osztályozó-ablak fordítási időben rögzített, lásd `dist_m10_10d_ustec/README.md`).

## Megjegyzések

- A dokumentáció (`docs/`) magyar nyelvű, és a teljes fejlesztési folyamatot rögzíti. Hivatkozik
  olyan kutatási scriptekre és mappákra (`research/`, `timeframe_deepdive/`, `Pardo/` stb.), amelyek
  nem részei ennek a repónak.
- A számlaszámokat és a lokális felhasználói útvonalakat anonimizáltuk (`<ICM_DEMO_LOGIN>`,
  `%APPDATA%`, `<TERMINAL_ID>` stb.).
