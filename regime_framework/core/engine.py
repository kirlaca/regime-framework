"""
core/engine.py — a rendszer tényleges vezérlő motorja (build-sorrend 6. pont).

Bar-onként, look-ahead nélkül összeköti a rezsim-réteget (`MarketConditionClassifier`) a
regisztrált komponensekkel: a `trend_band` alapján XOR-módon eldönti, melyik komponens aktív az
adott bar-on (a komponensek `applicable_trend_bands` halmazai egymást kölcsönösen kizáróak — ezt
az Engine induláskor ellenőrzi), majd lefuttatja annak `check_entry`/`check_exit` ciklusát.

Ez az ELSŐ pont a rendszerben, ahol több komponens EGYÜTT fut. Eddig mindegyik saját, elszigetelt
`validate()`-jében futott (lásd MeanReversionComponent/TrendFollowingComponent). Az Engine NEM
helyettesíti ezeket az elszigetelt validációkat, hanem RÁÉPÜL rájuk — a PLAN.md 6. build-sorrend
pontja explicit figyelmeztet: "egy komponens elszigetelt validációja NEM garantálja, hogy a teljes
rendszerben is jól teljesít" — ezért a `run()` riportja komponensenkénti bontást is ad, hogy
összevethető legyen az elszigetelt eredményekkel.

Ami MOST még HIÁNYZIK (tudatosan, a "csak bizonyított elemek kerülnek beljebb" elv szerint):
  - `SessionPhaseClassifier` bekötése — ezt megpróbáltuk (2026-08-19), de valós MT5 Optuna-
    újrafuttatással bebizonyosodott, hogy ÖSSZESSÉGÉBEN ROSSZABB eredményt ad, mint a komponensek
    saját, fix óraablaka (lásd MeanReversionComponent docstringje a részletes elemzésért) —
    felhasználóval egyeztetve VISSZAVONVA.
  - `vol_band` alapú finomabb dispatch (HIGH/LOW-vol altípusok) — ez a PLAN.md-ben még nyitott
    kérdés, jelenleg mindkét komponens mindkét vol_band-nél aktív a saját trend_band-jén.
  - Költség-modellezés (spread/szlippázs/jutalék) — ugyanaz az egyszerűsítés, mint a komponensek
    saját validate()-jénél.
Ezeket a PLAN.md-ben dokumentáljuk, nem itt hallgatjuk el.

`time_gated_components` (hozzáadva 2026-08-21, `LastHourContinuationComponent` bevezetésekor):
NEM minden komponens illik a `trend_band`-XOR rácsba — a "zárószakasz anomália" (lásd SESSION_LOG.md
2026-08-20) INTUÍCIÓJA trend-követő, de a jele egy fix naptári IDŐPONTHOZ kötött, a `trend_band`-től
FÜGGETLEN feltétel. Az ilyen komponensek a `time_gated_components` listán keresztül regisztrálódnak
— NINCS `applicable_trend_bands`-jük, az Engine nem is ellenőrzi őket az `_validate_no_overlap()`-ban
—, és csak akkor kapnak esélyt a `check_entry()`-re, ha a rendes `trend_band`-alapú komponens ADOTT
bar-on NEM jelzett (elsőbbségi sorrend: rezsim-komponens előbb, időablak-komponens csak utána). Mivel
az Engine egyszerre csak EGY pozíciót enged, egy már nyitott MeanReversion/TrendFollowing pozíció
"elfoglalhatja" azt a napot, mielőtt az időablak-komponens sorra kerülne — ez SZÁNDÉKOS (lásd
`research/last_hour_engine_conflict_check.py`: az esetek ~70-76%-ában szabad marad, ez elfogadható).

`quota_exempt_time_gated_components` (hozzáadva 2026-08-21, `FridayShortComponent` bevezetésekor):
a `research/friday_short_engine_conflict_check.py` megmutatta, hogy egy KÉSŐ napi (23:00) időablak-
komponensnél a normál `time_gated_components` sorrend már túl kevés szabad napot hagy (11.5-25.7%,
szemben a LastHourContinuation 69.7-75.5%-ával), mert a nap folyamán ADDIGRA már szinte mindig
elfogyott a napi kvóta. A `research/friday_short_quota_exception_check.py` megmutatta, hogy egy
SZŰK kvóta-KIVÉTEL (a napi limit GLOBÁLIS feloldása helyett, amiről a `research/
daily_trade_cap_check.py` kimutatta, hogy árt) valódi, kockázatmentes javulást hoz. Az itt
regisztrált komponensek CSAK akkor kapnak esélyt, ha (a) `position is None` (a VALÓDI egyidejűség-
tiltás TOVÁBBRA IS érvényes, ez sosem sérül), (b) a normál napi kvóta MÁR elfogyott ezen a napon
(`trades_taken_today >= max_trades_per_day` — ha még nem fogyott el, a normál `time_gated_components`
út már úgyis megpróbálta őket VOLNA, de ezek a komponensek NINCSENEK is a normál listában), ÉS
(c) a mai napon MÉG NEM használtuk el a kivétel-slotot (legfeljebb EGY bónusz-belépés/nap). Ez
SOSEM érinti a rendes komponensek/time_gated_components saját gyakoriságát — csak egy korábban
garantáltan üres helyre ad esélyt.
"""

