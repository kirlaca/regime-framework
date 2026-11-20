"""
components/trend_following.py — a második StrategyComponent, a TRENDING rezsim-cellákhoz.

A main_optuna_hybrid.py TrendFollowing szálának (gyors/lassú EMA-viszony belépés + ATR trailing
stop kilépés) portolása az új interfészbe. A régi kódbázis története fontos (lásd
main_optuna_hybrid.py fejléc-kommentje): az ELSŐ terv (Donchian-csatorna kitörés) HÁROM független,
fix paraméteres validáción következetesen profit factor <1-et adott — az EMA-alapú belépésre
váltás azért történt, mert az kevésbé zajérzékeny.

Miért csak TRENDING-nél aktív: a régi kódban ez a szál kizárólag `not is_ranging` (magas ADX)
mellett futott, ahogy a MeanReversion a `RANGING`-nél. Itt ugyanaz a minta az
`applicable_trend_bands` halmazon keresztül, mint a MeanReversionComponent-nél.

TÖRTÉNET (2026-08-19, a valós MT5 validáció után): az ELSŐ port a régi kód pontos belépési
mechanizmusát vette át (csak az EMA-keresztezés ÁTMENETI bar-ján lépett be), NAPVÉGI kényszerzárás
nélkül (a régi kód szándékosan több napon át futni hagyta a pozíciót). Ez valós adaton mindössze
9-17 trade-et adott szimbólumonként — kiderült, hogy ez STRUKTURÁLIS probléma: a keresztezés ritka,
egyetlen-bar esemény, amit a szűk (16:30-21:00) session-ablak tovább szűkített — ha a keresztezés a
session-ablakon KÍVÜL történt, a jel véglegesen elveszett.

A felhasználóval egyeztetve (döntés: overnight fee miatt a többnapos tartás NEM prioritás M10-M30
idősíkon — azt inkább H1-H4-en érdemes keresni) KÉT változtatás történt egyszerre:
  1. A belépés ÁLLAPOT-alapúra váltott (a keresztezés PONTOS bar-ja helyett bármelyik session-órás
     bar számít, ahol a gyors EMA már a lassú felett/alatt van) — sokkal több belépési lehetőség
     naponta.
  2. Napvégi kényszerzárás bekerült (mint a MeanReversionnél) — nincs overnight-kockázat/díj, és
     napi maximum EGY belépés (`trade_taken_today` flag), hogy egy korai kiütés után ne nyisson
     újra ugyanazon a napon (ugyanaz a minta, mint a régi kód Tuesday/EODRebalancing kizárása).
Ez a MOST érvényes, aktuális viselkedés — a fenti "TÖRTÉNET" bekezdés csak dokumentációs okból
maradt itt, hogy a döntés indoklása megmaradjon.

A fenti két változtatás valós MT5 adaton MIND AZ 5 szimbólumon nyereségesnek bizonyult (PF
1.04-1.29, ~230-250 trade/szimbólum, figyelmeztetés nélkül) — ez volt eddig a legerősebb eredmény
a rendszerben.

RSI-MOMENTUM-SZŰRŐ (hozzáadva 2026-08-19, KÜLÖN lépésként a fenti kettőtől, hogy a hatása
elkülöníthető legyen): a felhasználó vetette fel ("a belépési momentumot segíthetné esetleg RSI?").

ELSŐ VÁLTOZAT (SÁV, mindkét oldalról korlátozva: LONG 50<=RSI<=70, SHORT 30<=RSI<=50) valós MT5
adaton a win-rate-et mindenhol javította/stagnálta, de az ÖSSZ. PnL-t ~31%-kal rontotta (1045→721)
— méghozzá pont a két legerősebb szimbólumnál (JP225, GER40) esett a legtöbbet. Diagnózis: a felső
sávhatár (RSI<=70 LONG-nál) éppen a legerősebb trend-szakaszokat vágta ki — kereskedési közhely,
hogy erős trendben az RSI tartósan szélsőértéken maradhat, ami NEM kifulladás jele, hanem a trend
erejének megerősítése.

JAVÍTOTT, JELENLEGI VÁLTOZAT (felhasználóval egyeztetve): a FELSŐ határ megszűnt. LONG csak
`RSI >= rsi_long_min` (alapértelmezetten 50, nincs felső korlát), SHORT csak
`RSI <= rsi_short_max` (alapértelmezetten 50, nincs alsó korlát). Így a szűrő KIZÁRÓLAG a gyenge/
bizonytalan momentumú belépéseket zárja ki (RSI a felezővonal rossz oldalán), a túlfutást NEM
tekinti kizáró oknak.

SESSION-SZŰRÉS — KÍSÉRLET ÉS VISSZAVONÁS (2026-08-19, lásd MeanReversionComponent docstringjét a
teljes indoklásért): megpróbáltuk a fix "amerikai session" (16:30-21:00) óraablakot lecserélni a
`SessionPhaseClassifier`-re (két változatban), de mindkettő ÖSSZESSÉGÉBEN ROSSZABBNAK bizonyult
valós MT5 Optuna-újrafuttatással (US100/JP225-nél drámai összeomlás). Felhasználóval egyeztetve
VISSZAÁLLÍTVA az eredeti fix óraablakra.

BOLLINGER-KITÖRÉS MEGERŐSÍTÉS (hozzáadva 2026-08-20, "kettős megerősítés" — a felhasználó eredeti
felvetése: több TrendFollowing-jellegű komponens versenyezhetne egymással; ehelyett egy ÖT LÉPÉSES
olcsó mérés-lánc futott a `research/`-ben, mielőtt bármi bekerült volna ide, lásd
`components/double_confirmation.py` fejléc-docstringje a teljes lánc részletes leírásáért):
Bollinger-szalag kitörés (mint önálló, a Donchian-csatorna szerkezeti rokona, ami a régi
kódbázisban 3x megbukott) MÉGIS pozitívnak bizonyult US100/US500-on -> a Bollinger és a puszta
EMA-keresztezéses TrendFollowing jelei <60-70%-ban fedik át (nem redundáns mechanizmus) ->
ELLENTÉTES irányú napokon egyik komponensnek sem volt érdemi éle (52.6%-ban mindkettő veszített) ->
EGYETÉRTŐ napokon MINDKÉT komponens érdemben jobban teljesített, mint önmagában (US30-nál
negatívból pozitívba fordult) -> egy önálló "kettős megerősítés" (Bollinger ÉS EMA-keresztezés
UGYANAZON a baron) belépési szabály MINDHÁROM US-szimbólumon nyereséges volt (US100 PF 2.66, US500
PF 1.40, US30 PF 1.21 — ELSŐ eset, hogy US30 is nyereséges), és durva költség-érzékenységi becslés
után is NETTÓ PF 1.0 fölött maradt mindhárom szimbólumon.

Mivel a kettős-megerősítés feltétele (`bollinger_kitörés ÉS ema_fast>ema_slow`) STRUKTURÁLISAN
RÉSZHALMAZA a puszta TrendFollowing feltételének (`ema_fast>ema_slow` [+RSI, ami igazoltan
redundáns]) — minden bar, ahol a kettős megerősítés belépne, eleve kielégítené a sima
TrendFollowing feltételét is —, NINCS valódi verseny/konfliktus két külön jelforrás között, csak
egy SZŰKÍTŐ feltétel. A felhasználóval egyeztetve (2026-08-20) ezért NEM önálló, versengő komponens
lett belőle, hanem BEÉPÜLT ide, a meglévő EMA-feltétel MELLÉ (AND-kapcsolat) — `bollinger_period`/
`bollinger_k` új paraméterekkel. Az RSI-szűrő megmaradt (a `bollinger_breakout_experiment.py` és a
`double_confirmation_experiment.py` mérése szerint a Bollinger-feltétel mellett az RSI 100%-ban
redundáns, tehát a kettő együtt nem változtatja meg a trade-halmazt — ezt a live validáció is
megerősíti/cáfolja majd).

ISMERT, SZÁNDÉKOS EGYSZERŰSÍTÉSEK: nincs spread/szlippázs/jutalék modellezve. A keddi kizárás itt
nem releváns kérdés — a régi kódban is csak a MeanReversion/TurnaroundTuesday ütközött egymással,
a TrendFollowing sosem.

A gyors/lassú EMA span-ját a régi kód NAPOKBAN paraméterezte (TrendFastEmaDays/TrendSlowEmaDays),
majd bar-ra váltotta a tényleges idősík bars_per_day-je alapján. Ez a projekt mindenhol M10-et
használ (lásd PLAN.md), ezért itt fix BARS_PER_DAY=144 konstansként rögzítjük — ha valaha más
idősíkra váltanánk, ezt kell módosítani.
"""

