"""
components/friday_short.py — a NEGYEDIK, formálisan beépített StrategyComponent, ugyanabba a
"quota-exempt time_gated" architekturális kategóriába tartozik, mint a LastHourContinuation, DE
egy KÉSŐBBI, ritkább (heti egyszeri) naptári triggerrel, ezért az Engine-be egy KÜLÖN,
`quota_exempt_time_gated_components` listán keresztül regisztrálódik (lásd core/engine.py
modul-docstringje).

SZÁRMAZÁS (2026-08-21, felhasználói felvetés: nap×óra szezonalitás-térkép): a `research/
day_hour_seasonality_scan.py` (115-120 (nap,óra) cella, előjel-permutációs teszt, többszörös-
tesztelés-korrigálva) két gazdaságilag plauzibilis, mindhárom US-szimbólumon konzisztens előjelű
cellát talált — Hétfő 10:00 (LONG, végül GER40 diagnosztikai kontrollal MEGCÁFOLVA, lásd
SESSION_LOG.md) és **Péntek 23:00-00:00 szerveridő (SHORT, kb. NYSE-zárás környéke)**, ami a
`research/day_hour_confirmatory_check.py` mindkét előre bejelentett kritériumát teljesítette
(NETTÓ PF>1 mindhárom szimbólumon KÜLÖN-KÜLÖN ÉS összevonva, összevont NETTÓ z>=2).

⚠️ ARCHITEKTURÁLIS INDOKLÁS (miért `quota_exempt_time_gated_components`, NEM sima
`time_gated_components`): a `research/friday_short_engine_conflict_check.py` megmutatta, hogy a
normál `time_gated_components` sorrend (napi kvóta = 1, csak akkor kap esélyt, ha a nap MÉG NEM
"foglalt") ennél a KÉSŐI (23:00-ás) triggernél messze kevesebb szabad napot hagy (11.5-25.7%),
mint a LastHourContinuationnak (69.7-75.5%) — mire 23:00 lesz, a nap szinte mindig foglalt már
(MeanReversion/TrendFollowing/LastHourContinuation valamelyike miatt). A `research/
friday_short_quota_exception_check.py` megmutatta, hogy egy SZŰK, csak erre a slotra vonatkozó
napi-kvóta-KIVÉTEL (nem a limit globális feloldása, amiről a `research/daily_trade_cap_check.py`
kimutatta, hogy árt) valódi, a meglévő komponenseket ÉRINTETLENÜL hagyó javulást hoz (trade-szám
kb. 5x-re nő, nettó PF>1.5 mindhárom szimbólumon).

BELÉPÉS: minden PÉNTEKEN (alapból `target_day_of_week=4`), pontosan `target_hour`:00-kor
(alapból 23), SHORT irányban — ez egy FIX naptári triggerelt komponens, a jel NEM egy folyamatos
indikátoron alapul (ellentétben a MeanReversion/TrendFollowing-gal). KILÉPÉS: ATR-alapú SL
(biztonsági fék) VAGY `hold_bars` bar (alapból 6 = 1 óra) elteltével kényszerzárás — a mérés maga
a "fix idejű, rövid SHORT" ötletet validálta, nem egy trailing-stop-os "fusson tovább" logikát.

ISMERT, SZÁNDÉKOS EGYSZERŰSÍTÉS: nincs spread/szlippázs/jutalék modellezve a `validate()`-ben (a
`research/day_hour_confirmatory_check.py` külön, a valós történelmi spread-del becsülte ezt —
mindhárom szimbólumon NETTÓ PF > 1.5 maradt).
"""

import numpy as np

from regime_framework.core.indicators import compute_simple_atr
from regime_framework.core.types import BarContext, ExitDecision, Position, RegimeState, Signal, ValidationReport


