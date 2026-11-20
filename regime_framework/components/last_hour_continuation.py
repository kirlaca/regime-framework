"""
components/last_hour_continuation.py — a HARMADIK, formálisan beépített StrategyComponent, DE NEM
a `trend_band`-XOR rácsban (mint a MeanReversion/TrendFollowing), hanem egy IDŐABLAK-alapú,
párhuzamos mechanizmus (lásd `core/engine.py` `time_gated_components` paramétere).

SZÁRMAZÁS (2026-08-20-21, felhasználói felvetés: "zárószakasz anomália"): a kutatási lánc —
`research/last_hour_momentum_check.py` (kiindulómérés: a session utolsó órája [20:00-21:00
szerver-idő] mérhető, a véletlen-bolyongás alapvonalat meghaladó pozitív torzítást mutat UP-trend
napokon, DOWN-trend napokon nincs érdemi jel) -> `research/last_hour_continuation_experiment.py`
(önálló belépési szabály, mindhárom US-szimbólumon nyereséges: US100 PF 1.74, US500 PF 1.61, US30
PF 1.51) -> durva költség-érzékenységi becslés (mindhárom NETTÓ PF > 1.0: 1.59/1.42/1.35 — ELSŐ
eset, hogy US30 GENUINELY jól teljesít) -> `research/last_hour_engine_conflict_check.py` (a
meglévő MeanReversion/TrendFollowing Engine az UP-trend napok 24.5-30.3%-án MÁR foglalt lenne
20:00-kor, DE 69.7-75.5%-a szabad marad -> a mechanizmus nagyrészt átvihető egy integrált
rendszerbe).

⚠️ ARCHITEKTURÁLIS INDOKLÁS (miért NEM a `trend_band`-rácsba illeszkedik): a mechanizmus
INTUÍCIÓJA trend-követő (menj a nap kialakult irányával), DE a jele NEM egy folyamatos EMA/
Bollinger-indikátor, hanem egy FIX NAPTÁRI IDŐPONTHOZ (20:00) kötött, a nap addigi (16:30-20:00)
NYERS KUMULÁLT HOZAMÁNAK előjele — ez az aktiválási bar-ok mindössze ~22%-át érinti a session-nek
(6 a 27-ből), és teljesen független attól, mit mond a `MarketConditionClassifier` trend_band-je
abban a pillanatban (ezt sosem teszteltük/használtuk fel). A felhasználóval egyeztetve (a
`TrendFollowingComponent` amúgy is "már így is nagyon bonyolult") ez NEM oda épült be, hanem
külön, `core/engine.py`-ban egy ÚJ, a `trend_band`-XOR-tól FÜGGETLEN, párhuzamos dispatch-ágként.

BELÉPÉS: a "trend-szakasz" (session_start_hour:session_start_minute - final_hour_start, alapból
16:30-20:00) UTOLSÓ bar-jának záróárán, HA a trend-szakasz hozama pozitív volt — ez pontosan
megegyezik azzal a bar-ral, amin a validált kutatási script (`last_hour_continuation_experiment.py`)
is belépett. A trend-szakasz hozamát a `prepare_indicators()` számítja ki, napi bontásban, és
KIZÁRÓLAG a trend-szakasz saját utolsó bar-jára írja rá (nem a rákövetkező bar-ra — egy korábbi
verzió egy bar-nyi csúszást tartalmazott emiatt, smoke teszt fogta meg, lásd SESSION_LOG.md).
KILÉPÉS: ATR-alapú SL (biztonsági fék) VAGY a session végén (session_end_hour, alapból 21:00)
kényszerzárás — NEM trailing stop, a mérés maga a "tartsd az utolsó órára" ötletet validálta, nem
egy "fusson tovább" logikát.

ISMERT, SZÁNDÉKOS EGYSZERŰSÍTÉS: nincs spread/szlippázs/jutalék modellezve a `validate()`-ben (a
`research/last_hour_continuation_experiment.py` külön, durva becslést adott erre — mindhárom
szimbólumon NETTÓ PF > 1.0 maradt).
"""

import numpy as np

from regime_framework.core.indicators import compute_simple_atr
from regime_framework.core.types import BarContext, ExitDecision, Position, RegimeState, Signal, ValidationReport
from regime_framework.core.us_session import us_dst_hour_shift


