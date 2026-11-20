"""
regime_framework/validation/validate_mt5_port_fidelity.py

DEDIKÁLT, FUTTATOTT bit-pontos ellenőrzés (2026-09-11, felhasználói kérés folytatása): a
`RegimeClassifier.mqh` portjánál egyszer már alkalmazott módszert -- egy Python "streaming
szimulátor" bar-onként újraépíti az MQL5 TÉNYLEGES algoritmusát, és bit-pontosan összeveti a
meglévő batch (pandas) Python-implementációval -- most a TELJES `RegimeFramework_EA.mq5`
`OnTick()` vezérlési logikájára (dispatch, napi kvóta, kilépési prioritások) terjesztjük ki.
Eddig KIZÁRÓLAG a rezsim-osztályozóra készült ilyen dedikált, futtatott validáció (lásd
SESSION_LOG.md 2026-09-11 "MT5/MQL5 mély code review" bejegyzése) -- a korábbi review csak
soronkénti kód-összevetés volt, nem tényleges lefuttatott bit-pontos teszt.

MIT SZIMULÁL (az `Experts/RegimeFramework/RegimeFramework_EA.mq5` `OnTick()`-je alapján,
bar-onként, PONTOSAN ugyanabban a sorrendben):
  1. napváltás-detektálás -> napi kvóta-flag-ek (`trade_taken_today`/`fs_exception_used_today`)
     nullázása
  2. HA van nyitott pozíció:
     a. LHC-tulajdonú + `IsSessionEndBar(h,m)` (`h >= session_end_hour`) -> zárás
     b. FS-tulajdonú + `IsFsHoldEnd(barTime)` (`bars_elapsed >= hold_bars OR day_changed`,
        SAJÁT állapotból, NEM a batch előre-számolt oszlopból) -> zárás
     c. nem-FS + (napváltás az entry óta VAGY `h >= force_close_hour`) -> zárás (napvégi
        kényszerzárás, MOST MÁR a 2026-09-06-i javított, nap-váltás-alapú logikával)
     d. egyébként: TF esetén trailing stop frissítés, majd SL/TP-érintés ellenőrzése (a
        bróker natív stop-megbízásának megfelelője) -- MINDEN komponensre
  3. HA nincs nyitott pozíció ÉS a napi kvóta MÉG szabad: trend_band-XOR (MR/TF) -> ha nem
     jelzett, LHC (time-gated) -- az LHC belépési jelét ÚJRASZÁMOLJUK egy SAJÁT, MQL5-hű
     VISSZAFELÉ SÉTÁLÓ `ComputeTrendReturn()`-nel (lásd lent), NEM a batch előre-számolt
     `trend_return` oszlopból olvassuk -- ez pontosan az a rész, amit a korábbi (csak
     kód-olvasós) review P2-ként megjelölt (dátum-ellenőrzés NÉLKÜLI, óra/perc-mintázat
     alapú visszasétálás -- lásd `LastHourContinuation.mqh` `ComputeTrendReturn()`).
  4. HA nincs nyitott pozíció ÉS a napi kvóta MÁR elfogyott ÉS a FS-kivétel-slot még szabad:
     FS (quota-exempt).

SZÁNDÉKOSAN KIZÁRVA az összevetésből (mindkét oldalon ismert, dokumentált egyszerűsítés,
NEM a dispatch/időzítés-hűség kérdése -- lásd PLAN.md 0.1 és a 2026-09-11-i code review):
  - Élő bid/ask-hoz igazított SL/TP (`OpenPosition()` az ÉLŐ ask/bid-hez viszonyítja a
    slDistance/tpDistance-t) -- a szimulátor a batch Engine.run()-nal AZONOS, bar high/low
    alapú (resolve_fixed_exit-stílusú) kilépés-feloldást használ, hogy egy esetleges eltérés
    EGYÉRTELMŰEN a dispatch/időzítés hibájának legyen tulajdonítható, ne keveredjen az
    ismert SL/TP-végrehajtási különbséggel.
  - Naptári ünnepnap / spread-anomália / távoli-leállítás belépési kapuk -- a batch
    Engine.run()-nak nincs megfelelőjük, mindkét oldalon "nincs" állapotban tartva.
  - RSI/ATR/ADX/Bollinger/EMA indikátor-FORMULÁK -- ezeket a 2026-09-11-i code review már
    soronként ellenőrizte kód-szinten (és a rezsim-osztályozó saját bit-pontos validációja is
    megerősítette), itt a MEGLÉVŐ (`prepare_indicators()`/`classify_series()`) oszlopokat
    ÚJRAHASZNÁLJUK -- ez a szkript KIZÁRÓLAG a dispatch/állapotgép hűségét méri, nem az
    indikátor-matematikát.

Futtatás: python -m regime_framework.validation.validate_mt5_port_fidelity
(Élő MT5-terminál szükséges -- a jelenleg csatlakoztatott számla szimbólumkészletéből választ.)
"""

