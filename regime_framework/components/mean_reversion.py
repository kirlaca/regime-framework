"""
Az első valódi StrategyComponent — a main_optuna_anomaly.py MeanReversion szálának portolása az
új interfészbe (lásd PLAN.md 5. "Interfész-vázlat" és 6. build-sorrend, 4. pont).

Miért csak RANGING-nél aktív: a regime_conditional_backtest.py (régi kódbázis) már megmutatta,
hogy ez a csatorna-logika oldalazó napokon nyereséges (42.9% win-rate, +60.34 PnL), trendelő
napokon viszont veszteséges (25.4% win-rate, -166.97 PnL). Ez a komponens ezért a saját
applicable_trend_bands halmazán keresztül explicit módon KIZÁRJA magát TRENDING/TRANSITIONAL
rezsimből — ez maga a "réteg-szűrő" a gyakorlatban, amit a PLAN.md architektúra-vázlata leír.

ISMERT, SZÁNDÉKOS EGYSZERŰSÍTÉSEK:
  1. Nincs spread/szlippázs/jutalék modellezve — ez egy keresztmetszeti (minden komponensre
     közös) költség-kérdés, amit az Engine szintjén érdemes egyszer bekötni, nem itt duplikálni.
  2. Egyszerre csak egy pozíció, napon belüli kényszerzárással (EOD_FORCED) — ugyanaz a
     viselkedés, mint a régi simulate_trades()-ben.
  3. NINCS keddi kizárás (a régi kód `d != 1`-je). A régi rendszerben ez azért kellett, hogy a
     MeanReversion ne ütközzön a TurnaroundTuesday szállal (ami kizárólag keddet kezelte). Mivel
     a TurnaroundTuesday komponens még nem létezik ebben az architektúrában, nincs mivel
     ütköznie — a kizárást akkor adjuk hozzá (komponens-szinten vagy Engine-szintű XOR-
     szabályként), amikor a TurnaroundTuesday megépül. Döntés a felhasználóval egyeztetve
     (2026-08-19), lásd SESSION_LOG.md.
Ezeket a validate() eredménye NEM hivatott végleges, költség-korrigált teljesítménymérésnek
tekinteni — a célja a regresszió-ellenőrzés: hogy a portolás nem változtatott az entry/exit
logikán és a regime-kapun.

SESSION-SZŰRÉS — KÍSÉRLET ÉS VISSZAVONÁS (2026-08-19): megpróbáltuk lecserélni a fix "amerikai
session" (16:30-21:00) óraablakot a `SessionPhaseClassifier`-re, két változatban is (1: CORE_
SESSION-only, OPENING_RANGE+ROLLOVER kizárva; 2: csak ROLLOVER kizárva). Valós MT5 Optuna-
újrafuttatással MINDKETTŐ ÖSSZESSÉGÉBEN ROSSZABBNAK bizonyult, mint az eredeti fix ablak (a
kockázat-korrigált pontszámok összege 5 szimbólumon: ~255 [eredeti] → ~59 [1. verzió] → ~-0.4
[2. verzió]) — US100/JP225-nél mindkét verzió drámai összeomlást okozott. Kiderült: (a) a régi,
"hibás" US-ablak véletlenül majdnem egybeesett azzal, amit a klasszifikátor "OPENING_RANGE"-nek
jelöl az US-csoportnál — ott pont AZOKBAN az órákban volt a tényleges él; (b) a `GROUPS` konfigban
US/JP csoportnál a `rollover` halmaz ÜRES, így a 2. verzió ezekre a szimbólumokra gyakorlatilag
"nincs szűrés"-t jelentett, ami még rosszabb volt, mint az 1. verzió. **Következtetés: a
`SessionPhaseClassifier` kategorikus felosztása (OPENING_RANGE/CORE_SESSION/ROLLOVER) jó eszköz a
volatilitás-rezsim váltások mérésére, de nem azonos azzal, hogy "mikor van valódi éle ennek a
konkrét csatorna-logikának" — a felhasználóval egyeztetve VISSZAÁLLÍTVA az eredeti, empirikusan
bizonyítottan jobb fix óraablakra.**

MEGFIGYELÉS (felhasználó felvetése, 2026-08-19): a mintázat NEM egységes "US-session mindent visz"
jelenség — ha az lenne, GER40/EU50-nek is romlania kellett volna a fix (US-)ablak eltávolításakor,
de ehelyett JAVULTAK. Valószínűbb magyarázat: JP225-nél (0-24h kereskedett CFD) a valódi
kereskedhető trend a globálisan domináns US-szakaszban jelenik meg (nem a helyi tokiói nyitáskor),
míg GER40/EU50-nek van saját, valódi éle a saját (európai) óráiban, amit a US-ablakra kényszerítés
eddig elnyomott. NYITOTT ÖTLET jövőbeli finomításra: a session-ablak határait (jelenleg hardcode-olt)
Optuna-tanulhatóvá tenni szimbólumonként, hogy mindegyik megtalálja a SAJÁT optimális ablakát.
"""