class FridayShortComponent:
    name = "FridayShort"
    # SZÁNDÉKOSAN NINCS applicable_trend_bands -- ez a komponens NEM vesz részt a trend_band-XOR
    # rácsban, és NEM is a sima `time_gated_components` listán megy az Engine-be, hanem a
    # `quota_exempt_time_gated_components`-en (lásd fájl fejléc + core/engine.py docstring).

    def __init__(self, target_day_of_week=4, target_hour=23, hold_bars=6, sl_atr_multiplier=2.0, lot_size=0.1):
        self.target_day_of_week = target_day_of_week
        self.target_hour = target_hour
        self.hold_bars = hold_bars
        self.sl_atr_multiplier = sl_atr_multiplier
        self.lot_size = lot_size

    def is_regime_eligible(self, regime: RegimeState) -> bool:
        """Szándékosan MINDIG True -- ez a komponens a trend_band-től függetlenül, tisztán a
        naptári (nap+óra) trigger alapján aktiválódik."""
        return True

    def check_entry(self, ctx: BarContext) -> Signal | None:
        if ctx.day_of_week != self.target_day_of_week or ctx.hour != self.target_hour or ctx.minute != 0:
            return None
        atr = ctx.indicators.get("atr")
        if atr is None or np.isnan(atr) or atr == 0:
            return None
        sl_price = ctx.close + atr * self.sl_atr_multiplier   # SHORT -- az SL az entry FÖLÖTT van
        return Signal(direction="SHORT", sl_price=sl_price, tp_price=None)

    def check_exit(self, ctx: BarContext, position: Position) -> ExitDecision | None:
        if ctx.high >= position.sl_price:
            return ExitDecision(exit_price=position.sl_price, reason="SL")
        if ctx.indicators.get("is_hold_end_bar"):
            return ExitDecision(exit_price=ctx.close, reason="HOLD_END")
        return None

    def suggest_params(self, trial):
        """Optuna-paraméter-tér — csak az ehhez a komponenshez tartozó paramétereket ajánlja fel."""
        return {
            "sl_atr_multiplier": trial.suggest_float("fs_sl_atr_multiplier", 1.0, 4.0),
            "hold_bars": trial.suggest_int("fs_hold_bars", 3, 12),
        }

    def prepare_indicators(self, df):
        """Az `is_hold_end_bar` oszlopot NAPTÁRILAG, a trigger-bar pozíciójából számítjuk ki (a
        trigger MAGA is fix naptári időpont, ezért a kilépés is determinisztikusan levezethető,
        nincs szükség élő entry-nyomon-követésre) -- lásd a LastHourContinuation `is_session_end_bar`
        mintáját, ugyanaz az elv.

        ⚠️ A kilépést a `hold_bars` ÉS a trigger-nap UTOLSÓ bar-ja közül a KORÁBBIRA korlátozzuk
        (`min(...)`) -- a target_hour=23 miatt a `hold_bars` (alapból 6, azaz 1 óra) alapú
        természetes kilépés gyakran ÁTNYÚLNA a következő naptári napra (szombatra), az Engine
        (és ennek a komponensnek a saját `validate()`-je is) viszont MINDEN komponensre egységesen
        alkalmaz egy napvégi kényszerzárást -- enélkül a korlátozás nélkül a tényleges kilépés
        CSENDBEN egy bar-ral korábbra csúszna a validáltnál (`research/day_hour_confirmatory_
        check.py` HOLD_BARS=6-tal, napvégi kényszerzárás NÉLKÜL mérte az eredeti szabályt) --
        regressziós smoke teszt fogta meg ezt az eltérést, lásd SESSION_LOG.md."""
        df = df.copy()
        df["atr"] = compute_simple_atr(df)
        df = df.dropna(subset=["atr"]).reset_index(drop=True)
        df["hour"] = df["time"].dt.hour
        df["minute"] = df["time"].dt.minute
        df["day_of_week"] = df["time"].dt.dayofweek
        df["date"] = df["time"].dt.date

        df["is_hold_end_bar"] = False
        trigger_mask = (
            (df["day_of_week"] == self.target_day_of_week)
            & (df["hour"] == self.target_hour)
            & (df["minute"] == 0)
        )
        n = len(df)
        dates = df["date"].to_numpy()
        for trigger_idx in df.index[trigger_mask]:
            trigger_date = dates[trigger_idx]
            same_day_indices = df.index[df["date"] == trigger_date]
            last_day_idx = same_day_indices[-1]
            natural_exit_idx = trigger_idx + self.hold_bars
            exit_idx = min(natural_exit_idx, last_day_idx, n - 1)
            df.loc[exit_idx, "is_hold_end_bar"] = True

        return df

    def validate(self, df, market_classifier=None) -> ValidationReport:
        """Elszigetelt backtest, ugyanabban a szellemben, mint a LastHourContinuationé — NEM
        használja a `MarketConditionClassifier`-t (a `market_classifier` paraméter csak az
        interfész-egyezés kedvéért van itt), mert ez a komponens szándékosan a trend_band-től
        FÜGGETLEN."""
        indicator_df = self.prepare_indicators(df)

        n = len(indicator_df)
        close_vals = indicator_df["close"].to_numpy()
        high_vals = indicator_df["high"].to_numpy()
        low_vals = indicator_df["low"].to_numpy()
        atr_vals = indicator_df["atr"].to_numpy()
        is_hold_end_bar_vals = indicator_df["is_hold_end_bar"].to_numpy()
        hours = indicator_df["hour"].to_numpy()
        minutes = indicator_df["minute"].to_numpy()
        day_of_weeks = indicator_df["day_of_week"].to_numpy()
        dates = indicator_df["date"].to_numpy() if "date" in indicator_df.columns else \
            indicator_df["time"].dt.date.to_numpy()

        is_last_bar_of_day = np.zeros(n, dtype=bool)
        if n > 0:
            is_last_bar_of_day[:-1] = dates[:-1] != dates[1:]
            is_last_bar_of_day[-1] = True

        trade_log = []
        position = None
        entry_date = None

        for idx in range(n):
            ctx = BarContext(
                time=None, open=None, high=high_vals[idx], low=low_vals[idx], close=close_vals[idx],
                hour=int(hours[idx]), minute=int(minutes[idx]), day_of_week=int(day_of_weeks[idx]),
                date=dates[idx], regime=None,
                indicators={"atr": atr_vals[idx], "is_hold_end_bar": bool(is_hold_end_bar_vals[idx])},
            )

            if position is not None:
                exit_decision = self.check_exit(ctx, position)
                if exit_decision is None and is_last_bar_of_day[idx]:
                    exit_decision = ExitDecision(exit_price=ctx.close, reason="EOD_FORCED")
                if exit_decision is not None:
                    pnl = self.lot_size * (position.entry_price - exit_decision.exit_price)
                    trade_log.append({
                        "entry_date": entry_date, "exit_date": dates[idx],
                        "pos_type": position.pos_type, "exit_reason": exit_decision.reason, "pnl": pnl,
                    })
                    position = None
            else:
                signal = self.check_entry(ctx)
                if signal is not None:
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
        report.notes["hold_end_exits"] = sum(1 for t in trade_log if t["exit_reason"] == "HOLD_END")
        report.notes["eod_forced_exits"] = sum(1 for t in trade_log if t["exit_reason"] == "EOD_FORCED")

        if not report.is_reliable():
            report.warnings.append(f"Csak {len(trade_log)} trade — a 30-as megbízhatósági küszöb alatt.")
        if trade_log and profit_factor < 1.0:
            report.warnings.append(f"Profit factor ({profit_factor:.2f}) < 1 — nem nyereséges ezen az adatsoron.")
        report.warnings.append(
            "⚠️ NINCS spread/szlippázs/jutalék modellezve — lásd research/day_hour_confirmatory_"
            "check.py a valós történelmi spreaddel becsült nettó eredményért."
        )

        return report