import logging

import numpy as np
import pandas as pd

import MetaTrader5 as mt5

from regime_framework.components.friday_short import FridayShortComponent
from regime_framework.components.last_hour_continuation import LastHourContinuationComponent
from regime_framework.components.mean_reversion import MeanReversionComponent
from regime_framework.components.trend_following import TrendFollowingComponent
from regime_framework.core.engine import Engine
from regime_framework.core.types import ExitDecision
from regime_framework.data.mt5_source import fetch_rates

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

# IC Markets USTEC-re meleginditott Optuna-hangolas (regime_framework/research/
# icmarkets_ustec_warmstart_retune.py, 2026-09-05, score=91.03) -- EZ fut az egysegesitett
# `RegimeFramework_EA.mq5` peldany-alapertekekent is, lasd 2026-09-11_ea_unification/.
SYMBOL = "USTEC"
START_DATE = "2025-01-01"
END_DATE = "2026-08-01"

MR_PARAMS = dict(ema_period=40, mr_multiplier=1.9061195, sl_multiplier=2.0771436, risk_reward_ratio=1.8391381)
TF_PARAMS = dict(fast_ema_days=0.4404634, slow_ema_days=3.6701403, sl_atr_multiplier=1.8956209,
                  trail_atr_multiplier=4.7461750, rsi_long_min=44.8983746, rsi_short_max=44.9799269,
                  bollinger_period=14, bollinger_k=1.5654510)
LHC_PARAMS = dict(sl_atr_multiplier=1.7916306, min_trend_bars=12, final_hour_start=20, session_end_hour=21)
FS_PARAMS = dict(sl_atr_multiplier=1.1892803, hold_bars=11, target_day_of_week=4, target_hour=23)
SESSION = dict(session_start_hour=16, session_start_minute=30, session_end_hour=21)
FORCE_CLOSE_HOUR = 23
# JAVASOLT JAVÍTÁS (lásd SESSION_LOG.md): 23:00 helyett 23:49 -- a bróker (IC Markets/XM) hivatalos
# dokumentációja szerint a swap 00:00 SZERVERIDŐKOR számolódik el, nem 23:00-kor, tehát a régi
# InpForceCloseHour=23 (perc nélkül) kb. 1 órával feleslegesen korán zárt -- ez okozta a validált
# batch modelltől (ami a nap tényleges végéig, ~23:50-ig fut) való eltérést.
FORCE_CLOSE_MINUTE = 49
FS_SAFETY_CLOSE_HOUR = 23
FS_SAFETY_CLOSE_MINUTE = 49


def in_trend_window(hour, minute, session_start_hour, session_start_minute, final_hour_start):
    """`LastHourContinuation.mqh` `InTrendWindow()` -- SZÁNDÉKOSAN csak óra/percet néz, dátumot
    NEM -- ez pontosan az a viselkedés, amit a szkript empirikusan tesztel (lásd fájl fejléc P2)."""
    after_start = (hour > session_start_hour) or (hour == session_start_hour and minute >= session_start_minute)
    return after_start and hour < final_hour_start


