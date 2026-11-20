"""
validation/generate_live_baseline.py — referencia-generátor a "retail szint fölötti" élő-
teljesítmény-figyeléshez (2026-09-09, 1. fázis, lásd PLAN.md 7. pont és a
`live-vs-baseline-stat-monitoring-concept` memória).

Egyetlen célja: a JELENLEG ÉLESÍTETT paraméterekkel újra lefuttatja a walk-forward validációt, és
előállít egy `regime_framework/data/live_baselines.json`-t (komponensenkénti trade-count/win-rate/
profit-factor) -- ezt majd egy KÉSŐBBI (2. fázis) dashboard-funkció fogja összevetni a folyamatosan
gyűlő élő trade-ekkel, hogy jelezze, ha a live teljesítmény statisztikailag eltér a validáltól.

TÖRTÉNET (2026-09-09, egy nap alatt 3 lépésben bővült): induláskor MVP-ként CSAK az IC Markets
USTEC pilótára (91.03 pontszám, kézzel átmásolt paraméter-dict) -- majd `.set`-parserrel
(`mt5_set_parser.py`) és IC Markets US30-cal bővült -- majd, miután a felhasználó átjelentkeztette
a kutatási terminált XM demó fiókra, a 3 XM-es élő példánnyal (US100Cash#/US500Cash#/US30Cash#)
is. Az 5 `LIVE_INSTANCES`-bejegyzés így immár a TELJES ismert élő flottát lefedi (2 IC Markets +
3 XM) -- lásd SESSION_LOG.md 2026-09-09 bejegyzései a részletekért.

TUDATOSAN EL NEM HÁRÍTOTT KORLÁTOK (ne tessék véletlen hibának hinni, ha valaki később ide néz):
  - Ez az `optuna_research` (JAVÍTOTT, a napvégi-kényszerzárás-hibát tartalmazó verzióhoz képest
    korrigált) Engine-t futtatja -- NEM a ténylegesen élesített `D:\\XM\\Optuna` Python-másolatot
    és NEM az MQL5 EA-t. A Python-vs-MQL5 mechanizmus-eltérés (pl. a MeanReversion SL/TP-je élőben
    natív bróker-megbízásként fut, nem a Python `resolve_fixed_exit()` pesszimista feloldásával --
    lásd `RegimeFramework_EA.mq5` fejléc-kommentje) továbbra is fennáll -- ez egy ELFOGADOTT
    közelítés, nem hiba.
  - A `FOLD_BOUNDARIES` (`validation/validate_walk_forward.py`) jelenleg 2026-08-01-ig tart, NEM
    "a mai napig" -- a baseline ennyire friss. A fold-lista kiterjesztése külön, ide nem tartozó
    döntés.

2026-09-09, UTÓLAGOS JAVÍTÁS: a fenti "KÉZZEL átmásolva, nincs .set-parser" korlát megszűnt --
lásd `validation/mt5_set_parser.py`. A paraméterek mostantól KÖZVETLENÜL a terminál `.set`
fájljából olvasódnak be minden futtatáskor (`set_file_to_trial_params()`), nincs elavulás- vagy
elgépelés-kockázat. A parser írása közben kiderült: a projektben KÉTFÉLE `.set`-kódolás létezik
egymás mellett (BOM-os UTF-16LE az újabb, Python-generált fájloknál; BOM nélküli sima UTF-8 a
régebbi, MetaEditor-mentésű XM-fájloknál) -- a parser mindkettőt kezeli, lásd a modul saját
docstringje.

Előfeltétel: a megfelelő terminálnak kell csatlakoztatva lennie, MIELŐTT ezt a scriptet
futtatjuk -- ugyanaz a korlát, mint a `research/icmarkets_ustec_warmstart_retune.py`-nál (nincs a
projektben automatikus terminál-választás/multi-bróker-kapcsolat Python-oldalon). EGYSZERRE csak
EGY bróker példányai dolgozhatók fel (a terminál csak egy fiókba van bejelentkezve) -- ezért a
script per-példány próbálkozik, a más-brókeres (jelenleg nem elérhető) példányoknál hangos
figyelmeztetést ír, de NEM állítja meg a futást, és MEGŐRZI a `live_baselines.json`-ban már
meglévő, korábbi futtatásból származó bejegyzésüket (lásd `_load_existing_instances()`) --
minden bejegyzésnek saját `generated_at` mezője van, hogy a fogyasztó lássa, melyik mennyire friss.

2026-09-09, MÉG UGYANAZNAP: a felhasználó átjelentkeztette a kutatási terminált XM demó fiókra --
ez felfedte a projekt már dokumentált bróker-szimbólum-eltérését ([[broker_symbol_naming_mismatch]]
memória): a `.set`-fájlok fejléc-kommentje/az ÉLŐ XM-fiók `#`-es szimbólumneveket használ
(`US100Cash#`), de EZEN a demó fiókon `#` NÉLKÜLI nevek élnek (`US100Cash`) -- a felhasználó
megerősítette, hogy ez UGYANAZ a szimbólum, csak fiókonként más néven. Ezért a `LIVE_INSTANCES`
bejegyzések szétválasztják a `live_symbol`-t (dokumentáció/kimenet, `#`-es) a `fetch_symbol`-tól
(ténylegesen ezzel a névvel hívjuk a `symbol_select`/`fetch_rates`-et ezen a fiókon).

Futtatás: python -m regime_framework.validation.generate_live_baseline
"""

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import MetaTrader5 as mt5
import pandas as pd
from optuna.trial import FixedTrial