class LastHourContinuationComponent:
    name = "LastHourContinuation"
    # SZÁNDÉKOSAN NINCS applicable_trend_bands -- ez a komponens NEM vesz részt a trend_band-XOR
    # rácsban (lásd fájl fejléc), az Engine `time_gated_components` listáján keresztül, a
    # trend_band-től függetlenül, tisztán időablak-alapon aktiválódik.

    def __init__(self, session_start_hour=16, session_start_minute=30, final_hour_start=20,
                 session_end_hour=21, sl_atr_multiplier=2.5, lot_size=0.1, min_trend_bars=10,
                 dst_aware=False):
        self.session_start_hour = session_start_hour
        self.session_start_minute = session_start_minute
        self.final_hour_start = final_hour_start
        self.session_end_hour = session_end_hour
        self.sl_atr_multiplier = sl_atr_multiplier
        self.lot_size = lot_size
        self.min_trend_bars = min_trend_bars
        # `dst_aware` -- lásd core/us_session.py fejléc-kommentjét. SZÁNDÉKOSAN False
        # alapértelmezett -- a jelenlegi ÉLŐ (paraméter nélkül hívott) viselkedés bit-pontosan
        # változatlan marad, amíg ezt valaki explicit be nem kapcsolja.
        self.dst_aware = dst_aware

    def _in_trend_window(self, hour, minute, shift=0):
        start_hour = self.session_start_hour + shift
        final_hour = self.final_hour_start + shift
        after_start = (hour > start_hour) or \
                      (hour == start_hour and minute >= self.session_start_minute)
        return after_start and hour < final_hour

    def is_regime_eligible(self, regime: RegimeState) -> bool:
        """Szándékosan MINDIG True -- ez a komponens a trend_band-től függetlenül aktiválódik,
        kizárólag az időablak (lásd check_entry) dönt."""
        return True

    def check_entry(self, ctx: BarContext) -> Signal | None:
        """Csak PONTOSAN a trend-szakasz UTOLSÓ bar-ján jelezhet (ahol a `trend_return` indikátor
        nem-NaN — lásd `prepare_indicators()`) -- ez a bar-ja a záróár, amin a kutatási script is
        belépett (a KÖVETKEZŐ, final_hour_start:00-ás bar-on belépni egy bar-nyi csúszást jelentene
        a validált eredményhez képest)."""
        trend_return = ctx.indicators.get("trend_return")
        if trend_return is None or np.isnan(trend_return) or trend_return <= 0:
            return None

        atr = ctx.indicators["atr"]
        sl_price = ctx.close - atr * self.sl_atr_multiplier
        return Signal(direction="LONG", sl_price=sl_price, tp_price=None)

    def check_exit(self, ctx: BarContext, position: Position) -> ExitDecision | None:
        """ATR-alapú SL (biztonsági fék) VAGY session-végi kényszerzárás -- NEM trailing stop.
        Az `is_session_end_bar` indikátor (lásd `prepare_indicators()`) jelzi az utolsó órán
        BELÜLI utolsó bar-t (a session_end_hour ELŐTTI utolsó bar-t) -- ugyanaz a bar, amin a
        kutatási script is zárt, nem a session_end_hour-t MÁR ELÉRŐ, azt követő bar (egy korábbi
        verzió ott zárt, egy bar-nyi csúszást okozva a validált eredményhez képest)."""
        if ctx.low <= position.sl_price:
            return ExitDecision(exit_price=position.sl_price, reason="SL")
        if ctx.indicators.get("is_session_end_bar"):
            return ExitDecision(exit_price=ctx.close, reason="SESSION_END")
        return None

    def suggest_params(self, trial):
        """Optuna-paraméter-tér — csak az ehhez a komponenshez tartozó paramétereket ajánlja fel.
        `min_trend_bars` felső határa 20 (a 16:30-20:00 trend-ablak M10-en legfeljebb 21 bar-t ad
        — 20-nál kevesebb bar esetén már gyakorlatilag minden nap érvénytelenné válna)."""
        return {
            "sl_atr_multiplier": trial.suggest_float("lhc_sl_atr_multiplier", 1.0, 4.0),
            "min_trend_bars": trial.suggest_int("lhc_min_trend_bars", 5, 20),
        }

    def prepare_indicators(self, df):
        """A 'trend_return' oszlopot NAPONKÉNT számítja ki (a trend-szakasz [session_start -
        final_hour_start] hozama), és KIZÁRÓLAG a trend-szakasz LEZÁRÁSA UTÁNI ELSŐ bar-ra írja rá
        -- ez nem look-ahead, mert a trend-szakasz addigra már ténylegesen lezárult, csak az
        indexelést egyszerűsíti (a check_entry() ugyanezt a bar-ot vizsgálja, hour==final_hour_start,
        minute==0)."""
        df = df.copy()
        df["atr"] = compute_simple_atr(df)
        df = df.dropna(subset=["atr"]).reset_index(drop=True)
        df["hour"] = df["time"].dt.hour
        df["minute"] = df["time"].dt.minute
        df["date"] = df["time"].dt.date

        if self.dst_aware:
            shift_by_date = {d: us_dst_hour_shift(d) for d in df["date"].unique()}
            df["dst_shift"] = df["date"].map(shift_by_date)
        else:
            df["dst_shift"] = 0

        is_trend_bar = df.apply(
            lambda r: self._in_trend_window(int(r["hour"]), int(r["minute"]), int(r["dst_shift"])), axis=1)
        is_final_bar = (df["hour"] >= self.final_hour_start + df["dst_shift"]) & \
                       (df["hour"] < self.session_end_hour + df["dst_shift"])
        df["trend_return"] = np.nan
        df["is_session_end_bar"] = False

        for date, day_df in df.groupby("date"):
            day_trend_bars = day_df[is_trend_bar.loc[day_df.index]]
            if len(day_trend_bars) >= self.min_trend_bars:
                trend_return = np.log(day_trend_bars["close"].iloc[-1] / day_trend_bars["close"].iloc[0])
                last_trend_idx = day_trend_bars.index[-1]
                df.loc[last_trend_idx, "trend_return"] = trend_return

            day_final_bars = day_df[is_final_bar.loc[day_df.index]]
            if len(day_final_bars) > 0:
                df.loc[day_final_bars.index[-1], "is_session_end_bar"] = True

        return df

    def validate(self, df, market_classifier=None) -> ValidationReport:
        """Elszigetelt backtest, ugyanabban a szellemben, mint a másik két komponensé — NEM
        használja a `MarketConditionClassifier`-t (a `market_classifier` paraméter csak az
        interfész-egyezés kedvéért van itt, figyelmen kívül hagyva), mert ez a komponens
        szándékosan a trend_band-től FÜGGETLEN."""
        indicator_df = self.prepare_indicators(df)

        n = len(indicator_df)
        close_vals = indicator_df["close"].to_numpy()
        high_vals = indicator_df["high"].to_numpy()
        low_vals = indicator_df["low"].to_numpy()
        atr_vals = indicator_df["atr"].to_numpy()
        trend_return_vals = indicator_df["trend_return"].to_numpy()
        is_session_end_bar_vals = indicator_df["is_session_end_bar"].to_numpy()
        hours = indicator_df["hour"].to_numpy()
        minutes = indicator_df["minute"].to_numpy()
        dates = indicator_df["date"].to_numpy()

        is_last_bar_of_day = np.zeros(n, dtype=bool)
        if n > 0:
            is_last_bar_of_day[:-1] = dates[:-1] != dates[1:]
            is_last_bar_of_day[-1] = True

        trade_log = []
        position = None
        entry_date = None
        current_day = None
        trade_taken_today = False

        for idx in range(n):
            if dates[idx] != current_day:
                current_day = dates[idx]
                trade_taken_today = False

            ctx = BarContext(
                time=None, open=None, high=high_vals[idx], low=low_vals[idx], close=close_vals[idx],
                hour=int(hours[idx]), minute=int(minutes[idx]), day_of_week=0, date=dates[idx],
                regime=None,
                indicators={"atr": atr_vals[idx], "trend_return": trend_return_vals[idx],
                            "is_session_end_bar": bool(is_session_end_bar_vals[idx])},
            )

            if position is not None:
                exit_decision = self.check_exit(ctx, position)
                if exit_decision is None and is_last_bar_of_day[idx]:
                    exit_decision = ExitDecision(exit_price=ctx.close, reason="EOD_FORCED")
                if exit_decision is not None:
                    pnl = self.lot_size * (exit_decision.exit_price - position.entry_price)
                    trade_log.append({
                        "entry_date": entry_date, "exit_date": dates[idx],
                        "pos_type": position.pos_type, "exit_reason": exit_decision.reason, "pnl": pnl,
                    })
                    position = None
            elif not trade_taken_today:
                signal = self.check_entry(ctx)
                if signal is not None:
                    trade_taken_today = True
                    position = Position(pos_type=signal.direction, entry_price=ctx.close,
                                         entry_date=dates[idx], sl_price=signal.sl_price,
                                         tp_price=signal.tp_price, extra={})
                    entry_date = dates[idx]

        wins = [t for t in trade_log if t["pnl"] > 0]
        win_rate = len(wins) / len(trade_log) * 100 if trade_log else 0.0
        gross_win = sum(t["pnl"] for t in wins)
        gross_loss = abs(sum(t["pnl"] for t in trade_log if t["pnl"] <= 0))
        profit_factor = gross_win / gross_loss if gross_loss > 0 else float("inf")
        total_pnl = sum(t["pnl"] for t in trade_log)

        report = ValidationReport(
            component_name=self.name, trade_count=len(trade_log), win_rate=win_rate,
            profit_factor=profit_factor, total_pnl=total_pnl,
        )
        report.notes["n_bars"] = n
        report.notes["sl_exits"] = sum(1 for t in trade_log if t["exit_reason"] == "SL")
        report.notes["session_end_exits"] = sum(1 for t in trade_log if t["exit_reason"] == "SESSION_END")
        report.notes["eod_forced_exits"] = sum(1 for t in trade_log if t["exit_reason"] == "EOD_FORCED")

        if not report.is_reliable():
            report.warnings.append(f"Csak {len(trade_log)} trade — a 30-as megbízhatósági küszöb alatt.")
        if trade_log and profit_factor < 1.0:
            report.warnings.append(f"Profit factor ({profit_factor:.2f}) < 1 — nem nyereséges ezen az adatsoron.")
        report.warnings.append(
            "⚠️ NINCS spread/szlippázs/jutalék modellezve — lásd research/last_hour_continuation_"
            "experiment.py a durva költség-érzékenységi becslésért."
        )

        return report