def compute_trend_return_mql5(closes, hours, minutes, dates, idx, session_start_hour,
                                session_start_minute, final_hour_start, min_trend_bars, max_lookback=200):
    """`LastHourContinuation.mqh` `ComputeTrendReturn()` HŰ Python-portja: `idx`-től (=MQL5
    shift=1, a bar[1]) VISSZAFELÉ sétál, amíg `in_trend_window()` igaz.

    JAVÍTVA (2026-09-11, felhasználói kockázat-átbeszélés után -- lásd SESSION_LOG.md): a korábbi
    verzió NEM nézett dátumot, csak óra/percet -- elméleti kockázat volt, hogy hiányzó kora-reggeli
    bar-ok esetén a visszasétálás átcsúszna az ELŐZŐ nap saját ablakába. 55 920 valós baron 0
    eset jelentkezett, de az MQL5-oldali `LastHourContinuation.mqh`-ban is bekerült az explicit
    nap-határ-ellenőrzés, ezért itt is szinkronban tartjuk."""
    count = 0
    last_close = None
    first_close = None
    window_day = None
    for k in range(1, max_lookback + 1):
        pos = idx - k + 1
        if pos < 0:
            break
        if k == 1:
            window_day = dates[pos]
        elif dates[pos] != window_day:
            break   # JAVÍTÁS: már egy MÁSIK naptári napra estünk vissza -- állj meg
        h, m = hours[pos], minutes[pos]
        if not in_trend_window(h, m, session_start_hour, session_start_minute, final_hour_start):
            break
        c = closes[pos]
        count += 1
        if count == 1:
            last_close = c
        first_close = c
    if count < min_trend_bars or last_close is None or first_close is None:
        return 0.0, False, count
    return float(np.log(last_close / first_close)), True, count