from regime_framework.core.engine import Engine
from regime_framework.data.mt5_source import fetch_rates
from regime_framework.monitoring.heartbeat_dashboard import COMPONENT_LABELS
from regime_framework.optimization.objective import build_components
from regime_framework.regime.market_condition import MarketConditionClassifier
from regime_framework.validation.mt5_set_parser import set_file_to_trial_params
from regime_framework.validation.validate_walk_forward import FOLD_BOUNDARIES

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

MIN_RELIABLE_TRADES = 30   # a projekt saját szabálya, lásd ValidationReport.is_reliable()
START_DATE = "2023-11-01"  # a FOLD_BOUNDARIES legkorábbi foldjának bemelegítéséhez kell
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "data" / "live_baselines.json"

# component.name (Python, core/engine.py) -> OWNER_TAG_* (MQL5/dashboard) fordítás --
# a COMPONENT_LABELS (monitoring/heartbeat_dashboard.py) MEGFORDÍTVA, hogy a 2. fázis (dashboard)
# ugyanazokat a kulcsokat lássa itt is, amiket a _component_stats() már most is használ.
OWNER_TAG_BY_COMPONENT_NAME = {v: k for k, v in COMPONENT_LABELS.items()}

# A kutatási terminál (UGYANAZ a terminál-mappa, akár IC Marketsre, akár XM-re van éppen
# bejelentkeztetve -- lásd modul-docstring) két helyen tárolja a preset-fájlokat: az újabb,
# Python-generált IC Markets presetek az Experts/.../presets alatt vannak, a régebbi,
# MetaEditor-mentésű XM presetek a Presets/RegimeFramework alatt (lásd `mt5_set_parser.py`
# docstringje a kétféle kódolásról).
_TERMINAL_DIR = (
    Path.home() / "AppData" / "Roaming" / "MetaQuotes" / "Terminal"
    / "<TERMINAL_ID>"
)
_IC_MARKETS_PRESETS_DIR = _TERMINAL_DIR / "MQL5" / "Experts" / "RegimeFramework" / "presets"
_XM_PRESETS_DIR = _TERMINAL_DIR / "MQL5" / "Presets" / "RegimeFramework"