import numpy as np

from regime_framework.core.indicators import compute_rsi
from regime_framework.core.types import BarContext, ExitDecision, Position, RegimeState, Signal, ValidationReport
from regime_framework.core.us_session import us_dst_hour_shift
from regime_framework.regime.market_condition import MarketConditionClassifier

BARS_PER_DAY = 144   # M10 idősík — lásd PLAN.md, a projekt egészében ez a konvenció


class TrendFollowingComponent:
    name = "TrendFollowing"
    applicable_trend_bands = {"TRENDING"}

    def __init__(self, fast_ema_days=0.7, slow_ema_days=4.0, sl_atr_multiplier=2.5,
                 trail_atr_multiplier=3.5, lot_size=0.1,
                 rsi_period=14, rsi_long_min=50.0, rsi_short_max=50.0,
                 bollinger_period=20, bollinger_k=2.0,
                 session_start_hour=16, session_start_minute=30, session_end_hour=21,
                 dst_aware=False):
        self.fast_ema_days = fast_ema_days
        self.slow_ema_days = slow_ema_days
        self.sl_atr_multiplier = sl_atr_multiplier
        self.trail_atr_multiplier = trail_atr_multiplier
        self.lot_size = lot_size
        self.rsi_period = rsi_period
        self.rsi_long_min = rsi_long_min
        self.rsi_short_max = rsi_short_max
        self.bollinger_period = bollinger_period
        self.bollinger_k = bollinger_k
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
        """Állapot-alapú belépés: NEM a gyors/lassú EMA pontos keresztezési bar-ját várja, hanem
        bármelyik CORE_SESSION-ös, TRENDING-regime-ű bar-on jelez, ahol a gyors EMA már a lassú
        felett/alatt van. A napi max. egy belépés szabályát (hogy egy korai kiütés után ne nyisson
        újra aznap) az orkesztráló (validate(), később az Engine) felelőssége betartatni — lásd a
        fájl fejléc-docstringjének TÖRTÉNET szakaszát, miért váltottunk erre a pontos-keresztezés-
        alapú változatról.

        A BOLLINGER-KITÖRÉS FELTÉTEL (2026-08-20, lásd fejléc-docstring) SZŰKÍTI ezt a jelet: a
        záróárnak a sávon KÍVÜL kell lennie (nem csak az EMA-sorrendnek megfelelőnek), ugyanabba
        az irányba — ez adja a "kettős megerősítést"."""
        if not self.is_regime_eligible(ctx.regime):
            return None
        if not self._is_session_hour(ctx.hour, ctx.minute, ctx.date):
            return None

        fast_now = ctx.indicators["ema_fast"]
        slow_now = ctx.indicators["ema_slow"]
        atr = ctx.indicators["atr"]
        rsi = ctx.indicators["rsi"]
        bb_upper = ctx.indicators["bb_upper"]
        bb_lower = ctx.indicators["bb_lower"]

        if fast_now > slow_now and rsi >= self.rsi_long_min and ctx.close > bb_upper:
            return Signal(direction="LONG", sl_price=ctx.close - atr * self.sl_atr_multiplier, tp_price=None)
        if fast_now < slow_now and rsi <= self.rsi_short_max and ctx.close < bb_lower:
            return Signal(direction="SHORT", sl_price=ctx.close + atr * self.sl_atr_multiplier, tp_price=None)
        return None

    def check_exit(self, ctx: BarContext, position: Position) -> ExitDecision | None:
        """ATR trailing stop: a nyomkövetett szélsőérték csak a kedvező irányba mozoghat, a stop
        pedig csak szűkülhet (sosem lazul) — klasszikus trend-követő logika, szándékosan fix TP
        nélkül (a nyereséget a trailing stop engedi "futni")."""
        atr = ctx.indicators["atr"]
        if position.pos_type == "LONG":
            position.extra["trend_extreme"] = max(position.extra["trend_extreme"], ctx.high)
            trail_sl = position.extra["trend_extreme"] - atr * self.trail_atr_multiplier
            position.sl_price = max(position.sl_price, trail_sl)
            hit = ctx.low <= position.sl_price
        else:
            position.extra["trend_extreme"] = min(position.extra["trend_extreme"], ctx.low)
            trail_sl = position.extra["trend_extreme"] + atr * self.trail_atr_multiplier
            position.sl_price = min(position.sl_price, trail_sl)
            hit = ctx.high >= position.sl_price

        if hit:
            return ExitDecision(exit_price=position.sl_price, reason="TRAIL_SL")
        return None

    def suggest_params(self, trial):
        """Optuna-paraméter-tér — csak az ehhez a komponenshez tartozó paramétereket ajánlja fel."""
        return {
            "fast_ema_days": trial.suggest_float("tf_fast_ema_days", 0.3, 1.5),
            "slow_ema_days": trial.suggest_float("tf_slow_ema_days", 2.0, 8.0),
            "sl_atr_multiplier": trial.suggest_float("tf_sl_atr_multiplier", 1.5, 3.5),
            "trail_atr_multiplier": trial.suggest_float("tf_trail_atr_multiplier", 2.0, 5.0),
            "rsi_long_min": trial.suggest_float("tf_rsi_long_min", 40.0, 60.0),
            "rsi_short_max": trial.suggest_float("tf_rsi_short_max", 40.0, 60.0),
            "bollinger_period": trial.suggest_int("tf_bollinger_period", 10, 40),
            "bollinger_k": trial.suggest_float("tf_bollinger_k", 1.5, 3.0),
        }

    def prepare_indicators(self, df):
        df = df.copy()
        fast_span = max(2, int(round(self.fast_ema_days * BARS_PER_DAY)))
        slow_span = max(3, int(round(self.slow_ema_days * BARS_PER_DAY)))
        df["ema_fast"] = df["close"].ewm(span=fast_span, adjust=False).mean()
        df["ema_slow"] = df["close"].ewm(span=slow_span, adjust=False).mean()
        df["rsi"] = compute_rsi(df, period=self.rsi_period)

        sma = df["close"].rolling(window=self.bollinger_period).mean()
        std = df["close"].rolling(window=self.bollinger_period).std()
        df["bb_upper"] = sma + self.bollinger_k * std
        df["bb_lower"] = sma - self.bollinger_k * std

        df = df.dropna(subset=["ema_fast", "ema_slow", "rsi", "bb_upper", "bb_lower"]).reset_index(drop=True)
        df["hour"] = df["time"].dt.hour
        df["minute"] = df["time"].dt.minute
        df["date"] = df["time"].dt.date
        return df

    def validate(self, df, market_classifier: MarketConditionClassifier = None) -> ValidationReport:
        """Elszigetelt backtest, ugyanabban a szellemben, mint a MeanReversionComponent.validate()-je
        — napvégi kényszerzárással és napi max. egy belépéssel."""
        if market_classifier is None:
            market_classifier = MarketConditionClassifier()

        indicator_df = self.prepare_indicators(df)
        classified = market_classifier.classify_series(indicator_df)

        n = len(classified)
        close_vals = classified["close"].to_numpy()
        high_vals = classified["high"].to_numpy()
        low_vals = classified["low"].to_numpy()
        atr_vals = classified["atr"].to_numpy()
        ema_fast_vals = classified["ema_fast"].to_numpy()
        ema_slow_vals = classified["ema_slow"].to_numpy()
        rsi_vals = classified["rsi"].to_numpy()
        bb_upper_vals = classified["bb_upper"].to_numpy()
        bb_lower_vals = classified["bb_lower"].to_numpy()
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
        current_day = None
        trade_taken_today = False

        for idx in range(n):
            if dates[idx] != current_day:
                current_day = dates[idx]
                trade_taken_today = False

            regime = RegimeState(session_phase="CORE_SESSION", trend_band=trend_bands[idx])
            ctx = BarContext(
                time=None, open=None, high=high_vals[idx], low=low_vals[idx], close=close_vals[idx],
                hour=int(hours[idx]), minute=int(minutes[idx]), day_of_week=0, date=dates[idx],
                regime=regime,
                indicators={"atr": atr_vals[idx], "ema_fast": ema_fast_vals[idx],
                            "ema_slow": ema_slow_vals[idx], "rsi": rsi_vals[idx],
                            "bb_upper": bb_upper_vals[idx], "bb_lower": bb_lower_vals[idx]},
            )

            if position is not None:
                # HIBAJAVÍTÁS (2026-09-05, folytatás): `is_last_bar_of_day` önmagában NEM
                # elegendő biztosíték -- IC Markets M10-es részvényeken kiderült, hogy egy
                # NAP-VÉGI bar néha "eltűnik" a bemenetből (pl. NaN-szűrés/merge-artifact miatt),
                # így a régi kód sosem érte el az `is_last_bar_of_day[idx]` pillanatot azon a
                # napon, és a pozíció átcsúszott a KÖVETKEZŐ napra. Robusztusabb védelem: ha az
                # AKTUÁLIS bar dátuma MÁR eltér a belépés napjától, azonnal zárunk -- ez nem
                # függ attól, hogy melyik bar-t sikerült "utolsónak" azonosítani.
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
            # `and not is_last_bar_of_day[idx]` -- HIBAJAVÍTÁS (2026-09-05, IC Markets M10-es
            # részvény-kutatás során derült ki, empirikus trade-log-ellenőrzéssel): ha egy jel
            # PONT a nap utolsó bar-ján tüzelt, a régi kód belépett, DE a napvégi kényszerzárás
            # csak a "pozíció-már-nyitva" ágban fut, a KÖVETKEZŐ (már MÁSNAPI) bar-on -- a
            # pozíció így akár hétvégén át is nyitva maradhatott, nem modellezett swap-
            # kitettséget okozva. Ugyanez a hiba megvolt a `core/engine.py` Engine.run()-jában is,
            # ott is javítva. A `mean_reversion.py`-ban is (ahol nincs `trade_taken_today`, csak
            # `position is None`). Lásd `d--XM-optuna-research` memory-bejegyzés a felfedezés
            # kontextusáért -- a fix egyszerűen NEM enged új belépést a nap utolsó bar-ján
            # (ahelyett, hogy beengedné és utólag próbálná zárni).
            elif not trade_taken_today and not is_last_bar_of_day[idx]:
                signal = self.check_entry(ctx)
                if signal is not None:
                    trade_taken_today = True
                    position = Position(pos_type=signal.direction, entry_price=ctx.close,
                                         entry_date=dates[idx], sl_price=signal.sl_price,
                                         tp_price=signal.tp_price,
                                         extra={"trend_extreme": ctx.close})
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
        report.notes["rsi_gate"] = (f"LONG: RSI >= {self.rsi_long_min} | "
                                     f"SHORT: RSI <= {self.rsi_short_max}")
        report.notes["trail_sl_exits"] = sum(1 for t in trade_log if t["exit_reason"] == "TRAIL_SL")
        report.notes["eod_forced_exits"] = sum(1 for t in trade_log if t["exit_reason"] == "EOD_FORCED")
        if trade_log:
            hold_days = [(t["exit_date"] - t["entry_date"]).days for t in trade_log]
            report.notes["avg_hold_days"] = round(float(np.mean(hold_days)), 2)

        # LONG/SHORT bontás: a komponens LOGIKÁJA szimmetrikus, de a validációs minta nem
        # feltétlenül az — ha a mért időszak túlnyomórészt egy irányba trendelt, az egyik oldal
        # alig lett élesben tesztelve, és nem tudjuk, medve-/bikapiacon fordítva ugyanígy
        # teljesítene-e (felhasználói kérdés, 2026-08-19).
        long_trades = [t for t in trade_log if t["pos_type"] == "LONG"]
        short_trades = [t for t in trade_log if t["pos_type"] == "SHORT"]
        report.notes["long_trades"] = len(long_trades)
        report.notes["short_trades"] = len(short_trades)
        if long_trades:
            long_wins = [t for t in long_trades if t["pnl"] > 0]
            report.notes["long_win_rate"] = round(len(long_wins) / len(long_trades) * 100, 1)
            report.notes["long_pnl"] = round(sum(t["pnl"] for t in long_trades), 2)
        if short_trades:
            short_wins = [t for t in short_trades if t["pnl"] > 0]
            report.notes["short_win_rate"] = round(len(short_wins) / len(short_trades) * 100, 1)
            report.notes["short_pnl"] = round(sum(t["pnl"] for t in short_trades), 2)

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
        if trade_log and (len(long_trades) < 30 or len(short_trades) < 30):
            report.warnings.append(
                f"LONG/SHORT eloszlás kiegyensúlyozatlan ({len(long_trades)}/{len(short_trades)}) "
                f"— az alulreprezentált irány saját megbízhatósági küszöb (30) alatt van, tehát "
                f"az adott irányú teljesítmény (pl. medvepiaci viselkedés) még nincs érdemben tesztelve."
            )

        return report