def main():
    logger.info("--- 🔎 MT5-PORT-HŰSÉG VALIDÁCIÓ (streaming OnTick()-szimulátor vs. batch Engine.run()) ---")
    logger.info("Szimbólum: %s (%s - %s)\n", SYMBOL, START_DATE, END_DATE)

    if not mt5.initialize():
        logger.error("❌ MT5 inicializálás sikertelen: %s", mt5.last_error())
        return
    try:
        df = fetch_rates(SYMBOL, mt5.TIMEFRAME_M10, START_DATE, END_DATE)
    finally:
        mt5.shutdown()

    if df is None:
        logger.error("❌ Nem sikerült adatot lekérni %s-hoz.", SYMBOL)
        return
    logger.info("✅ %d gyertya letöltve.\n", len(df))

    mr = MeanReversionComponent(**MR_PARAMS, **SESSION)
    tf = TrendFollowingComponent(**TF_PARAMS, **SESSION)
    lhc = LastHourContinuationComponent(session_start_hour=SESSION["session_start_hour"],
                                         session_start_minute=SESSION["session_start_minute"], **LHC_PARAMS)
    fs = FridayShortComponent(**FS_PARAMS)

    # --- 1. rész: a MEGLÉVŐ batch Engine.run() (ez a "ground truth", amit eddig is éles
    #     paraméter-hangoláshoz/riportokhoz használtunk) ---
    engine = Engine(components=[mr, tf], time_gated_components=[lhc], quota_exempt_time_gated_components=[fs])
    batch_report, batch_trades = engine.run(df, return_trades=True)
    logger.info("Batch Engine.run(): %d trade, PF=%.2f, PnL=%.2f",
                batch_report.trade_count, batch_report.profit_factor, batch_report.total_pnl)

    # --- 2. rész: UGYANAZ az indikátor-előkészítés/klasszifikáció, amit az Engine belsőleg
    #     használ -- ÚJRAHASZNÁLVA (nem indikátor-formulát tesztelünk, lásd fájl fejléc) ---
    combined = engine._prepare_combined_df(df)
    classified = engine.market_classifier.classify_series(combined)

    n = len(classified)
    close_vals = classified["close"].to_numpy()
    high_vals = classified["high"].to_numpy()
    low_vals = classified["low"].to_numpy()
    hours = classified["hour"].to_numpy()
    minutes = classified["minute"].to_numpy()
    dates = classified["date"].to_numpy()
    day_of_weeks = classified["day_of_week"].to_numpy()
    trend_bands = classified["trend_band"].to_numpy()
    atr_vals = classified["atr"].to_numpy()
    ema_center_vals = classified["ema_center"].to_numpy()
    ema_fast_vals = classified["ema_fast"].to_numpy()
    ema_slow_vals = classified["ema_slow"].to_numpy()
    rsi_vals = classified["rsi"].to_numpy()
    bb_upper_vals = classified["bb_upper"].to_numpy()
    bb_lower_vals = classified["bb_lower"].to_numpy()
    batch_trend_return_vals = classified["trend_return"].to_numpy()
    batch_is_session_end_vals = classified["is_session_end_bar"].to_numpy()

    # KRITIKUS FELISMERÉS (a validáció FUTTATÁSA közben derült ki, lásd SESSION_LOG.md): a Python
    # oszlopok `hour`/`minute`-je a bar NYITÓ idejét címkézi, míg az MQL5 `OnTick()`-ben a h/m
    # mindig az ÚJ (épp most nyílt) bar órája -- ami PONTOSAN egy PERIOD-dal (M10-en 10 perccel)
    # KÉSŐBBI órát/percet jelent, mint az adott sor SAJÁT (nyitó-idő-címkés) h/m-je, hiszen az új
    # bar nyitása = az előző (bar[1], amin a döntés alapul) ZÁRÁSA. Az összes EGYETLEN-PILLANATRA
    # (nem tartományra) vonatkozó MQL5-ellenőrzéshez (`IsFinalTrendBar`, `IsSessionEndBar`,
    # `h >= InpForceCloseHour`, FS `target_hour`, FS biztonsági zárás) ezt az "eltolt" órát/percet
    # kell használni, NEM a sor saját címkéjét -- ELLENTÉTBEN a TARTOMÁNY-alapú ellenőrzésekkel
    # (`_is_session_hour()`/`InTrendWindow()`), amik a Python-oldali definícióval egyeznek meg, ha
    # a sor SAJÁT óráját használjuk (ezt a P2-teszt 0 eltérése is megerősítette). Enélkül a
    # streaming szimulátor egy TELJES bar-ral (itt: 10 perccel) tévesen később/máshol azonosította
    # volna az egyetlen-pillanatú küszöböket -- ez okozta az első, valódi vizsgálatot igénylő
    # eltérést (2025-04-09, LHC belépési bar).
    shifted_time = classified["time"] + pd.Timedelta(minutes=10)
    eff_hours = shifted_time.dt.hour.to_numpy()
    eff_minutes = shifted_time.dt.minute.to_numpy()

    is_last_bar_of_day = np.zeros(n, dtype=bool)
    if n > 0:
        is_last_bar_of_day[:-1] = dates[:-1] != dates[1:]
        is_last_bar_of_day[-1] = True

    # --- 3. rész: a SAJÁT, MQL5 OnTick()-et utánzó streaming dispatch-hurok ---
    streaming_trades = []
    position = None            # dict: pos_type, entry_price, entry_date, entry_bar_idx, sl_price, extra
    owner = None                # "MR"/"TF"/"LHC"/"FS"
    current_day = None
    trade_taken_today = False
    fs_exception_used_today = False

    lhc_disagreements = []     # (idx, mql5_trend_return, batch_trend_return) ahol az ENTRY DÖNTÉS eltért
    lhc_value_diffs = 0        # ahol a szám eltért, de a döntés (jel/nincs jel) véletlenül egyezett
    session_end_disagreements = 0

    for idx in range(n):
        if dates[idx] != current_day:
            current_day = dates[idx]
            trade_taken_today = False
            fs_exception_used_today = False

        h, m = int(hours[idx]), int(minutes[idx])         # sor SAJÁT (nyitó-idő) órája/perce -- a
        eh, em = int(eff_hours[idx]), int(eff_minutes[idx])  # MQL5 "új bar" órája/perce -- lásd fenti megjegyzés
        atr = atr_vals[idx]

        # --- MQL5-hű session-end / hold-end ELLENŐRZÉS (fájl fejléc 2/a, 2/b) -- mindig
        #     kiszámoljuk (nem csak ha van pozíció), hogy a batch oszloppal összevethessük ---
        mql5_is_session_end = eh >= LHC_PARAMS["session_end_hour"]
        if bool(mql5_is_session_end) != bool(batch_is_session_end_vals[idx]):
            session_end_disagreements += 1

        if position is not None:
            exit_decision = None

            # KRITIKUS SORREND-FELISMERÉS (a validáció FUTTATÁSA közben derült ki, lásd
            # SESSION_LOG.md): a bróker NATÍV SL/TP-megbízása FOLYAMATOSAN aktív -- bármikor
            # kiválthat a baron BELÜL, a tényleges ár-mozgás pillanatában -- míg az EA SAJÁT
            # időalapú zárásai (`IsSessionEndBar`, `IsFsHoldEnd`, `h>=InpForceCloseHour`) CSAK a
            # bar ZÁRÁSAKOR (az OnTick() új-bar ágában) futnak le. Ha egy adott baron BELÜL a SL/TP
            # is elérhető lett volna ÉS az időalapú küszöb is teljesülne AZON A BARON, a valóságban
            # a natív SL/TP szinte mindig HAMARABB (a bar VÉGE előtt) kiváltana, mint ahogy az EA
            # saját, csak a bar zárásakor kiértékelt logikája egyáltalán lefutna -- tehát a SL/TP-t
            # kell ELSŐBBSÉGBEN ellenőrizni, ugyanúgy, mint a batch `check_exit()`-ben (lásd
            # `mean_reversion.py` `resolve_fixed_exit()`/`last_hour_continuation.py` `check_exit()`
            # SAJÁT SL-elsőbbségét). Az ELSŐ (naiv) verzió ezt megfordítva, az időalapú zárásokat
            # ellenőrizte ELŐSZÖR (szó szerint követve az OnTick()-ben olvasható sorrendet) -- ez a
            # KÓD-SORREND hűen tükrözi, mikor fut le az EA-logika, de NEM a VALÓS, tick-szintű
            # esemény-sorrendet -- ez okozott 2 konkrét, megtalált eltérést (2025-05-08 TF, 2025-05-20
            # LHC), amíg ki nem derült.
            if owner == "TF":
                position["extra"]["trend_extreme"] = (
                    max(position["extra"]["trend_extreme"], high_vals[idx]) if position["pos_type"] == "LONG"
                    else min(position["extra"]["trend_extreme"], low_vals[idx])
                )
                trail_sl = (
                    position["extra"]["trend_extreme"] - atr * TF_PARAMS["trail_atr_multiplier"]
                    if position["pos_type"] == "LONG"
                    else position["extra"]["trend_extreme"] + atr * TF_PARAMS["trail_atr_multiplier"]
                )
                position["sl_price"] = (max(position["sl_price"], trail_sl) if position["pos_type"] == "LONG"
                                         else min(position["sl_price"], trail_sl))
            # resolve_fixed_exit-stílus: SL ELSŐBBSÉGET élvez, ha egy baron BELÜL mindkettő (SL és
            # TP) elérhető lett volna. CSAK a MeanReversionnek van fix TP-je (`tp_price` kulcs) --
            # TF/LHC/FS-nél `position.get("tp_price")` None, tehát a tp_hit mindig False marad rájuk.
            tp_price = position.get("tp_price")
            sl_hit = (low_vals[idx] <= position["sl_price"] if position["pos_type"] == "LONG"
                      else high_vals[idx] >= position["sl_price"])
            tp_hit = (tp_price is not None and (
                high_vals[idx] >= tp_price if position["pos_type"] == "LONG" else low_vals[idx] <= tp_price
            ))
            if sl_hit:
                # a TF-nél a "SL" mindig egy MOZGÓ (trailing) stop -- a batch check_exit() ezt
                # "TRAIL_SL"-nek nevezi, a többi komponensnél (MR/LHC/FS) egyszerűen "SL".
                reason = "TRAIL_SL" if owner == "TF" else "SL"
                exit_decision = ExitDecision(exit_price=position["sl_price"], reason=reason)
            elif tp_hit:
                exit_decision = ExitDecision(exit_price=tp_price, reason="TP")

            # `IsFsSafetyCloseTime()` -- MINDEN ticken/baron ellenőrzött, a `IsFsHoldEnd()`-nél
            # ELSŐBBSÉGET élvező biztonsági zárás (lásd FridayShort.mqh fejléc-kommentje) -- csak
            # akkor, ha a SL fentebb NEM váltott ki ezen a baron.
            fs_safety_close = (eh > FS_SAFETY_CLOSE_HOUR or
                                (eh == FS_SAFETY_CLOSE_HOUR and em >= FS_SAFETY_CLOSE_MINUTE))
            if exit_decision is None and owner == "FS" and fs_safety_close:
                exit_decision = ExitDecision(exit_price=close_vals[idx], reason="HOLD_END")
            elif exit_decision is None and owner == "LHC" and mql5_is_session_end:
                exit_decision = ExitDecision(exit_price=close_vals[idx], reason="SESSION_END")
            elif exit_decision is None and owner == "FS":
                # MQL5-hű `IsFsHoldEnd()`: SAJÁT állapotból (bars_elapsed/nap-váltás), NEM a batch
                # előre-számolt `is_hold_end_bar` oszlopból.
                bars_elapsed = idx - position["entry_bar_idx"]
                day_changed_fs = dates[idx] != position["entry_date"]
                mql5_is_hold_end = (bars_elapsed >= FS_PARAMS["hold_bars"]) or day_changed_fs
                if mql5_is_hold_end:
                    exit_decision = ExitDecision(exit_price=close_vals[idx], reason="HOLD_END")
            if exit_decision is None and owner != "FS":
                day_changed_eod = dates[idx] != position["entry_date"]
                force_close_time_reached = (eh > FORCE_CLOSE_HOUR or
                                             (eh == FORCE_CLOSE_HOUR and em >= FORCE_CLOSE_MINUTE))
                if day_changed_eod or force_close_time_reached:
                    exit_decision = ExitDecision(exit_price=close_vals[idx], reason="EOD_FORCED")
            if exit_decision is None and is_last_bar_of_day[idx]:
                exit_decision = ExitDecision(exit_price=close_vals[idx], reason="EOD_FORCED")

            if exit_decision is not None:
                if position["pos_type"] == "LONG":
                    pnl = exit_decision.exit_price - position["entry_price"]
                else:
                    pnl = position["entry_price"] - exit_decision.exit_price
                streaming_trades.append({
                    "entry_date": position["entry_date"], "exit_date": dates[idx],
                    "component": owner, "pos_type": position["pos_type"],
                    "exit_reason": exit_decision.reason, "pnl_per_lot": pnl,
                })
                position = None
                owner = None
            continue   # ugyanaz a bar nem nyithat UJ pozíciót, ha volt már nyitott -- lasd MQL5 "return"

        if is_last_bar_of_day[idx]:
            continue   # HIBAJAVÍTÁS-konzisztens: a nap utolsó bar-ján nem nyitunk (lásd Engine.run())

        if trade_taken_today:
            # csak az FS kvóta-kivétel probálkozhat
            if fs_exception_used_today:
                continue
            # JAVÍTOTT FS trigger (lásd SESSION_LOG.md): minute 0 helyett 10 -- lásd
            # FridayShort.mqh CheckEntry() 2026-09-11-i javításának indoklását.
            if eh != FS_PARAMS["target_hour"] or em != 10 or int(day_of_weeks[idx]) != FS_PARAMS["target_day_of_week"]:
                continue
            if atr == 0.0 or np.isnan(atr):
                continue
            fs_exception_used_today = True
            position = {"pos_type": "SHORT", "entry_price": close_vals[idx], "entry_date": dates[idx],
                        "entry_bar_idx": idx, "sl_price": close_vals[idx] + atr * FS_PARAMS["sl_atr_multiplier"],
                        "extra": {}}
            owner = "FS"
            continue

        trend_band = trend_bands[idx]
        signal_fired = False

        if trend_band == "RANGING":
            ema_center = ema_center_vals[idx]
            channel_high = ema_center + atr * MR_PARAMS["mr_multiplier"]
            channel_low = ema_center - atr * MR_PARAMS["mr_multiplier"]
            sl_dist = atr * MR_PARAMS["sl_multiplier"]
            in_session = (h > SESSION["session_start_hour"] or
                          (h == SESSION["session_start_hour"] and m >= SESSION["session_start_minute"])) \
                and h < SESSION["session_end_hour"]
            if in_session and close_vals[idx] > channel_high:
                position = {"pos_type": "SHORT", "entry_price": close_vals[idx], "entry_date": dates[idx],
                            "entry_bar_idx": idx, "sl_price": close_vals[idx] + sl_dist,
                            "tp_price": close_vals[idx] - sl_dist * MR_PARAMS["risk_reward_ratio"], "extra": {}}
                owner = "MR"
                signal_fired = True
            elif in_session and close_vals[idx] < channel_low:
                position = {"pos_type": "LONG", "entry_price": close_vals[idx], "entry_date": dates[idx],
                            "entry_bar_idx": idx, "sl_price": close_vals[idx] - sl_dist,
                            "tp_price": close_vals[idx] + sl_dist * MR_PARAMS["risk_reward_ratio"], "extra": {}}
                owner = "MR"
                signal_fired = True
        elif trend_band == "TRENDING":
            fast_now, slow_now = ema_fast_vals[idx], ema_slow_vals[idx]
            rsi = rsi_vals[idx]
            bb_upper, bb_lower = bb_upper_vals[idx], bb_lower_vals[idx]
            in_session = (h > SESSION["session_start_hour"] or
                          (h == SESSION["session_start_hour"] and m >= SESSION["session_start_minute"])) \
                and h < SESSION["session_end_hour"]
            if in_session and fast_now > slow_now and rsi >= TF_PARAMS["rsi_long_min"] and close_vals[idx] > bb_upper:
                position = {"pos_type": "LONG", "entry_price": close_vals[idx], "entry_date": dates[idx],
                            "entry_bar_idx": idx, "sl_price": close_vals[idx] - atr * TF_PARAMS["sl_atr_multiplier"],
                            "extra": {"trend_extreme": close_vals[idx]}}
                owner = "TF"
                signal_fired = True
            elif in_session and fast_now < slow_now and rsi <= TF_PARAMS["rsi_short_max"] and close_vals[idx] < bb_lower:
                position = {"pos_type": "SHORT", "entry_price": close_vals[idx], "entry_date": dates[idx],
                            "entry_bar_idx": idx, "sl_price": close_vals[idx] + atr * TF_PARAMS["sl_atr_multiplier"],
                            "extra": {"trend_extreme": close_vals[idx]}}
                owner = "TF"
                signal_fired = True

        if not signal_fired:
            is_final_trend_bar = (eh == LHC_PARAMS["final_hour_start"] and em == 0)
            if is_final_trend_bar and not (atr == 0.0 or np.isnan(atr)):
                mql5_tr, mql5_valid, _cnt = compute_trend_return_mql5(
                    close_vals, hours, minutes, dates, idx,
                    SESSION["session_start_hour"], SESSION["session_start_minute"],
                    LHC_PARAMS["final_hour_start"], LHC_PARAMS["min_trend_bars"],
                )
                batch_tr = batch_trend_return_vals[idx]
                batch_valid = not np.isnan(batch_tr)
                mql5_decision = mql5_valid and mql5_tr > 0
                batch_decision = batch_valid and batch_tr > 0
                if mql5_decision != batch_decision:
                    lhc_disagreements.append((idx, str(dates[idx]), mql5_tr if mql5_valid else None,
                                               batch_tr if batch_valid else None))
                elif mql5_valid and batch_valid and abs(mql5_tr - batch_tr) > 1e-9:
                    lhc_value_diffs += 1

                if mql5_decision:
                    position = {"pos_type": "LONG", "entry_price": close_vals[idx], "entry_date": dates[idx],
                                "entry_bar_idx": idx, "sl_price": close_vals[idx] - atr * LHC_PARAMS["sl_atr_multiplier"],
                                "extra": {}}
                    owner = "LHC"
                    signal_fired = True

        if signal_fired:
            trade_taken_today = True

    logger.info("Streaming szimulátor: %d trade\n", len(streaming_trades))

    # --- 4. rész: összevetés ---
    logger.info("--- Empirikus P2-teszt (LastHourContinuation ComputeTrendReturn) ---")
    logger.info("LHC belépési DÖNTÉS-eltérés (jelzett/nem jelzett máshogy): %d eset", len(lhc_disagreements))
    for idx, d, mql5_tr, batch_tr in lhc_disagreements[:10]:
        logger.info("  idx=%d dátum=%s mql5_trend_return=%s batch_trend_return=%s", idx, d, mql5_tr, batch_tr)
    logger.info("LHC szám-eltérés (döntés egyezett, de az érték nem pontosan egyezik): %d eset", lhc_value_diffs)
    logger.info("Session-end (IsSessionEndBar) eltérés a batch oszloptól: %d bar\n", session_end_disagreements)

    logger.info("--- Trade-log összevetés (streaming vs. batch Engine.run()) ---")
    logger.info("Batch trade-szám: %d | Streaming trade-szám: %d", len(batch_trades), len(streaming_trades))

    # a batch Engine.run() a komponens teljes nevét ("MeanReversion") adja, a streaming
    # szimulátor (OWNER_TAG_*-hoz hasonlóan) a rövid MQL5-kódot ("MR") -- csak összevetéshez
    # normalizáljuk, ez maga NEM az összevetés tárgya.
    COMPONENT_NAME_MAP = {
        "MeanReversion": "MR", "TrendFollowing": "TF",
        "LastHourContinuation": "LHC", "FridayShort": "FS",
    }

    def trade_key(t):
        component = COMPONENT_NAME_MAP.get(t["component"], t["component"])
        return (str(t["entry_date"]), component, t["pos_type"], t["exit_reason"])

    batch_keys = [trade_key(t) for t in batch_trades]
    streaming_keys = [trade_key(t) for t in streaming_trades]

    mismatches = 0
    for i, (bk, sk) in enumerate(zip(batch_keys, streaming_keys)):
        if bk != sk:
            mismatches += 1
            if mismatches <= 10:
                logger.info("  ELTÉRÉS #%d (index %d): batch=%s vs streaming=%s", mismatches, i, bk, sk)
    if len(batch_keys) != len(streaming_keys):
        logger.info("  ⚠️ ELTÉRŐ TRADE-SZÁM: batch=%d, streaming=%d", len(batch_keys), len(streaming_keys))

    if mismatches == 0 and len(batch_keys) == len(streaming_keys):
        logger.info("\n✅ TELJES EGYEZÉS: a streaming (MQL5-hű) dispatch bit-pontosan ugyanazokat a "
                     "trade-eket adja, mint a batch Engine.run() (%d/%d).", len(batch_keys), len(batch_keys))
    else:
        logger.info("\n⚠️ ELTÉRÉS TALÁLVA -- lásd fent, részletes vizsgálat szükséges.")


if __name__ == "__main__":
    main()