# Élő IC Markets példányok -- a $2000-os pilot mindkét lába (VÉGLEGES DÖNTÉS 2026-09-06: USTEC +
# US30, US500 TUDATOSAN KIHAGYVA a pilotból, lásd SESSION_LOG.md 2026-09-06 "$2000-os IC Markets
# élő pilot csak USTEC-re és US30-ra" bejegyzése -- NEM veendő fel ide, nem élő).
#
# Élő XM példányok -- a bróker-migráció ELŐTTI, eredeti XM-fiók három instance-e (lásd
# docs/BROKER_MIGRATION_DECISION.md). `live_symbol` (`#`-es) a TÉNYLEGES élő fiókon futó név,
# `fetch_symbol` a KUTATÁSI (demó) fiókon elérhető név -- ld. modul-docstring a magyarázatért.
# Magic-ok a `.set` fájlokból kiolvasva (`mt5_set_parser.py`-jal kereszt-ellenőrizve 2026-09-09-én).
LIVE_INSTANCES = [
    {
        "key": "IC Markets:USTEC:202609",
        "broker": "IC Markets",
        "live_symbol": "USTEC",
        "fetch_symbol": "USTEC",
        "magic": 202609,
        "set_file": _IC_MARKETS_PRESETS_DIR / "USTEC.set",
        "source": "research/icmarkets_ustec_warmstart_retune.py (2026-09-05, score=91.03)",
    },
    {
        "key": "IC Markets:US30:202611",
        "broker": "IC Markets",
        "live_symbol": "US30",
        "fetch_symbol": "US30",
        "magic": 202611,
        "set_file": _IC_MARKETS_PRESETS_DIR / "US30.set",
        "source": "research/icmarkets_us30_warmstart_retune.py (2026-09-05, score=40.89)",
    },
    {
        "key": "XM:US100Cash#:202609",
        "broker": "XM",
        "live_symbol": "US100Cash#",
        "fetch_symbol": "US100Cash",
        "magic": 202609,
        "set_file": _XM_PRESETS_DIR / "RegimeFramework_EA_US100Cash.set",
        "source": "RegimeFramework_EA_US100Cash.set fejléc (2026-08-22, bruttó pontszám 84.95, "
        "később nettóra újraellenőrizve -- lásd PRODUCTION_READINESS.md)",
    },
    {
        "key": "XM:US500Cash#:2026091",
        "broker": "XM",
        "live_symbol": "US500Cash#",
        "fetch_symbol": "US500Cash",
        # 2026091, NEM 202629 -- a .set fájl 202629-et ír, de a VPS-en éles EA saját maga
        # magic=2026091-et jelent be (heartbeat-fájl, ellenőrizve 2026-09-09-én) -- a
        # felhasználóval egyeztetve az ÉLŐ EA a mérvadó, a .set fájl itt elavult/eltérő.
        "magic": 2026091,
        "set_file": _XM_PRESETS_DIR / "RegimeFramework_EA_US500Cash.set",
        "source": "RegimeFramework_EA_US500Cash.set fejléc (magic kézzel javítva 202629 -> "
        "2026091-re, lásd a fenti megjegyzést)",
    },
    {
        "key": "XM:US30Cash#:202649",
        "broker": "XM",
        "live_symbol": "US30Cash#",
        "fetch_symbol": "US30Cash",
        "magic": 202649,
        "set_file": _XM_PRESETS_DIR / "RegimeFramework_EA_US30Cash.set",
        "source": "RegimeFramework_EA_US30Cash.set fejléc",
    },
    {
        # MÉG NEM ÉLES -- lásd timeframe_deepdive/FINDINGS_LOG.md 4-6. bejegyzés (nettó PF=2,08,
        # n=185, 2025-11-14..2026-09-15 validáció) és a dashboard saját tervezése szerint (lásd
        # _render_baseline_drift_cards fejléc-kommentje) egy 0-live-trade-es példány is
        # megjelenik "várakozik" jelzéssel -- ez egy TUDATOS előre-feltöltés, hogy a dashboard
        # azonnal legyen mihez viszonyítania, amint ez élesítésre kerül.
        "key": "IC Markets:USTEC:101001",
        "broker": "IC Markets",
        "live_symbol": "USTEC",
        "fetch_symbol": "USTEC",
        "magic": 101001,
        "set_file": _TERMINAL_DIR / "MQL5" / "Experts" / "RegimeFramework" / "dist_m10_10d_ustec"
        / "RegimeFramework_EA_M10_10d_USTEC.set",
        # FONTOS: ez a példány NEM a standard 8640 bar-os (60 napos) klasszifikátor-ablakkal lett
        # validálva, hanem 1320 bar-ral (10 kereskedési nap) -- lásd RegimeFramework_EA_M10_10d.mq5/
        # RegimeClassifier_M10_10d.mqh fejléc-kommentjét. A .set fájl ezt NEM hordozza (fordítás-idejű
        # MQL5 konstans), ezért itt KÜLÖN kell megadni, különben az Engine a rossz (8640-es)
        # alapértékkel futna.
        "classifier_window_bars": 1320,
        "source": "timeframe_deepdive/FINDINGS_LOG.md 4-6. bejegyzés (500-trial Optuna, 2026-09-17, "
        "Strategy Tester valós tick megerősítve IC Markets-en, PF=2.06 vs Python 2.08)",
    },
]


def _pooled_stats(trades):
    """Ugyanaz a képlet, mint core/engine.py:341-345 -- de a FOLD-OKON ÁTÍVELŐ, pool-olt nyers
    trade-listán számolva egyszer, NEM a kerekített, fold-onkénti report.notes-ból visszafejtve
    (az pontatlan lenne)."""
    trade_count = len(trades)
    if trade_count == 0:
        return {"trade_count": 0, "win_rate": 0.0, "profit_factor": 0.0, "reliable": False}
    wins = [t for t in trades if t["pnl"] > 0]
    gross_win = sum(t["pnl"] for t in wins)
    gross_loss = abs(sum(t["pnl"] for t in trades if t["pnl"] <= 0))
    win_rate = len(wins) / trade_count * 100
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else float("inf")
    return {
        "trade_count": trade_count,
        "win_rate": round(win_rate, 1),
        "profit_factor": round(profit_factor, 2) if profit_factor != float("inf") else None,
        "reliable": trade_count >= MIN_RELIABLE_TRADES,
    }