import numpy as np

from regime_framework.core.types import BarContext, ExitDecision, Position, RegimeState, Signal, ValidationReport
from regime_framework.core.us_session import us_dst_hour_shift
from regime_framework.regime.market_condition import MarketConditionClassifier


def resolve_fixed_exit(pos_type, high, low, sl_price, tp_price):
    """Pesszimista feloldás: ha egy gyertyán belül mindkettő (TP és SL) elérhető lett volna, az
    SL-t vesszük irányadónak — ugyanaz a szabály, mint a main_optuna_anomaly.py _resolve_exit()-je."""
    if pos_type == "LONG":
        tp_hit = high >= tp_price
        sl_hit = low <= sl_price
    else:
        tp_hit = low <= tp_price
        sl_hit = high >= sl_price
    if sl_hit:
        return sl_price, "SL"
    if tp_hit:
        return tp_price, "TP"
    return None, None


class MeanReversionComponent:
    name = "MeanReversion"
    applicable_trend_bands = {"RANGING"}

    def __init__(self, ema_period=70, mr_multiplier=2.2, sl_multiplier=1.5,
                 risk_reward_ratio=2.5, lot_size=0.1,
                 session_start_hour=16, session_start_minute=30, session_end_hour=21,
                 dst_aware=False):
        self.ema_period = ema_period
        self.mr_multiplier = mr_multiplier
        self.sl_multiplier = sl_multiplier
        self.risk_reward_ratio = risk_reward_ratio
        self.lot_size = lot_size
        self.session_start_hour = session_start_hour
        self.session_start_minute = session_start_minute
        self.session_end_hour = session_end_hour
        # `dst_aware` -- lásd core/us_session.py fejléc-kommentjét. SZÁNDÉKOSAN False
        # alapértelmezett -- a jelenlegi ÉLŐ (paraméter nélkül hívott) viselkedés bit-pontosan
        # változatlan marad, amíg ezt valaki explicit be nem kapcsolja.
        self.dst_aware = dst_aware

    def _is_session_hour(self, hour, minute, date=None):
        shift = us_dst_hour_shift(date) if (self.dst_aware and date is not None) else 0
        start_hour = self.session_start_hour + shift
        end_hour = self.session_end_hour + shift
        after_start = (hour > start_hour) or \
                      (hour == start_hour and minute >= self.session_start_minute)
        return after_start and hour < end_hour

    def is_regime_eligible(self, regime: RegimeState) -> bool:
        return regime is not None and regime.trend_band in self.applicable_trend_bands

    def check_entry(self, ctx: BarContext) -> Signal | None:
        if not self.is_regime_eligible(ctx.regime):
            return None
        if not self._is_session_hour(ctx.hour, ctx.minute, ctx.date):
            return None

        ema_center = ctx.indicators["ema_center"]
        atr = ctx.indicators["atr"]
        channel_high = ema_center + atr * self.mr_multiplier
        channel_low = ema_center - atr * self.mr_multiplier
        sl_dist = atr * self.sl_multiplier

        if ctx.close > channel_high:
            return Signal(direction="SHORT", sl_price=ctx.close + sl_dist,
                          tp_price=ctx.close - sl_dist * self.risk_reward_ratio)
        if ctx.close < channel_low:
            return Signal(direction="LONG", sl_price=ctx.close - sl_dist,
                          tp_price=ctx.close + sl_dist * self.risk_reward_ratio)
        return None

    def check_exit(self, ctx: BarContext, position: Position) -> ExitDecision | None:
        exit_price, reason = resolve_fixed_exit(position.pos_type, ctx.high, ctx.low,
                                                  position.sl_price, position.tp_price)
        if reason is None:
            return None
        return ExitDecision(exit_price=exit_price, reason=reason)

    def suggest_params(self, trial):
        """Optuna-paraméter-tér — csak az ehhez a komponenshez tartozó paramétereket ajánlja fel,
        hogy egy jövőbeli többkomponenses study-ban is elszigetelten hangolható legyen."""
        return {
            "ema_period": trial.suggest_int("mr_ema_period", 40, 100),
            "mr_multiplier": trial.suggest_float("mr_mr_multiplier", 1.5, 3.0),
            "sl_multiplier": trial.suggest_float("mr_sl_multiplier", 1.0, 2.5),
            "risk_reward_ratio": trial.suggest_float("mr_risk_reward_ratio", 1.5, 3.5),
        }

    def prepare_indicators(self, df):
        """Csak az ema_center-t adja hozzá — az atr/adx-et szándékosan NEM itt számoljuk, hanem a
        MarketConditionClassifier.classify_series() teszi meg (a saját trend/vol besorolásához úgyis
        kiszámolja őket); a duplikált számítás csak felesleges, kettős lekerekítést okozna a
        NaN-eldobásoknál."""
        df = df.copy()
        df["ema_center"] = df["close"].ewm(span=int(self.ema_period), adjust=False).mean()
        df = df.dropna(subset=["ema_center"]).reset_index(drop=True)
        df["hour"] = df["time"].dt.hour
        df["minute"] = df["time"].dt.minute
        df["date"] = df["time"].dt.date
        return df

    def validate(self, df, market_classifier: MarketConditionClassifier = None) -> ValidationReport:
        """Elszigetelt backtest: bar-onként ellenőrzi a regime-et (MarketConditionClassifier) és a
        saját entry/exit logikáját, egyszerre csak egy pozíciót tartva, napon belüli kényszer-
        zárással. Ez NEM a teljes, több-komponenses Engine (lásd build-sorrend 6. pont), hanem
        ennek az egy komponensnek az önálló, izolált tesztje, ugyanabban a szellemben, mint a
        rezsim-osztályozók saját validate()-je."""
        if market_classifier is None:
            market_classifier = MarketConditionClassifier()

        indicator_df = self.prepare_indicators(df)
        classified = market_classifier.classify_series(indicator_df)

        n = len(classified)
        close_vals = classified["close"].to_numpy()
        high_vals = classified["high"].to_numpy()
        low_vals = classified["low"].to_numpy()
        ema_vals = classified["ema_center"].to_numpy()
        atr_vals = classified["atr"].to_numpy()
        hours = classified["hour"].to_numpy()
        minutes = classified["minute"].to_numpy()
        dates = classified["date"].to_numpy()
        trend_bands = classified["trend_band"].to_numpy()
        vol_bands = classified["vol_band"].to_numpy()

        is_last_bar_of_day = np.zeros(n, dtype=bool)
        if n > 0:
            is_last_bar_of_day[:-1] = dates[:-1] != dates[1:]
            is_last_bar_of_day[-1] = True

        trade_log = []
        position = None
        entry_date = None
        entry_vol_band = None

        for idx in range(n):
            regime = RegimeState(session_phase="CORE_SESSION", trend_band=trend_bands[idx])
            ctx = BarContext(
                time=None, open=None, high=high_vals[idx], low=low_vals[idx], close=close_vals[idx],
                hour=int(hours[idx]), minute=int(minutes[idx]), day_of_week=0, date=dates[idx],
                regime=regime, indicators={"ema_center": ema_vals[idx], "atr": atr_vals[idx]},
            )

            if position is not None:
                # HIBAJAVÍTÁS (2026-09-05, folytatás) -- lásd `trend_following.py` azonos helyen
                # lévő részletes magyarázatát: `is_last_bar_of_day` önmagában nem elég megbízható
                # (néha "eltűnik" a nap utolsó bar-ja NaN-szűrés/merge-artifact miatt), ezért
                # elsődleges védelemként a napváltást magát nézzük.
                if dates[idx] != entry_date:
                    exit_decision = ExitDecision(exit_price=ctx.close, reason="EOD_FORCED")
                else:
                    exit_decision = self.check_exit(ctx, position)
                    if exit_decision is None and is_last_bar_of_day[idx]:
                        exit_decision = ExitDecision(exit_price=ctx.close, reason="EOD_FORCED")

                if exit_decision is not None:
                    if position.pos_type == "LONG":
                        pnl = self.lot_size * (exit_decision.exit_price - position.entry_price)
                    else:
                        pnl = self.lot_size * (position.entry_price - exit_decision.exit_price)
                    trade_log.append({
                        "entry_date": entry_date, "exit_date": dates[idx],
                        "pos_type": position.pos_type, "exit_reason": exit_decision.reason,
                        "pnl": pnl, "vol_band": entry_vol_band,
                    })
                    position = None
            # `is_last_bar_of_day[idx]` kizárás -- HIBAJAVÍTÁS (2026-09-05), lásd
            # `trend_following.py` azonos helyen lévő, részletesebb magyarázatát: ha egy jel
            # PONT a nap utolsó bar-ján tüzelt, a régi kód belépett, de a napvégi kényszerzárás
            # csak a KÖVETKEZŐ (már másnapi) bar-on futott volna -- a pozíció akár hétvégén át is
            # nyitva maradhatott.
            elif not is_last_bar_of_day[idx]:
                signal = self.check_entry(ctx)
                if signal is not None:
                    position = Position(pos_type=signal.direction, entry_price=ctx.close,
                                         entry_date=dates[idx], sl_price=signal.sl_price,
                                         tp_price=signal.tp_price)
                    entry_vol_band = vol_bands[idx]
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
        report.notes["regime_gate"] = f"csak {sorted(self.applicable_trend_bands)} trend_band mellett aktív"
        report.notes["sl_exits"] = sum(1 for t in trade_log if t["exit_reason"] == "SL")
        report.notes["tp_exits"] = sum(1 for t in trade_log if t["exit_reason"] == "TP")
        report.notes["eod_forced_exits"] = sum(1 for t in trade_log if t["exit_reason"] == "EOD_FORCED")

        # vol_band bontás: a komponens jelenleg NEM tesz különbséget LOW/HIGH volatilitás között
        # (csak trend_band-re kapuz) — ez a bontás megmutatja, van-e érdemi különbség a kettő
        # között, ami egy jövőbeli finomítást (pl. HIGH-vol-ra célzó komponens) alapozhatna meg.
        low_vol_trades = [t for t in trade_log if t["vol_band"] == "LOW"]
        high_vol_trades = [t for t in trade_log if t["vol_band"] == "HIGH"]
        report.notes["low_vol_trades"] = len(low_vol_trades)
        report.notes["high_vol_trades"] = len(high_vol_trades)
        if low_vol_trades:
            low_vol_wins = [t for t in low_vol_trades if t["pnl"] > 0]
            report.notes["low_vol_win_rate"] = round(len(low_vol_wins) / len(low_vol_trades) * 100, 1)
            report.notes["low_vol_pnl"] = round(sum(t["pnl"] for t in low_vol_trades), 2)
        if high_vol_trades:
            high_vol_wins = [t for t in high_vol_trades if t["pnl"] > 0]
            report.notes["high_vol_win_rate"] = round(len(high_vol_wins) / len(high_vol_trades) * 100, 1)
            report.notes["high_vol_pnl"] = round(sum(t["pnl"] for t in high_vol_trades), 2)

        if not report.is_reliable():
            report.warnings.append(
                f"Csak {len(trade_log)} trade — a 30-as megbízhatósági küszöb alatt "
                f"(lásd Turnaround Tuesday tanulság, PLAN.md 2. táblázat)."
            )
        if trade_log and profit_factor < 1.0:
            report.warnings.append(f"Profit factor ({profit_factor:.2f}) < 1 — nem nyereséges ezen az adatsoron.")
        if report.notes["eod_forced_exits"] > len(trade_log) * 0.5 and trade_log:
            report.warnings.append(
                "A trade-ek több mint fele EOD kényszerzárással zárult — érdemes megnézni, hogy az "
                "SL/TP távolság nem túl tág-e a rendelkezésre álló session-ablakhoz képest."
            )

        return report