import numpy as np

from regime_framework.core.position_sizing import FixedLotSizer
from regime_framework.core.types import BarContext, ExitDecision, Position, RegimeState, ValidationReport
from regime_framework.regime.market_condition import MarketConditionClassifier

NON_INDICATOR_COLUMNS = ("time", "open", "high", "low", "close", "hour", "minute", "date")


class Engine:
    def __init__(self, components, market_classifier: MarketConditionClassifier = None, lot_size=0.1,
                 time_gated_components=None, max_trades_per_day=1, quota_exempt_time_gated_components=None,
                 position_sizer=None, equity_start=10_000.0):
        self.components = list(components)
        self.time_gated_components = list(time_gated_components) if time_gated_components else []
        # lásd a modul-docstring `quota_exempt_time_gated_components` szakaszát
        self.quota_exempt_time_gated_components = (
            list(quota_exempt_time_gated_components) if quota_exempt_time_gated_components else []
        )
        self.market_classifier = market_classifier or MarketConditionClassifier()
        self.lot_size = lot_size
        # `max_trades_per_day` (hozzáadva 2026-08-21, felhasználói felvetés: "a napi egy trade
        # szabály nincs kőbe vésve"): alapértéken (1) VÁLTOZATLAN a régi viselkedés — legfeljebb
        # EGY belépés naponta, FÜGGETLENÜL attól, hogy egy korábbi pozíció már réges-rég zárva
        # van-e aznap. Ez a régi kódbázisból (main_optuna_hybrid.py) öröklődött, PLUSZ korlát a
        # `position is not None` ellenőrzés (ami a VALÓDI "sose két egyidejű pozíció" szabály)
        # FÖLÉ rakva. `None` = nincs napi limit, csak az egyidejűség-tiltás marad — ez teszi
        # lehetővé, hogy egy időablak-alapú komponens (pl. LastHourContinuation, vagy egy jövőbeli
        # "Péntek-esti zárás" komponens) akkor is aktiválódjon, ha aznap korábban MÁR volt egy
        # lezárt trade. Kísérleti kapcsoló — lásd research/daily_trade_cap_check.py a valós hatás
        # méréséért, MIELŐTT az alapértéket megváltoztatnánk.
        self.max_trades_per_day = max_trades_per_day
        # `position_sizer` (hozzáadva 2026-08-22, PRODUCTION_READINESS.md P1 #3): alapértéken
        # `FixedLotSizer(lot_size)` -- ez A JELENLEGI, VÁLTOZATLAN viselkedés (minden trade fix
        # `lot_size`, függetlenül az SL-távolságtól/tőkétől), byte-azonos eredménnyel a korábbi
        # kóddal. Csak akkor tér el, ha a hívó EXPLICIT módon egy `RiskBasedSizer`-t ad át (lásd
        # core/position_sizing.py) -- ekkor a lot-méret trade-enként, az aktuális `equity`
        # (kezdőérték `equity_start`) és az adott trade SL-távolsága alapján számolódik.
        self.position_sizer = position_sizer if position_sizer is not None else FixedLotSizer(lot_size)
        self.equity_start = equity_start
        self._validate_no_overlap()

    def _validate_no_overlap(self):
        """A komponensek `applicable_trend_bands` halmazainak kölcsönösen kizáróaknak KELL
        lenniük — ez maga az XOR-dispatch alapja. Ha két komponens ugyanarra a trend_band-re
        pályázna, az Engine nem tudná eldönteni, melyik fusson, ezért ez korai, hangos hibát dob
        induláskor, nem csendes, később nehezen visszakövethető viselkedést."""
        seen = {}
        for component in self.components:
            overlap = set(seen.keys()) & component.applicable_trend_bands
            if overlap:
                raise ValueError(
                    f"Átfedő trend_band-kapu: {component.name} és {seen[next(iter(overlap))]} "
                    f"mindketten pályáznak erre: {overlap} — az XOR-dispatch nem egyértelmű."
                )
            for band in component.applicable_trend_bands:
                seen[band] = component.name

    def _select_component(self, trend_band):
        for component in self.components:
            if trend_band in component.applicable_trend_bands:
                return component
        return None   # pl. TRANSITIONAL — szándékos "ne kereskedj" zóna, lásd PLAN.md 2.2

    def _prepare_combined_df(self, raw_df):
        """Minden regisztrált komponens saját indikátorát rávezeti egy közös, idő szerint
        összefésült DataFrame-re — a `MarketConditionClassifier` ezután EGYSZER fut le a végén
        (nem komponensenként duplán), ugyanúgy, mint korábban az egyes komponensek saját
        validate()-jében, csak most egyetlen közös menetben.

        Az újonnan hozott oszlopokat `col not in combined.columns` alapján válogatjuk ki (NEM egy
        fix NON_INDICATOR_COLUMNS listával) — ez egyszerre old meg két ütközési forrást: (1) a
        `raw_df`-ből átmásolt, változatlan oszlopokat (pl. `spread_price`), amiket MINDEN
        komponens `prepare_indicators()`-e érintetlenül visszaad, és amik enélkül minden egyes
        merge-nél újra "ütköznének" (2026-08-21: 3. komponens hozzáadásakor ez élesen kiderült —
        pandas `MergeError: duplicate columns {'spread_price_x'}` néhány körrel később, mert 2
        komponensnél még csendben csak felesleges `_x`/`_y` oszlopokat hozott létre); (2) a
        komponensek KÖZTI indikátornév-ütközést (pl. `TrendFollowingComponent` ÉS
        `LastHourContinuationComponent` is saját `atr`-t számol — a második jelentkezőét itt
        eldobjuk, ami korrekt, mert mindkettő ugyanazt a `compute_simple_atr()`-t hívja ugyanazon
        raw OHLC-n, tehát az érték azonos, csak a FORRÁS az, amelyik előbb ér oda)."""
        combined = raw_df.copy()
        all_components = self.components + self.time_gated_components + self.quota_exempt_time_gated_components
        for component in all_components:
            prepared = component.prepare_indicators(raw_df)
            new_cols = [c for c in prepared.columns if c not in combined.columns]
            if new_cols:
                combined = combined.merge(prepared[["time"] + new_cols], on="time", how="inner")
        combined["hour"] = combined["time"].dt.hour
        combined["minute"] = combined["time"].dt.minute
        combined["date"] = combined["time"].dt.date
        combined["day_of_week"] = combined["time"].dt.dayofweek
        return combined

    def run(self, df, stats_start_date=None, return_trades=False) -> ValidationReport:
        """Egyszerre csak EGY pozíció lehet nyitva a teljes rendszerben (valódi "kapcsoló", nem
        portfólió — ugyanaz az elv, mint a main_optuna_hybrid.py simulate_trades_hybrid()-jében).
        Napi belépés-szám a `self.max_trades_per_day`-jel korlátozva (alapérték 1 — lásd
        `__init__` docstringjét, miért/hogyan lazítható ez) és napvégi kényszerzárás mindkét
        jelenlegi komponensnél megegyezik, ezért ez a hurok komponens-függetlenül, generikusan
        írható meg.

        `stats_start_date` (opcionális `datetime.date`): ha meg van adva, a df MINDEN bar-ja részt
        vesz a regime-osztályozás/indikátorok bemelegítésében és a szimulációban (a korábbi
        pozíciók/napi-limitek folytonosan öröklődnek), de a riport metrikái (win-rate, PF, PnL)
        CSAK az ezen dátum-on/UTÁN NYITOTT trade-eket számolják — ez teszi lehetővé a walk-forward
        validációt (lásd validate_walk_forward.py): egy bővülő ablakos fold csak a saját
        dátumtartományában mért teljesítményt jelenti, de a korábbi adatot bemelegítésként
        felhasználja, nem dobja el a rezsim-osztályozás pontossága kedvéért.

        `return_trades`: ha True, a visszatérési érték `(report, trade_log)` — a nyers trade-lista
        (dict-ek: entry_date/exit_date/component/pos_type/exit_reason/pnl/cost/net_pnl/lot/
        entry_price/sl_price/entry_sl_price/exit_price) diagnosztikai célra, pl. egy adott
        negyedéven belüli napi/heti bontáshoz. Alapból False (a meglévő hívók csak a riportot
        kapják), hogy ne törjön a már meglévő interfész. A `cost`/`net_pnl` mezők 2026-08-22-én
        kerültek be (lásd PRODUCTION_READINESS.md 1. pont) — a belépéskori történelmi spread durva
        becslése, ugyanaz az egyszerűsített modell, mint a korábbi kutatási scriptekben
        (`cost_sensitivity_check.py` stb.). A `lot` mező (2026-08-22, PRODUCTION_READINESS.md P1
        #3, lásd `position_sizer`) a trade TÉNYLEGES lot-mérete — `FixedLotSizer`-nél mindig
        `self.lot_size`, `RiskBasedSizer`-nél trade-enként eltérő, a BELÉPÉSKORI SL-távolság
        alapján. A `pnl`/`cost` már EZZEL a lot-tal van skálázva (nem `self.lot_size`-szal!) — az
        "egy lotra eső" nyers érték `pnl / lot`. FONTOS: `sl_price` a pozíció ZÁRÁSKORI (esetlegesen
        trailing stop által már elmozdított, lásd `TrendFollowingComponent.check_exit()`) SL-je,
        `entry_sl_price` viszont a BELÉPÉSKORI, eredeti SL — a lot-méretezés `entry_sl_price`-ot
        használja, NEM `sl_price`-ot; a kettő trailing komponenseknél eltér."""
        combined = self._prepare_combined_df(df)
        classified = self.market_classifier.classify_series(combined)

        n = len(classified)
        close_vals = classified["close"].to_numpy()
        high_vals = classified["high"].to_numpy()
        low_vals = classified["low"].to_numpy()
        hours = classified["hour"].to_numpy()
        minutes = classified["minute"].to_numpy()
        dates = classified["date"].to_numpy()
        # bar-pontos időbélyeg a trade-loghoz (2026-09-23, belépési-útvonal diagnosztikához --
        # az entry_date/exit_date csak naptári nap, abból nem azonosítható a konkrét bar)
        bar_times = classified["time"].to_numpy()
        day_of_weeks = classified["day_of_week"].to_numpy()
        trend_bands = classified["trend_band"].to_numpy()
        vol_bands = classified["vol_band"].to_numpy()
        # a belépéskori történelmi spread -- költség-becsléshez (lásd PRODUCTION_READINESS.md 1.
        # pont). `raw_df`-ből jön (nem `classified`-ból közvetlenül, mert az utóbbi oszlop-
        # ütközés miatt esetenként átnevezhető -- lásd `_prepare_combined_df` docstringje), de
        # mivel a `combined`/`classified` a `raw_df.copy()`-ból indul és a "spread_price" oszlop
        # elsőként MINDIG a raw_df-ből származik, `classified["spread_price"]` biztonságosan
        # ugyanaz, mint a nyers adaton mérve.
        spread_vals = classified["spread_price"].to_numpy() if "spread_price" in classified.columns else None

        all_components = self.components + self.time_gated_components + self.quota_exempt_time_gated_components
        indicator_arrays = {"atr": classified["atr"].to_numpy(), "adx": classified["adx"].to_numpy()}
        for component in all_components:
            prepared = component.prepare_indicators(df)
            for col in prepared.columns:
                if col in NON_INDICATOR_COLUMNS or col in indicator_arrays:
                    continue
                indicator_arrays[col] = classified[col].to_numpy()

        is_last_bar_of_day = np.zeros(n, dtype=bool)
        if n > 0:
            is_last_bar_of_day[:-1] = dates[:-1] != dates[1:]
            is_last_bar_of_day[-1] = True

        trade_log = []
        position = None
        owning_component = None
        entry_date = None
        entry_time = None
        entry_spread_price = None
        entry_sl_price = None
        entry_lot = None
        equity = self.equity_start
        current_day = None
        trades_taken_today = 0
        quota_exempt_used_today = False
        no_active_component_bars = 0

        for idx in range(n):
            if dates[idx] != current_day:
                current_day = dates[idx]
                trades_taken_today = 0
                quota_exempt_used_today = False

            regime = RegimeState(session_phase="CORE_SESSION",
                                  trend_band=trend_bands[idx], vol_band=vol_bands[idx])
            ctx = BarContext(
                time=None, open=None, high=high_vals[idx], low=low_vals[idx], close=close_vals[idx],
                hour=int(hours[idx]), minute=int(minutes[idx]), day_of_week=int(day_of_weeks[idx]),
                date=dates[idx], regime=regime,
                indicators={key: arr[idx] for key, arr in indicator_arrays.items()},
            )

            if position is not None:
                # HIBAJAVÍTÁS (2026-09-05, folytatás) -- lásd `components/trend_following.py`
                # azonos helyen lévő részletes magyarázatát: `is_last_bar_of_day` önmagában nem
                # elég megbízható (a `_prepare_combined_df()` komponensenkénti inner-join/NaN-
                # szűrése miatt egy nap tényleges utolsó bar-ja néha "eltűnik" a bemenetből),
                # ezért elsődleges védelemként a napváltást magát nézzük.
                if dates[idx] != entry_date:
                    exit_decision = ExitDecision(exit_price=ctx.close, reason="EOD_FORCED")
                else:
                    exit_decision = owning_component.check_exit(ctx, position)
                    if exit_decision is None and is_last_bar_of_day[idx]:
                        exit_decision = ExitDecision(exit_price=ctx.close, reason="EOD_FORCED")

                if exit_decision is not None:
                    if position.pos_type == "LONG":
                        pnl = entry_lot * (exit_decision.exit_price - position.entry_price)
                    else:
                        pnl = entry_lot * (position.entry_price - exit_decision.exit_price)
                    # költség-becslés: a belépéskori történelmi spread, a trade TÉNYLEGES lot-jára
                    # skálázva (2026-08-22 előtt ez mindig `self.lot_size` volt -- lásd
                    # `position_sizer`, PRODUCTION_READINESS.md P1 #3) -- ugyanaz az egyszerűsített
                    # modell, mint a `cost_sensitivity_check.py`/`last_hour_continuation_
                    # experiment.py`-ban (lásd PRODUCTION_READINESS.md 1. pont). Hiányzó
                    # spread-adatnál cost=0 (optimista, de NEM dobjuk el a trade-et).
                    cost = (
                        entry_spread_price * entry_lot
                        if entry_spread_price is not None and not np.isnan(entry_spread_price)
                        else 0.0
                    )
                    net_pnl = pnl - cost
                    equity += net_pnl
                    trade_log.append({
                        "entry_date": entry_date, "exit_date": dates[idx],
                        "entry_time": entry_time, "exit_time": bar_times[idx],
                        "component": owning_component.name, "pos_type": position.pos_type,
                        "exit_reason": exit_decision.reason, "pnl": pnl,
                        "cost": cost, "net_pnl": net_pnl, "lot": entry_lot,
                        "entry_price": position.entry_price, "sl_price": position.sl_price,
                        "entry_sl_price": entry_sl_price, "exit_price": exit_decision.exit_price,
                    })
                    position = None
                    owning_component = None
            # `and not is_last_bar_of_day[idx]` -- HIBAJAVÍTÁS (2026-09-05, IC Markets M10-es
            # részvény-kutatás során derült ki, empirikus trade-log-ellenőrzéssel): ha egy jel
            # PONT a nap utolsó bar-ján tüzelt, a régi kód belépett, DE a napvégi kényszerzárás
            # csak a "pozíció-már-nyitva" ágban fut, a KÖVETKEZŐ (már MÁSNAPI) bar-on -- a
            # pozíció így akár hétvégén át is nyitva maradhatott, nem modellezett swap-kitettséget
            # okozva. Ugyanez a fix a `quota_exempt_time_gated_components` ágban is lentebb.
            elif (self.max_trades_per_day is None or trades_taken_today < self.max_trades_per_day) \
                    and not is_last_bar_of_day[idx]:
                active_component = self._select_component(regime.trend_band)
                if active_component is None:
                    no_active_component_bars += 1
                signal = active_component.check_entry(ctx) if active_component is not None else None
                if signal is None:
                    # a rendes trend_band-komponens NEM jelzett ezen a bar-on (vagy nincs is
                    # ilyen a jelen trend_band-hez) -- csak EKKOR kapnak esélyt az időablak-
                    # alapú komponensek, elsőbbségi sorrendben (lásd modul-docstring)
                    for tg_component in self.time_gated_components:
                        signal = tg_component.check_entry(ctx)
                        if signal is not None:
                            active_component = tg_component
                            break
                if signal is not None:
                    trades_taken_today += 1
                    owning_component = active_component
                    position = Position(pos_type=signal.direction, entry_price=ctx.close,
                                         entry_date=dates[idx], sl_price=signal.sl_price,
                                         tp_price=signal.tp_price,
                                         extra={"trend_extreme": ctx.close})
                    entry_date = dates[idx]
                    entry_time = bar_times[idx]
                    entry_spread_price = spread_vals[idx] if spread_vals is not None else None
                    entry_sl_price = signal.sl_price
                    entry_lot = self.position_sizer.calc_lot(equity, abs(ctx.close - entry_sl_price), ctx.close)
            elif self.quota_exempt_time_gated_components and not quota_exempt_used_today \
                    and not is_last_bar_of_day[idx]:   # ugyanaz a 2026-09-05-i hibajavítás
                # a normál napi kvóta MÁR elfogyott -- csak a kvóta-KIVÉTELES komponensek kapnak
                # esélyt, legfeljebb egyszer naponta (lásd modul-docstring)
                signal = None
                for qe_component in self.quota_exempt_time_gated_components:
                    signal = qe_component.check_entry(ctx)
                    if signal is not None:
                        owning_component = qe_component
                        break
                if signal is not None:
                    quota_exempt_used_today = True
                    position = Position(pos_type=signal.direction, entry_price=ctx.close,
                                         entry_date=dates[idx], sl_price=signal.sl_price,
                                         tp_price=signal.tp_price,
                                         extra={"trend_extreme": ctx.close})
                    entry_date = dates[idx]
                    entry_time = bar_times[idx]
                    entry_spread_price = spread_vals[idx] if spread_vals is not None else None
                    entry_sl_price = signal.sl_price
                    entry_lot = self.position_sizer.calc_lot(equity, abs(ctx.close - entry_sl_price), ctx.close)

        warmup_trade_count = 0
        if stats_start_date is not None:
            warmup_trade_count = sum(1 for t in trade_log if t["entry_date"] < stats_start_date)
            trade_log = [t for t in trade_log if t["entry_date"] >= stats_start_date]

        wins = [t for t in trade_log if t["pnl"] > 0]
        win_rate = len(wins) / len(trade_log) * 100 if trade_log else 0.0
        gross_win = sum(t["pnl"] for t in wins)
        gross_loss = abs(sum(t["pnl"] for t in trade_log if t["pnl"] <= 0))
        profit_factor = gross_win / gross_loss if gross_loss > 0 else float("inf")
        total_pnl = sum(t["pnl"] for t in trade_log)

        # NETTÓ (spread-korrigált) mutatók -- lásd PRODUCTION_READINESS.md 1. pont. A `report.
        # total_pnl`/`profit_factor` TOVÁBBRA IS bruttó (visszafelé kompatibilis minden meglévő
        # hívóval) -- a nettó számok külön `notes`-kulcsokként jelennek meg, amiket az Optuna
        # célfüggvény (`optimization/objective.py`) explicit ezekért olvas ki.
        net_wins = [t for t in trade_log if t["net_pnl"] > 0]
        net_win_rate = len(net_wins) / len(trade_log) * 100 if trade_log else 0.0
        net_gross_win = sum(t["net_pnl"] for t in net_wins)
        net_gross_loss = abs(sum(t["net_pnl"] for t in trade_log if t["net_pnl"] <= 0))
        net_profit_factor = net_gross_win / net_gross_loss if net_gross_loss > 0 else float("inf")
        total_net_pnl = sum(t["net_pnl"] for t in trade_log)
        total_cost = sum(t["cost"] for t in trade_log)
        # `equity`/`final_equity` a TELJES szimulált időszakot tükrözi (a bemelegítő szakaszt is,
        # ha `stats_start_date` van megadva -- lásd `position_sizer`, PRODUCTION_READINESS.md P1
        # #3), NEM csak a `trade_log` stats-szűrt részét. Fix lot (`FixedLotSizer`) esetén ez a két
        # mező diagnosztikai jellegű, semmilyen meglévő logika nem olvassa.
        final_equity = equity
        total_return_pct = (final_equity - self.equity_start) / self.equity_start * 100 if self.equity_start else 0.0

        report = ValidationReport(
            component_name="Engine", trade_count=len(trade_log), win_rate=win_rate,
            profit_factor=profit_factor, total_pnl=total_pnl,
        )
        report.notes["n_bars"] = n
        report.notes["no_active_component_bars"] = no_active_component_bars
        report.notes["components"] = [c.name for c in self.components]
        report.notes["time_gated_components"] = [c.name for c in self.time_gated_components]
        report.notes["quota_exempt_time_gated_components"] = [c.name for c in self.quota_exempt_time_gated_components]
        report.notes["total_cost"] = round(total_cost, 2)
        report.notes["total_net_pnl"] = round(total_net_pnl, 2)
        report.notes["net_win_rate"] = round(net_win_rate, 1)
        report.notes["net_profit_factor"] = round(net_profit_factor, 2) if net_profit_factor != float("inf") else float("inf")
        report.notes["final_equity"] = round(final_equity, 2)
        report.notes["total_return_pct"] = round(total_return_pct, 2)
        if stats_start_date is not None:
            report.notes["stats_start_date"] = str(stats_start_date)
            report.notes["warmup_trades_excluded"] = warmup_trade_count

        for component in self.components + self.time_gated_components + self.quota_exempt_time_gated_components:
            comp_trades = [t for t in trade_log if t["component"] == component.name]
            if not comp_trades:
                report.notes[f"{component.name}_trades"] = 0
                continue
            comp_wins = [t for t in comp_trades if t["pnl"] > 0]
            comp_gross_win = sum(t["pnl"] for t in comp_wins)
            comp_gross_loss = abs(sum(t["pnl"] for t in comp_trades if t["pnl"] <= 0))
            report.notes[f"{component.name}_trades"] = len(comp_trades)
            report.notes[f"{component.name}_win_rate"] = round(len(comp_wins) / len(comp_trades) * 100, 1)
            report.notes[f"{component.name}_pnl"] = round(sum(t["pnl"] for t in comp_trades), 2)
            report.notes[f"{component.name}_pf"] = (
                round(comp_gross_win / comp_gross_loss, 2) if comp_gross_loss > 0 else float("inf")
            )
            comp_net_wins = [t for t in comp_trades if t["net_pnl"] > 0]
            comp_net_gross_win = sum(t["net_pnl"] for t in comp_net_wins)
            comp_net_gross_loss = abs(sum(t["net_pnl"] for t in comp_trades if t["net_pnl"] <= 0))
            report.notes[f"{component.name}_net_pnl"] = round(sum(t["net_pnl"] for t in comp_trades), 2)
            report.notes[f"{component.name}_net_pf"] = (
                round(comp_net_gross_win / comp_net_gross_loss, 2) if comp_net_gross_loss > 0 else float("inf")
            )

        if not report.is_reliable():
            report.warnings.append(
                f"Csak {len(trade_log)} trade — a 30-as megbízhatósági küszöb alatt "
                f"(lásd Turnaround Tuesday tanulság, PLAN.md 2. táblázat)."
            )
        if trade_log and profit_factor < 1.0:
            report.warnings.append(f"Profit factor ({profit_factor:.2f}) < 1 — nem nyereséges ezen az adatsoron.")

        if return_trades:
            return report, trade_log
        return report