def generate_for_instance(instance):
    live_symbol = instance["live_symbol"]
    fetch_symbol = instance["fetch_symbol"]
    logger.info("--- %s (fetch=%s, magic=%d) ---", instance["key"], fetch_symbol, instance["magic"])

    if not mt5.symbol_select(fetch_symbol, True):
        raise RuntimeError(
            f"{fetch_symbol} nem választható ki ezen a terminálon/fiókon -- "
            f"más bróker van csatlakoztatva, mint amihez ez a példány tartozik?"
        )

    params = set_file_to_trial_params(instance["set_file"])
    logger.info("  Paraméterek beolvasva: %s", instance["set_file"])

    end_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    df = fetch_rates(fetch_symbol, mt5.TIMEFRAME_M10, START_DATE, end_date)
    if df is None or len(df) == 0:
        raise RuntimeError(f"Nem sikerült OHLC-adatot lekérni {fetch_symbol}-ra.")

    components, time_gated, quota_exempt = build_components(FixedTrial(params))
    classifier_window_bars = instance.get("classifier_window_bars")
    if classifier_window_bars is not None:
        logger.info("  Egyedi klasszifikátor-ablak: %d bar (NEM az alapértelmezett 8640)",
                    classifier_window_bars)

    trades_by_component = {name: [] for name in OWNER_TAG_BY_COMPONENT_NAME}
    folds_used = 0
    for fold_start, fold_end in FOLD_BOUNDARIES:
        fold_df = df[df["time"] < pd.Timestamp(fold_end)]
        if len(fold_df) == 0:
            continue
        classifier = (MarketConditionClassifier(rolling_window_bars=classifier_window_bars)
                      if classifier_window_bars is not None else None)
        engine = Engine(components, market_classifier=classifier, time_gated_components=time_gated,
                         quota_exempt_time_gated_components=quota_exempt)
        _report, trades = engine.run(
            fold_df, stats_start_date=pd.Timestamp(fold_start).date(), return_trades=True
        )
        folds_used += 1
        for t in trades:
            trades_by_component.setdefault(t["component"], []).append(t)

    components_out = {}
    for comp_name, tag in OWNER_TAG_BY_COMPONENT_NAME.items():
        components_out[tag] = _pooled_stats(trades_by_component.get(comp_name, []))

    logger.info(
        "  %d fold feldolgozva. Komponensenkénti trade-szám: %s",
        folds_used, {tag: s["trade_count"] for tag, s in components_out.items()},
    )

    return {
        "broker": instance["broker"],
        "symbol": live_symbol,
        "magic": instance["magic"],
        "params_source": instance["source"],
        "params_set_file": str(instance["set_file"]),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "components": components_out,
    }


def _load_existing_instances():
    """A korábbi futtatás(ok)ból megmaradt bejegyzések -- ezekre van szükség, mert a terminál
    EGYSZERRE csak EGY brókerhez van csatlakoztatva, tehát egyetlen futtatás sosem tudja az
    ÖSSZES `LIVE_INSTANCES`-t frissíteni. Enélkül minden futtatás kitörölné az éppen NEM elérhető
    bróker korábban megszerzett eredményeit."""
    if not OUTPUT_PATH.exists():
        return {}
    try:
        return json.loads(OUTPUT_PATH.read_text(encoding="utf-8")).get("instances", {})
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("⚠️ Nem sikerült beolvasni a meglévő %s-t (%s) -- üresről indulunk.",
                        OUTPUT_PATH, exc)
        return {}


def main():
    if not mt5.initialize():
        logger.error("❌ MT5 inicializálás sikertelen: %s -- fut-e a megfelelő terminál?", mt5.last_error())
        return 1
    try:
        instances_out = _load_existing_instances()
        refreshed, skipped = [], []
        for instance in LIVE_INSTANCES:
            try:
                instances_out[instance["key"]] = generate_for_instance(instance)
                refreshed.append(instance["key"])
            except RuntimeError as exc:
                skipped.append(instance["key"])
                logger.warning("⚠️ Kihagyva (%s): %s", instance["key"], exc)
    finally:
        mt5.shutdown()

    if not refreshed:
        logger.error("❌ Egyetlen példány sem frissült ezen a futtatáson -- fut-e a megfelelő terminál?")
        return 1

    output = {
        "_meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source_script": "regime_framework/validation/generate_live_baseline.py",
            "fold_boundaries_source": "regime_framework.validation.validate_walk_forward.FOLD_BOUNDARIES",
            "engine_source": "optuna_research (helyi, javított Engine -- NEM a D:\\XM\\Optuna élő másolat, lásd modul-docstring)",
            "min_reliable_trades": MIN_RELIABLE_TRADES,
        },
        "instances": instances_out,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("\n✅ Baseline elmentve: %s", OUTPUT_PATH)
    logger.info("   Frissítve: %s", refreshed)
    if skipped:
        logger.info("   Kihagyva (nem ezen a terminálon/fiókon elérhető, korábbi adat megőrizve): %s", skipped)
    return 0


if __name__ == "__main__":
    sys.exit(main())
